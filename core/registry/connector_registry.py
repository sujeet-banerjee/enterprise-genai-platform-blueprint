"""Configuration-driven registry and factory for ingestion connectors (#115)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from core.interfaces.connector import BaseConnector, RawItem, SyncCursor


class ConnectorRegistry:
    """Registry for ingestion connectors."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "ingestion.yaml"
            config_path = str(default_path)
        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}
        self._providers: Dict[str, Callable[..., BaseConnector]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register("noop", self._build_noop)
        self.register("filesystem", self._build_filesystem)
        self.register("sharepoint", self._build_sharepoint)
        self.register("confluence", self._build_confluence)

    @staticmethod
    def _build_sharepoint(name: str = "sharepoint", config: Dict[str, Any] | None = None, **kwargs: Any) -> BaseConnector:
        from core.implementations.connectors.sharepoint import SharePointConnector

        merged = dict(config or {})
        merged.pop("type", None)
        merged.pop("provider", None)
        merged.update(kwargs)
        return SharePointConnector(name=name, config=config, **merged)

    @staticmethod
    def _build_confluence(name: str = "confluence", config: Dict[str, Any] | None = None, **kwargs: Any) -> BaseConnector:
        from core.implementations.connectors.confluence import ConfluenceConnector

        merged = dict(config or {})
        merged.pop("type", None)
        merged.pop("provider", None)
        merged.update(kwargs)
        return ConfluenceConnector(name=name, config=config, **merged)

    @staticmethod
    def _build_noop(name: str = "noop", **kwargs: Any) -> BaseConnector:
        class NoopConnector(BaseConnector):
            def __init__(self, name: str = "noop", config: Dict[str, Any] | None = None):
                super().__init__(name=name, source_type="noop", config=config)

            def validate(self) -> None:
                return None

            def discover(self) -> List[Dict[str, Any]]:
                return []

            def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any):
                return []

        return NoopConnector(name=name, config=kwargs.get("config"))

    @staticmethod
    def _build_filesystem(
        name: str = "filesystem",
        config: Dict[str, Any] | None = None,
        path: Optional[str] = None,
        documents_path: Optional[str] = None,
        **kwargs: Any,
    ) -> BaseConnector:
        class FilesystemConnector(BaseConnector):
            def __init__(
                self,
                name: str = "filesystem",
                config: Dict[str, Any] | None = None,
                path: Optional[str] = None,
                documents_path: Optional[str] = None,
            ):
                super().__init__(name=name, source_type="filesystem", config=config)
                self.path = path or documents_path or (config or {}).get("path") or (config or {}).get("documents_path")

            def validate(self) -> None:
                if not self.path:
                    raise ValueError("filesystem connector requires 'path' or 'documents_path'")

            def discover(self) -> List[Dict[str, Any]]:
                return [{"type": "filesystem", "path": self.path}]

            def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any):
                if not self.path:
                    return []
                p = Path(self.path)
                if not p.exists():
                    return []
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                items = []
                if isinstance(data, dict) and isinstance(data.get("docs"), list):
                    docs = data["docs"]
                elif isinstance(data, list):
                    docs = data
                else:
                    return []
                for i, d in enumerate(docs):
                    if isinstance(d, str):
                        content = d
                        meta: Dict[str, Any] = {}
                        acl = None
                    elif isinstance(d, dict):
                        content = str(d.get("content") or d.get("text") or "")
                        meta = dict(d.get("metadata") or {})
                        acl = d.get("acl") or meta.get("acl")
                        if isinstance(acl, dict):
                            meta.pop("acl", None)
                        else:
                            acl = None
                    else:
                        continue
                    items.append(RawItem(id=str(i), content=content, metadata=meta, acl=acl))
                return items

        return FilesystemConnector(name=name, config=config, path=path, documents_path=documents_path)

    def register(self, provider_name: str, factory: Callable[..., BaseConnector]) -> None:
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def describe(self) -> Dict[str, Any]:
        ingestion_cfg = self.config.get("ingestion") or self.config
        return {
            "enabled": bool(ingestion_cfg.get("enabled", False)),
            "default_connector": ingestion_cfg.get("default_connector"),
            "providers": self.list_providers(),
            "connectors": list((ingestion_cfg.get("connectors") or {}).keys()),
        }

    def create(self, name: Optional[str] = None, **kwargs: Any) -> Optional[BaseConnector]:
        ingestion_cfg = self.config.get("ingestion") or self.config
        if not ingestion_cfg.get("enabled", False):
            return None
        connectors = ingestion_cfg.get("connectors") or {}
        connector_name = name or ingestion_cfg.get("default_connector")
        if not connector_name:
            return None
        connector_name = str(connector_name)
        entry = connectors.get(connector_name) or {}
        provider = str(entry.get("type") or entry.get("provider") or connector_name).lower()
        factory = self._providers.get(provider)
        if factory is None:
            raise ValueError(f"Unknown connector provider: {provider}")
        cfg = dict(entry)
        return factory(name=connector_name, config=cfg, **cfg, **kwargs)
