"""S3 connector (ACL-aware)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.interfaces.connector import BaseConnector, RawItem, SyncCursor


class S3Connector(BaseConnector):
    """Minimal S3 connector with pluggable client for testability."""

    def __init__(
        self,
        name: str = "s3",
        config: Dict[str, Any] | None = None,
        bucket: Optional[str] = None,
        prefix: str = "",
        client: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, source_type="s3", config=config)
        self.bucket = bucket or (self.config or {}).get("bucket")
        self.prefix = prefix or (self.config or {}).get("prefix") or ""
        self.client = client or (self.config or {}).get("client")

    def validate(self) -> None:
        if not self.bucket:
            raise ValueError("S3 connector requires bucket")

    def discover(self) -> List[Dict[str, Any]]:
        return [{"bucket": self.bucket, "prefix": self.prefix}]

    def fetch(self, cursor: Optional[SyncCursor] = None, **kwargs: Any) -> Iterable[RawItem]:
        if self.client and callable(getattr(self.client, "list_objects", None)):
            items = self.client.list_objects(bucket=self.bucket, prefix=self.prefix, cursor=cursor)
        else:
            items = (self.config or {}).get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            yield RawItem(
                id=str(it.get("id") or it.get("key") or ""),
                content=str(it.get("content") or it.get("body") or ""),
                metadata={k: v for k, v in it.items() if k not in {"content", "body", "acl"}},
                acl=it.get("acl") if isinstance(it.get("acl"), dict) else None,
            )
