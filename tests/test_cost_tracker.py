"""Tests for issue #14: cost must reflect token counts and per-model pricing.

Acceptance criteria:
1. Cost reflects token counts and the active model's configured rates.
2. Changing pricing in config changes reported/enforced cost.
"""

import time
from pathlib import Path

import yaml

from app.main import build_pipeline
from core.services.cost_tracker import (
    DEFAULT_INPUT_COST_PER_1K,
    DEFAULT_OUTPUT_COST_PER_1K,
    CostTracker,
)
from core.services.failure_classifier import FailureType


def test_cost_computed_from_token_counts_and_rates():
    tracker = CostTracker(input_cost_per_1k=0.03, output_cost_per_1k=0.06)

    result = tracker.compute("gpt-4", time.time(), input_tokens=1000, output_tokens=500)

    # 1000/1000 * 0.03 + 500/1000 * 0.06 = 0.03 + 0.03
    assert result["estimated_cost_usd"] == 0.06
    assert result["input_tokens"] == 1000
    assert result["output_tokens"] == 500


def test_changing_rates_changes_reported_cost():
    cheap = CostTracker(input_cost_per_1k=0.001, output_cost_per_1k=0.002)
    pricey = CostTracker(input_cost_per_1k=0.03, output_cost_per_1k=0.06)

    cheap_result = cheap.compute("m", time.time(), input_tokens=1000, output_tokens=1000)
    pricey_result = pricey.compute("m", time.time(), input_tokens=1000, output_tokens=1000)

    assert cheap_result["estimated_cost_usd"] < pricey_result["estimated_cost_usd"]


def test_zero_pricing_yields_zero_cost():
    tracker = CostTracker(input_cost_per_1k=0.0, output_cost_per_1k=0.0)

    result = tracker.compute("local-model", time.time(), input_tokens=5000, output_tokens=100)

    assert result["estimated_cost_usd"] == 0.0


def test_missing_pricing_uses_documented_defaults():
    tracker = CostTracker()

    result = tracker.compute("unpriced-model", time.time(), input_tokens=1000, output_tokens=1000)

    expected = (1000 / 1000.0) * DEFAULT_INPUT_COST_PER_1K + (1000 / 1000.0) * DEFAULT_OUTPUT_COST_PER_1K
    assert result["estimated_cost_usd"] == expected
    assert result["input_cost_per_1k"] == DEFAULT_INPUT_COST_PER_1K
    assert result["output_cost_per_1k"] == DEFAULT_OUTPUT_COST_PER_1K


def test_model_pricing_map_resolves_by_model_name():
    tracker = CostTracker(
        model_pricing={"gpt-4": {"input_cost_per_1k": 0.03, "output_cost_per_1k": 0.06}}
    )

    result = tracker.compute("gpt-4", time.time(), input_tokens=1000, output_tokens=0)

    assert result["estimated_cost_usd"] == 0.03


def test_rates_are_surface_in_result():
    tracker = CostTracker(input_cost_per_1k=0.03, output_cost_per_1k=0.06)

    result = tracker.compute("gpt-4", time.time(), input_tokens=10, output_tokens=5)

    assert result["input_cost_per_1k"] == 0.03
    assert result["output_cost_per_1k"] == 0.06
    assert "latency_ms" in result
    assert result["model"] == "gpt-4"


def test_no_token_counts_yields_zero_cost():
    tracker = CostTracker(input_cost_per_1k=0.03, output_cost_per_1k=0.06)

    result = tracker.compute("gpt-4", time.time())

    assert result["estimated_cost_usd"] == 0.0
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _pipeline_configs(tmp_path: Path, model_pricing: dict | None, max_cost: float, name: str = "cfg"):
    workdir = tmp_path / name
    workdir.mkdir(exist_ok=True)
    models = _write_yaml(
        workdir / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096, **(model_pricing or {})}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )
    retrieval = _write_yaml(
        workdir / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "similarity_metric": "cosine",
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "governance": {"enabled": True, "max_cost_per_request_usd": max_cost},
            "evaluation": {"enabled": False},
            "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
            "observability": {"low_retrieval_score_threshold": 0.0},
        },
    )
    return models, retrieval


def test_pipeline_reports_configured_pricing(tmp_path):
    models, retrieval = _pipeline_configs(
        tmp_path,
        model_pricing={"input_cost_per_1k": 10.0, "output_cost_per_1k": 20.0},
        max_cost=1_000_000.0,
    )

    pipeline = build_pipeline(
        models_config_path=Path(models), retrieval_config_path=Path(retrieval)
    )
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    cost = result["cost"]
    assert cost["input_cost_per_1k"] == 10.0
    assert cost["output_cost_per_1k"] == 20.0
    assert cost["input_tokens"] > 0
    assert cost["output_tokens"] > 0
    expected = (cost["input_tokens"] / 1000.0) * 10.0 + (cost["output_tokens"] / 1000.0) * 20.0
    assert abs(cost["estimated_cost_usd"] - expected) < 1e-12


def test_changing_pricing_in_config_changes_enforced_cost(tmp_path):
    # Same token budget, same governance threshold; only pricing differs.
    max_cost = 0.001
    free_models, free_retrieval = _pipeline_configs(
        tmp_path,
        model_pricing={"input_cost_per_1k": 0.0, "output_cost_per_1k": 0.0},
        max_cost=max_cost,
        name="free",
    )
    pricey_models, pricey_retrieval = _pipeline_configs(
        tmp_path,
        model_pricing={"input_cost_per_1k": 1000.0, "output_cost_per_1k": 1000.0},
        max_cost=max_cost,
        name="pricey",
    )

    free_pipeline = build_pipeline(
        models_config_path=Path(free_models), retrieval_config_path=Path(free_retrieval)
    )
    pricey_pipeline = build_pipeline(
        models_config_path=Path(pricey_models), retrieval_config_path=Path(pricey_retrieval)
    )

    free_result = free_pipeline.run("What is artificial intelligence?", raise_on_failure=False)
    pricey_result = pricey_pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert free_result["failure_tags"] == []
    assert FailureType.COST_LIMIT_EXCEEDED.value in pricey_result["failure_tags"]


def test_unpriced_model_still_governed_via_defaults(tmp_path):
    models, retrieval = _pipeline_configs(tmp_path, model_pricing=None, max_cost=0.0)

    pipeline = build_pipeline(
        models_config_path=Path(models), retrieval_config_path=Path(retrieval)
    )
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    # No pricing declared -> default rates are non-zero, so a zero budget trips.
    assert FailureType.COST_LIMIT_EXCEEDED.value in result["failure_tags"]
    assert result["cost"]["input_cost_per_1k"] == DEFAULT_INPUT_COST_PER_1K


def test_cost_governor_allows_generous_budget(tmp_path):
    models, retrieval = _pipeline_configs(
        tmp_path, model_pricing={"input_cost_per_1k": 0.03, "output_cost_per_1k": 0.06}, max_cost=1.0
    )

    pipeline = build_pipeline(
        models_config_path=Path(models), retrieval_config_path=Path(retrieval)
    )
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert result["failure_tags"] == []
    assert result["cost"]["estimated_cost_usd"] <= 1.0


def test_governance_disabled_reports_cost_without_enforcement(tmp_path):
    models, retrieval = _pipeline_configs(
        tmp_path,
        model_pricing={"input_cost_per_1k": 1000.0, "output_cost_per_1k": 1000.0},
        max_cost=0.0000001,
    )

    pipeline = build_pipeline(
        models_config_path=Path(models), retrieval_config_path=Path(retrieval)
    )
    # Flip governance off after construction: cost is still reported, never enforced.
    pipeline.cost_governor = None
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert result["failure_tags"] == []
    assert result["cost"]["estimated_cost_usd"] > 0.0
