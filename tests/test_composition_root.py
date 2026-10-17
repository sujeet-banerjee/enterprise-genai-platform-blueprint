import ast
from pathlib import Path

import yaml

from app.main import RETRIEVAL_CONFIG_PATH, build_pipeline
from core.interfaces.retriever import Document

MAIN_PATH = Path(__file__).resolve().parent.parent / "app" / "main.py"

TMP_DOCS = [
    {"content": "Artificial Intelligence is the simulation of human intelligence."},
    {"content": "Machine Learning is a subset of AI focused on learning from data."},
]


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _write_docs(path: Path) -> str:
    import json

    path.write_text(json.dumps(TMP_DOCS), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path, embedding_model: str = "dummy") -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": embedding_model,
            "models": {
                "dummy": {"provider": "dummy", "context_window": 4096, "temperature": 0.2},
            },
            "embedding_models": {
                "dummy": {"provider": "dummy", "model_name": "dummy-embedder"},
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
    default_retriever: str = "dummy",
    retrievers: dict | None = None,
    evaluation_enabled: bool = True,
    active_reranker: str | None = None,
    rerankers: dict | None = None,
) -> str:
    retrieval: dict = {
        "default_retriever": default_retriever,
        "top_k": 3,
        "similarity_metric": "cosine",
        "retrievers": retrievers or {"dummy": {"provider": "dummy"}},
    }
    reranking: dict = {"strategy": "lexical_hybrid", "top_k": 3}
    if active_reranker is not None:
        reranking["active_reranker"] = active_reranker
    if rerankers is not None:
        reranking["rerankers"] = rerankers

    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": retrieval,
            "governance": {
                "enabled": True,
                "max_cost_per_request_usd": 0.05,
                "safety_margin_tokens": 200,
            },
            "evaluation": {
                "enabled": evaluation_enabled,
                "active_evaluator": "dummy",
                "evaluators": {"dummy": {"provider": "dummy"}},
            },
            "reranking": reranking,
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
            "observability": {"low_retrieval_score_threshold": 0.25},
        },
    )


def test_main_module_has_no_concrete_implementation_imports():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "core.implementations"
        ):
            offenders.append(node.module)
        elif isinstance(node, ast.Import):
            offenders.extend(
                alias.name for alias in node.names if alias.name.startswith("core.implementations")
            )
    assert offenders == [], f"Composition root must not import concrete implementations: {offenders}"


def test_build_pipeline_resolves_components_from_config(tmp_path):
    models = _models_config(tmp_path)
    retrieval = _retrieval_config(tmp_path)

    pipeline = build_pipeline(models_config_path=Path(models), retrieval_config_path=Path(retrieval))

    assert type(pipeline.embedder).__name__ == "DummyEmbedder"
    assert type(pipeline.retriever).__name__ == "DummyRetriever"
    assert type(pipeline.reranker).__name__ == "SimpleReranker"
    assert type(pipeline.evaluator).__name__ == "DummyEvaluator"
    assert pipeline.embedder.dimension == pipeline.retriever.index_dimension


def test_active_embedding_model_switches_embedder(tmp_path):
    dummy_pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path, embedding_model="dummy")),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )
    real_pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path, embedding_model="all-MiniLM-L6-v2")),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )

    assert type(dummy_pipeline.embedder).__name__ == "DummyEmbedder"
    assert type(real_pipeline.embedder).__name__ == "SimpleEmbedder"
    assert dummy_pipeline.embedder.dimension != real_pipeline.embedder.dimension


def test_default_retriever_switches_retriever(tmp_path):
    docs_path = _write_docs(tmp_path / "docs.json")

    dummy_pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(tmp_path, default_retriever="dummy")
        ),
    )
    simple_pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                default_retriever="simple",
                retrievers={
                    "simple": {"provider": "simple", "documents_path": docs_path},
                },
            )
        ),
    )

    assert type(dummy_pipeline.retriever).__name__ == "DummyRetriever"
    assert type(simple_pipeline.retriever).__name__ == "SimpleRetriever"
    assert simple_pipeline.retriever.index_dimension == simple_pipeline.embedder.dimension


def test_reranker_selected_from_config(tmp_path):
    models = _models_config(tmp_path)

    default_pipeline = build_pipeline(
        models_config_path=Path(models),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )
    dummy_pipeline = build_pipeline(
        models_config_path=Path(models),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                active_reranker="dummy",
                rerankers={"dummy": {"provider": "dummy"}},
            )
        ),
    )
    disabled_pipeline = build_pipeline(
        models_config_path=Path(models),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                active_reranker="none",
                rerankers={"none": {"provider": "none"}},
            )
        ),
    )

    assert type(default_pipeline.reranker).__name__ == "SimpleReranker"
    assert type(dummy_pipeline.reranker).__name__ == "DummyReranker"
    assert disabled_pipeline.reranker is None


def test_evaluation_disabled_yields_null_evaluator(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path, evaluation_enabled=False)),
    )

    assert type(pipeline.evaluator).__name__ == "NullEvaluator"


def test_pipeline_runs_query_end_to_end(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )

    result = pipeline.run("What is artificial intelligence?")

    assert result["response"]
    assert result["failure_tags"] == []
    assert len(result["retrieved_docs"]) >= 1
    assert result["observability"]["top_k"] >= 1


def test_default_composition_root_serves_query():
    import app.main as main_module

    result = main_module.pipeline.run("What is machine learning?")

    assert result["response"]
    assert result["failure_tags"] == []
    assert len(result["retrieved_docs"]) >= 1
    assert RETRIEVAL_CONFIG_PATH.exists()


def test_build_pipeline_uses_configured_documents_for_retrieval(tmp_path):
    docs_path = _write_docs(tmp_path / "docs.json")
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                default_retriever="simple",
                retrievers={"simple": {"provider": "simple", "documents_path": docs_path}},
            )
        ),
    )

    embedding = pipeline.embedder.embed("Machine Learning is a subset of AI")
    results = pipeline.retriever.retrieve_with_scores(embedding, top_k=2)

    assert len(results) == 2
    assert all(isinstance(item.document, Document) for item in results)
    contents = " ".join(item.document.content for item in results)
    assert "Machine Learning" in contents
