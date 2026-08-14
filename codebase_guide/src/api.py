"""HTTP surface for the guide: an `APIRouter` that mounts anywhere.

A router rather than an app, so the guide can be attached to an existing FastAPI service
(`app.include_router(guide_router(config))`) or served standalone from `app.py`.

The index and agent are built once, lazily, on the first request. Indexing and model
setup take seconds and would otherwise be paid at import time by every process that
merely mounts the router. Only `POST /guide/ask` needs the `agent` extra; the three
lookup endpoints work on an install without it, which is why nothing from `.agent` is
imported at module level.

One repository per process: the index is module state, because the router's paths are
fixed and mounting the same router twice would collide anyway. To serve several repos,
mount several processes, or call the tools directly with your own `GuideIndex`.
"""

import logging
import threading
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import GuideConfig
from .index import GuideIndex, open_index

logger = logging.getLogger("codebase-guide")

router = APIRouter(prefix="/guide", tags=["codebase-guide"])

_state: dict = {}

# The lazy first-request build is not free: `open_index` may parse the whole repo and
# building the agent constructs a chat client. Two requests arriving on a cold process
# would otherwise both do all of it, which is what "built once" is supposed to prevent.
# Reentrant because `_agent()` builds the index it needs from inside the lock.
_build_lock = threading.RLock()


class AskRequest(BaseModel):
    """One question for the guide, optionally continuing an earlier thread."""

    question: str
    thread_id: str | None = None


class AskResponse(BaseModel):
    """The guide's answer, plus the thread id to reuse for follow-ups."""

    answer: str
    thread_id: str
    repo: str
    backend: str


class OverviewResponse(BaseModel):
    """The architecture briefing and index statistics for the indexed repo."""

    repo: str
    backend: str
    commit: str
    stats: dict
    digest: str


def configure(config: GuideConfig | None = None, index: GuideIndex | None = None) -> None:
    """Point the router at a repository, replacing any previous one.

    Call before serving to explain a repo other than the default (`$GUIDE_REPO_ROOT`
    or the working directory), or to inject an index built elsewhere.

    Args:
        config: Target repo configuration.
        index: A pre-opened index. Takes precedence over `config`.
    """
    _state.clear()
    if config is not None:
        _state["config"] = config
    if index is not None:
        _state["index"] = index


def guide_router(config: GuideConfig | None = None, index: GuideIndex | None = None):
    """Configure the guide and return its router, for one-line mounting.

    Equivalent to `configure(...)` followed by using `router`, which is the form to
    reach for when the two steps need to happen at different times.

    Args:
        config: Target repo configuration. Defaults to `$GUIDE_REPO_ROOT` or the
            working directory, resolved on the first request.
        index: A pre-opened index, taking precedence over `config`.

    Returns:
        The `APIRouter` to hand to `app.include_router`.
    """
    configure(config=config, index=index)
    return router


def _index() -> GuideIndex:
    """Return the open index, opening it on first use.

    Double-checked: the lock is only taken on the cold path, so every request after the
    first sees a plain dictionary lookup.
    """
    if "index" not in _state:
        with _build_lock:
            if "index" not in _state:
                config = _state.get("config") or GuideConfig.load()
                _state["config"] = config
                _state["index"] = open_index(config)
    return _state["index"]


def _agent():
    """Return the compiled agent, building it on first use.

    The `agent` extra is imported here rather than at module level. Mounting this router
    must not require langgraph: `POST /guide/ask` is the only endpoint that answers with
    a model, and an import at the top would make the three lookup endpoints unreachable
    on a `[serve,vector]` install - a `ModuleNotFoundError` raised by `guide_router`
    itself, long before anyone asked a question.

    Raises:
        ImportError: The `agent` extra is not installed.
    """
    if "agent" not in _state:
        with _build_lock:
            if "agent" not in _state:
                from .agent import build_guide_agent

                _state["agent"] = build_guide_agent(_index())
    return _state["agent"]


def _open_index_or_503() -> GuideIndex:
    """Open the index, turning a failed build into a diagnosable response.

    Opening can fail for reasons that are not the caller's business and not a bug in
    this service - an unreadable map, an unwalkable root. An unhandled 500 makes that
    look like a crash, so it is reported as 503 with a reference into the log. The
    message deliberately carries no detail: a failure here often wraps a psycopg
    connection error, which names the database host, port and user.

    Returns:
        The open index.

    Raises:
        HTTPException: 503, when the index cannot be opened.
    """
    try:
        return _index()
    except Exception as exc:
        reference = uuid4().hex[:8]
        logger.exception("Index unavailable [ref %s]", reference)
        raise HTTPException(
            status_code=503,
            detail=f"index unavailable; see server log for ref {reference}",
        ) from exc


@router.post("/ask", response_model=AskResponse)
def ask_guide(request: AskRequest) -> AskResponse:
    """Ask the guide a question about the indexed codebase."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    thread_id = request.thread_id or str(uuid4())
    index = _open_index_or_503()
    try:
        # Same lazy seam as `_agent()`, for the same reason.
        from .agent import ask

        answer = ask(_agent(), question, thread_id=thread_id)
    except ImportError as exc:
        logger.warning("Answering is unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="answering requires the 'agent' extra "
                   "(pip install codebase-guide[agent]); the lookup endpoints still work",
        ) from exc
    except Exception as exc:
        reference = uuid4().hex[:8]
        logger.exception("Guide failed to answer [ref %s]", reference)
        raise HTTPException(
            status_code=502,
            detail=f"guide failed to answer; see server log for ref {reference}",
        ) from exc

    return AskResponse(
        answer=answer, thread_id=thread_id, repo=index.repo_name, backend=index.backend
    )


@router.get("/overview", response_model=OverviewResponse)
def overview() -> OverviewResponse:
    """Get the architecture briefing without spending a model call."""
    index = _open_index_or_503()
    return OverviewResponse(
        repo=index.repo_name,
        backend=index.backend,
        commit=index.code_map.commit,
        stats=index.code_map.stats(),
        digest=index.digest,
    )


@router.get("/symbols/{qualname}")
def symbol(qualname: str) -> dict:
    """Look up one symbol's doc comment and connections, with no model in the loop.

    Useful for wiring the guide into an editor or a docs page, where the graph is
    wanted but a natural-language answer is not.
    """
    index = _open_index_or_503()
    matches = index.code_map.resolve(qualname)
    if not matches:
        raise HTTPException(status_code=404, detail=f"no symbol named '{qualname}'")
    if len(matches) > 1:
        return {"ambiguous": matches}

    found = index.code_map.symbols[matches[0]]
    return {
        "symbol": {
            "qualname": found.qualname,
            "kind": found.kind,
            "location": found.location,
            "signature": found.signature,
            "doc": found.doc,
            "tags": found.tags,
            "extra": found.extra,
        },
        "neighborhood": index.code_map.neighborhood(found.qualname),
    }


@router.get("/search")
def search(q: str, kind: str = "", limit: int = 8) -> dict:
    """Semantic search over doc comments, returning raw hits.

    `backend` is read after the search, not before, so it reports the backend the hits
    actually came from - a query-time fallback to lexical shows up here.
    """
    index = _open_index_or_503()
    hits = index.search(q, k=max(1, min(limit, 50)), kinds=(kind,) if kind else None)
    return {"backend": index.backend, "hits": [h.to_dict() for h in hits]}
