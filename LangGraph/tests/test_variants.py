"""The variant registry is the one list every part of the pipeline uses."""

import pytest

from src.llm.variants import DEFAULT_VARIANT, VARIANTS, selected_variant


def test_default_is_registered():
    assert DEFAULT_VARIANT in VARIANTS


def test_names_match_keys():
    assert all(name == variant.name for name, variant in VARIANTS.items())


def test_every_variant_has_a_retriever_node(monkeypatch):
    # Building the module's own graph needs an API key to construct the client, not to call it.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from src.llm.workflow import RETRIEVER_NODES, build_workflow

    for variant in VARIANTS.values():
        assert variant.tools in RETRIEVER_NODES
        build_workflow(variant)


def test_batch_and_metrics_use_the_registry():
    from src import batch, metrics

    assert batch.VARIANTS is VARIANTS
    assert batch.DEFAULT_VARIANT == DEFAULT_VARIANT
    assert metrics.VARIANT in VARIANTS


def test_selected_variant(monkeypatch):
    monkeypatch.delenv("WORKFLOW_VARIANT", raising=False)
    assert selected_variant().name == DEFAULT_VARIANT
    monkeypatch.setenv("WORKFLOW_VARIANT", "mcp")
    assert selected_variant().name == "mcp"
    with pytest.raises(ValueError):
        selected_variant("nope")
