import pytest
from core.interfaces.retriever import Document
from core.implementations.chunker import FixedSizeChunker, WordChunker, SmallChunker, LargeChunker
from core.services.chunking_service import ChunkingService


def test_fixed_size_chunker():
    chunker = FixedSizeChunker(chunk_size=50, chunk_overlap=10)
    text = "Artificial Intelligence and Machine Learning are transforming modern enterprise architectures."
    chunks = chunker.chunk_text(text)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 50


def test_word_chunker():
    chunker = WordChunker(chunk_size=5, chunk_overlap=1)
    text = "One two three four five six seven eight nine ten"
    chunks = chunker.chunk_text(text)

    assert len(chunks) >= 2
    assert "One two three four five" in chunks[0]


def test_chunk_document_preserves_metadata():
    doc = Document(content="Sentence one. Sentence two. Sentence three. Sentence four.", metadata={"source": "test.pdf"})
    chunker = FixedSizeChunker(chunk_size=20, chunk_overlap=5)

    chunks = chunker.chunk_document(doc)
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c.metadata["source"] == "test.pdf"
        assert c.metadata["chunk_index"] == i
        assert c.metadata["total_chunks"] == len(chunks)


def test_chunking_service_from_config():
    service = ChunkingService("config/retrieval.yaml")
    small_chunker = service.get_chunker("small")
    large_chunker = service.get_chunker("large")

    assert isinstance(small_chunker, FixedSizeChunker)
    assert isinstance(large_chunker, FixedSizeChunker)
    assert small_chunker.chunk_size < large_chunker.chunk_size
