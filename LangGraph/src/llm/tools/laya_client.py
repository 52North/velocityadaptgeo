"""Client for the Laya decision model, served by the `laya` compose service (`laya-serve`).

Laya answers typed questions about a state in one forward pass (no text generation). Here it
is asked the manager's `next_action`, on the state `management.decision_state` builds. See
metrics/.docs/laya_finetune_plan.md.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

LAYA_URL = os.environ.get("LAYA_URL", "http://laya:8000")
LAYA_API_KEY = os.environ.get("LAYA_API_KEY")
# The checkpoint to answer with: pinned, since a JSON state carries no language evidence and
# laya-serve's router would otherwise fall back to its multilingual checkpoint.
LAYA_MODEL = os.environ.get("LAYA_MODEL", "english")
# The token budgets the fine-tune trains with (state = max_len - head_max_len), so the zero-shot
# baseline and the fine-tuned checkpoint see the same truncation.
LAYA_MAX_LEN = int(os.environ.get("LAYA_MAX_LEN", "1024"))
LAYA_HEAD_MAX_LEN = int(os.environ.get("LAYA_HEAD_MAX_LEN", "256"))
# CPU inference takes 0.2-0.5 s; the first request after a restart can take longer.
LAYA_TIMEOUT = float(os.environ.get("LAYA_TIMEOUT", "30"))

# The criteria keys must stay the manager's ALLOWED_ACTIONS. Shared by the live client and the
# training export, so the model is asked the same question it was trained on.
NEXT_ACTION = {
    "next_action": {
        "type": "choice",
        "instructions": "What should the geospatial workflow manager do next?",
        "criteria": {
            "search": "a capability the goal needs is not yet a node in the graph",
            "build": "the user asked to edit, wire or remove existing nodes",
            "validate": "the graph was edited by hand and not yet validated",
            "chat": "greeting or question about an earlier answer; nothing to build",
            "done": "every needed capability is in the graph, or only unmet ones remain",
        },
    }
}


async def predict(state: dict, questions: dict) -> dict:
    """POST one state and its questions to `/v1/systemone`; returns the response body."""
    headers = {"Authorization": f"Bearer {LAYA_API_KEY}"} if LAYA_API_KEY else {}
    body = {
        "state": state,
        "questions": questions,
        "model": LAYA_MODEL,
        "max_len": LAYA_MAX_LEN,
        "head_max_len": LAYA_HEAD_MAX_LEN,
    }
    async with httpx.AsyncClient(timeout=LAYA_TIMEOUT) as client:
        resp = await client.post(
            f"{LAYA_URL.rstrip('/')}/v1/systemone", json=body, headers=headers
        )
        resp.raise_for_status()
        return resp.json()


async def shadow_next_action(state: dict) -> dict:
    """Laya's pick for `next_action`, to log next to Haiku's. Never raises: a failure is logged.

    `answer_confidence` is the chosen option's probability; `confidence` is Laya's own
    (normalised entropy over the options). `state_tokens` and `truncated` show whether the
    state fit the budget.
    """
    started = time.perf_counter()
    try:
        body = await predict(state, NEXT_ACTION)
        answer = body["answers"]["next_action"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Laya shadow prediction failed: %r", exc)
        return {"error": repr(exc), "ms": round((time.perf_counter() - started) * 1000)}
    usage = body.get("usage") or {}
    return {
        "choice": answer.get("choice"),
        "probabilities": answer.get("probabilities"),
        "answer_confidence": answer.get("answer_confidence"),
        "confidence": answer.get("confidence"),
        "model": (body.get("routing") or {}).get("model"),
        "state_tokens": usage.get("state_tokens"),
        "state_tokens_dropped": usage.get("state_tokens_dropped"),
        "truncated": usage.get("truncated"),
        "ms": round((time.perf_counter() - started) * 1000),
    }
