import pytest

from core.implementations.chunker import (
    ChunkerFactory,
    ConfigurableChunker,
    FixedSizeChunker,
    LargeChunker,
    SmallChunker,
    WordChunker,
)
from core.interfaces.chunker import BaseChunker
from core.interfaces.retriever import Document


def test_fixed_size_chunker_returns_document_chunks():
    chunker = FixedSizeChunker(chunk_size=50, chunk_overlap=10)
    text = "Artificial Intelligence and Machine Learning are transforming modern enterprise architectures."
    chunks = chunker.chunk_text(text)

    assert len(chunks) > 1
    assert all(isinstance(c, Document) for c in chunks)
    for chunk in chunks:
        assert len(chunk.content) <= 50


def test_word_chunker_splits_by_words():
    chunker = WordChunker(chunk_size=5, chunk_overlap=1)
    text = "One two three four five six seven eight nine ten"
    chunks = chunker.chunk_text(text)

    assert len(chunks) >= 2
    assert "One two three four five" in chunks[0].content
    assert all(c.metadata["chunk_strategy"] == "word" for c in chunks)


def test_word_chunker_invalid_parameters_raise():
    with pytest.raises(ValueError):
        WordChunker(chunk_size=0)
    with pytest.raises(ValueError):
        WordChunker(chunk_size=5, chunk_overlap=-1)
    with pytest.raises(ValueError):
        WordChunker(chunk_size=5, chunk_overlap=5)


def test_chunk_documents_preserves_source_metadata():
    docs = [
        Document(
            content="Sentence one. Sentence two. Sentence three. Sentence four.",
            metadata={"source": "test.pdf"},
        )
    ]
    chunker = FixedSizeChunker(chunk_size=20, chunk_overlap=5)

    chunks = chunker.chunk_documents(docs)
    assert len(chunks) > 1
    for c in chunks:
        assert c.metadata["source"] == "test.pdf"
        assert "chunk_index" in c.metadata


def test_chunker_factory_creates_word_strategy():
    chunker = ChunkerFactory.create("word")
    assert isinstance(chunker, WordChunker)
    assert isinstance(chunker, BaseChunker)


def test_chunker_factory_small_and_large_still_resolve():
    small = ChunkerFactory.create("small")
    large = ChunkerFactory.create("large")
    assert isinstance(small, SmallChunker)
    assert isinstance(large, LargeChunker)
    assert isinstance(small, ConfigurableChunker)
    assert small.chunk_size < large.chunk_size
