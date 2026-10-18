"""Tests for issue #10: the ``governance.enabled`` flag must gate the governance services.

Acceptance criteria:
1. ``governance.enabled: false`` disables cost + retrieval-policy enforcement.
2. ``governance.enabled: true`` restores enforcement without code changes.
"""

from pathlib import Path

import yaml

from app.main import build_pipeline
from core.services.failure_classifier import FailureType


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path, context_window: int = 4096) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {
                "dummy": {
                    "provider": "dummy",
                    "context_window": context_window,
                    "temperature": 0.0,
                }
            },
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _retrieval_config(
    tmp_path: Path,
    *,
    enabled: bool | None = True,
    max_cost: float = 0.05,
    top_k: int = 3,
) -> str:
    payload: dict = {
        "retrieval": {
            "default_retriever": "dummy",
            "top_k": top_k,
            "similarity_metric": "cosine",
            "retrievers": {"dummy": {"provider": "dummy"}},
        },
        "evaluation": {"enabled": True, "active_evaluator": "dummy",
                       "evaluators": {"dummy": {"provider": "dummy"}}},
        "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
        "token_budget": {"default_mode": "strict", "max_output_cap": 512},
        "observability": {"low_retrieval_score_threshold": 0.0},
    }
    if enabled is not None:
        payload["governance"] = {
            "enabled": enabled,
            "max_cost_per_request_usd": max_cost,
            "safety_margin_tokens": 200,
        }
    return _write_yaml(tmp_path / "retrieval.yaml", payload)


def _pipeline(tmp_path: Path, *, enabled: bool | None, max_cost: float = 0.05,
              context_window: int = 4096, top_k: int = 3):
    return build_pipeline(
        models_config_path=Path(_models_config(tmp_path, context_window=context_window)),
        retrieval_config_path=Path(
            _retrieval_config(tmp_path, enabled=enabled, max_cost=max_cost, top_k=top_k)
        ),
    )


def test_governance_enabled_attaches_services(tmp_path):
    pipeline = _pipeline(tmp_path, enabled=True)

    assert pipeline.cost_governor is not None
    assert pipeline.retrieval_policy_service is not None


def test_governance_disabled_detaches_services(tmp_path):
    pipeline = _pipeline(tmp_path, enabled=False)

    assert pipeline.cost_governor is None
    assert pipeline.retrieval_policy_service is None


def test_governance_missing_defaults_to_enabled(tmp_path):
    pipeline = _pipeline(tmp_path, enabled=None)

    assert pipeline.cost_governor is not None
    assert pipeline.retrieval_policy_service is not None


def test_governance_enabled_enforces_cost_limit(tmp_path):
    pipeline = _pipeline(tmp_path, enabled=True, max_cost=0.0)

    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert FailureType.COST_LIMIT_EXCEEDED.value in result["failure_tags"]


def test_governance_disabled_skips_cost_limit(tmp_path):
    pipeline = _pipeline(tmp_path, enabled=False, max_cost=0.0)

    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert FailureType.COST_LIMIT_EXCEEDED.value not in result["failure_tags"]


def test_governance_enabled_caps_top_k_disabled_does_not(tmp_path):
    capped = _pipeline(tmp_path, enabled=True, context_window=700, top_k=3)
    uncapped = _pipeline(tmp_path, enabled=False, context_window=700, top_k=3)

    capped_result = capped.run("What is artificial intelligence?", raise_on_failure=False)
    uncapped_result = uncapped.run("What is artificial intelligence?", raise_on_failure=False)

    assert capped_result["observability"]["top_k"] < uncapped_result["observability"]["top_k"]
    assert uncapped_result["observability"]["top_k"] == 3
