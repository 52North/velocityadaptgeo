"""Every retriever node hands auto_build candidates of the same shape."""

import asyncio

from src.llm.nodes import retriever
from tests.fakes import STATE

ROW = ("http://pygeoapi:80/", "buffer", "Buffer", "Buffers a geometry.",
       {"inputs": {"geometry": {}, "distance": {}}, "outputs": {"result": {}}})
CANDIDATE_KEYS = ["server_url", "process_id", "title", "description", "inputs", "outputs"]


def test_catalog_candidates_have_the_search_shape(monkeypatch):
    from src.llm.tools.ogc_client import _candidate

    monkeypatch.setattr(retriever, "list_ogc_processes", lambda: [_candidate(ROW)])
    result = asyncio.run(retriever.catalog_retriever_node(STATE, llm=None))

    [candidate] = result["candidate_processes"]
    assert list(candidate) == CANDIDATE_KEYS
    assert candidate["inputs"] == {"geometry": {}, "distance": {}}
    assert "Catalog processes:" in result["messages"][0].content


def test_catalog_failure_is_logged_not_raised(monkeypatch):
    def broken():
        raise ConnectionError("no database")

    monkeypatch.setattr(retriever, "list_ogc_processes", broken)
    result = asyncio.run(retriever.catalog_retriever_node(STATE, llm=None))

    assert result["candidate_processes"] == []
    assert result["decision_history"][-1]["error"] == "no database"


def test_catalog_text_loses_hidden_characters_but_not_names():
    from src.llm.tools.ogc_client import _candidate

    hidden = "Buffers\u200b a geometry.\u202e\U000e0041\x07\nSecond line."
    row = (*ROW[:3], hidden, {"inputs": {"geo\u200bmetry": {"description": "in\u2066put"}}, "outputs": {}})
    candidate = _candidate(row)

    assert candidate["description"] == "Buffers a geometry.\nSecond line."
    # Names stay exact: an edge must match the server's spelling.
    assert candidate["inputs"] == {"geo\u200bmetry": {"description": "input"}}
