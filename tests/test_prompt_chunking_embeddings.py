import inspect
import pytest

from app.pipeline import RAGPipeline
from core.implementations.chunker import ChunkerFactory, ConfigurableChunker, LargeChunker, SmallChunker
from core.implementations.faiss_retriever import FAISSRetriever
from core.implementations.simple_embedder import SimpleEmbedder
from core.services.experiment_runner import ExperimentRunner
from core.services.prompt_builder import PromptBuilder


def test_prompt_builder_loads_profiles_and_pipeline_has_no_hardcoded_prompt():
    builder = PromptBuilder("config/prompt_config.yaml")
    assert "default" in builder.list_profiles()
    assert "concise" in builder.list_profiles()
    assert "analytical" in builder.list_profiles()

    default_prompt = builder.build("What is AI?", [{"content": "AI simulates human intelligence."}])
    assert "You are a helpful assistant." in default_prompt
    assert "AI simulates human intelligence." in default_prompt

    builder.set_profile("concise")
    concise_prompt = builder.build("What is AI?", [{"content": "AI simulates human intelligence."}])
    assert "concise enterprise AI assistant" in concise_prompt

    # Verify RAGPipeline source code does not hardcode "You are a helpful assistant."
    pipeline_src = inspect.getsource(RAGPipeline)
    assert "You are a helpful assistant." not in pipeline_src


def test_prompt_builder_unknown_profile_raises():
    builder = PromptBuilder("config/prompt_config.yaml")
    with pytest.raises(ValueError):
        builder.set_profile("non_existent_profile")


def test_chunking_strategies_small_vs_large():
    long_doc = (
        "Artificial intelligence and machine learning enable enterprises to automate complex workflows. "
        "Retrieval augmented generation combines dense vector indexing with large language models. "
        "Observability, token governance, and evaluation metrics ensure trustworthy production deployments. "
        "Chunking strategies control the granularity of passages stored in the vector index."
    )

    small_chunker = ChunkerFactory.create("small")
    large_chunker = ChunkerFactory.create("large")

    assert isinstance(small_chunker, SmallChunker)
    assert isinstance(large_chunker, LargeChunker)
    assert small_chunker.chunk_size < large_chunker.chunk_size

    small_chunks = small_chunker.chunk_text(long_doc)
    large_chunks = large_chunker.chunk_text(long_doc)

    assert len(small_chunks) > len(large_chunks)
    assert all(len(c.content) <= small_chunker.chunk_size for c in small_chunks)
    assert all(c.metadata["chunk_strategy"] == "small" for c in small_chunks)
    assert all(c.metadata["chunk_strategy"] == "large" for c in large_chunks)


def test_chunker_invalid_parameters_raise():
    with pytest.raises(ValueError):
        ConfigurableChunker(strategy="unknown_strategy")
    with pytest.raises(ValueError):
        ConfigurableChunker(strategy="small", chunk_size=0)
    with pytest.raises(ValueError):
        ConfigurableChunker(strategy="small", chunk_size=50, chunk_overlap=60)


def test_embedding_models_selection_and_experiment_comparison():
    minilm = SimpleEmbedder(model_name="sentence-transformers/all-MiniLM-L6-v2")
    mpnet = SimpleEmbedder(model_name="sentence-transformers/all-mpnet-base-v2")

    assert minilm.dimension == 384
    assert mpnet.dimension == 768

    vec_minilm = minilm.embed("Enterprise RAG architecture")
    vec_mpnet = mpnet.embed("Enterprise RAG architecture")

    assert len(vec_minilm) == 384
    assert len(vec_mpnet) == 768

    # Both models integrate seamlessly with FAISSRetriever of matching dimension
    docs = [
        {"content": "Artificial Intelligence is the simulation of human intelligence."},
        {"content": "Machine Learning is a subset of AI focused on learning from data."},
        {"content": "Neural networks are models inspired by the human brain."},
    ]
    faiss_minilm = FAISSRetriever(docs=docs, embedder=minilm)
    faiss_mpnet = FAISSRetriever(docs=docs, embedder=mpnet)
    assert faiss_minilm.index_dimension == 384
    assert faiss_mpnet.index_dimension == 768

    # Comparative experiment runner evaluates both models and chunking strategies
    runner = ExperimentRunner()
    comparison = runner.compare_embedding_models(
        docs=docs,
        query="What is Artificial Intelligence?",
        model_names=[
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-mpnet-base-v2",
        ],
    )
    assert len(comparison["results"]) == 2
    r1 = comparison["results"]["sentence-transformers/all-MiniLM-L6-v2"]
    r2 = comparison["results"]["sentence-transformers/all-mpnet-base-v2"]

    assert r1["embedding_dimension"] == 384
    assert r2["embedding_dimension"] == 768
    assert len(r1["retrieved_documents"]) > 0
    assert len(r2["retrieved_documents"]) > 0
    assert len(r1["retrieval_scores"]) > 0
    assert "context_precision" in r1["metrics"]
    assert "context_precision" in r2["metrics"]

    chunk_comparison = runner.compare_chunking_strategies(
        docs=[{"content": " ".join([d["content"] for d in docs] * 3)}],
        query="What are neural networks?",
        strategies=("small", "large"),
    )
    assert (
        chunk_comparison["results"]["small"]["num_indexed_chunks"]
        >= chunk_comparison["results"]["large"]["num_indexed_chunks"]
    )
