import pytest
from core.interfaces.retriever import Document
from core.implementations.simple_embedder import SimpleEmbedder
from core.services.embedding_experiment_runner import EmbeddingExperimentRunner


def test_simple_embedder_dimension_selection():
    minilm = SimpleEmbedder(model_name="sentence-transformers/all-MiniLM-L6-v2")
    assert minilm.dimension == 384
    emb1 = minilm.embed("Hello world")
    assert len(emb1) == 384

    mpnet = SimpleEmbedder(model_name="sentence-transformers/all-mpnet-base-v2")
    assert mpnet.dimension == 768
    emb2 = mpnet.embed("Hello world")
    assert len(emb2) == 768


def test_embedding_experiment_runner():
    docs = [
        Document(content="Artificial intelligence and neural networks."),
        Document(content="Relational databases and SQL queries."),
        Document(content="Cloud computing and Kubernetes deployments.")
    ]

    runner = EmbeddingExperimentRunner()
    result = runner.compare_models(
        docs=docs,
        query="Explain artificial intelligence",
        models=[
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-mpnet-base-v2"
        ],
        top_k=2
    )

    assert "query" in result
    assert "experiments" in result
    assert len(result["experiments"]) == 2

    exp1, exp2 = result["experiments"]

    assert exp1["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert exp1["embedding_dimension"] == 384
    assert len(exp1["retrieved_documents"]) == 2
    assert len(exp1["retrieval_scores"]) == 2
    assert "metrics" in exp1

    assert exp2["embedding_model"] == "sentence-transformers/all-mpnet-base-v2"
    assert exp2["embedding_dimension"] == 768
    assert len(exp2["retrieved_documents"]) == 2
    assert len(exp2["retrieval_scores"]) == 2
    assert "metrics" in exp2
