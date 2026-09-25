"""Prüft ein PROV-Dokument (Turtle) grob gegen die Pflichtanforderungen von OGC API Processes Part 5."""
import sys
from rdflib import Graph
g = Graph().parse(sys.argv[1] if len(sys.argv) > 1 else "job_prov.ttl")
P = """PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX wfdesc: <http://purl.org/wf4ever/wfdesc#>
PREFIX wfprov: <http://purl.org/wf4ever/wfprov#>
"""
checks = {
 "Job-Entität (wfdesc:ProcessRun) mit prov:atLocation":
   "ASK { ?j a prov:Entity, wfdesc:ProcessRun ; prov:atLocation ?l }",
 "Prozess-Entität (wfdesc:Process bzw. Workflow) mit prov:atLocation":
   "ASK { ?p a prov:Entity ; a ?t ; prov:atLocation ?l FILTER(?t IN (wfdesc:Process, wfdesc:Workflow)) }",
 "Job-Aktivität (wfprov:WorkflowRun/ProcessRun) verbindet Job und Prozess":
   "ASK { ?a a prov:Activity ; a ?t . ?j prov:wasGeneratedBy ?a . ?a prov:qualifiedUsage/prov:entity ?p . ?p a wfdesc:Workflow "
   "FILTER(?t IN (wfprov:WorkflowRun, wfprov:ProcessRun)) }",
 "Jeder Input: used + prov:hadRole":
   "ASK { ?a a wfprov:WorkflowRun ; prov:qualifiedUsage [ prov:entity ?e ; prov:hadRole ?r ] . ?e a wfprov:Artifact }",
 "Jedes Ergebnis: wasGeneratedBy Job-Aktivität + prov:hadRole":
   "ASK { ?e a wfprov:Artifact ; prov:qualifiedGeneration [ prov:activity ?a ; prov:hadRole ?r ] . ?a a wfprov:WorkflowRun }",
 "Empfohlen: Start-/Endzeit der Job-Aktivität":
   "ASK { ?a a wfprov:WorkflowRun ; prov:startedAtTime ?s ; prov:endedAtTime ?e }",
 "Empfohlen: SoftwareAgent":
   "ASK { ?ag a prov:SoftwareAgent }",
}
ok = True
for name, q in checks.items():
    r = bool(g.query(P + q).askAnswer); ok &= r
    print(("✔" if r else "✘"), name)
sys.exit(0 if ok else 1)
