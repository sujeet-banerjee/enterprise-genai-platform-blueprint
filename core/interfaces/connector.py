"""Connector interface for pluggable data ingestion.

Implements Workstream H (#115): ACL-aware ingestion framework with pluggable connectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from core.interfaces.retriever import Document


@dataclass
class SyncCursor:
    """Cursor for incremental sync."""

    value: Any
    updated_at: Optional[datetime] = None


@dataclass
class RawItem:
    """Raw item fetched by a connector before normalization."""

    id: str
    content: str
    metadata: Dict[str, Any]
    acl: Optional[Dict[str, Any]] = None


class BaseConnector(ABC):
    """Contract for ingestion connectors."""

    name: str
    source_type: str

    def __init__(self, name: str, source_type: str, config: Dict[str, Any] | None = None, **kwargs: Any) -> None:
        self.name = str(name)
        self.source_type = str(source_type)
        self.config = dict(config) if config is not None else {}

    @abstractmethod
    def validate(self) -> None:
        """Validate connector configuration."""

    @abstractmethod
    def discover(self) -> List[Dict[str, Any]]:
        """Discover available sources/collections."""

    @abstractmethod
    def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any) -> Iterable[RawItem]:
        """Fetch items starting from cursor."""

    def to_documents(self, items: Iterable[RawItem]) -> List[Document]:
        """Convert raw items to Documents with ACL metadata preserved."""
        docs: List[Document] = []
        for item in items:
            meta: Dict[str, Any] = dict(item.metadata) if item.metadata else {}
            if item.acl:
                meta.update(item.acl)
            meta.setdefault("source", self.source_type)
            meta.setdefault("connector", self.name)
            meta.setdefault("source_id", item.id)
            docs.append(Document(content=item.content, metadata=meta))
        return docs

    def sync(self, cursor: Optional[SyncCursor] = None) -> tuple[List[Document], Optional[SyncCursor]]:
        """Sync and return documents plus next cursor for incremental sync."""
        items = list(self.fetch(cursor=cursor))
        docs = self.to_documents(items)
        next_cursor = self._next_cursor(items, cursor)
        return docs, next_cursor

    def _next_cursor(self, items: List[RawItem], cursor: Optional[SyncCursor]) -> Optional[SyncCursor]:
        """Compute next cursor. Override for incremental sync."""
        return None
