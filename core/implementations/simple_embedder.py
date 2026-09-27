import hashlib
import numpy as np
from typing import List, Optional
from core.interfaces.embedder import BaseEmbedder


class SimpleEmbedder(BaseEmbedder):
    """
    Configurable embedding model implementation.
    Supports sentence-transformers models (e.g. all-MiniLM-L6-v2, all-mpnet-base-v2)
    with dimension determined from the selected model and deterministic fallback for offline environments.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

        # Determine embedding dimension based on model specification
        if "mpnet" in model_name.lower():
            self._dimension = 768
        elif "minilm" in model_name.lower():
            self._dimension = 384
        else:
            self._dimension = 384

        try:
            from sentence_transformers import SentenceTransformer
            # Try loading cached local model first to avoid network timeout delays
            self._model = SentenceTransformer(model_name, local_files_only=True)
            if hasattr(self._model, "get_sentence_embedding_dimension"):
                self._dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception:
            self._model = None

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> List[float]:
        if self._model is not None:
            try:
                emb = self._model.encode(text)
                return emb.tolist() if hasattr(emb, "tolist") else list(emb)
            except Exception:
                pass

        return self._deterministic_embed(text, self._dimension)

    def _deterministic_embed(self, text: str, dim: int) -> List[float]:
        vec = np.zeros(dim, dtype=np.float32)
        words = text.lower().split()
        if not words:
            return vec.tolist()

        for w in words:
            for i in range(3):
                h = int(hashlib.md5(f"{w}_{i}".encode()).hexdigest(), 16)
                idx = h % dim
                sign = 1.0 if (h // dim) % 2 == 0 else -1.0
                vec[idx] += sign
            for j in range(len(w) - 2):
                ngram = w[j:j + 3]
                h = int(hashlib.md5(ngram.encode()).hexdigest(), 16)
                idx = h % dim
                sign = 1.0 if (h // dim) % 2 == 0 else -1.0
                vec[idx] += 0.5 * sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()
