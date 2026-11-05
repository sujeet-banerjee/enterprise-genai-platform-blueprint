"""BaseStore interface and registry.

Backend-agnostic contract for durable state (run history, traces,
experiments, audit events). Defaults to in-memory; concrete backends
registered via factory/config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


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
    """Build store from config (memory default).

    Supports cross-region strategy via optional `region` and `replication` config
    (Workstream I #118): namespace keys by region and expose region in health.
    """
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

        store: BaseStore = MemoryStore(**config)
    elif backend == "postgres":
        from core.services.store_backends import PostgresStore

        store = PostgresStore(**config)
    elif backend == "sqlite":
        from core.services.store_backends import SQLiteStore

        store = SQLiteStore(**config)
    else:
        from core.services.store_backends import MemoryStore

        store = MemoryStore(**config)

    # Optional cross-region namespace wrapper (config-driven; default off)
    region = config.get("region")
    replication = config.get("replication") or {}
    if region or replication:
        from core.services.store_backends import RegionalStore

        store = RegionalStore(store, region=region, replication=replication)
    return store
