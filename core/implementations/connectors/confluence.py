"""Confluence connector (ACL-aware)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.interfaces.connector import BaseConnector, RawItem, SyncCursor


class ConfluenceConnector(BaseConnector):
    """Minimal ACL-aware Confluence connector."""

    def __init__(
        self,
        name: str = "confluence",
        config: Dict[str, Any] | None = None,
        base_url: Optional[str] = None,
        space: Optional[str] = None,
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, source_type="confluence", config=config)
        self.base_url = base_url or (self.config or {}).get("base_url")
        self.space = space or (self.config or {}).get("space")
        self.client = client or (self.config or {}).get("client")

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("Confluence connector requires base_url")

    def discover(self) -> List[Dict[str, Any]]:
        return [{"base_url": self.base_url, "space": self.space}]

    def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any) -> Iterable[RawItem]:
        if self.client and callable(getattr(self.client, "list_pages", None)):
            items = self.client.list_pages(base_url=self.base_url, space=self.space, cursor=cursor)
        else:
            items = (self.config or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            yield RawItem(
                id=str(it.get("id") or it.get("page_id") or ""),
                content=str(it.get("content") or it.get("body") or ""),
                metadata={k: v for k, v in it.items() if k not in {"content", "body", "acl"}},
                acl=it.get("acl") if isinstance(it.get("acl"), dict) else None,
            )
