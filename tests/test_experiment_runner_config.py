"""Tests for issue #17: ExperimentRunner resolves components via config-driven
registries instead of hardcoded if/else selection.

Acceptance criteria:
1. Backend selection follows ``retrieval.default_retriever``.
2. Evaluator/reranker selection follows config.
"""

import inspect
from pathlib import Path

import pytest
import yaml

import core.services.experiment_runner as experiment_runner_module
from core.services.experiment_runner import ExperimentRunner

PROMPT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "prompt_config.yaml"

DOCS = [
    {"content": "Artificial intelligence simulates human intelligence."},
    {"content": "Machine learning learns patterns from data."},
    {"content": "Neural networks are inspired by the brain."},
]
QUERY = "What is artificial intelligence?"


def _write_yaml(path, payload: dict) -> str:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(path)


def _retrieval_config(
    default_retriever: str = "faiss",
    evaluator: str = "dummy",
    evaluation_enabled: bool = True,
    reranking_enabled: bool = True,
) -> dict:
    return {
        "retrieval": {
            "default_retriever": default_retriever,
            "top_k": 3,
            "similarity_metric": "cosine",
            "retrievers": {
                "faiss": {"provider": "faiss"},
                "simple": {"provider": "simple"},
            },
        },
        "evaluation": {
            "enabled": evaluation_enabled,
            "active_evaluator": evaluator,
            "evaluators": {
                "dummy": {"provider": "dummy"},
                "engine": {"provider": "engine"},
                "noop": {"provider": "noop"},
            },
        },
        "reranking": {
            "enabled": reranking_enabled,
            "active_reranker": "simple",
            "strategy": "lexical_hybrid",
            "rerankers": {"simple": {"provider": "simple"}, "none": {"provider": "none"}},
        },
        "chunking": {
            "active_strategy": "small",
            "strategies": {"small": {"chunk_size": 120, "chunk_overlap": 20, "separator": " "}},
        },
        "token_budget": {
            "default_mode": "strict",
            "max_output_cap": 512,
            "min_output_tokens": 16,
            "chars_per_token": 4,
        },
        "observability": {"redact_sensitive_data": True, "low_retrieval_score_threshold": 0.0},
        "governance": {"enabled": False},
    }


def _make_runner(tmp_path, retrieval: dict) -> "ExperimentRunner":
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
    retrieval_path = tmp_path / "retrieval.yaml"
    _write_yaml(retrieval_path, retrieval)
    return ExperimentRunner(
        models_config_path=str(models),
        prompt_config_path=str(PROMPT_CONFIG),
        retrieval_config_path=str(retrieval_path),
    )


@pytest.mark.parametrize(
    ("default_retriever", "expected"),
    [("faiss", "FAISSRetriever"), ("simple", "SimpleRetriever")],
)
def test_retriever_follows_default_retriever_config(tmp_path, default_retriever, expected):
    runner = _make_runner(tmp_path, _retrieval_config(default_retriever=default_retriever))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY)
    assert result["retriever"] == expected


def test_explicit_retriever_backend_overrides_config(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(default_retriever="faiss"))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY, retriever_backend="simple")
    assert result["retriever"] == "SimpleRetriever"


def test_reranker_follows_config_selection(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(reranking_enabled=True))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY)
    assert result["reranker"] == "SimpleReranker"


def test_reranker_disabled_via_config_when_not_overridden(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(reranking_enabled=False))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY, use_reranker=None)
    assert result["reranker"] is None


def test_use_reranker_override_forces_reranker_on(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(reranking_enabled=False))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY, use_reranker=True)
    assert result["reranker"] == "SimpleReranker"


def test_use_reranker_override_forces_reranker_off(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(reranking_enabled=True))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY, use_reranker=False)
    assert result["reranker"] is None


@pytest.mark.parametrize(
    ("evaluator", "expected"),
    [("dummy", "DummyEvaluator"), ("engine", "EvaluationEngine")],
)
def test_evaluator_follows_config(tmp_path, evaluator, expected):
    runner = _make_runner(tmp_path, _retrieval_config(evaluator=evaluator))
    result = runner.run_single_experiment(docs=DOCS, query=QUERY)
    assert result["evaluator"] == expected


def test_evaluator_disabled_via_config(tmp_path):
    runner = _make_runner(
        tmp_path, _retrieval_config(evaluation_enabled=False, evaluator="dummy")
    )
    result = runner.run_single_experiment(docs=DOCS, query=QUERY)
    assert result["evaluator"] == "NullEvaluator"


def test_compare_chunking_strategies_uses_config_retriever(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config(default_retriever="simple"))
    comparison = runner.compare_chunking_strategies(
        docs=[{"content": " ".join(d["content"] for d in DOCS) * 3}],
        query=QUERY,
        strategies=("small", "large"),
    )
    assert set(comparison["results"]) == {"small", "large"}
    for run in comparison["results"].values():
        assert run["retriever"] == "SimpleRetriever"


def test_compare_embedding_models_uses_selected_embedders(tmp_path):
    runner = _make_runner(tmp_path, _retrieval_config())
    comparison = runner.compare_embedding_models(
        docs=DOCS, query=QUERY, model_names=["emb-a", "emb-b"]
    )
    assert comparison["results"]["emb-a"]["embedding_model"] == "emb-a"
    assert comparison["results"]["emb-b"]["embedding_model"] == "emb-b"
    assert comparison["results"]["emb-a"]["retriever"] == "FAISSRetriever"


def test_module_has_no_concrete_implementation_imports():
    source = inspect.getsource(experiment_runner_module)
    for concrete in ("FAISSRetriever", "SimpleRetriever", "SimpleReranker", "EvaluationEngine"):
        assert concrete not in source, f"{concrete} should be resolved via registries, not imported"
