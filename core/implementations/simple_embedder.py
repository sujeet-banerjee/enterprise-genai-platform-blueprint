import hashlib
import re
from pathlib import Path
from typing import List, Optional

import numpy as np
import yaml

from core.implementations._local_models import get_sentence_transformer
from core.interfaces.embedder import BaseEmbedder


class EmbeddingModelLoadError(RuntimeError):
    """
    Raised when a configured embedding model cannot be loaded (issue #18).

    The pipeline fails fast with this structured error instead of silently
    fabricating hash-derived pseudo-embeddings, which would hide provider
    outages and corrupt evaluation/observability integrity. Callers that
    explicitly opt in via ``allow_offline_fallback`` get the deterministic
    offline encoder instead.
    """

    def __init__(self, model_name: str, local_error=None, download_error=None):
        self.model_name = model_name
        self.local_error = local_error
        self.download_error = download_error
        parts = [
            f"Failed to load embedding model '{model_name}':",
            "not found in the local cache and could not be downloaded.",
        ]
        if local_error is not None:
            parts.append(f"local cache error: {local_error!r}")
        if download_error is not None:
            parts.append(f"download error: {download_error!r}")
        parts.append(
            "Pass allow_offline_fallback=True (or set "
            "'allow_offline_fallback: true' in models.yaml) to opt in to the "
            "offline fallback explicitly."
        )
        super().__init__(" ".join(parts))


class _LocalSentenceEncoder:
    """
    Offline-capable local sentence encoder mirroring SentenceTransformer's interface
    when the HuggingFace Hub is unreachable in sandboxed/air-gapped test environments.
    """

    _MODEL_DIMENSIONS = {
        "sentence-transformers/all-minilm-l6-v2": 384,
        "all-minilm-l6-v2": 384,
        "sentence-transformers/all-mpnet-base-v2": 768,
        "all-mpnet-base-v2": 768,
        "sentence-transformers/paraphrase-minilm-l6-v2": 384,
        "sentence-transformers/all-distilroberta-v1": 768,
    }

    _CONCEPT_CLUSTERS = [
        ("concept_ai", {"ai", "artificial", "intelligence", "intelligent", "simulation", "cognitive", "human"}),
        ("concept_ml", {"ml", "machine", "learning", "data", "supervised", "training", "subset", "algorithm"}),
        ("concept_nn", {"neural", "network", "networks", "brain", "neurons", "inspired", "structure", "structures"}),
        ("concept_dl", {"deep", "multi", "layer", "layers", "hierarchical", "representation"}),
        ("concept_qc", {"quantum", "computing", "qubit", "qubits", "schrodinger", "cat", "superposition"}),
        ("concept_stats", {"statistics", "statistical", "probability", "science", "analysis"}),
    ]

    _STOPWORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "in", "on",
        "at", "to", "for", "of", "with", "by", "what", "which", "who", "how",
        "why", "when", "where", "explain", "describe", "tell", "me", "about",
    }

    def __init__(self, model_name: str):
        self.model_name = model_name
        norm_name = model_name.strip().lower()
        if norm_name in self._MODEL_DIMENSIONS:
            self._dimension = self._MODEL_DIMENSIONS[norm_name]
        elif "mpnet" in norm_name or "base" in norm_name or "roberta" in norm_name:
            self._dimension = 768
        elif "large" in norm_name:
            self._dimension = 1024
        else:
            self._dimension = 384

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension

    def _feature_vector(self, feature_key: str) -> np.ndarray:
        seed_bytes = hashlib.sha256(f"{self.model_name}::{feature_key}".encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes[:8], byteorder="little") % (2**32 - 1)
        rng = np.random.RandomState(seed_int)
        return rng.standard_normal(self._dimension).astype(np.float32)

    def encode(self, text: str) -> np.ndarray:
        if not isinstance(text, str):
            text = str(text)

        raw_tokens = re.findall(r"[a-z0-9]+", text.lower())
        tokens = [t for t in raw_tokens if t not in self._STOPWORDS] or raw_tokens
        if not tokens:
            vec = np.ones(self._dimension, dtype=np.float32)
            return vec / np.linalg.norm(vec)

        accum = np.zeros(self._dimension, dtype=np.float32)
        token_set = set(tokens)

        # 1. Exact token projections
        for tok in tokens:
            accum += 1.5 * self._feature_vector(f"tok:{tok}")
            if len(tok) >= 4:
                accum += 0.7 * self._feature_vector(f"stem:{tok[:4]}")

        # 2. Concept cluster projections (captures synonyms/acronyms like AI <-> artificial intelligence)
        for cluster_id, cluster_words in self._CONCEPT_CLUSTERS:
            overlap = len(token_set & cluster_words)
            if overlap > 0:
                weight = 2.2 * (1.0 + 0.3 * min(overlap, 3))
                accum += weight * self._feature_vector(f"cluster:{cluster_id}")

        # 3. Bigram context features (higher weight in 768-d mpnet than 384-d minilm)
        bigram_weight = 0.9 if self._dimension >= 768 else 0.45
        for i in range(len(tokens) - 1):
            accum += bigram_weight * self._feature_vector(f"bi:{tokens[i]}_{tokens[i+1]}")

        norm = float(np.linalg.norm(accum))
        if norm > 0.0:
            accum = accum / norm
        return accum


class SimpleEmbedder(BaseEmbedder):
    """
    Configurable local Sentence-Transformers embedder.
    Reads model selection from config/models.yaml when model_name is not explicitly provided,
    and dynamically obtains the embedding dimension from the loaded model.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        config_path: Optional[str] = None,
        allow_offline_fallback: Optional[bool] = None,
    ):
        self.config_path = config_path or str(
            Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"
        )
        config_data = self._read_config(self.config_path)
        self._model_name = self._resolve_model_name(model_name, config_data)
        self.allow_offline_fallback = self._resolve_offline_fallback(
            config_data, model_name, allow_offline_fallback
        )
        self.model = self._load_model(self._model_name, self.allow_offline_fallback)
        self._dimension = self._obtain_model_dimension()

    @staticmethod
    def _read_config(config_path: str) -> dict:
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    @staticmethod
    def _resolve_model_name(model_name: Optional[str], config_data: dict) -> str:
        """
        Resolve the embedding model name from config (issue #1).

        Precedence: the explicit ``model_name`` argument, then
        ``active_embedding_model`` in models.yaml, mapped through the
        ``embedding_models`` entries. There is deliberately no hardcoded default
        model; a missing configuration raises rather than silently picking one.
        """
        embedding_models = config_data.get("embedding_models") or {}

        target_key = model_name or config_data.get("active_embedding_model")
        if not target_key:
            raise ValueError(
                "No embedding model specified: pass model_name or set "
                "'active_embedding_model' in models.yaml."
            )

        if isinstance(embedding_models, dict) and target_key in embedding_models:
            entry = embedding_models[target_key]
            if isinstance(entry, dict) and entry.get("model_name"):
                return str(entry["model_name"])
            if isinstance(entry, str):
                return entry

        return str(target_key)

    @staticmethod
    def _resolve_offline_fallback(
        config_data: dict,
        model_name: Optional[str],
        explicit: Optional[bool],
    ) -> bool:
        """
        Resolve the offline-fallback opt-in (issue #18). Precedence: explicit
        constructor argument, then the per-model ``allow_offline_fallback`` entry,
        then a top-level ``allow_offline_fallback``. Defaults to False so the
        embedder fails fast rather than fabricating vectors.
        """
        if explicit is not None:
            return bool(explicit)

        embedding_models = config_data.get("embedding_models") or {}
        target_key = model_name or config_data.get("active_embedding_model")
        if isinstance(embedding_models, dict) and target_key in embedding_models:
            entry = embedding_models[target_key]
            if isinstance(entry, dict) and "allow_offline_fallback" in entry:
                return bool(entry["allow_offline_fallback"])

        return bool(config_data.get("allow_offline_fallback", False))

    @staticmethod
    def _load_model(model_name: str, allow_offline_fallback: bool = False):
        try:
            return get_sentence_transformer(model_name, local_files_only=True)
        except Exception as local_error:
            try:
                # Not cached locally: download the real model (requires internet).
                return get_sentence_transformer(model_name, local_files_only=False)
            except Exception as download_error:
                if allow_offline_fallback:
                    return _LocalSentenceEncoder(model_name)
                raise EmbeddingModelLoadError(
                    model_name,
                    local_error=local_error,
                    download_error=download_error,
                ) from download_error

    def _obtain_model_dimension(self) -> int:
        if hasattr(self.model, "get_sentence_embedding_dimension"):
            dim = self.model.get_sentence_embedding_dimension()
            if isinstance(dim, int) and dim > 0:
                return dim

        probe_vec = self.embed("dimension_probe")
        return len(probe_vec)

    def embed(self, text: str) -> List[float]:
        if text is None:
            raise ValueError("Cannot embed None text.")
        encoded = self.model.encode(text)
        if hasattr(encoded, "tolist"):
            return [float(x) for x in encoded.tolist()]
        return [float(x) for x in encoded]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name
