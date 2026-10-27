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

from core.services.attribution import AttributionContext, current_attribution
from core.services.audit_store import build_audit_sink
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
        sink: Optional[Any] = None,
        export_dir: Optional[Any] = None,
        store: Optional[Any] = None,
    ):
        self.enabled = bool(enabled)
        self.path = Path(path) if path else None
        self.export_dir = Path(export_dir) if export_dir else None
        self.max_entries = max(1, int(max_entries))
        self._redactor = redactor or SensitiveDataRedactor()
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._events: Deque[Dict[str, Any]] = deque(maxlen=self.max_entries)
        self._sink = sink
        self._store = store
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
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one audit event; returns the stored (redacted) event.

        Returns ``None`` when auditing is disabled or the logger is closed, so
        callers can invoke it unconditionally. ``tenant`` (issue #48) attributes
        the event to a tenant/workspace without touching the event payload.
        ``attribution`` (issue #50) carries tenant/workspace/app/user/cost center;
        it defaults to the request-scoped context, or the default dimensions.
        """
        if not self.enabled or self._closed:
            return None
        context = current_attribution() or AttributionContext()
        dimensions = dict(attribution) if isinstance(attribution, dict) else context.dimensions()
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": round(float(self._clock()), 6),
            "event_type": str(event_type),
            "action": str(action),
            "outcome": str(outcome),
            "request_id": request_id,
            "tenant": str(tenant) if tenant is not None else None,
            "attribution": self._redactor.redact_obj(dimensions),
            "details": self._redactor.redact_obj(dict(details or {})),
        }
        with self._lock:
            self._events.append(event)
            if self._sink is not None:
                self._sink.append(event)
            if self._store is not None:
                try:
                    self._store.set(f"audit:{event.get('event_id')}", event)
                except Exception:
                    pass
            if self._sink is None and self._store is None and self.path is not None:
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
        outcome: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        if self._sink is not None:
            return self._sink.events(
                limit=limit,
                tenant=tenant,
                event_type=event_type,
                outcome=outcome,
                since=since,
                until=until,
            )
        items = []
        if self._store is not None:
            try:
                items = list(self._store.list(prefix="audit:", limit=10000))
            except Exception:
                items = []
        if not items:
            with self._lock:
                items = list(self._events)
        if event_type is not None:
            items = [item for item in items if item.get("event_type") == event_type]
        if tenant is not None:
            items = [item for item in items if item.get("tenant") == str(tenant)]
        if outcome is not None:
            items = [item for item in items if item.get("outcome") == outcome]
        if since is not None:
            items = [item for item in items if float(item.get("timestamp") or 0.0) >= since]
        if until is not None:
            items = [item for item in items if float(item.get("timestamp") or 0.0) <= until]
        if limit is not None:
            items = items[-int(limit):]
        return items

    def count(self) -> int:
        if self._sink is not None:
            return self._sink.count()
        with self._lock:
            return len(self._events)

    # -- integrity / retention -------------------------------------------

    @property
    def sink(self) -> Optional[Any]:
        """The immutable store when enabled, else ``None``."""
        return self._sink

    def verify(self, region: Optional[str] = None) -> Dict[str, Any]:
        if self._sink is None:
            return {
                "available": False,
                "valid": None,
                "reason": "immutable audit store is not enabled",
            }
        try:
            result = self._sink.verify(region)
        except KeyError:
            return {
                "available": True,
                "valid": False,
                "reason": f"unknown audit region: {region}",
            }
        return {"available": True, **result}

    def purge(
        self, now: Optional[float] = None, export_dir: Optional[Any] = None
    ) -> Dict[str, Any]:
        if self._sink is None:
            raise RuntimeError("immutable audit store is not enabled")
        target = export_dir if export_dir is not None else self.export_dir
        return self._sink.purge(now=now, export_dir=target)

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
        clock: Optional[Callable[[], float]] = None,
        store: Optional[Any] = None,
    ) -> "AuditLogger":
        """Build a logger from an ``audit`` config section (default: disabled)."""
        config = config or {}
        enabled = bool(config.get("enabled", False))
        sink = build_audit_sink(config, clock=clock) if enabled else None
        retention = config.get("retention") or {}
        export_dir = retention.get("export_dir") if isinstance(retention, dict) else None
        return cls(
            enabled=enabled,
            path=config.get("path"),
            redactor=redactor,
            max_entries=int(config.get("max_entries", 1000)),
            clock=clock,
            sink=sink,
            export_dir=export_dir,
            store=store,
        )
