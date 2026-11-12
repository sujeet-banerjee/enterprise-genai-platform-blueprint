"""Config-driven parameter sweep + Pareto report (issue #181).

Fast dummy providers only: no model downloads, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.optimize import main as optimize_main
from core.evaluation.config_sweep import (
    SweepConfigError,
    SweepLimitError,
    expand_combinations,
    gate_recommended,
    load_optimization_config,
    normalize_parameters,
    pareto_frontier,
    recommend_overlay,
    run_sweep,
)
from core.evaluation.eval_datasets import EvalCase, EvalDataset

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_CONFIG = REPO_ROOT / "deployment" / "smoke" / "config"


class _FakeRunner:
    """Deterministic runner keyed by (top_k, reranker)."""

    def __init__(self, table: Dict[Any, Dict[str, float]]):
        self.table = table
        self.calls: List[Dict[str, Any]] = []

    def run_single_experiment(self, docs, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        key = (kwargs.get("top_k"), kwargs.get("use_reranker"))
        spec = self.table[key]
        return {
            "metrics": {"context_recall": spec["q"]},
            "cost_usd": spec["c"],
            "latency_summary": {"total_ms": spec["l"]},
            "retrieved_documents": [],
        }


def _rag_dataset() -> EvalDataset:
    return EvalDataset(
        name="rag",
        path=None,
        format="json",
        cases=[EvalCase(query="q1")],
        docs=[],
    )


def _write_dummy_config(config_dir: Path, top_k: int = 1) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "models.yaml").write_text(
        yaml.safe_dump(
            {
                "active_model": "dummy",
                "active_embedding_model": "dummy",
                "models": {
                    "dummy": {
                        "provider": "dummy",
                        "context_window": 4096,
                        "temperature": 0.0,
                        "max_tokens": 64,
                    }
                },
                "embedding_models": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "prompt_config.yaml").write_text(
        (SMOKE_CONFIG / "prompt_config.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (config_dir / "retrieval.yaml").write_text(
        yaml.safe_dump(
            {
                "retrieval": {
                    "default_retriever": "simple",
                    "top_k": top_k,
                    "similarity_metric": "cosine",
                    "low_score_threshold": 0.0,
                    "avg_chunk_tokens": 128,
                    "retrievers": {"simple": {"provider": "simple"}},
                },
                "evaluation": {"enabled": False},
                "reranking": {"enabled": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_benchmark(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "docs": [{"content": "alpha"}, {"content": "beta"}],
                "cases": [{"query": "alpha", "relevant_doc_ids": [0]}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_normalize_parameters_aliases_and_validation():
    params = normalize_parameters(
        {
            "retriever": ["simple"],
            "embedding": ["dummy"],
            "chunking": ["small"],
            "use_reranker": ["true", False],
            "top_k": ["3", 5],
        }
    )
    assert params["retriever_backend"] == ["simple"]
    assert params["embedding_model"] == ["dummy"]
    assert params["chunk_strategy"] == ["small"]
    assert params["reranker"] == [True, False]
    assert params["top_k"] == [3, 5]

    with pytest.raises(SweepConfigError, match="Unknown sweep parameter"):
        normalize_parameters({"similarity_metric": ["cosine"]})
    with pytest.raises(SweepConfigError, match="at least one value"):
        normalize_parameters({"top_k": []})
    with pytest.raises(SweepConfigError, match="must be >= 1"):
        normalize_parameters({"top_k": [0]})


def test_expand_combinations_is_deterministic_and_complete():
    combos = expand_combinations({"top_k": [3, 5], "reranker": [True, False]})
    assert combos == [
        {"reranker": True, "top_k": 3},
        {"reranker": True, "top_k": 5},
        {"reranker": False, "top_k": 3},
        {"reranker": False, "top_k": 5},
    ]


def test_expand_combinations_respects_max_limit():
    with pytest.raises(SweepLimitError, match="above max_combinations=2"):
        expand_combinations({"top_k": [1, 2, 3]}, max_combinations=2)
    with pytest.raises(SweepConfigError, match="max_combinations must be >= 1"):
        expand_combinations({"top_k": [1]}, max_combinations=0)


def test_pareto_frontier_removes_dominated_rows():
    rows = [
        {"combination_id": "a", "quality": 0.5, "cost_usd": 0.01, "latency_ms": 100},
        {"combination_id": "b", "quality": 0.9, "cost_usd": 0.02, "latency_ms": 200},
        {"combination_id": "c", "quality": 0.9, "cost_usd": 0.03, "latency_ms": 300},
        {"combination_id": "d", "quality": 0.95, "cost_usd": 0.05, "latency_ms": 500},
    ]
    frontier = pareto_frontier(rows)
    assert [row["combination_id"] for row in frontier] == ["a", "b", "d"]


def test_recommend_overlay_prefers_quality_within_budget():
    frontier = [
        {"combination_id": "a", "quality": 0.5, "cost_usd": 0.01, "latency_ms": 100, "p95_latency_ms": 110, "parameters": {"top_k": 1}},
        {"combination_id": "b", "quality": 0.9, "cost_usd": 0.02, "latency_ms": 200, "p95_latency_ms": 220, "parameters": {"top_k": 2}},
        {"combination_id": "d", "quality": 0.95, "cost_usd": 0.05, "latency_ms": 500, "p95_latency_ms": 520, "parameters": {"top_k": 3}},
    ]
    rec = recommend_overlay(
        frontier,
        {"quality": "context_recall", "cost_budget_usd": 0.03, "latency_budget_ms": 400},
    )
    assert rec is not None
    assert rec["combination_id"] == "b"
    assert rec["within_budget"] is True
    assert rec["config_overlay"] == {"retrieval": {"top_k": 2}}


def test_recommend_overlay_flags_infeasible_budget():
    frontier = [
        {"combination_id": "a", "quality": 0.9, "cost_usd": 0.5, "latency_ms": 900, "p95_latency_ms": 950, "parameters": {"top_k": 2}},
    ]
    rec = recommend_overlay(frontier, {"cost_budget_usd": 0.01})
    assert rec is not None
    assert rec["within_budget"] is False


def test_run_sweep_disabled_is_a_noop():
    summary = run_sweep({"enabled": False})
    assert summary["skipped"] is True
    assert summary["recommended"] is None
    assert summary["rows"] == []


def test_run_sweep_empty_parameters_is_a_noop():
    summary = run_sweep({"enabled": True, "parameters": {}})
    assert summary["skipped"] is True
    assert "empty" in summary["reason"]


def test_run_sweep_rows_frontier_and_overlay_with_fake_runner():
    table = {
        (1, False): {"q": 0.5, "c": 0.01, "l": 100},
        (2, False): {"q": 0.9, "c": 0.02, "l": 200},
        (1, True): {"q": 0.6, "c": 0.03, "l": 250},
        (2, True): {"q": 0.9, "c": 0.03, "l": 300},
    }
    runner = _FakeRunner(table)
    summary = run_sweep(
        {
            "enabled": True,
            "parameters": {"top_k": [1, 2], "reranker": [False, True]},
            "objective": {"quality": "context_recall", "cost_budget_usd": 0.03},
        },
        dataset=_rag_dataset(),
        runner=runner,
    )
    assert summary["num_combinations"] == 4
    assert len(summary["rows"]) == 4
    assert summary["pareto_frontier"] == ["combo-0001", "combo-0002"]
    rec = summary["recommended"]
    assert rec["combination_id"] == "combo-0002"
    assert rec["config_overlay"]["retrieval"]["top_k"] == 2
    assert rec["config_overlay"]["reranking"]["enabled"] is False
    assert len(runner.calls) == 4


def test_run_sweep_with_real_dummy_providers(tmp_path):
    config_dir = tmp_path / "config"
    _write_dummy_config(config_dir)
    benchmark = _write_benchmark(tmp_path / "benchmark.json")
    summary = run_sweep(
        {
            "enabled": True,
            "dataset": str(benchmark),
            "max_combinations": 10,
            "parameters": {"top_k": [1, 2]},
            "objective": {
                "quality": "context_recall",
                "cost_budget_usd": 1.0,
                "latency_budget_ms": 60000,
            },
        },
        config_dir=config_dir,
    )
    assert summary["enabled"] is True
    assert summary["num_combinations"] == 2
    assert summary["dataset"]["name"] == "benchmark"
    for row in summary["rows"]:
        assert row["metrics"]["context_recall"] == pytest.approx(1.0)
        assert row["num_cases"] == 1
    assert summary["recommended"] is not None
    assert summary["recommended"]["config_overlay"]["retrieval"]["top_k"] in (1, 2)


def test_gate_recommended_maps_row_to_budget_gate():
    summary = {
        "dataset": {"name": "bench", "num_cases": 1},
        "recommended": {
            "metrics": {"context_recall": 0.9},
            "cost_usd": 0.02,
            "latency_ms": 120.0,
            "p95_latency_ms": 150.0,
        },
    }
    gate = gate_recommended(
        summary,
        {"context_recall": 0.8, "max_cost_per_request_usd": 0.01},
    )
    assert gate is not None
    assert gate["passed"] is False
    assert any("max_cost_per_request_usd" in failure for failure in gate["failures"])


def _write_optimization(path: Path, config: Dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_load_optimization_config_accepts_flat_and_wrapped(tmp_path):
    flat = _write_optimization(tmp_path / "flat.yaml", {"enabled": False, "max_combinations": 5})
    wrapped = _write_optimization(
        tmp_path / "wrapped.yaml", {"optimization": {"enabled": True}}
    )
    assert load_optimization_config(flat)["max_combinations"] == 5
    assert load_optimization_config(wrapped)["enabled"] is True


def test_cli_disabled_config_exits_zero(tmp_path):
    config = _write_optimization(tmp_path / "optimization.yaml", {"enabled": False})
    assert optimize_main(["--config", str(config), "--json"]) == 0


def test_cli_real_sweep_and_gate(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_dummy_config(config_dir)
    benchmark = _write_benchmark(tmp_path / "benchmark.json")
    config = _write_optimization(
        tmp_path / "optimization.yaml",
        {
            "enabled": True,
            "dataset": str(benchmark),
            "max_combinations": 10,
            "parameters": {"top_k": [1, 2]},
            "objective": {
                "quality": "context_recall",
                "cost_budget_usd": 1.0,
                "latency_budget_ms": 60000,
                "min_quality": 0.5,
            },
        },
    )

    assert optimize_main(["--config", str(config), "--config-dir", str(config_dir), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recommended"]["config_overlay"]["retrieval"]["top_k"] in (1, 2)

    assert (
        optimize_main(
            ["--config", str(config), "--config-dir", str(config_dir), "--gate", "--json"]
        )
        == 0
    )
    gated = json.loads(capsys.readouterr().out)
    assert gated["gate"]["passed"] is True

    assert (
        optimize_main(
            [
                "--config",
                str(config),
                "--config-dir",
                str(config_dir),
                "--gate",
                "--threshold",
                "context_recall=1.0001",
                "--json",
            ]
        )
        == 1
    )
    failed = json.loads(capsys.readouterr().out)
    assert failed["gate"]["passed"] is False


def test_cli_rejects_oversized_matrix_and_unknown_parameters(tmp_path, capsys):
    config_dir = tmp_path / "config"
    _write_dummy_config(config_dir)
    benchmark = _write_benchmark(tmp_path / "benchmark.json")
    oversized = _write_optimization(
        tmp_path / "oversized.yaml",
        {
            "enabled": True,
            "dataset": str(benchmark),
            "max_combinations": 1,
            "parameters": {"top_k": [1, 2]},
        },
    )
    assert optimize_main(["--config", str(oversized), "--config-dir", str(config_dir)]) == 2
    assert "above max_combinations" in capsys.readouterr().err

    unknown = _write_optimization(
        tmp_path / "unknown.yaml",
        {"enabled": True, "parameters": {"similarity_metric": ["cosine"]}},
    )
    assert optimize_main(["--config", str(unknown), "--config-dir", str(config_dir)]) == 2
    assert "Unknown sweep parameter" in capsys.readouterr().err
