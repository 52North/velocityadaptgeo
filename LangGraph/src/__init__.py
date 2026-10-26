"""The LangGraph backend."""

from pathlib import Path

# Loaded here, before any `src.` module, since most of them read their settings at import time.
# Without override: a variable already set by the shell, compose or `src.batch --variant` wins.
# Skipped without python-dotenv: metrics/report imports `src.batch` with the standard library only.
try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
