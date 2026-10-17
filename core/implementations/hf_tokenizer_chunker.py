from typing import List, Optional

from transformers import AutoTokenizer

from core.interfaces.chunker import BaseChunker
from core.interfaces.retriever import Document


class HFTokenizerChunker(BaseChunker):
    """
    Genuine token-aware chunker using the real tokenizer of an embedding model.

    Chunk boundaries are measured in model sub-word tokens (not characters), so
    chunk sizes map directly onto an embedding model's context window. The
    tokenizer is loaded from a real HuggingFace model id.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        chunk_size: int = 128,
        chunk_overlap: int = 20,
    ):
        if chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        if chunk_overlap < 0:
            raise ValueError(f"chunk_overlap cannot be negative, got {chunk_overlap}")
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})"
            )

        self._model_name = model_name
        self._chunk_size = int(chunk_size)
        self._chunk_overlap = int(chunk_overlap)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    @property
    def strategy_name(self) -> str:
        return "token"

    def chunk_text(self, text: str, metadata: Optional[dict] = None) -> List[Document]:
        token_ids = self._tokenizer.encode(text or "", add_special_tokens=False)
        if not token_ids:
            return []

        base_meta = dict(metadata) if metadata else {}
        chunks: List[Document] = []
        step = self._chunk_size - self._chunk_overlap
        start = 0
        chunk_idx = 0

        while start < len(token_ids):
            end = min(start + self._chunk_size, len(token_ids))
            decoded = self._tokenizer.decode(token_ids[start:end], skip_special_tokens=True)
            piece = (decoded if isinstance(decoded, str) else " ".join(decoded)).strip()
            if piece:
                meta = dict(base_meta)
                meta.update(
                    {
                        "chunk_index": chunk_idx,
                        "chunk_strategy": "token",
                        "chunk_size": self._chunk_size,
                        "chunk_overlap": self._chunk_overlap,
                        "token_start": start,
                        "token_end": end,
                    }
                )
                chunks.append(Document(content=piece, metadata=meta))
                chunk_idx += 1

            if end >= len(token_ids):
                break
            next_start = end - self._chunk_overlap
            start = next_start if next_start > start else start + step

        return chunks
