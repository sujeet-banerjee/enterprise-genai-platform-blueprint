"""Query-length guard (issue #73, finding 5).

Before this, ``QueryRequest.query`` had only ``min_length=1`` and no upper bound:
a single request could exceed the model context window (the token budget
truncated *documents*, never the query). The guard rejects an over-long query
before any embedding/retrieval work and classifies it in the failure taxonomy as
``query_too_long``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_llm import DummyLLM
from core.interfaces.retriever import Document
from core.services.failure_classifier import FailureType
from core.services.guardrails import QueryTooLongError, validate_query_length

REPO = Path(__file__).resolve().parents[1]
PROMPT_CONFIG = REPO / "config" / "prompt_config.yaml"
DOCS = [{"content": "Artificial intelligence simulates human intelligence."}]


class _RecordingRetriever:
    """Retriever that records whether it was ever queried."""

    def __init__(self, docs):
        self.docs = [Document(content=d["content"]) for d in docs]
        self.called = False

    def retrieve(self, query_embedding, top_k=3):  # noqa: D102
        self.called = True
        return self.docs

    def retrieve_with_scores(self, query_embedding, top_k=3):  # noqa: D102
        self.called = True
        return [(d, 1.0) for d in self.docs]

    @property
    def index_dimension(self):  # noqa: D102
        return 7


def _build_pipeline(*, max_query_chars) -> "object":
    from app.pipeline import RAGPipeline
    from core.config.generation_config import GenerationConfig
    from core.services.cost_tracker import CostTracker
    from core.services.prompt_builder import PromptBuilder
    from core.services.token_budget_service import TokenBudgetService

    return RAGPipeline(
        embedder=DummyEmbedder(dimension=7),
        prompt_builder=PromptBuilder(str(PROMPT_CONFIG)),
        retriever=_RecordingRetriever(DOCS),
        llm=DummyLLM(),
        evaluator=None,
        token_budget_service=TokenBudgetService(policy_mode="strict", config_path=None),
        generation_config=GenerationConfig(max_tokens=32, temperature=0.0),
        cost_tracker=CostTracker(),
        max_query_chars=max_query_chars,
    )


# -- unit ------------------------------------------------------------------


def test_validate_passes_when_under_bound():
    validate_query_length("short query", 100)  # no raise


def test_validate_disabled_when_bound_none_or_nonpositive():
    validate_query_length("x" * 10_000, None)
    validate_query_length("x" * 10_000, 0)


def test_validate_raises_with_metadata():
    with pytest.raises(QueryTooLongError) as excinfo:
        validate_query_length("x" * 50, 10)
    assert excinfo.value.length == 50
    assert excinfo.value.max_chars == 10
    assert excinfo.value.failure_type == FailureType.QUERY_TOO_LONG.value


# -- pipeline --------------------------------------------------------------


def test_pipeline_rejects_over_long_query_before_retrieval():
    pipeline = _build_pipeline(max_query_chars=20)
    result = pipeline.run("x" * 50, raise_on_failure=False)

    assert result["response"] is None
    assert result["failure_type"] == FailureType.QUERY_TOO_LONG.value
    assert result["observability"]["failed_stage"] == "query_validation"
    # the retriever must never have been touched
    assert pipeline.retriever.called is False


def test_pipeline_raises_when_raise_on_failure_true():
    pipeline = _build_pipeline(max_query_chars=5)
    with pytest.raises(QueryTooLongError):
        pipeline.run("this query is definitely too long")


def test_pipeline_allows_query_within_bound():
    pipeline = _build_pipeline(max_query_chars=10_000)
    result = pipeline.run("what is ai?", raise_on_failure=False)

    assert result.get("failure_type") is None
    assert pipeline.retriever.called is True


def test_pipeline_bound_disabled_allows_any_length():
    pipeline = _build_pipeline(max_query_chars=None)
    result = pipeline.run("y" * 5_000, raise_on_failure=False)
    assert result.get("failure_type") is None


def test_pipeline_reads_bound_from_config(tmp_path):
    retrieval = tmp_path / "retrieval.yaml"
    retrieval.write_text(
        yaml.safe_dump({"guardrails": {"max_query_chars": 15}}), encoding="utf-8"
    )
    from app.pipeline import RAGPipeline
    from core.config.generation_config import GenerationConfig
    from core.services.cost_tracker import CostTracker
    from core.services.prompt_builder import PromptBuilder
    from core.services.token_budget_service import TokenBudgetService

    pipeline = RAGPipeline(
        embedder=DummyEmbedder(dimension=7),
        prompt_builder=PromptBuilder(str(PROMPT_CONFIG)),
        retriever=_RecordingRetriever(DOCS),
        llm=DummyLLM(),
        evaluator=None,
        token_budget_service=TokenBudgetService(policy_mode="strict", config_path=str(retrieval)),
        generation_config=GenerationConfig(max_tokens=32, temperature=0.0),
        cost_tracker=CostTracker(),
        config_path=str(retrieval),
    )
    assert pipeline.max_query_chars == 15
    result = pipeline.run("z" * 40, raise_on_failure=False)
    assert result["failure_type"] == FailureType.QUERY_TOO_LONG.value


# -- API -------------------------------------------------------------------


def _make_app(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "active_model": "dummy",
                "active_embedding_model": "emb-a",
                "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
                "embedding_models": {"emb-a": {"provider": "dummy", "model_name": "emb-a"}},
            }
        ),
        encoding="utf-8",
    )
    retrieval = tmp_path / "retrieval.yaml"
    retrieval.write_text(
        yaml.safe_dump(
            {
                "retrieval": {
                    "default_retriever": "dummy",
                    "top_k": 3,
                    "retrievers": {"dummy": {"provider": "dummy"}},
                },
                "evaluation": {
                    "enabled": False,
                    "active_evaluator": "dummy",
                    "evaluators": {"dummy": {"provider": "dummy"}},
                },
                "reranking": {"enabled": False},
                "guardrails": {"max_query_chars": 20},
            }
        ),
        encoding="utf-8",
    )
    return TestClient(
        create_app(
            models_config_path=models,
            retrieval_config_path=retrieval,
            prompt_config_path=PROMPT_CONFIG,
        )
    )


def test_api_returns_400_query_too_long(tmp_path):
    with _make_app(tmp_path) as client:
        response = client.post("/v1/query", json={"query": "x" * 50})
        assert response.status_code == 400
        body = response.json()
        assert body["failure_type"] == FailureType.QUERY_TOO_LONG.value
        assert body["failure_tags"] == [FailureType.QUERY_TOO_LONG.value]
        assert body["request_id"]
        assert "error" in body


def test_api_allows_query_within_bound(tmp_path):
    with _make_app(tmp_path) as client:
        response = client.post("/v1/query", json={"query": "what is ai?"})
        assert response.status_code == 200
