"""Append-only audit logging for governance / policy / security events (issue #28).

Unlike per-request observability traces, the audit log is a structured,
append-only record of *decisions*: governance (cost) rejections, retrieval-policy
actions, runtime config changes (pipeline rebuilds) and redaction events. Every
recorded payload is passed through :class:`SensitiveDataRedactor` before it is
stored, so the audit trail itself never leaks secrets.

The logger is intentionally simple and dependency-free:

* an in-memory bounded ring (``max_entries``) backs the read API, and
* when ``path`` is configured, each event is appended as one JSON object per
  line (JSONL) so the file is a durable, append-only forensic trail.

It is off by default (``audit.enabled: false``); the composition root only
constructs an enabled logger when configured.
"""

import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from core.services.observability import SensitiveDataRedactor


class AuditLogger:
    """Structured, append-only audit trail with optional JSONL persistence."""

    def __init__(
        self,
        enabled: bool = True,
        path: Optional[Any] = None,
        redactor: Optional[SensitiveDataRedactor] = None,
        max_entries: int = 1000,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.enabled = bool(enabled)
        self.path = Path(path) if path else None
        self.max_entries = max(1, int(max_entries))
        self._redactor = redactor or SensitiveDataRedactor()
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=self.max_entries)
        self._closed = False
        if self.enabled and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- ingestion --------------------------------------------------------

    def record(
        self,
        event_type: str,
        action: str,
        outcome: str,
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one audit event; returns the stored (redacted) event.

        Returns ``None`` when auditing is disabled or the logger is closed, so
        callers can invoke it unconditionally. ``tenant`` (issue #48) attributes
        the event to a tenant/workspace without touching the event payload.
        """
        if not self.enabled or self._closed:
            return None
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": round(float(self._clock()), 6),
            "event_type": str(event_type),
            "action": str(action),
            "outcome": str(outcome),
            "request_id": request_id,
            "tenant": str(tenant) if tenant is not None else None,
            "details": self._redactor.redact_obj(dict(details or {})),
        }
        with self._lock:
            self._events.append(event)
            if self.path is not None:
                try:
                    with open(self.path, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
                except OSError:
                    # Persistence failures must never break request handling.
                    pass
        return event

    # -- reads ------------------------------------------------------------

    def events(
        self,
        limit: Optional[int] = None,
        event_type: Optional[str] = None,
        tenant: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if event_type is not None:
            items = [item for item in items if item["event_type"] == event_type]
        if tenant is not None:
            items = [item for item in items if item.get("tenant") == str(tenant)]
        if limit is not None:
            items = items[-int(limit):]
        return items

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def close(self) -> None:
        self._closed = True

    # -- config -----------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: Optional[Dict[str, Any]],
        redactor: Optional[SensitiveDataRedactor] = None,
    ) -> "AuditLogger":
        """Build a logger from an ``audit`` config section (default: disabled)."""
        config = config or {}
        return cls(
            enabled=bool(config.get("enabled", False)),
            path=config.get("path"),
            redactor=redactor,
            max_entries=int(config.get("max_entries", 1000)),
        )
