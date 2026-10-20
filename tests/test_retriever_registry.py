import json
from typing import List

import pytest
import yaml

from core.implementations.dummy_embedder import DummyEmbedder
from core.implementations.dummy_retriever import DummyRetriever
from core.implementations.faiss_retriever import FAISSRetriever
from core.implementations.simple_retriever import SimpleRetriever
from core.interfaces.retriever import BaseRetriever, Document
from core.registry.retriever_registry import RetrieverRegistry


def _write_config(tmp_path, payload: dict) -> str:
    path = tmp_path / "retrieval.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def test_registry_loads_config_file():
    registry = RetrieverRegistry()
    assert registry.config.get("retrieval", {}).get("default_retriever") == "faiss"
    assert "retrievers" in registry.config["retrieval"]


def test_registry_lists_builtin_providers():
    registry = RetrieverRegistry()
    providers = registry.list_providers()
    assert set(["faiss", "simple", "dummy", "kg"]).issubset(set(providers))


def test_registry_lists_configured_retrievers():
    registry = RetrieverRegistry()
    assert set(registry.list_retrievers()) == {"faiss", "simple", "dummy", "kg"}


def test_resolve_uses_default_retriever_from_config():
    registry = RetrieverRegistry()
    key, provider, entry = registry.resolve()
    assert key == "faiss"
    assert provider == "faiss"
    assert entry.get("similarity_metric") == "cosine"


def test_resolve_explicit_name_overrides_default():
    registry = RetrieverRegistry()
    key, provider, _entry = registry.resolve("dummy")
    assert key == "dummy"
    assert provider == "dummy"


def test_resolve_unknown_provider_raises(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "not-real", "retrievers": {}}},
    )
    registry = RetrieverRegistry(config_path)
    with pytest.raises(ValueError, match="Unknown retriever provider"):
        registry.resolve()


def test_resolve_missing_default_raises(tmp_path):
    config_path = _write_config(tmp_path, {"retrieval": {"retrievers": {"dummy": {"provider": "dummy"}}}})
    registry = RetrieverRegistry(config_path)
    with pytest.raises(ValueError, match="default_retriever"):
        registry.resolve()


def test_create_dummy_retriever_from_config(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "dummy", "retrievers": {"dummy": {"provider": "dummy"}}}},
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create()
    assert isinstance(retriever, DummyRetriever)
    results = retriever.retrieve_with_scores([0.1] * 10, top_k=2)
    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_create_dummy_uses_embedder_dimension(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "dummy", "retrievers": {"dummy": {"provider": "dummy"}}}},
    )
    registry = RetrieverRegistry(config_path)
    embedder = DummyEmbedder(dimension=42)
    retriever = registry.create(embedder=embedder)
    assert retriever.index_dimension == 42


def test_create_dummy_uses_real_embedder_dimension(tmp_path, real_embedder):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "dummy", "retrievers": {"dummy": {"provider": "dummy"}}}},
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=real_embedder)
    assert retriever.index_dimension == real_embedder.dimension == 384


def test_create_faiss_retriever_with_explicit_dimension(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "faiss", "retrievers": {"faiss": {"provider": "faiss"}}}},
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create(dimension=8)
    assert isinstance(retriever, FAISSRetriever)
    assert retriever.index_dimension == 8


def test_create_faiss_loads_documents_from_configured_path(tmp_path, real_embedder):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(
        json.dumps([{"content": "alpha"}, {"content": "beta"}, {"content": "gamma"}]),
        encoding="utf-8",
    )
    config_path = _write_config(
        tmp_path,
        {
            "retrieval": {
                "default_retriever": "faiss",
                "retrievers": {
                    "faiss": {"provider": "faiss", "documents_path": str(corpus)}
                },
            }
        },
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=real_embedder)
    assert isinstance(retriever, FAISSRetriever)
    assert retriever.total_documents == 3
    assert len(retriever.retrieve(real_embedder.embed("alpha"), top_k=1)) == 1


def test_create_simple_retriever_requires_embedder(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "simple", "retrievers": {"simple": {"provider": "simple"}}}},
    )
    registry = RetrieverRegistry(config_path)
    with pytest.raises(ValueError, match="requires an embedder"):
        registry.create()


def test_create_simple_retriever_with_embedder_and_docs(tmp_path, real_embedder):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "simple", "retrievers": {"simple": {"provider": "simple"}}}},
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create(
        embedder=real_embedder,
        docs=[{"content": "hello"}, {"content": "world"}],
    )
    assert isinstance(retriever, SimpleRetriever)
    assert retriever.index_dimension == real_embedder.dimension == 384


class _EchoRetriever(BaseRetriever):
    def retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]:
        return [Document(content="custom")]

    @property
    def index_dimension(self) -> int:
        return 5


def test_register_custom_provider_is_plug_and_play(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"retrieval": {"default_retriever": "echo", "retrievers": {"echo": {"provider": "echo"}}}},
    )
    registry = RetrieverRegistry(config_path)
    registry.register("echo", lambda **kwargs: _EchoRetriever())
    retriever = registry.create()
    assert isinstance(retriever, _EchoRetriever)
    assert retriever.retrieve([0.0] * 5)[0].content == "custom"


def test_create_faiss_uses_similarity_metric_from_config(tmp_path, real_embedder):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([{"content": "alpha"}]), encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        {
            "retrieval": {
                "default_retriever": "faiss",
                "retrievers": {
                    "faiss": {
                        "provider": "faiss",
                        "similarity_metric": "l2",
                        "documents_path": str(corpus),
                    }
                },
            }
        },
    )
    registry = RetrieverRegistry(config_path)
    retriever = registry.create(embedder=real_embedder)
    assert retriever.similarity_metric == "l2"
