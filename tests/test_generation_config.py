"""Tests for issue #12: generation parameters must come from the model config.

Acceptance criteria:
1. The active model's ``temperature`` / ``max_tokens`` are applied at runtime.
2. Changing them in ``models.yaml`` changes generation behaviour (no code change).
"""

from pathlib import Path

import yaml

from app.main import _generation_config_from_model, build_pipeline
from core.config.generation_config import GenerationConfig


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path, model_cfg: dict, model_name: str = "dummy") -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": model_name,
            "active_embedding_model": "dummy",
            "models": {model_name: model_cfg},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )


def _retrieval_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "similarity_metric": "cosine",
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "governance": {
                "enabled": True,
                "max_cost_per_request_usd": 0.05,
                "safety_margin_tokens": 200,
            },
            "evaluation": {"enabled": False},
            "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
            "observability": {"low_retrieval_score_threshold": 0.0},
        },
    )


def _pipeline(tmp_path: Path, model_cfg: dict, model_name: str = "dummy"):
    return build_pipeline(
        models_config_path=Path(_models_config(tmp_path, model_cfg, model_name)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )


def test_temperature_from_model_config_is_applied(tmp_path):
    pipeline = _pipeline(tmp_path, {"provider": "dummy", "context_window": 4096, "temperature": 0.25})

    assert pipeline.generation_config.temperature == 0.25


def test_max_tokens_from_model_config_is_applied(tmp_path):
    pipeline = _pipeline(
        tmp_path,
        {"provider": "dummy", "context_window": 4096, "temperature": 0.2, "max_tokens": 96},
    )

    assert pipeline.generation_config.max_tokens == 96


def test_max_new_tokens_hf_naming_falls_back_for_max_tokens(tmp_path):
    # HuggingFace-style configs (e.g. local-qwen) use ``max_new_tokens``.
    pipeline = _pipeline(
        tmp_path,
        {
            "provider": "local_hf",
            "model_name": "Qwen/Qwen2.5-0.5B-Instruct",
            "context_window": 32768,
            "max_new_tokens": 64,
        },
        model_name="local-qwen",
    )

    assert pipeline.generation_config.max_tokens == 64


def test_missing_generation_keys_use_defaults(tmp_path):
    pipeline = _pipeline(tmp_path, {"provider": "dummy", "context_window": 4096})

    assert pipeline.generation_config.temperature == 0.7
    assert pipeline.generation_config.top_p == 0.9
    assert pipeline.generation_config.max_tokens == 256
    assert pipeline.generation_config.stop is None


def test_top_p_and_stop_from_model_config(tmp_path):
    pipeline = _pipeline(
        tmp_path,
        {
            "provider": "dummy",
            "context_window": 4096,
            "top_p": 0.5,
            "stop": ["\n", "END"],
        },
    )

    assert pipeline.generation_config.top_p == 0.5
    assert pipeline.generation_config.stop == ["\n", "END"]


def test_changing_model_config_changes_generation_behaviour(tmp_path):
    low_temp = _pipeline(tmp_path, {"provider": "dummy", "context_window": 4096, "temperature": 0.1})
    high_temp = _pipeline(tmp_path, {"provider": "dummy", "context_window": 4096, "temperature": 0.9})

    assert low_temp.generation_config.temperature != high_temp.generation_config.temperature
    assert low_temp.generation_config.temperature == 0.1
    assert high_temp.generation_config.temperature == 0.9


def test_reserved_output_tokens_follows_model_max_tokens(tmp_path):
    pipeline = _pipeline(
        tmp_path,
        {"provider": "dummy", "context_window": 4096, "max_tokens": 128},
    )

    assert pipeline.retrieval_policy_service is not None
    assert pipeline.retrieval_policy_service.reserved_output_tokens == 128


def test_generation_config_reaches_llm_at_runtime(tmp_path):
    # DummyLLM echoes the GenerationConfig it receives, proving the configured
    # values are what actually gets passed to the LLM during pipeline.run().
    pipeline = _pipeline(
        tmp_path,
        {"provider": "dummy", "context_window": 4096, "temperature": 0.33, "max_tokens": 42},
    )

    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert "temperature=0.33" in result["response"]
    assert "max_tokens=" in result["response"]


def test_generation_config_helper_defaults_and_types():
    cfg = _generation_config_from_model({"temperature": 0.5, "max_tokens": 10})

    assert isinstance(cfg, GenerationConfig)
    assert cfg.temperature == 0.5
    assert cfg.max_tokens == 10

    empty = _generation_config_from_model({})
    assert empty.temperature == 0.7
    assert empty.max_tokens == 256
