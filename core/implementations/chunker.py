from pathlib import Path
from typing import List, Optional
import yaml

from core.interfaces.chunker import BaseChunker
from core.interfaces.retriever import Document


class ConfigurableChunker(BaseChunker):
    """
    Configuration-driven document chunker supporting 'small', 'large', and custom strategies
    declared in config/retrieval.yaml.
    """

    def __init__(
        self,
        strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separator: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        cfg = self._load_config(config_path)
        chunking_cfg = cfg.get("chunking") or {}
        strategies_cfg = chunking_cfg.get("strategies") or {}

        resolved_strategy = (strategy or chunking_cfg.get("active_strategy") or "small").lower()
        if strategy is not None and resolved_strategy not in strategies_cfg and chunk_size is None:
            raise ValueError(
                f"Unknown chunking strategy '{strategy}'. Available strategies: {list(strategies_cfg.keys())}"
            )

        strat_params = strategies_cfg.get(resolved_strategy) or {}

        resolved_size = chunk_size if chunk_size is not None else strat_params.get("chunk_size")
        if resolved_size is None or int(resolved_size) <= 0:
            raise ValueError(f"Invalid chunk_size '{resolved_size}' for strategy '{resolved_strategy}'.")

        resolved_overlap = (
            chunk_overlap
            if chunk_overlap is not None
            else strat_params.get("chunk_overlap", 0)
        )
        if int(resolved_overlap) < 0 or int(resolved_overlap) >= int(resolved_size):
            raise ValueError(
                f"chunk_overlap ({resolved_overlap}) must be >= 0 and < chunk_size ({resolved_size})."
            )

        self._strategy_name = resolved_strategy
        self._chunk_size = int(resolved_size)
        self._chunk_overlap = int(resolved_overlap)
        self._separator = separator if separator is not None else str(strat_params.get("separator", " "))

    @staticmethod
    def _load_config(config_path: Optional[str] = None) -> dict:
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    @property
    def strategy_name(self) -> str:
        return self._strategy_name

    def chunk_text(self, text: str, metadata: Optional[dict] = None) -> List[Document]:
        cleaned = (text or "").strip()
        if not cleaned:
            return []

        base_meta = dict(metadata) if metadata else {}
        if len(cleaned) <= self._chunk_size:
            meta = dict(base_meta)
            meta.update(
                {
                    "chunk_index": 0,
                    "chunk_strategy": self._strategy_name,
                    "chunk_size": self._chunk_size,
                    "chunk_overlap": self._chunk_overlap,
                }
            )
            return [Document(content=cleaned, metadata=meta)]

        chunks: List[Document] = []
        step = max(1, self._chunk_size - self._chunk_overlap)
        start = 0
        chunk_idx = 0
        text_len = len(cleaned)

        while start < text_len:
            end = min(text_len, start + self._chunk_size)
            if end < text_len and self._separator:
                # Prefer breaking at last separator inside the window to avoid splitting words
                sep_pos = cleaned.rfind(self._separator, start + max(1, self._chunk_size // 2), end)
                if sep_pos != -1 and sep_pos > start:
                    end = sep_pos

            piece = cleaned[start:end].strip()
            if piece:
                meta = dict(base_meta)
                meta.update(
                    {
                        "chunk_index": chunk_idx,
                        "chunk_strategy": self._strategy_name,
                        "chunk_size": self._chunk_size,
                        "chunk_overlap": self._chunk_overlap,
                        "char_start": start,
                        "char_end": end,
                    }
                )
                chunks.append(Document(content=piece, metadata=meta))
                chunk_idx += 1

            if end >= text_len:
                break

            next_start = end - self._chunk_overlap
            if next_start <= start:
                next_start = start + step
            start = next_start

        return chunks


class SmallChunker(ConfigurableChunker):
    """
    Chunker preconfigured for the 'small' strategy from config/retrieval.yaml.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        config_path: Optional[str] = None,
    ):
        super().__init__(
            strategy="small",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            config_path=config_path,
        )


class LargeChunker(ConfigurableChunker):
    """
    Chunker preconfigured for the 'large' strategy from config/retrieval.yaml.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        config_path: Optional[str] = None,
    ):
        super().__init__(
            strategy="large",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            config_path=config_path,
        )


class ChunkerFactory:
    """
    Factory for creating chunkers based on declarative strategy names.
    """

    @staticmethod
    def create(
        strategy: Optional[str] = None,
        config_path: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> BaseChunker:
        norm = (strategy or "").lower()
        if norm == "small":
            return SmallChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                config_path=config_path,
            )
        if norm == "large":
            return LargeChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                config_path=config_path,
            )
        return ConfigurableChunker(
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            config_path=config_path,
        )
