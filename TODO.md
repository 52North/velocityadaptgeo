# TODO

Stand: 2026-10-01, Branch `feature/port-type-checks`

## Port-Typprüfung (dieser Branch)

Erledigt: lockere Typprüfung im Validator (`LangGraph/src/llm/nodes/validator.py`), Typen werden zur Prüfzeit über `fetch_port_specs()` aus dem Katalog geholt. `object` passt zu GeoJSON/Raster/bbox, Fehler nur bei klaren Konflikten (z. B. `number` → `object`, GeoJSON → Raster).

- [ ] Diff reviewen, entscheiden ob mergen
- [ ] Prozessdefinitionen in `pygeoapi_instance/processes/` mit OGC-Vokabular anreichern (`"format": "geojson-feature-collection"`, `"contentMediaType": "image/tiff"` …) und Katalog neu crawlen – erst dann unterscheidet die Prüfung Raster von Vektor
- [ ] Unit-Tests ins Repo (pytest ist schon Dependency); `validate_graph(graph, port_specs=...)` ist ohne DB testbar
- [ ] Pflicht-Inputs prüfen (`required: True` / `minOccurs ≥ 1`, weder Kante noch Wert in `config`) – kollidiert mit der Manager-Regel „unbekannte Werte offen lassen“, also vorher klären: Fehler oder nur Warnung?
- [ ] Manager-Prompt (`management.py`) behauptet, der Validator prüfe „type mismatches, dangling inputs“ – Typen stimmen jetzt, dangling inputs nicht; Prompt oder Validator angleichen
- [ ] Manuell hinzugefügte Knoten (`add_node`, `add_top_candidate`) bekommen keine Ports – der Validator nimmt jetzt die aus dem Katalog, aber das Frontend zeigt am Knoten weiterhin keine Ports an
- [ ] Validator fragt bei jedem Aufruf die DB ab – bei Bedarf cachen

## Morgen: Workflows speichern / wiederverwenden

- [ ] Fertige Graphen speichern und vom User manuell bearbeiten lassen (Edit-Endpunkt in `app.py` existiert schon)
- [ ] Alternativ/zusätzlich: Rezepte als nummerierte Listen mit Schritt-Verweisen, z. B. „(1) minus (4)“; Planner holt Top-k Rezepte als Vorlage und schreibt daraus einen eigenen Plan (`plan`, `plan_cursor`, `step_nodes` im State, `origin` pro Schritt)
- [ ] `GraphBuildDecision` in `auto_builder.py` erlaubt nur eine eingehende Kante pro neuem Knoten → Liste von Verbindungen zulassen (nötig z. B. für `geometry-difference` mit `subject` + `subtrahend`)

## Evaluation

- [ ] Cool-Spots-Prompts mit Haiku vs. größerem Modell, jeweils mit/ohne Rezept (2×2) – trennt Workflow-Abstraktion von Discovery + Verdrahtung
- [ ] Gebaute Graphen gegen die Kette aus `pygeoapi_instance/CoolSpots/cool_spots.py` vergleichen
- [ ] Anchoring testen: Prompts „fast wie Cool Spots, aber …“ – taucht die Abweichung im Plan auf?
