"""Ingestion service hooks for sync and incremental cursors (#115)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.interfaces.connector import SyncCursor
from core.registry.connector_registry import ConnectorRegistry
from core.services.acl import normalize_document


class IngestionService:
    def __init__(
        self,
        config_path: Optional[str] = None,
        registry: Optional[ConnectorRegistry] = None,
        state_path: Optional[str] = None,
    ) -> None:
        self.registry = registry or ConnectorRegistry(config_path=config_path)
        ingestion_cfg = self.registry.config.get("ingestion") or self.registry.config
        self.state_path = state_path or ingestion_cfg.get("state_path") or "data/ingestion_state.json"
        self._state_path = Path(self.state_path)

    def _load_state(self) -> Dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

    def list_connectors(self) -> Dict[str, Any]:
        return self.registry.describe()

    def sync(self, connector_name: Optional[str] = None, since: Optional[Any] = None) -> Dict[str, Any]:
        connector = self.registry.create(name=connector_name)
        if connector is None:
            return {"enabled": False, "connector": connector_name, "documents": [], "count": 0}
        connector.validate()
        state = self._load_state()
        name = connector_name or (self.registry.config.get("ingestion") or self.registry.config).get("default_connector") or connector.name
        cursor_data = state.get(str(name))
        cursor = None
        if cursor_data is not None:
            try:
                cursor = SyncCursor(value=cursor_data.get("value"), updated_at=cursor_data.get("updated_at"))
            except Exception:
                cursor = SyncCursor(value=cursor_data)
        docs, next_cursor = connector.sync(cursor=cursor)
        normalized = []
        for d in docs:
            nd = normalize_document(d)
            normalized.append(nd)
        state[str(name)] = {"value": getattr(next_cursor, "value", None) if next_cursor else None}
        self._save_state(state)
        return {"enabled": True, "connector": name, "documents": normalized, "count": len(normalized), "cursor": getattr(next_cursor, "value", None) if next_cursor else None}
