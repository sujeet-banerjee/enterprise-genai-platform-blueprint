"""Issue #124 (K): eval dataset schema + loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.evaluation.eval_datasets import (
    EvalDataset,
    EvalDatasetValidationError,
    discover_eval_datasets,
    load_eval_dataset,
    parse_dataset_payload,
    validate_eval_dataset_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_legacy_benchmark_json_schema():
    ds = load_eval_dataset(REPO_ROOT / "data" / "benchmark.json", name="benchmark")
    assert isinstance(ds, EvalDataset)
    assert ds.kind == "ir_benchmark"
    assert ds.name == "benchmark"
    assert ds.format == "json"
    assert len(ds.docs) == 6
    assert len(ds.cases) == 6
    assert ds.cases[0].query
    assert ds.cases[0].relevant_doc_ids == (0,)
    # reference synthesized from relevant docs for RAG-style consumers
    assert "intelligence" in ds.cases[0].reference.lower()


def test_parse_rag_case_list_with_aliases_and_metadata():
    payload = [
        {
            "question": "What is RAG?",
            "ground_truth": ["Retrieval", "augmented"],
            "tags": "rag",
            "domain": "retrieval",
            "metadata": {"owner": "k"},
        },
        {"input": "Q2", "expected_answer": "A2", "labels": ["qa"]},
    ]
    ds = parse_dataset_payload(payload, name="qa", fmt="json")
    assert ds.kind == "rag_eval"
    assert len(ds.cases) == 2
    assert ds.cases[0].query == "What is RAG?"
    assert ds.cases[0].reference == "Retrieval augmented"
    assert ds.cases[0].tags == ("rag",)
    assert ds.cases[0].metadata["owner"] == "k"
    assert ds.cases[0].metadata["domain"] == "retrieval"
    assert ds.cases[1].tags == ("qa",)


def test_load_jsonl_case_list(tmp_path):
    path = _write(
        tmp_path / "domain.jsonl",
        '{"query":"Q1","reference":"A1","tags":["t1"]}\n\n{"query":"Q2","expected":"A2"}\n',
    )
    ds = load_eval_dataset(path, name="domain")
    assert ds.format == "jsonl"
    assert [c.query for c in ds.cases] == ["Q1", "Q2"]
    assert [c.reference for c in ds.cases] == ["A1", "A2"]


def test_discover_from_config_loads_declared_datasets(tmp_path):
    # domain-specific JSONL + built-in benchmark path resolved from repo root
    local = _write(tmp_path / "support.jsonl", '{"query":"How reset?","reference":"Use portal."}\n')
    cfg = {
        "eval_datasets": {
            "enabled": True,
            "default_dataset": "support",
            "datasets": {
                "support": {"path": str(local), "domain": "support", "task": "qa"},
                "benchmark": "data/benchmark.json",
            },
        }
    }
    found = discover_eval_datasets(cfg)
    assert [d.name for d in found] == ["support", "benchmark"]
    assert found[0].metadata["domain"] == "support"
    assert found[0].metadata["task"] == "qa"
    assert found[1].kind == "ir_benchmark"


def test_discover_disabled_returns_empty_unless_paths_given(tmp_path):
    local = _write(tmp_path / "x.json", '[{"query":"q","reference":"r"}]')
    cfg = {"eval_datasets": {"enabled": False, "datasets": {"x": str(local)}}}
    assert discover_eval_datasets(cfg) == []
    explicit = discover_eval_datasets({"enabled": False}, paths=[local])
    assert len(explicit) == 1 and explicit[0].cases[0].query == "q"


def test_validation_errors_are_clear(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(EvalDatasetValidationError, match="not found"):
        load_eval_dataset(missing)

    bad_fmt = _write(tmp_path / "x.csv", "a,b")
    with pytest.raises(EvalDatasetValidationError, match="Unsupported"):
        load_eval_dataset(bad_fmt)

    empty = _write(tmp_path / "e.json", '{"cases":[]}')
    with pytest.raises(EvalDatasetValidationError, match="at least one case"):
        load_eval_dataset(empty)

    no_query = _write(tmp_path / "q.json", '[{"reference":"r"}]')
    with pytest.raises(EvalDatasetValidationError, match="missing a non-empty query"):
        load_eval_dataset(no_query)

    bad_jsonl = _write(tmp_path / "b.jsonl", '{"query":"q"}\n{not json}\n')
    with pytest.raises(EvalDatasetValidationError, match="invalid JSONL at line 2"):
        load_eval_dataset(bad_jsonl)


def test_validate_eval_dataset_file_summary(tmp_path):
    path = _write(tmp_path / "ok.jsonl", '{"query":"q","reference":"r"}\n')
    out = validate_eval_dataset_file(path)
    assert out["ok"] is True
    assert out["dataset"]["num_cases"] == 1
    assert out["dataset"]["kind"] == "rag_eval"


def test_parse_wrapped_payload_preserves_dataset_metadata():
    ds = parse_dataset_payload(
        {"name": "legal", "domain": "legal", "version": "1", "cases": [{"query": "q"}]},
        name="fallback",
    )
    assert ds.name == "legal"
    assert ds.metadata["domain"] == "legal"
    assert ds.metadata["version"] == "1"
