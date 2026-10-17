from pathlib import Path

import yaml

from app.main import build_pipeline
from core.implementations.dummy_reranker import DummyReranker
from core.implementations.simple_reranker import SimpleReranker
from core.registry.reranker_registry import RerankerRegistry


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _retrieval_config(tmp_path: Path, *, reranking_enabled: bool, provider: str = "simple") -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {
                "enabled": True,
                "active_evaluator": "dummy",
                "evaluators": {"dummy": {"provider": "dummy"}},
            },
            "reranking": {
                "enabled": reranking_enabled,
                "active_reranker": provider,
                "strategy": "lexical_hybrid",
                "top_k": 3,
                "rerankers": {
                    "simple": {"provider": "simple"},
                    "dummy": {"provider": "dummy"},
                },
            },
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
            "observability": {"low_retrieval_score_threshold": 0.0},
        },
    )


def _build(tmp_path: Path, *, reranking_enabled: bool, provider: str = "simple"):
    return build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(tmp_path, reranking_enabled=reranking_enabled, provider=provider)
        ),
    )


def test_registry_enabled_by_default_when_flag_absent(tmp_path):
    config_path = _write_yaml(
        tmp_path / "retrieval.yaml",
        {"retrieval": {"default_retriever": "dummy", "retrievers": {"dummy": {"provider": "dummy"}}}},
    )
    registry = RerankerRegistry(config_path)
    assert registry.is_enabled() is True
    assert isinstance(registry.create(), SimpleReranker)


def test_registry_disabled_by_config(tmp_path):
    registry = RerankerRegistry(_retrieval_config(tmp_path, reranking_enabled=False))
    assert registry.is_enabled() is False
    assert registry.create() is None


def test_create_enabled_override_forces_reranker(tmp_path):
    registry = RerankerRegistry(_retrieval_config(tmp_path, reranking_enabled=False))
    assert isinstance(registry.create(enabled=True), SimpleReranker)


def test_create_disabled_override_suppresses_reranker(tmp_path):
    registry = RerankerRegistry(_retrieval_config(tmp_path, reranking_enabled=True))
    assert registry.create(enabled=False) is None


def test_create_selects_configured_provider(tmp_path):
    registry = RerankerRegistry(
        _retrieval_config(tmp_path, reranking_enabled=True, provider="dummy")
    )
    assert isinstance(registry.create(), DummyReranker)


def test_composition_passes_no_reranker_when_disabled(tmp_path):
    assert _build(tmp_path, reranking_enabled=False).reranker is None


def test_pipeline_skips_reranking_stage_when_disabled(tmp_path):
    pipeline = _build(tmp_path, reranking_enabled=False)

    result = pipeline.run("machine learning")

    assert result["failure_tags"] == []
    observability = result["observability"]
    assert observability["reranker"] == "none"
    assert observability["reranking_enabled"] is False
    assert observability["latency"]["reranking_ms"] == 0.0
    assert result["retrieval_scores"] == observability["initial_retrieval_scores"]


def test_pipeline_runs_reranking_stage_when_enabled(tmp_path):
    pipeline = _build(tmp_path, reranking_enabled=True)

    result = pipeline.run("machine learning")

    observability = result["observability"]
    assert observability["reranking_enabled"] is True
    assert observability["reranker"] == "SimpleReranker"


def test_toggling_enabled_changes_observability(tmp_path):
    disabled = _build(tmp_path, reranking_enabled=False)
    enabled = _build(tmp_path, reranking_enabled=True)

    assert disabled.reranker is None
    assert enabled.reranker is not None
    assert disabled.run("machine learning")["observability"]["reranking_enabled"] is False
    assert enabled.run("machine learning")["observability"]["reranking_enabled"] is True
