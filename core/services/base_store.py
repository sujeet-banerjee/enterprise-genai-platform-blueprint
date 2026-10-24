"""BaseStore interface and registry.

Backend-agnostic contract for durable state (run history, traces,
experiments, audit events). Defaults to in-memory; concrete backends
registered via factory/config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional


class BaseStore(ABC):
    """Minimal pluggable store contract."""

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a single record by key."""

    @abstractmethod
    def set(self, key: str, value: Dict[str, Any], ttl_seconds: Optional[float] = None) -> None:
        """Set/replace a record by key."""

    @abstractmethod
    def list(self, prefix: str = "", limit: int = 1000, **filters: Any) -> List[Dict[str, Any]]:
        """List records matching prefix/filters."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a record by key. Return True if deleted."""

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """Health/status for readiness probes."""

    def close(self) -> None:
        """Optional cleanup."""

    def clear(self) -> None:
        """Optional clear for tests."""


class StoreBackendError(RuntimeError):
    """Raised when a store backend fails in a way that callers can degrade."""


def _serialize_value(value: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure serializable dict."""
    # Best-effort shallow copy
    return dict(value)


def build_store(config_path: Optional[str] = None, **overrides: Any) -> BaseStore:
    """Build store from config (memory default)."""
    from pathlib import Path

    import yaml

    config: Dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                config = data
    config.update(overrides)

    backend = str(config.get("backend", "memory")).strip().lower()
    if backend in ("", "none"):
        backend = "memory"

    if backend == "memory":
        from core.services.store_backends import MemoryStore

        return MemoryStore(**config)
    if backend == "postgres":
        from core.services.store_backends import PostgresStore

        return PostgresStore(**config)
    if backend == "sqlite":
        from core.services.store_backends import SQLiteStore

        return SQLiteStore(**config)

    from core.services.store_backends import MemoryStore

    return MemoryStore(**config)
