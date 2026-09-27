from typing import List, Optional
from core.interfaces.chunker import BaseChunker


class FixedSizeChunker(BaseChunker):
    """
    Splits text into fixed-size character chunks with optional overlap.
    """

    def __init__(self, chunk_size: int = 200, chunk_overlap: int = 20):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ValueError(f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str) -> List[str]:
        if not text:
            return []

        chunks = []
        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += step

        return chunks


class WordChunker(BaseChunker):
    """
    Splits text by words (whitespace delimited) with optional word overlap.
    """

    def __init__(self, chunk_size: int = 50, chunk_overlap: int = 10):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ValueError(f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str) -> List[str]:
        if not text:
            return []

        words = text.split()
        if not words:
            return []

        chunks = []
        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(words):
            end = min(start + self.chunk_size, len(words))
            chunk_words = words[start:end]
            chunk_str = " ".join(chunk_words).strip()
            if chunk_str:
                chunks.append(chunk_str)
            if end >= len(words):
                break
            start += step

        return chunks


class SmallChunker(FixedSizeChunker):
    """Pre-configured small chunking strategy."""
    def __init__(self, chunk_size: int = 100, chunk_overlap: int = 20):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


class LargeChunker(FixedSizeChunker):
    """Pre-configured large chunking strategy."""
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
