"""prov_tracker - erzeugt aus einem Lauf des Agenten-Graphen (`llm.workflow.compiled_graph`)
ein W3C-PROV-Dokument, angelehnt an den Entwurf "OGC API - Processes - Part 5: Provenance".

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
           `describedByProcess` auf den echten pygeoapi-Prozess. Kanten des `workflow_graph`
           werden zu `used`-Beziehungen zwischen den Schritten.
  - "high": die volle Knoten-für-Knoten-Nachverfolgung (siehe Phase 2 oben) inkl.
           State-Versionierung über den gesamten Agenten-Loop hinweg.

Nutzung (siehe auch verify_prov.py):
    tracker = ProvTracker(compiled_graph, root_url=PROV_ROOT_URL, process_id=PROV_PROCESS_ID,
                          job_id=job_id, output_keys=["workflow_graph"], node_reads=NODE_READS)
    result = await compiled_graph.ainvoke(inputs, config={"callbacks": [tracker]})
    tracker.add_result("final_reply", result["messages"][-1].content)
    tracker.document.serialize("job_prov.json", indent=2)   # PROV-JSON
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
from prov.model import ProvDocument, PROV, PROV_TYPE, PROV_ROLE, PROV_LOCATION, PROV_LABEL, PROV_VALUE

WFDESC = "http://purl.org/wf4ever/wfdesc#"
WFPROV = "http://purl.org/wf4ever/wfprov#"
SCHEMA = "https://schema.org/"

# Prototyp-Konfiguration - Platzhalter, per Env-Var überschreibbar, bevor es einen echten
# öffentlichen Endpunkt für diesen Agenten gibt.
PROV_ROOT_URL = os.environ.get("PROV_ROOT_URL", "http://localhost:8000")
PROV_PROCESS_ID = os.environ.get("PROV_PROCESS_ID", "geo-agent-workflow")
PROV_NAMESPACE = os.environ.get("PROV_NAMESPACE", "https://velocityadaptgeo.local/prov#")
PROV_DIR = os.environ.get("PROV_DIR", "prov")
PROV_GRANULARITY = os.environ.get("PROV_GRANULARITY", "low").strip().lower()  # "low" | "high"

# Graph-Knoten-IDs aus llm/workflow.py -> welche WorkflowState-Keys die Node-Funktion tatsächlich
# liest (verifiziert gegen den jeweiligen Node-Code), damit `prov:used` nicht überbehauptet.
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


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


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

        self._root_run: UUID | None = None
        self._node_runs: dict[UUID, Any] = {}      # run_id -> PROV-Aktivität des Knotens
        self._run_parent: dict[UUID, UUID | None] = {}
        self._key_version: dict[str, int] = {}     # State-Key -> aktuelle Versionsnummer
        self._key_steps: dict[str, list[tuple[int, int]]] = {}  # Key -> [(version, step)]
        self._invocations: dict[str, int] = {}     # Knoten -> Anzahl Ausführungen (Loops!)
        self._agents: dict[str, Any] = {}
        self._node_step: dict[UUID, int] = {}
        self._job_agents_associated: set[str] = set()  # dedup für "low": Agent schon an Job-Aktivität gehängt?

        d = self.document = ProvDocument()
        self.wfdesc = d.add_namespace("wfdesc", WFDESC)
        self.wfprov = d.add_namespace("wfprov", WFPROV)
        self.schema = d.add_namespace("schema", SCHEMA)
        d.add_namespace("proc", f"{self.root}/processes/")
        d.add_namespace("jobs", f"{self.root}/jobs/")
        d.add_namespace("job", f"{self.root}/jobs/{self.job_id}/")
        d.add_namespace("ex", ex_namespace)

        self._build_prospective(compiled_graph, user)

    # ------------------------------------------------------------------ Phase 1
    def _build_prospective(self, app, user: str | None) -> None:
        d = self.document
        graph_json = app.get_graph().to_json()
        graph_hash = _digest(graph_json)

        # Generalisierter Prozess (= Workflow-Definition), mit Versions-Fingerprint.
        # Der Hash beantwortet "welche Definition hat diesen Lauf erzeugt?" (vgl. Issue #632).
        self.process = d.entity(f"proc:{self.process_id}", {
            PROV_TYPE: self.wfdesc["Workflow"],
            PROV_LOCATION: f"{self.root}/processes/{self.process_id}",
            "ex:graphHash": graph_hash,
            **({"ex:gitCommit": c} if (c := _git_commit()) else {}),
        })
        self.node_desc = {}
        if self.granularity == "high":
            # Zerlegung des Agenten-Workflows in seine eigenen Knoten als wfdesc:Process -
            # nur relevant, wenn wir auch pro Knoten eine Aktivität anlegen (siehe on_chain_start).
            for node in graph_json["nodes"]:
                nid = node["id"]
                if nid in ("__start__", "__end__"):
                    continue
                ent = d.entity(f"proc:{self.process_id}/nodes/{nid}", {PROV_TYPE: self.wfdesc["Process"], PROV_LABEL: nid})
                d.hadMember(self.process, ent)  # wfdesc:hasSubProcess, hier als PROV-Membership
                self.node_desc[nid] = ent

        # Job (Entität) + Ausführung (Aktivität) - Pflicht laut Part 5
        self.job = d.entity(f"jobs:{self.job_id}", {
            PROV_TYPE: self.wfdesc["ProcessRun"],
            PROV_LOCATION: f"{self.root}/jobs/{self.job_id}",
        })
        self.job_activity = d.activity("job:run", other_attributes={PROV_TYPE: self.wfprov["WorkflowRun"]})
        d.wasGeneratedBy(self.job, self.job_activity)
        d.used(self.job_activity, self.process, other_attributes={PROV_ROLE: "process"})

        self.engine = self._agent("langgraph", PROV["SoftwareAgent"], {"ex:version": _pkg_version("langgraph")})
        d.wasAssociatedWith(self.job_activity, self.engine, plan=self.process)
        if user:
            u = self._agent(user, PROV["Person"])
            d.actedOnBehalfOf(self.engine, u)
            d.wasAssociatedWith(self.job_activity, u)

    # ------------------------------------------------------------------ Helpers
    def _agent(self, name: str, ptype, attrs: dict | None = None):
        if name not in self._agents:
            self._agents[name] = self.document.agent(f"ex:agent/{_slug(name)}", {PROV_TYPE: ptype, PROV_LABEL: name, **(attrs or {})})
        return self._agents[name]

    def _state_entity(self, key: str, value: Any, *, step: int):
        """Neue Version eines State-Keys anlegen: state/<key>/v<n>, erzeugt in Step <step>."""
        self._key_version[key] = self._key_version.get(key, 0) + 1
        n = self._key_version[key]
        self._key_steps.setdefault(key, []).append((n, step))
        attrs = {PROV_TYPE: self.wfprov["Artifact"], PROV_LABEL: key, "ex:digest": _digest(value)}
        # Values within embed_limit are stored whole (no truncation needed); only values
        # beyond it get a short, clearly-marked preview instead of ballooning the document.
        full = value if isinstance(value, str) else json.dumps(value, default=str)
        attrs[PROV_VALUE] = full if len(full) <= self.embed_limit else _preview(value, limit=120)
        ent = self.document.entity(f"job:state/{key}/v{n}", attrs)
        if n > 1:
            self.document.wasRevisionOf(ent, f"job:state/{key}/v{n - 1}")
        return ent

    def _version_visible_at(self, key: str, step: int) -> str | None:
        """LangGraph-Semantik: ein Knoten in Step k sieht nur Updates aus Steps < k."""
        visible = [v for v, s in self._key_steps.get(key, []) if s < step]
        return f"job:state/{key}/v{visible[-1]}" if visible else None

    def _enclosing_node(self, run_id: UUID | None):
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
                self.job_activity.add_attributes({"prov:startTime": _now()})
                for key, value in (inputs or {}).items():  # initiale Inputs (Pflicht: used + role)
                    ent = self._state_entity(key, value, step=0)
                    self.document.used(self.job_activity, ent, other_attributes={PROV_ROLE: key})
                return

            if self.granularity != "high":
                return  # "low": keine Knoten-Aktivitäten, nur der Root-Run oben zählt

            node = md.get("langgraph_node")
            if node is None or name != node:
                return  # innere Runnables eines Knotens ignorieren
            parent_act = self._enclosing_node(parent_run_id)
            if parent_act is not None and node in parent_act.get_attribute(PROV_LABEL):
                return  # gleichnamiges inneres Runnable desselben Knotens

            self._invocations[node] = self._invocations.get(node, 0) + 1
            i = self._invocations[node]
            desc = self.node_desc.get(node)
            act = self.document.activity(f"job:nodes/{node}/{i}", _now(), None, {
                PROV_TYPE: self.wfprov["ProcessRun"],
                PROV_LABEL: node,
                self.wfprov["describedByProcess"]: desc.identifier if desc else f"proc:{self.process_id}/nodes/{node}",
                self.wfprov["wasPartOfWorkflowRun"]: (parent_act or self.job_activity).identifier,
                "ex:step": md.get("langgraph_step"),
                "ex:triggers": ",".join(md.get("langgraph_triggers", ())),
                "ex:runId": str(run_id),
            })
            self.document.wasAssociatedWith(act, self.engine)
            self._node_runs[run_id] = act

            step = md.get("langgraph_step", 10**9)
            self._node_step[run_id] = step
            reads = self.node_reads.get(node, list((inputs or {}).keys()))
            for key in reads:
                if (ent := self._version_visible_at(key, step)) is not None:
                    self.document.used(act, ent, other_attributes={PROV_ROLE: key})

    def on_chain_end(self, outputs, *, run_id, **kw):
        with self._lock:
            if run_id == self._root_run:
                self._finish(outputs)
                return
            act = self._node_runs.get(run_id)
            if act is None:
                return
            act.add_attributes({"prov:endTime": _now(),
                                self.schema["actionStatus"]: self.schema["CompletedActionStatus"]})
            if isinstance(outputs, dict):
                for key, value in outputs.items():
                    ent = self._state_entity(key, value, step=self._node_step.get(run_id, 10**9))
                    self.document.wasGeneratedBy(ent, act, other_attributes={PROV_ROLE: key})

    def on_chain_error(self, error, *, run_id, **kw):
        with self._lock:
            act = self._node_runs.get(run_id) or (self.job_activity if run_id == self._root_run else None)
            if act is None:
                return
            # Status nach schema.org (PROV/wfprov kennen keinen Status für Aktivitäten)
            act.add_attributes({
                "prov:endTime": _now(),
                self.schema["actionStatus"]: self.schema["FailedActionStatus"],
                self.schema["error"]: repr(error)[:500],
            })
            if act is self.job_activity:
                act.add_attributes({"ex:ogcJobStatus": "failed"})

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
            agent = self._agent(f"{provider}/{model}", PROV["SoftwareAgent"],
                                {"ex:provider": provider, "ex:model": model,
                                 **({"ex:temperature": params["temperature"]} if "temperature" in params else {})})
            self._associate(act, agent)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kw):
        with self._lock:
            self._run_parent[run_id] = parent_run_id
            act = self._enclosing_node(parent_run_id) if self.granularity == "high" else self.job_activity
            if act is not None:
                name = (serialized or {}).get("name") or kw.get("name") or "tool"
                self._associate(act, self._agent(f"tool/{name}", PROV["SoftwareAgent"]))

    def _associate(self, act, agent) -> None:
        """wasAssociatedWith, aber bei 'low' (immer dieselbe Ziel-Aktivität: job_activity)
        dedupliziert - sonst würde jeder LLM-/Tool-Aufruf im Lauf eine weitere, redundante
        Assoziation an dieselbe Job-Aktivität anhängen."""
        if act is self.job_activity:
            key = str(agent.identifier)
            if key in self._job_agents_associated:
                return
            self._job_agents_associated.add(key)
        self.document.wasAssociatedWith(act, agent)

    # ------------------------------------------------------------------ Abschluss
    def _make_result(self, key: str, value: Any) -> None:
        """Register a job-level output artifact: wasGeneratedBy job-activity + role."""
        d = self.document
        result = d.entity(f"job:results/{key}", {PROV_TYPE: self.wfprov["Artifact"], PROV_LABEL: key,
                                                 "ex:digest": _digest(value),
                                                 PROV_LOCATION: f"{self.root}/jobs/{self.job_id}/results/{key}"})
        d.wasGeneratedBy(result, self.job_activity, other_attributes={PROV_ROLE: key})
        if key in self._key_version:
            d.specializationOf(f"job:state/{key}/v{self._key_version[key]}", result)

    def add_result(self, key: str, value: Any) -> None:
        """Register a job-level output that is not a raw WorkflowState key - e.g. a value
        derived from a reducer key (like the assistant's final reply out of `messages`)
        after the run has finished. Thread-safe like every other public entry point."""
        with self._lock:
            self._make_result(key, value)

    def _build_steps(self, workflow_graph: dict) -> None:
        """"low"-Granularität: eine Aktivität pro OGC-Prozess, der tatsächlich im finalen
        `workflow_graph` gelandet ist - keine Zwischenschritte (erfolglose Suchen, Validierung,
        manuelle Edits). `describedByProcess` zeigt auf den echten pygeoapi-Prozess, nicht auf
        einen Platzhalter, weil die Graph-Knoten schon `server_url`+`type` aus dem echten
        Katalog tragen. Kanten des Graphen werden zu `used`-Beziehungen zwischen den Schritten."""
        d = self.document
        nodes = {n["id"]: n for n in (workflow_graph or {}).get("nodes", [])}
        step_entity = {}
        for node_id, node in nodes.items():
            server_url = (node.get("config") or {}).get("server_url", "")
            proc_type = node.get("type", node_id)
            act = d.activity(f"job:steps/{node_id}", other_attributes={
                PROV_TYPE: self.wfprov["ProcessRun"],
                PROV_LABEL: proc_type,
                self.wfprov["describedByProcess"]: f"{server_url.rstrip('/')}/processes/{proc_type}",
                self.wfprov["wasPartOfWorkflowRun"]: self.job_activity.identifier,
            })
            self._associate(act, self.engine)
            ent = d.entity(f"job:steps/{node_id}/result", {
                PROV_TYPE: self.wfprov["Artifact"], PROV_LABEL: proc_type,
                "ex:digest": _digest(node.get("config")),
                PROV_VALUE: _preview(node.get("config"), limit=self.embed_limit),
            })
            d.wasGeneratedBy(ent, act, other_attributes={PROV_ROLE: node_id})
            step_entity[node_id] = ent
        for edge in (workflow_graph or {}).get("edges", []):
            source, target = edge.get("source"), edge.get("target")
            if source in step_entity and target in nodes:
                d.used(f"job:steps/{target}", step_entity[source],
                       other_attributes={PROV_ROLE: edge.get("target_input") or "input"})

    def _finish(self, final_state):
        self.job_activity.add_attributes({"prov:endTime": _now(),
                                          self.schema["actionStatus"]: self.schema["CompletedActionStatus"],
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


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return "unknown"
