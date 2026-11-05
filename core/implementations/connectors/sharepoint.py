"""SharePoint connector (ACL-aware)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.interfaces.connector import BaseConnector, RawItem, SyncCursor


class SharePointConnector(BaseConnector):
    """Minimal ACL-aware SharePoint connector.

    Uses a pluggable client callable for testability; can be wired to MS Graph later.
    """

    def __init__(
        self,
        name: str = "sharepoint",
        config: Dict[str, Any] | None = None,
        site_url: Optional[str] = None,
        library: Optional[str] = None,
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, source_type="sharepoint", config=config)
        self.site_url = site_url or (self.config or {}).get("site_url")
        self.library = library or (self.config or {}).get("library") or "Documents"
        self.client = client or (self.config or {}).get("client")

    def validate(self) -> None:
        if not self.site_url:
            raise ValueError("SharePoint connector requires site_url")

    def discover(self) -> List[Dict[str, Any]]:
        return [{"site_url": self.site_url, "library": self.library}]

    def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any) -> Iterable[RawItem]:
        if self.client and callable(getattr(self.client, "list_items", None)):
            items = self.client.list_items(site_url=self.site_url, library=self.library, cursor=cursor)
        else:
            items = (self.config or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            yield RawItem(
                id=str(it.get("id") or it.get("item_id") or ""),
                content=str(it.get("content") or it.get("text") or ""),
                metadata={k: v for k, v in it.items() if k not in {"content", "text", "acl"}},
                acl=it.get("acl") if isinstance(it.get("acl"), dict) else None,
            )
