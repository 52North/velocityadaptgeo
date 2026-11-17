"""Write the HTTP API's OpenAPI spec to `LangGraph/openapi.json`: `uv run python -m src.openapi`.

With APP_ENV=production the service does not serve its spec, so this file is the published one;
tests/test_app.py fails when it is out of date. It describes every route, the demo frontend's
too; README.md ("HTTP API for other services") says which of them are the contract.
"""

import json
import os
from pathlib import Path

OPENAPI_FILE = Path(__file__).resolve().parent.parent / "openapi.json"


def spec() -> str:
    # The Anthropic client is built when the app is imported, never called here.
    os.environ.setdefault("ANTHROPIC_API_KEY", "unused")
    from src.app import app

    return json.dumps(app.openapi(), indent=2) + "\n"


if __name__ == "__main__":
    OPENAPI_FILE.write_text(spec(), encoding="utf-8")
    print(OPENAPI_FILE)
