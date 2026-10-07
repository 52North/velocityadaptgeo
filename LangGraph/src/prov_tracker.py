"""prov_tracker - erzeugt aus einem Lauf des Agenten-Graphen (`llm.workflow.compiled_graph`)
ein W3C-PROV-Dokument, angelehnt an den Entwurf "OGC API - Processes - Part 5: Provenance".

Ausgabeformat: JSON nach dem 52N-Building-Block "Cool Spot Workflow Provenance Profile"
(https://github.com/52North/bblocks-openscience/tree/ospd26_52north/_sources/52n-provenance/cool-spots),
einem Profil von `ogc.ogc-utils.prov`. Das Dokument ist ein JSON-Array aus Entitäten
(`entityType`), Aktivitäten (`activityType`) und Agenten (`agentType`), die sich per
`{"id": ...}` referenzieren. Prüfen mit `validate_prov.py`.

Getrackt wird der LangGraph-Agenten-Loop selbst (manager/retriever/auto_build/builder/
validator/responder/chat), nicht die davon losgelöste Ausführung echter OGC-Prozesse in
`execution/runner.py` (reines asyncio/httpx, kein LangChain-Lauf, für einen
BaseCallbackHandler nicht beobachtbar). "Prozess" im PROV-Sinn ist hier der Agenten-Workflow
selbst - dies ist ein Prototyp, keine strikt OGC-konforme Implementierung.

Zwei Phasen:
  1. Prospektiv (vor dem Lauf):   Workflow- und Knotenbeschreibungen (wfdesc),
                                  Job-Entität, Job-Aktivität, initiale Inputs.
  2. Retrospektiv (während Lauf): pro Knotenausführung eine Aktivität (wfprov:ProcessRun)
                                  mit Start-/Endzeit, gelesenen und geschriebenen
                                  State-Versionen, beteiligten LLMs als SoftwareAgent.

Zwei Granularitäten, per `granularity`/`PROV_GRANULARITY`-Env-Var wählbar:
  - "low"  (Default): keine Zwischenschritte. Nur eine Aktivität pro OGC-Prozess, der am
           Ende tatsächlich im `workflow_graph` gelandet ist (z.B. geocode, buffer), mit
           dem echten pygeoapi-Prozess als `hadPlan`. Kanten des `workflow_graph`
           werden zu `used`-Beziehungen zwischen den Schritten.
  - "high": die volle Knoten-für-Knoten-Nachverfolgung (siehe Phase 2 oben) inkl.
           State-Versionierung über den gesamten Agenten-Loop hinweg.

Nutzung (siehe auch verify_prov.py):
    tracker = ProvTracker(compiled_graph, root_url=PROV_ROOT_URL, process_id=PROV_PROCESS_ID,
                          job_id=job_id, output_keys=["workflow_graph"], node_reads=NODE_READS)
    result = await compiled_graph.ainvoke(inputs, config={"callbacks": [tracker]})
    tracker.add_result("final_reply", result["messages"][-1].content)
    tracker.document.serialize("job_prov.json", indent=2)
"""
from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import os
import subprocess
import threading
import uuid
from typing import Any, Iterable
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

WFDESC = "http://purl.org/wf4ever/wfdesc#"
WFPROV = "http://purl.org/wf4ever/wfprov#"
SCHEMA = "https://schema.org/"

# JSON-LD-Kontext des PROV-Building-Blocks; definiert die Terme ohne Präfix (used,
# wasGeneratedBy, entityType, ...). Die Präfixe (ex:, schema:, ...) kommen aus dem Profil.
PROV_CONTEXT_URL = "https://ogcincubator.github.io/bblock-prov-schema/build/annotated/ogc-utils/prov/context.jsonld"

# Prototyp-Konfiguration - Platzhalter, per Env-Var überschreibbar, bevor es einen echten
# öffentlichen Endpunkt für diesen Agenten gibt.
PROV_ROOT_URL = os.environ.get("PROV_ROOT_URL", "http://localhost:8000")
PROV_PROCESS_ID = os.environ.get("PROV_PROCESS_ID", "geo-agent-workflow")
PROV_NAMESPACE = os.environ.get("PROV_NAMESPACE", "https://velocityadaptgeo.local/prov#")
PROV_DIR = os.environ.get("PROV_DIR", "prov")
PROV_GRANULARITY = os.environ.get("PROV_GRANULARITY", "low").strip().lower()  # "low" | "high"

# Graph-Knoten-IDs aus llm/workflow.py -> welche WorkflowState-Keys die Node-Funktion tatsächlich
# liest (verifiziert gegen den jeweiligen Node-Code), damit `used` nicht überbehauptet.
NODE_READS: dict[str, list[str]] = {
    "manager": [
        "messages", "workflow_graph", "candidate_processes", "last_validation",
        "unmet_capabilities", "iteration", "max_iterations", "decision_history",
    ],
    "retriever": ["step"],
    "auto_build": ["candidate_processes", "workflow_graph", "messages", "step"],
    "builder": ["step", "workflow_graph"],
    "validator": ["workflow_graph"],
    "responder": [
        "messages", "workflow_graph", "candidate_processes", "last_validation",
        "unmet_capabilities", "decision_history",
    ],
    "chat": ["messages"],
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _digest(value: Any) -> str:
    """Stabiler Inhalts-Hash, damit große Werte nicht ins PROV-Dokument müssen."""
    try:
        raw = json.dumps(value, sort_keys=True, default=str).encode()
    except Exception:
        raw = repr(value).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _preview(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


@functools.lru_cache(maxsize=1)
def _git_commit() -> str | None:
    """Cached: the commit cannot change during the process's lifetime, and the subprocess
    call would otherwise block the event loop on every single turn."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


class ProvDocument:
    """Minimaler Builder für das Profil-JSON: geordnete Sammlung von Entitäten, Aktivitäten
    und Agenten (je ein dict mit `id`), Beziehungen werden direkt als Properties eingetragen."""

    def __init__(self, ex_namespace: str = PROV_NAMESPACE):
        self.ex_namespace = ex_namespace
        self._records: dict[str, dict] = {}

    def _record(self, rid: str, type_key: str, types: list[str], attrs: dict | None) -> dict:
        rec = self._records.get(rid)
        if rec is None:
            rec = self._records[rid] = {"id": rid, type_key: types}
        rec.update({k: v for k, v in (attrs or {}).items() if v is not None})
        return rec

    def entity(self, rid: str, types: Iterable[str] = (), attrs: dict | None = None) -> dict:
        return self._record(rid, "entityType", ["prov:Entity", *types], attrs)

    def activity(self, rid: str, types: Iterable[str] = (), attrs: dict | None = None) -> dict:
        return self._record(rid, "activityType", ["prov:Activity", *types], attrs)

    def agent(self, rid: str, types: Iterable[str] = (), attrs: dict | None = None) -> dict:
        return self._record(rid, "agentType", ["prov:Agent", *types], attrs)

    def get(self, rid: str) -> dict | None:
        return self._records.get(rid)

    @staticmethod
    def add(rec: dict, key: str, value: Any) -> None:
        """Wert an eine Property anhängen: einzeln als Wert, ab dem zweiten als Liste
        (wie im Profil-Beispiel); Duplikate werden ignoriert."""
        if key not in rec:
            rec[key] = value
            return
        current = rec[key] if isinstance(rec[key], list) else [rec[key]]
        if value not in current:
            rec[key] = current + [value]

    @staticmethod
    def ref(rid: str) -> dict:
        return {"id": rid}

    # --- PROV-Relationen (einfach + qualifiziert, damit die Rolle erhalten bleibt) ---
    def used(self, activity: dict, entity_id: str, role: str | None = None) -> None:
        self.add(activity, "used", self.ref(entity_id))
        if role:
            self.add(activity, "qualifiedUsage", {"type": "Usage", "entity": entity_id, "hadRole": _role(role)})

    def was_generated_by(self, entity: dict, activity_id: str, role: str | None = None) -> None:
        self.add(entity, "wasGeneratedBy", self.ref(activity_id))
        if role:
            self.add(entity, "qualifiedGeneration", {"type": "Generation", "activity": activity_id, "hadRole": _role(role)})

    def was_associated_with(self, activity: dict, agent_id: str, plan: str | None = None) -> None:
        self.add(activity, "wasAssociatedWith", self.ref(agent_id))
        if plan:
            self.add(activity, "qualifiedAssociation", {"type": "Association", "agent": agent_id, "hadPlan": plan})

    # --- Ausgabe ---
    def to_json(self) -> list[dict]:
        return json.loads(json.dumps(list(self._records.values()), default=str))

    def jsonld_context(self) -> list:
        """Kontext, um das Dokument als JSON-LD/RDF zu lesen (z.B. für check_ogc.py). Präfixe
        wie im Profil (context.jsonld), `ex:` jedoch auf den eigenen Namensraum gebunden."""
        return [PROV_CONTEXT_URL, {
            "dcterms": "http://purl.org/dc/terms/",
            "ex": self.ex_namespace,
            "prov": "http://www.w3.org/ns/prov#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "schema": SCHEMA,
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "wfdesc": WFDESC,
            "wfprov": WFPROV,
        }]

    def to_jsonld(self) -> dict:
        return {"@context": self.jsonld_context(), "@graph": self.to_json()}

    def serialize(self, destination: str, indent: int | None = 2) -> None:
        with open(destination, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=indent, ensure_ascii=False)


class ProvTracker(BaseCallbackHandler):
    """LangChain/LangGraph-Callback, der pro Lauf ein PROV-Dokument aufbaut."""

    raise_error = False  # Provenance darf den Workflow nie abbrechen
    # LangChain dispatcht Callbacks bei ainvoke/astream sonst per run_in_executor in einen
    # Thread (BaseCallbackHandler.run_inline default ist False). Dieser Graph läuft
    # ausschließlich async und ohne parallele Knoten - inline halten vermeidet unnötige
    # Thread-Hops und hält die Aufrufreihenfolge exakt an LangGraphs eigener Reihenfolge
    # (worauf u.a. `_version_visible_at` sich verlässt). Gleiches Muster wie RunTracker
    # in metrics.py.
    run_inline = True

    def __init__(
        self,
        compiled_graph,
        *,
        root_url: str,
        process_id: str,
        job_id: str | None = None,
        output_keys: Iterable[str] | None = None,
        node_reads: dict[str, list[str]] | None = None,
        user: str | None = None,
        embed_values_up_to: int = 200,
        ex_namespace: str = PROV_NAMESPACE,
        granularity: str = PROV_GRANULARITY,
    ):
        self.root = root_url.rstrip("/")
        self.process_id = process_id
        self.job_id = job_id or str(uuid.uuid4())
        self.output_keys = list(output_keys) if output_keys else None
        self.node_reads = node_reads or {}   # optional: welche State-Keys ein Knoten wirklich liest
        self.embed_limit = embed_values_up_to
        self.granularity = granularity if granularity in ("low", "high") else "low"
        self._lock = threading.Lock()

        # IRIs statt projektspezifischer Präfixe, damit die IDs ohne eigenen Kontext eindeutig sind
        self.process_iri = f"{self.root}/processes/{self.process_id}"
        self.job_iri = f"{self.root}/jobs/{self.job_id}"

        self._root_run: UUID | None = None
        self._node_runs: dict[UUID, dict] = {}     # run_id -> PROV-Aktivität des Knotens
        self._run_parent: dict[UUID, UUID | None] = {}
        self._key_version: dict[str, int] = {}     # State-Key -> aktuelle Versionsnummer
        self._key_steps: dict[str, list[tuple[int, int]]] = {}  # Key -> [(version, step)]
        self._invocations: dict[str, int] = {}     # Knoten -> Anzahl Ausführungen (Loops!)
        self._agents: dict[str, dict] = {}
        self._node_step: dict[UUID, int] = {}

        self.document = ProvDocument(ex_namespace)
        self._build_prospective(compiled_graph, user)

    # ------------------------------------------------------------------ Phase 1
    def _build_prospective(self, app, user: str | None) -> None:
        d = self.document
        graph_json = app.get_graph().to_json()

        # Generalisierter Prozess (= Workflow-Definition), mit Versions-Fingerprint.
        # Der Hash beantwortet "welche Definition hat diesen Lauf erzeugt?" (vgl. https://github.com/opengeospatial/ogcapi-processes/issues/632).
        self.process = d.entity(self.process_iri, ["prov:Plan", WFDESC + "Workflow"], {
            "rdfs:label": self.process_id,
            "atLocation": self.process_iri,
            "ex:graphHash": _digest(graph_json),
            "ex:gitCommit": _git_commit(),
        })
        self.node_desc: dict[str, str] = {}
        if self.granularity == "high":
            # Zerlegung des Agenten-Workflows in seine eigenen Knoten als wfdesc:Process -
            # nur relevant, wenn wir auch pro Knoten eine Aktivität anlegen (siehe on_chain_start).
            self.process["entityType"].append("prov:Collection")
            for node in graph_json["nodes"]:
                nid = node["id"]
                if nid in ("__start__", "__end__"):
                    continue
                iri = f"{self.process_iri}/nodes/{nid}"
                d.entity(iri, ["prov:Plan", WFDESC + "Process"], {"rdfs:label": nid})
                d.add(self.process, "hadMember", iri)  # wfdesc:hasSubProcess, hier als PROV-Membership
                self.node_desc[nid] = iri

        # Job (Entität) + Ausführung (Aktivität) - Pflicht laut Part 5
        self.job = d.entity(self.job_iri, [WFDESC + "ProcessRun"], {"atLocation": self.job_iri})
        self.job_activity = d.activity(f"{self.job_iri}/run", [WFPROV + "WorkflowRun"],
                                       {"rdfs:label": f"Run of {self.process_id}"})
        d.was_generated_by(self.job, self.job_activity["id"])
        d.used(self.job_activity, self.process_iri, role="process")

        self.engine = self._agent("langgraph", "prov:SoftwareAgent", {"schema:softwareVersion": _pkg_version("langgraph")})
        d.was_associated_with(self.job_activity, self.engine["id"], plan=self.process_iri)
        if user:
            u = self._agent(user, "prov:Person")
            d.add(self.engine, "actedOnBehalfOf", d.ref(u["id"]))
            d.was_associated_with(self.job_activity, u["id"])

    # ------------------------------------------------------------------ Helpers
    def _agent(self, name: str, ptype: str, attrs: dict | None = None) -> dict:
        if name not in self._agents:
            # Ist der Name schon eine IRI (z.B. ORCID eines Nutzers), dient er direkt als ID.
            rid = name if name.startswith(("http://", "https://")) else f"ex:agent/{_slug(name)}"
            self._agents[name] = self.document.agent(rid, [ptype], {"rdfs:label": name, **(attrs or {})})
        return self._agents[name]

    def _state_iri(self, key: str, n: int) -> str:
        return f"{self.job_iri}/state/{key}/v{n}"

    def _state_entity(self, key: str, value: Any, *, step: int) -> dict:
        """Neue Version eines State-Keys anlegen: state/<key>/v<n>, erzeugt in Step <step>."""
        self._key_version[key] = self._key_version.get(key, 0) + 1
        n = self._key_version[key]
        self._key_steps.setdefault(key, []).append((n, step))
        # Values within embed_limit are stored whole (no truncation needed); only values
        # beyond it get a short, clearly-marked preview instead of ballooning the document.
        full = value if isinstance(value, str) else json.dumps(value, default=str)
        ent = self.document.entity(self._state_iri(key, n), [WFPROV + "Artifact"], {
            "rdfs:label": key,
            "ex:digest": _digest(value),
            "value": full if len(full) <= self.embed_limit else _preview(value, limit=120),
        })
        if n > 1:
            self.document.add(ent, "wasRevisionOf", self.document.ref(self._state_iri(key, n - 1)))
        return ent

    def _version_visible_at(self, key: str, step: int) -> str | None:
        """LangGraph-Semantik: ein Knoten in Step k sieht nur Updates aus Steps < k."""
        visible = [v for v, s in self._key_steps.get(key, []) if s < step]
        return self._state_iri(key, visible[-1]) if visible else None

    def _enclosing_node(self, run_id: UUID | None) -> dict | None:
        while run_id is not None:
            if run_id in self._node_runs:
                return self._node_runs[run_id]
            run_id = self._run_parent.get(run_id)
        return None

    # ------------------------------------------------------------------ Phase 2
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kw):
        with self._lock:
            self._run_parent[run_id] = parent_run_id
            md = metadata or {}
            name = kw.get("name")

            if self._root_run is None:  # erster Chain-Start = Workflow-Lauf
                self._root_run = run_id
                self.job_activity["startedAtTime"] = _now()
                for key, value in (inputs or {}).items():  # initiale Inputs (Pflicht: used + role)
                    ent = self._state_entity(key, value, step=0)
                    self.document.used(self.job_activity, ent["id"], role=key)
                return

            if self.granularity != "high":
                return  # "low": keine Knoten-Aktivitäten, nur der Root-Run oben zählt

            node = md.get("langgraph_node")
            if node is None or name != node:
                return  # innere Runnables eines Knotens ignorieren
            parent_act = self._enclosing_node(parent_run_id)
            if parent_act is not None and parent_act.get("rdfs:label") == node:
                return  # gleichnamiges inneres Runnable desselben Knotens

            self._invocations[node] = self._invocations.get(node, 0) + 1
            i = self._invocations[node]
            act = self.document.activity(f"{self.job_iri}/nodes/{node}/{i}", [WFPROV + "ProcessRun"], {
                "rdfs:label": node,
                "startedAtTime": _now(),
                "dcterms:isPartOf": self.document.ref((parent_act or self.job_activity)["id"]),
                "ex:step": md.get("langgraph_step"),
                "ex:triggers": ",".join(md.get("langgraph_triggers", ())),
                "ex:runId": str(run_id),
            })
            # wfprov:describedByProcess -> Knotenbeschreibung als Plan der Ausführung
            self.document.was_associated_with(act, self.engine["id"],
                                              plan=self.node_desc.get(node, f"{self.process_iri}/nodes/{node}"))
            self._node_runs[run_id] = act

            step = md.get("langgraph_step", 10**9)
            self._node_step[run_id] = step
            reads = self.node_reads.get(node, list((inputs or {}).keys()))
            for key in reads:
                if (ent_id := self._version_visible_at(key, step)) is not None:
                    self.document.used(act, ent_id, role=key)

    def on_chain_end(self, outputs, *, run_id, **kw):
        with self._lock:
            if run_id == self._root_run:
                self._finish(outputs)
                return
            act = self._node_runs.get(run_id)
            if act is None:
                return
            act.update({"endedAtTime": _now(), "schema:actionStatus": "schema:CompletedActionStatus"})
            if isinstance(outputs, dict):
                for key, value in outputs.items():
                    ent = self._state_entity(key, value, step=self._node_step.get(run_id, 10**9))
                    ent["generatedAtTime"] = act["endedAtTime"]
                    self.document.was_generated_by(ent, act["id"], role=key)

    def on_chain_error(self, error, *, run_id, **kw):
        with self._lock:
            act = self._node_runs.get(run_id) or (self.job_activity if run_id == self._root_run else None)
            if act is None:
                return
            # Status nach schema.org (PROV/wfprov kennen keinen Status für Aktivitäten)
            act.update({
                "endedAtTime": _now(),
                "schema:actionStatus": "schema:FailedActionStatus",
                "schema:error": repr(error)[:500],
            })
            if act is self.job_activity:
                act["ex:ogcJobStatus"] = "failed"

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kw):
        self._record_model(serialized, run_id, parent_run_id, metadata, kw)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, metadata=None, **kw):
        self._record_model(serialized, run_id, parent_run_id, metadata, kw)

    def _record_model(self, serialized, run_id, parent_run_id, metadata, kw):
        with self._lock:
            self._run_parent[run_id] = parent_run_id
            act = self._enclosing_node(parent_run_id) if self.granularity == "high" else self.job_activity
            if act is None:
                return
            md = metadata or {}
            params = kw.get("invocation_params") or {}
            model = md.get("ls_model_name") or params.get("model") or params.get("model_name") \
                or (serialized or {}).get("name") or "unknown-model"
            provider = md.get("ls_provider", "unknown")
            agent = self._agent(f"{provider}/{model}", "prov:SoftwareAgent",
                                {"ex:provider": provider, "ex:model": model, "ex:temperature": params.get("temperature")})
            # ProvDocument.add dedupliziert - jeder weitere LLM-Aufruf derselben Aktivität
            # hängt keine redundante Assoziation an.
            self.document.was_associated_with(act, agent["id"])

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kw):
        with self._lock:
            self._run_parent[run_id] = parent_run_id
            act = self._enclosing_node(parent_run_id) if self.granularity == "high" else self.job_activity
            if act is not None:
                name = (serialized or {}).get("name") or kw.get("name") or "tool"
                self.document.was_associated_with(act, self._agent(f"tool/{name}", "prov:SoftwareAgent")["id"])

    # ------------------------------------------------------------------ Abschluss
    def _make_result(self, key: str, value: Any) -> None:
        """Register a job-level output artifact: wasGeneratedBy job-activity + role."""
        d = self.document
        iri = f"{self.job_iri}/results/{key}"
        result = d.entity(iri, [WFPROV + "Artifact"], {
            "rdfs:label": key, "ex:digest": _digest(value), "atLocation": iri, "generatedAtTime": _now(),
        })
        d.was_generated_by(result, self.job_activity["id"], role=key)
        if key in self._key_version:
            d.add(d.get(self._state_iri(key, self._key_version[key])), "specializationOf", d.ref(iri))

    def add_result(self, key: str, value: Any) -> None:
        """Register a job-level output that is not a raw WorkflowState key - e.g. a value
        derived from a reducer key (like the assistant's final reply out of `messages`)
        after the run has finished. Thread-safe like every other public entry point."""
        with self._lock:
            self._make_result(key, value)

    def _build_steps(self, workflow_graph: dict) -> None:
        """"low"-Granularität: eine Aktivität pro OGC-Prozess, der tatsächlich im finalen
        `workflow_graph` gelandet ist - keine Zwischenschritte (erfolglose Suchen, Validierung,
        manuelle Edits). `hadPlan` zeigt auf den echten pygeoapi-Prozess, nicht auf
        einen Platzhalter, weil die Graph-Knoten schon `server_url`+`type` aus dem echten
        Katalog tragen. Kanten des Graphen werden zu `used`-Beziehungen zwischen den Schritten."""
        d = self.document
        nodes = {n["id"]: n for n in (workflow_graph or {}).get("nodes", [])}
        steps, step_result = {}, {}
        for node_id, node in nodes.items():
            server_url = (node.get("config") or {}).get("server_url", "")
            proc_type = node.get("type", node_id)
            act = d.activity(f"{self.job_iri}/steps/{node_id}", [WFPROV + "ProcessRun"], {
                "rdfs:label": proc_type,
                "dcterms:isPartOf": d.ref(self.job_activity["id"]),
            })
            # wfprov:describedByProcess -> der echte OGC-Prozess als Plan der Ausführung
            d.was_associated_with(act, self.engine["id"],
                                  plan=f"{server_url.rstrip('/')}/processes/{proc_type}" if server_url else None)
            ent = d.entity(f"{self.job_iri}/steps/{node_id}/result", [WFPROV + "Artifact"], {
                "rdfs:label": proc_type,
                "ex:digest": _digest(node.get("config")),
                "value": _preview(node.get("config"), limit=self.embed_limit),
            })
            d.was_generated_by(ent, act["id"], role=node_id)
            steps[node_id], step_result[node_id] = act, ent["id"]
        for edge in (workflow_graph or {}).get("edges", []):
            source, target = edge.get("source"), edge.get("target")
            if source in step_result and target in steps:
                d.used(steps[target], step_result[source], role=edge.get("target_input") or "input")

    def _finish(self, final_state):
        self.job_activity.update({"endedAtTime": _now(),
                                  "schema:actionStatus": "schema:CompletedActionStatus",
                                  "ex:ogcJobStatus": "successful"})
        keys = self.output_keys or list((final_state or {}).keys())
        for key in keys:
            if key not in (final_state or {}):
                continue
            self._make_result(key, final_state[key])
        if self.granularity == "low":
            self._build_steps((final_state or {}).get("workflow_graph") or {})


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def _role(name: str) -> str:
    """Rollen sind IRIs/CURIEs (prov:hadRole ist objektwertig)."""
    return f"ex:role/{_slug(name)}"


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "unknown"
