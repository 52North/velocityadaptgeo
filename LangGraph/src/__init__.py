"""The LangGraph backend."""

from pathlib import Path

from dotenv import load_dotenv

# Loaded here, before any `src.` module, since most of them read their settings at import time.
# Without override: a variable already set by the shell, compose or `src.batch --variant` wins.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
