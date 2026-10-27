"""Reading the few-shot example files."""

from pathlib import Path

import pytest

from src.fewshot import ExampleError, load_examples, parse_example

EXAMPLES = Path(__file__).resolve().parents[2] / "fewshot_examples"

GOOD = """
id: a
request: "Buffer Munich by 500 m."
solution:
  workflow_graph:
    nodes:
      - {id: c_1, type: city-boundary}
      - {id: b_2, type: buffer}
    edges:
      - {source: c_1, source_output: boundary, target: b_2, target_input: geometry}
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_template_is_a_valid_example():
    example = parse_example(EXAMPLES / "_template.yaml")
    assert example["id"] == "munich-buffer-500m"
    assert example["source_file"] == "_template.yaml"


def test_template_and_readme_are_not_loaded():
    assert load_examples(EXAMPLES) == []


@pytest.mark.parametrize("text, reason", [
    ("id: a\nrequest: r\n", "solution"),
    ("id: ''\nrequest: r\nsolution: {workflow_graph: {nodes: [{id: n, type: t}]}}\n", "id"),
    ("id: a\nrequest: r\nsolution: {workflow_graph: {nodes: []}}\n", "nodes"),
    ("id: a\nrequest: r\nsolution: {workflow_graph: {nodes: [{id: n}]}}\n", "type"),
    ("id: a\nrequest: r\nsolution: {workflow_graph: {nodes: [{id: n, type: t}], edges: [{source: n, target: x, source_output: o, target_input: i}]}}\n", "not in nodes"),
    ("id: a\nrequest: [r\n", "YAML"),
])
def test_broken_examples_are_refused_with_a_reason(tmp_path, text, reason):
    with pytest.raises(ExampleError, match=reason):
        parse_example(write(tmp_path, "x.yaml", text))


def test_broken_files_and_repeated_ids_are_skipped(tmp_path, caplog):
    write(tmp_path, "a.yaml", GOOD)
    write(tmp_path, "b.yaml", GOOD)  # same id as a.yaml
    write(tmp_path, "c.yml", "id: c\n")
    write(tmp_path, "_draft.yaml", "not: loaded\n")
    write(tmp_path, "notes.txt", "ignored")

    examples = load_examples(tmp_path)

    assert [e["source_file"] for e in examples] == ["a.yaml"]
    assert "b.yaml" in caplog.text and "c.yml" in caplog.text and "_draft" not in caplog.text
