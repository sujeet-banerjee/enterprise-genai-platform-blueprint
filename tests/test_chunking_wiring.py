"""Tests for issue #9: chunking config + ChunkerFactory wired into the pipeline.

Two acceptance criteria are exercised here:

1. Changing ``chunking.active_strategy`` changes the produced chunks.
2. ``ChunkerFactory`` honors configuration for *all* strategies
   (word/fixed/token in addition to the already config-driven small/large).
"""

import json
from pathlib import Path

import yaml

from core.implementations.chunker import (
    ChunkerFactory,
    FixedSizeChunker,
    LargeChunker,
    SmallChunker,
    WordChunker,
)
from core.implementations.hf_tokenizer_chunker import HFTokenizerChunker
from core.registry.retriever_registry import RetrieverRegistry

LONG_TEXT = " ".join(["token"] * 300)


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _write_corpus(path: Path, contents: list) -> str:
    path.write_text(json.dumps([{"content": c} for c in contents]), encoding="utf-8")
    return str(path)


def _chunking_config(tmp_path: Path, *, active_strategy=None, strategies=None, enabled=None) -> str:
    chunking: dict = {"strategies": strategies or {}}
    if active_strategy is not None:
        chunking["active_strategy"] = active_strategy
    if enabled is not None:
        chunking["enabled"] = enabled
    return _write_yaml(tmp_path / "retrieval.yaml", {"chunking": chunking})


def _retriever_config(tmp_path: Path, corpus_path: str, chunking: dict | None = None, name: str = "retrieval.yaml") -> str:
    payload: dict = {
        "retrieval": {
            "default_retriever": "simple",
            "retrievers": {"simple": {"provider": "simple", "documents_path": corpus_path}},
        }
    }
    if chunking is not None:
        payload["chunking"] = chunking
    return _write_yaml(tmp_path / name, payload)


def test_factory_word_strategy_reads_config(tmp_path):
    cfg = _chunking_config(tmp_path, strategies={"word": {"chunk_size": 7, "chunk_overlap": 2}})

    chunker = ChunkerFactory.create("word", config_path=cfg)

    assert isinstance(chunker, WordChunker)
    assert chunker.chunk_size == 7
    assert chunker.chunk_overlap == 2


def test_factory_word_strategy_falls_back_to_defaults(tmp_path):
    cfg = _chunking_config(tmp_path, strategies={})

    chunker = ChunkerFactory.create("word", config_path=cfg)

    assert isinstance(chunker, WordChunker)
    assert chunker.chunk_size == 50
    assert chunker.chunk_overlap == 10


def test_factory_fixed_strategy_reads_config(tmp_path):
    cfg = _chunking_config(tmp_path, strategies={"fixed": {"chunk_size": 33, "chunk_overlap": 3}})

    chunker = ChunkerFactory.create("fixed", config_path=cfg)

    assert isinstance(chunker, FixedSizeChunker)
    assert chunker.chunk_size == 33
    assert chunker.chunk_overlap == 3


def test_factory_explicit_args_override_config(tmp_path):
    cfg = _chunking_config(tmp_path, strategies={"word": {"chunk_size": 7, "chunk_overlap": 2}})

    chunker = ChunkerFactory.create("word", config_path=cfg, chunk_size=99, chunk_overlap=9)

    assert chunker.chunk_size == 99
    assert chunker.chunk_overlap == 9


def test_factory_token_strategy_reads_config_and_chunks_by_tokens(tmp_path):
    cfg = _chunking_config(
        tmp_path,
        strategies={"token": {"chunk_size": 16, "chunk_overlap": 4}},
    )

    chunker = ChunkerFactory.create("token", config_path=cfg)

    assert isinstance(chunker, HFTokenizerChunker)
    assert chunker.chunk_size == 16
    assert chunker.chunk_overlap == 4

    chunks = chunker.chunk_text("machine learning models learn patterns from data " * 20)
    assert len(chunks) > 1
    for chunk in chunks:
        tokens = chunker._tokenizer.encode(chunk.content, add_special_tokens=False)
        assert len(tokens) <= 16


def test_factory_create_from_config_uses_active_strategy(tmp_path):
    cfg = _chunking_config(
        tmp_path,
        active_strategy="large",
        strategies={
            "small": {"chunk_size": 120, "chunk_overlap": 20, "separator": " "},
            "large": {"chunk_size": 400, "chunk_overlap": 50, "separator": " "},
        },
    )

    chunker = ChunkerFactory.create_from_config(cfg)

    assert isinstance(chunker, LargeChunker)
    assert chunker.chunk_size == 400
    assert chunker.chunk_overlap == 50


def test_factory_create_from_config_small(tmp_path):
    cfg = _chunking_config(
        tmp_path,
        active_strategy="small",
        strategies={"small": {"chunk_size": 90, "chunk_overlap": 10, "separator": " "}},
    )

    chunker = ChunkerFactory.create_from_config(cfg)

    assert isinstance(chunker, SmallChunker)
    assert chunker.chunk_size == 90


def test_registry_chunks_indexed_documents_using_active_strategy(tmp_path, real_embedder):
    corpus = _write_corpus(tmp_path / "corpus.json", [LONG_TEXT])
    cfg = _retriever_config(
        tmp_path,
        corpus,
        chunking={
            "active_strategy": "small",
            "strategies": {"small": {"chunk_size": 120, "chunk_overlap": 20, "separator": " "}},
        },
    )

    retriever = RetrieverRegistry(cfg).create(embedder=real_embedder)

    assert len(retriever.docs) > 1
    assert all(doc.metadata.get("chunk_strategy") == "small" for doc in retriever.docs)
    assert all(len(doc.content) <= 120 for doc in retriever.docs)


def test_registry_active_strategy_change_changes_chunks(tmp_path, real_embedder):
    corpus = _write_corpus(tmp_path / "corpus.json", [LONG_TEXT])
    strategies = {
        "small": {"chunk_size": 120, "chunk_overlap": 20, "separator": " "},
        "large": {"chunk_size": 400, "chunk_overlap": 50, "separator": " "},
    }

    def build(active: str):
        cfg = _retriever_config(
            tmp_path,
            corpus,
            chunking={"active_strategy": active, "strategies": strategies},
            name=f"{active}.yaml",
        )
        return RetrieverRegistry(cfg).create(embedder=real_embedder)

    small = build("small")
    large = build("large")

    assert len(small.docs) > len(large.docs) > 0
    assert all(len(doc.content) <= 120 for doc in small.docs)
    assert all(len(doc.content) <= 400 for doc in large.docs)


def test_registry_chunking_disabled_passes_documents_through(tmp_path, real_embedder):
    corpus = _write_corpus(tmp_path / "corpus.json", [LONG_TEXT])
    cfg = _retriever_config(
        tmp_path,
        corpus,
        chunking={
            "enabled": False,
            "active_strategy": "small",
            "strategies": {"small": {"chunk_size": 120, "chunk_overlap": 20}},
        },
    )

    retriever = RetrieverRegistry(cfg).create(embedder=real_embedder)

    assert len(retriever.docs) == 1
    assert "chunk_strategy" not in retriever.docs[0].metadata


def test_registry_without_chunking_config_passes_through(tmp_path, real_embedder):
    corpus = _write_corpus(tmp_path / "corpus.json", ["alpha", "beta"])
    cfg = _retriever_config(tmp_path, corpus, chunking=None)

    retriever = RetrieverRegistry(cfg).create(embedder=real_embedder)

    assert len(retriever.docs) == 2
    assert all("chunk_strategy" not in doc.metadata for doc in retriever.docs)


def test_registry_accepts_explicit_chunker_override(tmp_path, real_embedder):
    corpus = _write_corpus(tmp_path / "corpus.json", [LONG_TEXT])
    cfg = _retriever_config(tmp_path, corpus, chunking=None)

    retriever = RetrieverRegistry(cfg).create(
        embedder=real_embedder, chunker=WordChunker(chunk_size=10, chunk_overlap=0)
    )

    assert len(retriever.docs) > 1
    assert all(doc.metadata.get("chunk_strategy") == "word" for doc in retriever.docs)


def test_build_pipeline_chunks_documents_via_config(tmp_path):
    from app.main import build_pipeline

    corpus = _write_corpus(tmp_path / "corpus.json", [LONG_TEXT])
    models = _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096, "temperature": 0.0}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )
    retrieval = _retriever_config(
        tmp_path,
        corpus,
        chunking={
            "active_strategy": "large",
            "strategies": {"large": {"chunk_size": 400, "chunk_overlap": 50, "separator": " "}},
        },
        name="retrieval.yaml",
    )

    pipeline = build_pipeline(models_config_path=Path(models), retrieval_config_path=Path(retrieval))

    assert len(pipeline.retriever.docs) > 1
    assert all(doc.metadata.get("chunk_strategy") == "large" for doc in pipeline.retriever.docs)
