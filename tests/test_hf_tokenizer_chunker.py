import pytest

from core.implementations.chunker import ChunkerFactory
from core.implementations.hf_tokenizer_chunker import HFTokenizerChunker


@pytest.fixture(scope="module")
def chunker():
    return HFTokenizerChunker(chunk_size=20, chunk_overlap=5)


def test_chunks_long_text(chunker):
    text = (
        "Artificial intelligence is the simulation of human intelligence processes "
        "by computer systems. "
    ) * 6
    chunks = chunker.chunk_text(text)
    assert len(chunks) >= 2
    assert all(chunk.metadata["chunk_strategy"] == "token" for chunk in chunks)


def test_chunk_token_size_is_bounded(chunker):
    text = "word " * 200
    chunks = chunker.chunk_text(text)
    for chunk in chunks:
        tokens = chunker._tokenizer.encode(chunk.content, add_special_tokens=False)
        assert len(tokens) <= 20


def test_empty_text_yields_no_chunks(chunker):
    assert chunker.chunk_text("") == []


def test_overlapping_chunks_share_tokens():
    chunker = HFTokenizerChunker(chunk_size=20, chunk_overlap=5)
    text = " ".join(str(i) for i in range(120))
    chunks = chunker.chunk_text(text)
    assert len(chunks) >= 2
    assert chunks[0].metadata["token_end"] > chunks[1].metadata["token_start"]


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        HFTokenizerChunker(chunk_size=0)
    with pytest.raises(ValueError):
        HFTokenizerChunker(chunk_size=10, chunk_overlap=10)


def test_factory_creates_token_chunker():
    chunker = ChunkerFactory.create(strategy="token")
    assert isinstance(chunker, HFTokenizerChunker)
    assert chunker.strategy_name == "token"
