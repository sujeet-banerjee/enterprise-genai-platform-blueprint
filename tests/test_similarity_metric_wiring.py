"""Tests for issue #15: `retrieval.similarity_metric` must be consumed from config.

Acceptance criteria:
1. Changing `similarity_metric` changes index/metric selection with no code change.
2. Per-retriever entries can override the global value.
"""

import json
from pathlib import Path

import pytest
import yaml

from app.main import build_pipeline
from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.faiss_retriever import FAISSRetriever
from core.registry.retriever_registry import RetrieverRegistry


def _write_config(tmp_path, payload: dict) -> str:
    path = tmp_path / "retrieval.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def _faiss_config(metric: str | None, entry_metric: str | None = None) -> dict:
    faiss_entry: dict = {"provider": "faiss"}
    if entry_metric is not None:
        faiss_entry["similarity_metric"] = entry_metric
    retrieval: dict = {
        "default_retriever": "faiss",
        "retrievers": {"faiss": faiss_entry},
    }
    if metric is not None:
        retrieval["similarity_metric"] = metric
    return {"retrieval": retrieval}


def test_global_similarity_metric_selects_l2_index(tmp_path):
    config_path = _write_config(tmp_path, _faiss_config("l2"))

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert isinstance(retriever, FAISSRetriever)
    assert retriever.similarity_metric == "l2"
    assert type(retriever.index).__name__ == "IndexFlatL2"


def test_global_similarity_metric_selects_inner_product_index(tmp_path):
    config_path = _write_config(tmp_path, _faiss_config("cosine"))

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert retriever.similarity_metric == "cosine"
    assert type(retriever.index).__name__ == "IndexFlatIP"


@pytest.mark.parametrize(
    ("metric", "expected_index"),
    [("cosine", "IndexFlatIP"), ("l2", "IndexFlatL2")],
)
def test_changing_global_metric_changes_index_without_code_change(
    tmp_path, metric, expected_index
):
    config_path = _write_config(tmp_path, _faiss_config(metric))

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert retriever.similarity_metric == metric
    assert type(retriever.index).__name__ == expected_index


def test_retriever_entry_overrides_global_metric(tmp_path):
    config_path = _write_config(tmp_path, _faiss_config("l2", entry_metric="cosine"))

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert retriever.similarity_metric == "cosine"
    assert type(retriever.index).__name__ == "IndexFlatIP"


def test_config_without_metric_defaults_to_cosine(tmp_path):
    config_path = _write_config(tmp_path, _faiss_config(None))

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert retriever.similarity_metric == "cosine"
    assert type(retriever.index).__name__ == "IndexFlatIP"


def test_non_faiss_providers_tolerate_global_metric(tmp_path):
    config_path = _write_config(
        tmp_path,
        {
            "retrieval": {
                "default_retriever": "dummy",
                "similarity_metric": "l2",
                "retrievers": {"dummy": {"provider": "dummy"}},
            }
        },
    )

    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=DummyEmbedder())

    assert isinstance(retriever, DummyRetriever)


def test_metric_changes_scores_for_same_vectors():
    docs = ["alpha doc", "beta doc"]
    embeddings = [[1.0, 0.0, 0.0], [0.5, 0.5, 0.0]]
    query = [1.0, 0.0, 0.0]

    cosine = FAISSRetriever(dimension=3, similarity_metric="cosine")
    cosine.build_index(docs, embeddings=embeddings)
    l2 = FAISSRetriever(dimension=3, similarity_metric="l2")
    l2.build_index(docs, embeddings=embeddings)

    cosine_results = cosine.retrieve_with_scores(query, top_k=2)
    l2_results = l2.retrieve_with_scores(query, top_k=2)

    # Both metrics rank the identical vector first...
    assert cosine_results[0].document.content == "alpha doc"
    assert l2_results[0].document.content == "alpha doc"
    # ...but the scoring function differs (dot product vs distance transform).
    assert cosine_results[1].score != l2_results[1].score
    assert 0.0 < cosine_results[1].score <= 1.0
    assert 0.0 < l2_results[1].score <= 1.0


def _e2e_configs(tmp_path: Path, metric: str, name: str) -> tuple[str, str]:
    workdir = tmp_path / name
    workdir.mkdir(exist_ok=True)

    corpus = workdir / "corpus.json"
    corpus.write_text(
        json.dumps(
            [
                {"content": "artificial intelligence builds intelligent machines"},
                {"content": "machine learning trains models from data"},
                {"content": "vector search retrieves similar documents"},
            ]
        ),
        encoding="utf-8",
    )

    models = workdir / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "active_model": "dummy",
                "active_embedding_model": "dummy",
                "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
                "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    retrieval = workdir / "retrieval.yaml"
    retrieval.write_text(
        yaml.safe_dump(
            {
                "retrieval": {
                    "default_retriever": "faiss",
                    "top_k": 3,
                    "similarity_metric": metric,
                    "retrievers": {
                        "faiss": {"provider": "faiss", "documents_path": str(corpus)},
                    },
                },
                "governance": {"enabled": True, "max_cost_per_request_usd": 1_000_000.0},
                "evaluation": {"enabled": False},
                "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
                "token_budget": {"default_mode": "strict", "max_output_cap": 512},
                "observability": {"low_retrieval_score_threshold": 0.0},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return str(models), str(retrieval)


@pytest.mark.parametrize(
    ("metric", "expected_index"),
    [("cosine", "IndexFlatIP"), ("l2", "IndexFlatL2")],
)
def test_end_to_end_pipeline_honors_configured_similarity_metric(
    tmp_path, metric, expected_index
):
    models, retrieval = _e2e_configs(tmp_path, metric=metric, name=metric)

    pipeline = build_pipeline(
        models_config_path=Path(models), retrieval_config_path=Path(retrieval)
    )
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    assert result.get("error") is None, result.get("failure_tags")
    assert result["retrieval_scores"]
    assert isinstance(pipeline.retriever, FAISSRetriever)
    assert pipeline.retriever.similarity_metric == metric
    assert type(pipeline.retriever.index).__name__ == expected_index
