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
                "local-qwen": {
                    "provider": "local_hf",
                    "model_name": "Qwen/Qwen2.5-0.5B-Instruct",
                    "context_window": 32768,
                    "max_new_tokens": 64,
                },
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


def _genuine_models_config(tmp_path: Path) -> str:
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
    default_retriever: str = "dummy",
    retrievers: dict | None = None,
    evaluation_enabled: bool = True,
    active_evaluator: str = "dummy",
    active_reranker: str | None = None,
    rerankers: dict | None = None,
    query_expansion: dict | None = None,
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

    evaluators: dict = {"dummy": {"provider": "dummy"}}
    if active_evaluator == "semantic":
        evaluators["semantic"] = {
            "provider": "semantic",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        }

    config: dict = {
        "retrieval": retrieval,
        "governance": {
            "enabled": True,
            "max_cost_per_request_usd": 0.05,
            "safety_margin_tokens": 200,
        },
        "evaluation": {
            "enabled": evaluation_enabled,
            "active_evaluator": active_evaluator,
            "evaluators": evaluators,
        },
        "reranking": reranking,
        "token_budget": {"default_mode": "strict", "max_output_cap": 512},
        "observability": {"low_retrieval_score_threshold": 0.25},
    }
    if query_expansion is not None:
        config["query_expansion"] = query_expansion

    return _write_yaml(tmp_path / "retrieval.yaml", config)


def _genuine_retrieval_config(tmp_path: Path, docs_path: str) -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "simple",
                "top_k": 3,
                "similarity_metric": "cosine",
                "retrievers": {
                    "simple": {"provider": "simple", "documents_path": docs_path},
                },
            },
            "governance": {
                "enabled": True,
                "max_cost_per_request_usd": 0.05,
                "safety_margin_tokens": 200,
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
                "strategy": "lexical_hybrid",
                "top_k": 3,
                "active_reranker": "cross_encoder",
                "rerankers": {
                    "cross_encoder": {
                        "provider": "cross_encoder",
                        "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                        "top_k": 3,
                    },
                },
            },
            "token_budget": {"default_mode": "strict", "max_output_cap": 64},
            "observability": {"low_retrieval_score_threshold": 0.0},
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


def test_query_expansion_off_by_default(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
    )
    assert pipeline.query_expander is None


def test_query_expansion_selected_from_config(tmp_path):
    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(
            _retrieval_config(
                tmp_path,
                query_expansion={
                    "enabled": True,
                    "active_expander": "synonym",
                    "max_variants": 2,
                    "expanders": {
                        "synonym": {
                            "provider": "synonym",
                            "synonyms": {"ai": ["artificial intelligence"]},
                        }
                    },
                },
            )
        ),
    )
    assert type(pipeline.query_expander).__name__ == "SynonymQueryExpander"
    result = pipeline.run("What is ai?")
    assert result["observability"]["query_expansion_enabled"] is True


def test_genuine_components_resolve_from_config(tmp_path):
    docs_path = _write_docs(tmp_path / "docs.json")
    pipeline = build_pipeline(
        models_config_path=Path(_genuine_models_config(tmp_path)),
        retrieval_config_path=Path(_genuine_retrieval_config(tmp_path, docs_path)),
    )

    assert type(pipeline.embedder).__name__ == "SimpleEmbedder"
    assert type(pipeline.retriever).__name__ == "SimpleRetriever"
    assert type(pipeline.reranker).__name__ == "CrossEncoderReranker"
    assert type(pipeline.evaluator).__name__ == "SemanticEvaluator"
    assert type(pipeline.llm).__name__ == "LocalHFLLM"
    assert pipeline.embedder.dimension == pipeline.retriever.index_dimension == 384


def test_pipeline_runs_query_end_to_end_with_genuine_components(tmp_path):
    docs_path = _write_docs(tmp_path / "docs.json")
    pipeline = build_pipeline(
        models_config_path=Path(_genuine_models_config(tmp_path)),
        retrieval_config_path=Path(_genuine_retrieval_config(tmp_path, docs_path)),
    )

    result = pipeline.run("What is artificial intelligence?")

    assert result["response"]
    assert result["failure_tags"] == []
    assert len(result["retrieved_docs"]) >= 1
    assert result["observability"]["top_k"] >= 1
    assert result["observability"]["llm_model"].endswith("Qwen2.5-0.5B-Instruct")
    assert result["observability"]["reranker"] == "CrossEncoderReranker"
    assert set(result["metrics"]) >= {"context_precision", "answer_relevance", "faithfulness"}


def test_genuine_pipeline_reranks_with_cross_encoder(tmp_path):
    docs_path = _write_docs(tmp_path / "docs.json")
    pipeline = build_pipeline(
        models_config_path=Path(_genuine_models_config(tmp_path)),
        retrieval_config_path=Path(_genuine_retrieval_config(tmp_path, docs_path)),
    )

    result = pipeline.run("What is machine learning?")

    assert "Machine Learning" in result["retrieved_docs"][0]
    assert result["observability"]["reranking_enabled"] is True
    assert result["retrieval_scores"] == result["observability"]["retrieval_scores"]


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
    from app.main import GOVERNANCE_CONFIG_PATH, OBSERVABILITY_CONFIG_PATH

    pipeline = build_pipeline(
        governance_config_path=GOVERNANCE_CONFIG_PATH,
        observability_config_path=OBSERVABILITY_CONFIG_PATH,
    )

    result = pipeline.run("What is machine learning?")

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
