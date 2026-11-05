"""Azure Blob connector (ACL-aware)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.interfaces.connector import BaseConnector, RawItem, SyncCursor


class AzureBlobConnector(BaseConnector):
    """Minimal Azure Blob connector with pluggable client."""

    def __init__(
        self,
        name: str = "azure_blob",
        config: Dict[str, Any] | None = None,
        container: Optional[str] = None,
        prefix: str = "",
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, source_type="azure_blob", config=config)
        self.container = container or (self.config or {}).get("container")
        self.prefix = prefix or (self.config or {}).get("prefix") or ""
        self.client = client or (self.config or {}).get("client")

    def validate(self) -> None:
        if not self.container:
            raise ValueError("Azure Blob connector requires container")

    def discover(self) -> List[Dict[str, Any]]:
        return [{"container": self.container, "prefix": self.prefix}]

    def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any) -> Iterable[RawItem]:
        if self.client and callable(getattr(self.client, "list_blobs", None)):
            items = self.client.list_blobs(container=self.container, prefix=self.prefix, cursor=cursor)
        else:
            items = (self.config or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            yield RawItem(
                id=str(it.get("id") or it.get("name") or ""),
                content=str(it.get("content") or it.get("body") or ""),
                metadata={k: v for k, v in it.items() if k not in {"content", "body", "acl"}},
                acl=it.get("acl") if isinstance(it.get("acl"), dict) else None,
            )
