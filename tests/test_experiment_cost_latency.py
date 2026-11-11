"""Cost and latency telemetry in experiment results (issue #179).

`ExperimentRunner` runs the same pipeline as production (via
`app.bootstrap.assemble_components`), but previously dropped the pipeline's
`cost` block and did not aggregate cost/latency across a comparison. These
tests pin the additive telemetry so cost-effectiveness questions can be
answered from an experiment report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from core.services.experiment_runner import ExperimentRunner

PROMPT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "prompt_config.yaml"

DOCS = [
    {"content": "Artificial intelligence simulates human intelligence."},
    {"content": "Machine learning learns patterns from data."},
    {"content": "Neural networks are inspired by the brain."},
]
QUERY = "What is artificial intelligence?"


def _write_yaml(path: Path, payload: dict) -> str:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def _retrieval_config() -> dict:
    return {
        "retrieval": {
            "default_retriever": "dummy",
            "top_k": 3,
            "similarity_metric": "cosine",
            "retrievers": {"dummy": {"provider": "dummy"}},
        },
        "evaluation": {
            "enabled": True,
            "active_evaluator": "dummy",
            "evaluators": {"dummy": {"provider": "dummy"}},
        },
        "reranking": {
            "enabled": False,
            "active_reranker": "none",
            "rerankers": {"none": {"provider": "none"}},
        },
        "chunking": {
            "active_strategy": "small",
            "strategies": {
                "small": {"chunk_size": 120, "chunk_overlap": 20, "separator": " "},
                "large": {"chunk_size": 400, "chunk_overlap": 0, "separator": " "},
            },
        },
        "token_budget": {"default_mode": "strict", "max_output_cap": 512},
    }


def _make_runner(tmp_path: Path) -> ExperimentRunner:
    models = tmp_path / "models.yaml"
    _write_yaml(
        models,
        {
            "active_model": "dummy",
            "active_embedding_model": "emb-a",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {
                "emb-a": {"provider": "dummy", "model_name": "emb-a"},
                "emb-b": {"provider": "dummy", "model_name": "emb-b"},
            },
        },
    )
    retrieval = tmp_path / "retrieval.yaml"
    _write_yaml(retrieval, _retrieval_config())
    return ExperimentRunner(
        models_config_path=str(models),
        prompt_config_path=str(PROMPT_CONFIG),
        retrieval_config_path=str(retrieval),
    )


def test_run_single_experiment_includes_cost_and_latency_summary(tmp_path):
    runner = _make_runner(tmp_path)
    result = runner.run_single_experiment(docs=DOCS, query=QUERY)

    assert isinstance(result["cost"], dict)
    assert result["cost"]["estimated_cost_usd"] > 0
    assert result["cost_usd"] == result["cost"]["estimated_cost_usd"]

    summary = result["latency_summary"]
    assert set(summary) == {"total_ms", "stages", "slowest_stage", "slowest_stage_ms"}
    assert summary["total_ms"] > 0
    assert summary["stages"], "expected per-stage latencies"
    assert summary["slowest_stage"] in summary["stages"]
    assert summary["slowest_stage_ms"] == summary["stages"][summary["slowest_stage"]]


def test_latency_summary_filters_alias_and_total_keys():
    summary = ExperimentRunner._latency_summary(
        {
            "retrieval": 10.0,
            "retrieval_ms": 10.0,
            "llm_generation": 30.0,
            "llm_generation_ms": 30.0,
            "total_pipeline": 40.0,
            "total_pipeline_ms": 40.0,
            "total_ms": 40.0,
        }
    )
    assert summary["stages"] == {"retrieval": 10.0, "llm_generation": 30.0}
    assert summary["total_ms"] == 40.0
    assert summary["slowest_stage"] == "llm_generation"
    assert summary["slowest_stage_ms"] == 30.0


def test_summarize_run_keeps_only_numeric_quality_metrics():
    run: Dict[str, Any] = {
        "metrics": {"faithfulness": 0.9, "retrieval_recall": 0.8, "label": "x", "flag": True},
        "cost": {"estimated_cost_usd": 0.0123},
        "latency": {"total_ms": 42.0},
    }
    summary = ExperimentRunner.summarize_run(run)
    assert summary["cost_usd"] == 0.0123
    assert summary["total_latency_ms"] == 42.0
    assert summary["quality"] == {"faithfulness": 0.9, "retrieval_recall": 0.8}


def test_summarize_run_handles_missing_cost_and_latency():
    summary = ExperimentRunner.summarize_run({})
    assert summary == {"cost_usd": 0.0, "total_latency_ms": 0.0, "quality": {}}


def test_compare_embedding_models_includes_summary(tmp_path):
    runner = _make_runner(tmp_path)
    result = runner.compare_embedding_models(
        docs=DOCS, query=QUERY, model_names=["emb-a", "emb-b"]
    )

    summary = result["summary"]
    assert summary["count"] == 2
    assert set(summary["runs"]) == {"emb-a", "emb-b"}
    assert summary["quality_metric"] == "faithfulness"
    assert summary["best_quality"]["metric"] == "faithfulness"
    assert summary["total_cost_usd"] == sum(
        run["cost_usd"] for run in summary["runs"].values()
    )
    assert summary["avg_cost_usd"] == summary["total_cost_usd"] / 2
    assert summary["cheapest"]["name"] in {"emb-a", "emb-b"}
    assert summary["fastest"]["name"] in {"emb-a", "emb-b"}
    for run in result["results"].values():
        assert "cost" in run and "latency_summary" in run


def test_compare_chunking_strategies_includes_summary(tmp_path):
    runner = _make_runner(tmp_path)
    result = runner.compare_chunking_strategies(
        docs=DOCS, query=QUERY, strategies=("small", "large")
    )

    summary = result["summary"]
    assert summary["count"] == 2
    assert set(summary["runs"]) == {"small", "large"}
    assert summary["quality_metric"] == "faithfulness"
    assert summary["avg_total_latency_ms"] >= 0


def test_summarize_comparison_selects_cheapest_fastest_and_best_quality():
    runs = {
        "cheap": {
            "metrics": {"faithfulness": 0.5},
            "cost": {"estimated_cost_usd": 0.001},
            "latency": {"total_ms": 90.0},
        },
        "fast": {
            "metrics": {"faithfulness": 0.6},
            "cost": {"estimated_cost_usd": 0.02},
            "latency": {"total_ms": 10.0},
        },
        "best": {
            "metrics": {"faithfulness": 0.95},
            "cost": {"estimated_cost_usd": 0.05},
            "latency": {"total_ms": 50.0},
        },
    }
    summary = ExperimentRunner.summarize_comparison(runs)
    assert summary["cheapest"] == {"name": "cheap", "cost_usd": 0.001}
    assert summary["fastest"] == {"name": "fast", "total_latency_ms": 10.0}
    assert summary["best_quality"] == {
        "name": "best",
        "value": 0.95,
        "metric": "faithfulness",
    }


def test_summarize_comparison_tie_break_is_deterministic():
    runs = {
        "beta": {"metrics": {"faithfulness": 0.7}, "cost": {"estimated_cost_usd": 0.01}},
        "alpha": {"metrics": {"faithfulness": 0.7}, "cost": {"estimated_cost_usd": 0.01}},
    }
    summary = ExperimentRunner.summarize_comparison(runs)
    assert summary["best_quality"]["name"] == "alpha"
    assert summary["cheapest"]["name"] == "alpha"
