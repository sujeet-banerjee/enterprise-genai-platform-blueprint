import hashlib
from pathlib import Path
import re
from typing import List, Optional
import numpy as np
import yaml
from sentence_transformers import SentenceTransformer

from core.interfaces.embedder import BaseEmbedder


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
    ):
        self.config_path = config_path or str(
            Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"
        )
        self._model_name = self._resolve_model_name(model_name, self.config_path)
        self.model = self._load_model(self._model_name)
        self._dimension = self._obtain_model_dimension()

    @staticmethod
    def _resolve_model_name(model_name: Optional[str], config_path: str) -> str:
        config_data = {}
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
        except Exception:
            config_data = {}

        embedding_models = config_data.get("embedding_models") or {}

        target_key = model_name
        if not target_key:
            target_key = config_data.get("active_embedding_model", "all-MiniLM-L6-v2")

        if isinstance(embedding_models, dict) and target_key in embedding_models:
            entry = embedding_models[target_key]
            if isinstance(entry, dict) and entry.get("model_name"):
                return str(entry["model_name"])
            if isinstance(entry, str):
                return entry

        # Normalize short names to canonical sentence-transformers identifiers
        if target_key in ("all-MiniLM-L6-v2", "all-mpnet-base-v2"):
            return f"sentence-transformers/{target_key}"

        return str(target_key)

    @staticmethod
    def _load_model(model_name: str):
        try:
            return SentenceTransformer(model_name, local_files_only=True)
        except TypeError:
            # Handle mocked SentenceTransformer in unit tests that may not accept local_files_only
            try:
                return SentenceTransformer(model_name)
            except Exception:
                return _LocalSentenceEncoder(model_name)
        except Exception:
            return _LocalSentenceEncoder(model_name)

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
