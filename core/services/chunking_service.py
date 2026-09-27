import yaml
from typing import Dict, Any, Union, Optional
from core.interfaces.chunker import BaseChunker
from core.implementations.chunker import FixedSizeChunker, WordChunker, SmallChunker, LargeChunker


class ChunkingService:
    """
    Factory service to build chunkers from configuration.
    """

    def __init__(self, config_or_path: Union[str, dict] = "config/retrieval.yaml"):
        if isinstance(config_or_path, str):
            try:
                with open(config_or_path, "r") as f:
                    self.config = yaml.safe_load(f) or {}
            except Exception:
                self.config = {}
        else:
            self.config = config_or_path or {}

    def get_chunker(self, strategy_name: Optional[str] = None) -> BaseChunker:
        chunking_cfg = self.config.get("chunking", {})
        target = strategy_name or chunking_cfg.get("active_strategy", "small")

        strategies = chunking_cfg.get("strategies", {})
        strategy_cfg = strategies.get(target, {})

        strategy_type = strategy_cfg.get("type", target).lower()
        chunk_size = strategy_cfg.get("chunk_size", 100 if target == "small" else 500)
        chunk_overlap = strategy_cfg.get("chunk_overlap", 20 if target == "small" else 50)

        if strategy_type in ["small", "fixed", "character"]:
            return FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy_type in ["large"]:
            return LargeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy_type in ["word", "token"]:
            return WordChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        else:
            return FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
