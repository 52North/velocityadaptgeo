"""Validiert ein PROV-JSON-Dokument gegen das 52N-Provenance-Profil (Building Block
"Cool Spot Workflow Provenance Profile", ein Profil von ogc.ogc-utils.prov).

    uv run python validate_prov.py prov/job_prov.json [weitere.json ...]

Die Schemas werden online geladen (GitHub bzw. OGC-Building-Block-Register).
"""
import json
import sys
import urllib.request
from functools import lru_cache

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

PROFILE_SCHEMA_URL = (
    "https://raw.githubusercontent.com/52North/bblocks-openscience/ospd26_52north/"
    "_sources/52n-provenance/cool-spots/schema.yaml"
)
# Building-Block-Referenzen (`bblocks://<id>`) -> veröffentlichtes Schema im OGC-Register
# (https://ogcincubator.github.io/bblock-prov-schema/build/register.json).
BBLOCK_SCHEMAS = {
    "ogc.ogc-utils.prov": "https://ogcincubator.github.io/bblock-prov-schema/build/annotated/ogc-utils/prov/schema.json",
}


@lru_cache(maxsize=None)
def _fetch(url: str) -> dict:
    if url.startswith("bblocks://"):
        url = BBLOCK_SCHEMAS[url.removeprefix("bblocks://")]
    with urllib.request.urlopen(url, timeout=30) as resp:
        return yaml.safe_load(resp.read())  # YAML ist Obermenge von JSON


def _retrieve(uri: str) -> Resource:
    return Resource.from_contents(_fetch(uri))


def validator() -> Draft202012Validator:
    registry = Registry(retrieve=_retrieve)
    return Draft202012Validator(_fetch(PROFILE_SCHEMA_URL), registry=registry, format_checker=FormatChecker())


def _deepest(err):
    """oneOf/anyOf-Fehler bis zur konkretesten Ursache (tiefster Instanzpfad) verfolgen."""
    def walk(e):
        yield e
        for sub in e.context or ():
            yield from walk(sub)
    leaves = [e for e in walk(err) if not e.context]
    return max(leaves, key=lambda e: len(e.absolute_path), default=err)


def validate(doc) -> list[str]:
    """Liefert eine Liste von Fehlermeldungen; leer = gültig."""
    v = validator()
    if v.is_valid(doc):
        return []
    # Die Wurzel ist ein anyOf (Liste | Entity | Activity) - dessen Fehlermeldung ist nutzlos.
    # Bei einer Liste daher jedes Element einzeln prüfen und den aussagekräftigsten Fehler melden.
    items = list(enumerate(doc)) if isinstance(doc, list) else [(None, doc)]
    messages = []
    for i, item in items:
        candidate = [item] if i is not None else item
        if (err := best_match(v.iter_errors(candidate))) is None:
            continue
        err = _deepest(err)
        path = list(err.absolute_path)[1:] if i is not None else list(err.absolute_path)
        where = "/".join(map(str, ([i] if i is not None else []) + path)) or "<root>"
        label = f" ({item.get('id')})" if isinstance(item, dict) and item.get("id") else ""
        messages.append(f"{where}{label}: {err.message[:300]}")
    return messages or ["<root>: document does not match the schema"]


if __name__ == "__main__":
    ok = True
    for path in sys.argv[1:] or ["prov/job_prov.json"]:
        with open(path) as f:
            errors = validate(json.load(f))
        ok &= not errors
        print(("✔" if not errors else "✘"), path)
        for msg in errors:
            print("   ", msg)
    sys.exit(0 if ok else 1)
