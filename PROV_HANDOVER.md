# Übergabe: PROV-Dokument aus LangGraph-Workflow erzeugen (OGC API – Processes Part 5)

Dieses Dokument fasst eine Vorab-Diskussion zusammen und dient als Arbeitsauftrag für Claude Code.
Es liegt zusammen mit einem getesteten Prototyp in diesem Ordner:

| Datei | Zweck |
|---|---|
| `langgraph_prov.py` | Prototyp: `ProvTracker`, ein LangChain/LangGraph-Callback, der pro Lauf ein PROV-Dokument aufbaut |
| `example.py` | Minimalbeispiel (Parallelzweige, Schleife, LLM-Knoten) |
| `check_ogc.py` | Prüft ein Turtle-PROV-Dokument per SPARQL gegen die Pflichtanforderungen von Part 5 |
| `job_prov.{provn,ttl,json}` | Beispielausgabe von `example.py` |

Abhängigkeiten: `pip install langgraph prov rdflib` (getestet mit langgraph 1.2.12, langchain-core 1.6.5, prov 2.x/3.x).

---

## 1. Ziel

Unser bestehender LangGraph-Workflow soll bei jedem Lauf automatisch ein **W3C-PROV-Dokument** erzeugen,
das sich am Entwurf **„OGC API – Processes – Part 5: Provenance“** orientiert
(GitHub: `opengeospatial/ogcapi-processes`, Ordner `extensions/provenance`, Stand Sept. 2026, noch in Arbeit).

- Vor dem Lauf bekannt: die Endpunkte/Knoten und der erste Input.
- Während des Laufs kommen hinzu: alle Outputs, Start-/Endzeiten, beteiligte Software (LLMs, Tools).

## 2. Begriffliche Grundlage (Ergebnis der Diskussion)

**Provenance** ist im OGC-Kontext nicht eigens definiert; der Entwurf verweist auf **W3C PROV**:
Informationen über Entitäten, Aktivitäten und Akteure, die an der Entstehung von Daten beteiligt waren,
um Qualität, Verlässlichkeit oder Vertrauenswürdigkeit beurteilen zu können.
Part 5 grenzt das ein auf: *woher Inputs kamen, wie sie verarbeitet wurden und wie Ergebnisse für nachgelagerte Verarbeitung/Entscheidungen bereitgestellt wurden.*

**Kernentscheidung: PROV beschreibt den konkreten Lauf, nicht den Prozess generalisiert.**

- *Prospektiv* (wie es ablaufen soll) = Prozess-/Workflow-Beschreibung → `wfdesc`
- *Retrospektiv* (was tatsächlich passiert ist) = der Lauf mit Zeiten, Inputs, Outputs, Software → `wfprov` / PROV
- Der generalisierte Prozess erscheint im PROV-Dokument **nur als referenzierte Entität** (Link auf `/processes/{processID}`), seine eigentliche Beschreibung liegt in der Prozessdefinition.
- Zeiten, konkrete Inputs/Outputs, Software-/Modellversionen gehören **eindeutig** ins PROV-Dokument.

Abgrenzung zu **ISO 19115 Lineage**: datensatzorientiert, beschreibend (oft Freitext), grob, manuell gepflegt.
PROV nach Part 5: laufbezogen, formales Graphmodell, feingranular, automatisch erzeugt.
Beides ergänzt sich (Lineage-ProcessStep könnte auf das PROV-Dokument eines Jobs verweisen) – für dieses Vorhaben aber nicht relevant.

## 3. Anforderungen aus Part 5 (Entwurf)

Endpunkt: `GET /jobs/{jobID}/prov`, nur für Jobs mit `status: successful`, Content-Negotiation über gängige PROV-Formate (JSON empfohlen).

**Pflicht (SHALL):**
1. `prov:Entity` für den **Job**, `prov:type wfdesc:ProcessRun`, `prov:location` = `{root}/jobs/{jobID}`
2. `prov:Entity` für den **Prozess** (bei Workflows: Root-Prozess), `prov:type wfdesc:Process`, `prov:location` = `{root}/processes/{processID}`
3. Mindestens eine `prov:Activity` (Typ z. B. `wfprov:WorkflowRun` / `wfprov:ProcessRun`), die Job- und Prozess-Entität verbindet
4. Für **jeden Input**: `prov:Entity` mit Typ `wfprov:Artifact` + `prov:used` durch die Job-Aktivität + `prov:role` = `{inputID}`
5. Für **jedes Ergebnis**: `prov:Entity` mit Typ `wfprov:Artifact` + `prov:wasGeneratedBy` Job-Aktivität + `prov:role` = `{outputID}`

**Empfohlen (SHOULD):** Start-/Endzeit (passend zu `started`/`finished` im Job-Status), `prov:SoftwareAgent` für beteiligte Software,
`prov:Agent` für den auslösenden Nutzer via `wasAssociatedWith`, Link auf `/prov` im Job-Status.
Wie fein Zwischenschritte modelliert werden, lässt der Entwurf bewusst offen.

Offener Punkt im Standard (Issue #632): Wird ein Prozess ersetzt (Part 2), zeigt `/processes/{id}` evtl. auf eine neuere Version
→ nicht mehr eindeutig, welche Definition den Job erzeugt hat. **Wir lösen das mit einem Hash der Graph-Definition + Git-Commit.**

## 4. Architektur des Prototyps

`ProvTracker` ist ein `BaseCallbackHandler`, wird per `config={"callbacks": [tracker]}` übergeben – der Graph selbst bleibt unverändert.

**Phase 1 – prospektiv (Konstruktor):**
- Liest `compiled_graph.get_graph().to_json()`
- Workflow-Entität (`wfdesc:Workflow`) mit `ex:graphHash` und `ex:gitCommit`
- Jeder Knoten als `wfdesc:Process`, per `hadMember` am Workflow
- Job-Entität, Job-Aktivität (`wfprov:WorkflowRun`), LangGraph als `SoftwareAgent`, optional Nutzer als `prov:Person`

**Phase 2 – retrospektiv (Callbacks):**
- Erster `on_chain_start` = Workflow-Lauf → Startzeit + initiale Inputs (`used` mit Rolle)
- `on_chain_start` mit `metadata["langgraph_node"] == name` = Knotenausführung → Aktivität `job:nodes/{node}/{n}` (Typ `wfprov:ProcessRun`) mit Step, Triggers, Run-ID, `wfprov:describedByProcess`, `wfprov:wasPartOfWorkflowRun`
- `on_chain_end` → Endzeit, jeder geschriebene State-Key wird neue Entität `job:state/{key}/v{n}` (`wasGeneratedBy` + `wasRevisionOf` Vorgängerversion)
- `on_chat_model_start` / `on_llm_start` / `on_tool_start` → `SoftwareAgent` (Modell, Provider, Temperatur) am umschließenden Knoten
- Ende des Root-Runs → Ergebnis-Entitäten `job:results/{key}` für `output_keys` (`wasGeneratedBy` Job-Aktivität + Rolle), `specializationOf` zur letzten State-Version
- `on_chain_error` → Endzeit + `schema:actionStatus schema:FailedActionStatus` + `schema:error` (Knoten und Job-Aktivität), Job zusätzlich `ex:ogcJobStatus "failed"`; bei Erfolg `schema:CompletedActionStatus` bzw. `"successful"`

**Namensräume:** `proc:` = `{root}/processes/`, `jobs:` = `{root}/jobs/`, `job:` = `{root}/jobs/{jobID}/`, `wfdesc`, `wfprov`, `ex:` (Platzhalter!).

## 5. Wichtige Designentscheidungen und Fallstricke

1. **State-Versionierung:** Nur mit Versionen lässt sich sagen, welcher Knoten welchen Stand gelesen hat. Große Werte nur als SHA-256 (`ex:digest`), kleine (≤ `embed_values_up_to` Zeichen) als `prov:value`-Vorschau.
2. **Schleifen:** Pro Ausführung eigene Aktivität (`summarize/1`, `summarize/2`) – genau der Unterschied Prozess vs. Lauf.
3. **Parallelzweige – Race Condition (gefunden und behoben):** LangGraph gibt allen Knoten eines Steps denselben Snapshot, Callbacks kommen aber in beliebiger Reihenfolge. Lösung: Versionen sind an die Step-Nummer gebunden; ein Knoten in Step k „sieht“ nur Versionen aus Steps < k (`_version_visible_at`).
4. **„used“ überbehauptet:** Jeder Knoten bekommt den ganzen State; standardmäßig wird alles als gelesen verbucht. Über `node_reads={"knoten": ["key1", ...]}` präzisieren. **Da unsere Endpunkte vorab bekannt sind, sollten wir diese Info hier hinterlegen.**
5. **Innere Runnables** eines Knotens erben dessen Metadaten → Filter: nur Chains, deren `name == langgraph_node` und die nicht in einer gleichnamigen Knoten-Aktivität stecken.
6. **Typen als QNames** (`self.wfprov["Artifact"]`, `PROV["SoftwareAgent"]`), nicht als Strings – sonst wertlos in RDF.
7. `raise_error = False`: Provenance darf den Workflow nie abbrechen.
8. Rollen werden in RDF als `prov:qualifiedUsage` / `prov:qualifiedGeneration` mit `prov:hadRole` serialisiert (kein einfaches `prov:used`-Triple) – beim Abfragen beachten.

**Bekannte offene Punkte:**
- Reducer-Keys (z. B. `messages` mit `add_messages`): Entität steht für das *Update*, nicht den Gesamtwert
- Subgraphen: sollten über die Parent-Kette funktionieren, ungetestet
- Async (`ainvoke`/`astream`): sollte funktionieren (Handler ist thread-safe per Lock), ungetestet
- Fehlgeschlagene Läufe werden erfasst (Status per schema.org, da PROV/wfprov keinen Status kennen), obwohl Part 5 nur erfolgreiche Jobs vorsieht (bewusst)
- `ex:`-Namensraum durch eigenen ersetzen
- Einbindung in einen OGC-API-Processes-Server (z. B. pygeoapi) unter `/jobs/{jobID}/prov` noch nicht umgesetzt

---

## 6. Arbeitsauftrag für Claude Code

1. **Projekt verstehen:** Den bestehenden LangGraph-Workflow finden (State-Definition, Knoten, Kanten, wo `invoke`/`stream` aufgerufen wird). Kurz zusammenfassen: Knoten, State-Keys, welche Keys Inputs und welche Ergebnisse sind, wo LLMs/Tools genutzt werden, ob Subgraphen, Reducer, async oder Parallelzweige vorkommen.
2. **Tracker einbinden:** `langgraph_prov.py` ins Projekt übernehmen und am Aufrufpunkt als Callback übergeben. `root_url`, `process_id`, `job_id`, `output_keys` passend setzen.
3. **`node_reads` pflegen:** Aus dem Code ableiten, welche State-Keys jeder Knoten tatsächlich liest, und als Mapping hinterlegen. Unsichere Fälle markieren und nachfragen.
4. **An das Projekt anpassen:** Nur wo nötig – z. B. Reducer-Keys, Subgraphen, async, eigene Metadaten (Endpunkt-URLs der Knoten als `prov:location` o. ä.), eigener Namensraum statt `ex:`.
5. **Einmal durchlaufen lassen:** Workflow mit realistischem Input ausführen, PROV als JSON, Turtle und PROV-N speichern.
6. **Prüfen:** `python check_ogc.py <datei>.ttl` – alle Checks müssen ✔ sein. Zusätzlich plausibilisieren: Stimmt die Anzahl Knoten-Aktivitäten mit dem Lauf überein? Lesen parallele Knoten die richtigen Versionen? Sind alle Ergebnisse vorhanden?
7. **Bericht:** Was angepasst wurde, Ergebnis der Checks, Auffälligkeiten, offene Fragen.

Wichtig: Den bestehenden Workflow-Code möglichst nicht verändern; Provenance ist eine Zusatzschicht.
Vor größeren Umbauten nachfragen.
