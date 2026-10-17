import json
from pathlib import Path

import yaml

from app.main import build_pipeline
from core.implementations.cross_encoder_reranker import CrossEncoderReranker
from core.implementations.dummy_reranker import DummyReranker
from core.implementations.simple_reranker import SimpleReranker
from core.registry.reranker_registry import RerankerRegistry

DOCS = [
    {"content": "Machine Learning is a subset of AI focused on learning from data."},
    {"content": "Neural networks are models inspired by the human brain."},
    {"content": "The cafeteria serves soup on Tuesdays."},
]


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _write_docs(path: Path) -> str:
    path.write_text(json.dumps(DOCS), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "local-qwen",
            "active_embedding_model": "all-MiniLM-L6-v2",
            "models": {
                "local-qwen": {
                    "provider": "local_hf",
                    "model_name": "Qwen/Qwen2.5-0.5B-Instruct",
                    "context_window": 32768,
                    "max_new_tokens": 64,
                },
            },
            "embedding_models": {
                "all-MiniLM-L6-v2": {
                    "provider": "sentence_transformers",
                    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                },
            },
        },
    )


def _retrieval_config(
    tmp_path: Path,
    *,
    reranking_enabled: bool,
    provider: str = "cross_encoder",
    docs_path: str,
) -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "simple",
                "top_k": 3,
                "retrievers": {"simple": {"provider": "simple", "documents_path": docs_path}},
            },
            "evaluation": {
                "enabled": True,
                "active_evaluator": "semantic",
                "evaluators": {
                    "semantic": {
                        "provider": "semantic",
                        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    },
                },
            },
            "reranking": {
                "enabled": reranking_enabled,
                "active_reranker": provider,
                "strategy": "lexical_hybrid",
                "top_k": 3,
                "rerankers": {
                    "simple": {"provider": "simple"},
                    "cross_encoder": {
                        "provider": "cross_encoder",
                        "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                        "top_k": 3,
                    },
                    "dummy": {"provider": "dummy"},
                },
            },
            "token_budget": {"default_mode": "strict", "max_output_cap": 64},
            "observability": {"low_retrieval_score_threshold": 0.0},
        },
    )


def _build(tmp_path: Path, *, reranking_enabled: bool, provider: str = "cross_encoder"):
    docs_path = _write_docs(tmp_path / "docs.json")
    return build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                reranking_enabled=reranking_enabled,
                provider=provider,
                docs_path=docs_path,
            )
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
    registry = RerankerRegistry(
        _retrieval_config(tmp_path, reranking_enabled=False, docs_path="unused.json")
    )
    assert registry.is_enabled() is False
    assert registry.create() is None


def test_create_enabled_override_forces_reranker(tmp_path):
    registry = RerankerRegistry(
        _retrieval_config(
            tmp_path, reranking_enabled=False, provider="simple", docs_path="unused.json"
        )
    )
    assert isinstance(registry.create(enabled=True), SimpleReranker)


def test_create_disabled_override_suppresses_reranker(tmp_path):
    registry = RerankerRegistry(
        _retrieval_config(tmp_path, reranking_enabled=True, docs_path="unused.json")
    )
    assert registry.create(enabled=False) is None


def test_create_selects_configured_provider(tmp_path):
    registry = RerankerRegistry(
        _retrieval_config(
            tmp_path, reranking_enabled=True, provider="dummy", docs_path="unused.json"
        )
    )
    assert isinstance(registry.create(), DummyReranker)


def test_composition_passes_no_reranker_when_disabled(tmp_path):
    assert _build(tmp_path, reranking_enabled=False).reranker is None


def test_composition_uses_cross_encoder_reranker_when_enabled(tmp_path):
    pipeline = _build(tmp_path, reranking_enabled=True)
    assert isinstance(pipeline.reranker, CrossEncoderReranker)


def test_pipeline_skips_reranking_stage_when_disabled(tmp_path):
    pipeline = _build(tmp_path, reranking_enabled=False)

    result = pipeline.run("What is machine learning?")

    assert result["failure_tags"] == []
    observability = result["observability"]
    assert observability["reranker"] == "none"
    assert observability["reranking_enabled"] is False
    assert observability["latency"]["reranking_ms"] == 0.0
    assert result["retrieval_scores"] == observability["initial_retrieval_scores"]


def test_pipeline_runs_reranking_stage_when_enabled(tmp_path):
    pipeline = _build(tmp_path, reranking_enabled=True)

    result = pipeline.run("What is machine learning?")

    observability = result["observability"]
    assert observability["reranking_enabled"] is True
    assert observability["reranker"] == "CrossEncoderReranker"
    assert observability["latency"]["reranking_ms"] >= 0.0


def test_toggling_enabled_changes_observability(tmp_path):
    disabled = _build(tmp_path, reranking_enabled=False)
    enabled = _build(tmp_path, reranking_enabled=True)

    assert disabled.reranker is None
    assert enabled.reranker is not None
    assert disabled.run("What is machine learning?")["observability"]["reranking_enabled"] is False
    assert enabled.run("What is machine learning?")["observability"]["reranking_enabled"] is True
