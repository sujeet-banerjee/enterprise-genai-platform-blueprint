"""Bounded async operation/job service for long-running query work (issue #279).

Tracks coarse lifecycle for async query operations and provides a unified view
that can include experiments. State is bounded in-memory and optionally mirrored
to a configured BaseStore (operations:* namespace).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED}


class OperationQueueFullError(RuntimeError):
    """Raised when the bounded active-operation budget is exhausted."""


def _now() -> float:
    return round(time.time(), 6)


def _coerce_statuses(status: Optional[str]) -> Optional[set[str]]:
    if not status:
        return None
    values = {item.strip().lower() for item in str(status).split(",") if item.strip()}
    return values or None


class OperationJobsService:
    """In-process async operation tracker with optional BaseStore backing."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_workers: int = 2,
        max_operations: int = 500,
        recent_window_seconds: int = 3600,
        store: Optional[Any] = None,
        store_prefix: str = "operations",
        store_ttl_seconds: Optional[int] = None,
    ):
        self.enabled = bool(enabled)
        self.max_workers = max(1, int(max_workers))
        self.max_operations = max(1, int(max_operations))
        self.recent_window_seconds = max(1, int(recent_window_seconds))
        self.store_ttl_seconds = (
            max(1, int(store_ttl_seconds)) if store_ttl_seconds is not None else None
        )
        self._store = store
        self._store_prefix = str(store_prefix or "operations")
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="operation")

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _store_key(self, op_id: str) -> str:
        return f"{self._store_prefix}:{op_id}"

    def _persist(self, entry: Dict[str, Any]) -> None:
        if self._store is None:
            return
        try:
            self._store.set(
                self._store_key(str(entry["id"])),
                dict(entry),
                ttl_seconds=self.store_ttl_seconds,
            )
        except TypeError:
            self._store.set(self._store_key(str(entry["id"])), dict(entry))
        except Exception:
            pass

    def _load_store_entries(self) -> List[Dict[str, Any]]:
        if self._store is None:
            return []
        try:
            items = self._store.list(prefix=f"{self._store_prefix}:", limit=max(self.max_operations, 10000))
        except Exception:
            return []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def _evict_locked(self) -> None:
        while len(self._entries) > self.max_operations:
            old_id, _ = self._entries.popitem(last=False)
            if self._store is not None:
                try:
                    self._store.delete(self._store_key(old_id))
                except Exception:
                    pass

    def _active_count_locked(self) -> int:
        entries = list(self._entries.values())
        for stored in self._load_store_entries():
            op_id = str(stored.get("id"))
            if op_id not in self._entries:
                entries.append(stored)
        return sum(
            1
            for entry in entries
            if str(entry.get("status") or "") not in TERMINAL_STATUSES
        )

    def _remember(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self._entries[entry["id"]] = dict(entry)
        self._entries.move_to_end(entry["id"])
        self._evict_locked()
        self._persist(entry)
        return dict(entry)

    def _get_locked(self, op_id: str) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(op_id)
        if entry is not None:
            return dict(entry)
        if self._store is None:
            return None
        try:
            stored = self._store.get(self._store_key(op_id))
        except Exception:
            stored = None
        if isinstance(stored, dict) and stored.get("id"):
            self._entries[op_id] = dict(stored)
            self._entries.move_to_end(op_id)
            self._evict_locked()
            return dict(stored)
        return None

    def get(self, op_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._get_locked(op_id)

    def submit_query(
        self,
        *,
        request_id: str,
        kind: str,
        owner: str,
        tenant: Optional[str],
        workspace: Optional[str],
        app: Optional[str],
        payload: Dict[str, Any],
        runner: Callable[[], Dict[str, Any]],
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        now = _now()
        with self._lock:
            if self._active_count_locked() >= self.max_operations:
                raise OperationQueueFullError(
                    f"Operation queue is full (max {self.max_operations})."
                )
        entry = {
            "id": request_id,
            "request_id": request_id,
            "kind": kind,
            "status": STATUS_QUEUED,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
            "stage": STATUS_QUEUED,
            "progress": {"stage": STATUS_QUEUED, "message": "Queued"},
            "owner": owner,
            "tenant": tenant,
            "workspace": workspace,
            "app": app,
            "requested_fields": sorted(str(key) for key in (payload or {})),
            "result": None,
            "error": None,
            "failure_type": None,
            "failure_tags": [],
        }
        with self._lock:
            self._remember(entry)

        def _run() -> None:
            with self._lock:
                current = self._get_locked(request_id)
                if current is None or current.get("status") in TERMINAL_STATUSES:
                    return
                current["status"] = STATUS_RUNNING
                current["started_at"] = current.get("started_at") or _now()
                current["updated_at"] = _now()
                current["stage"] = STATUS_RUNNING
                current["progress"] = {"stage": STATUS_RUNNING, "message": "Running"}
                self._remember(current)
            try:
                result = runner() or {}
                failure_type = result.get("failure_type")
                status = STATUS_FAILED if result.get("error") or failure_type else STATUS_COMPLETED
                with self._lock:
                    current = self._get_locked(request_id) or dict(entry)
                    current.update(
                        status=status,
                        finished_at=_now(),
                        updated_at=_now(),
                        stage=status,
                        progress={"stage": status, "message": status.capitalize()},
                        result=result,
                        error=result.get("error"),
                        failure_type=failure_type,
                        failure_tags=list(result.get("failure_tags") or []),
                    )
                    final = self._remember(current)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    current = self._get_locked(request_id) or dict(entry)
                    current.update(
                        status=STATUS_FAILED,
                        finished_at=_now(),
                        updated_at=_now(),
                        stage=STATUS_FAILED,
                        progress={"stage": STATUS_FAILED, "message": "Failed"},
                        result=None,
                        error=str(exc),
                        failure_type="unknown_failure",
                        failure_tags=[],
                    )
                    final = self._remember(current)
            if on_complete is not None:
                try:
                    on_complete(dict(final))
                except Exception:
                    pass

        self._executor.submit(_run)
        return dict(entry)

    def _visible(self, entry: Dict[str, Any], *, owner: str, tenant: Optional[str]) -> bool:
        if tenant is not None and entry.get("tenant") not in (None, tenant):
            return False
        return str(entry.get("owner") or "") == str(owner)

    def list_operations(
        self,
        *,
        owner: str,
        tenant: Optional[str],
        status: Optional[str] = None,
        mine: bool = True,
        recent_window_seconds: Optional[int] = None,
        limit: int = 100,
        experiment_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        statuses = _coerce_statuses(status)
        window = self.recent_window_seconds if recent_window_seconds is None else max(1, int(recent_window_seconds))
        cutoff = _now() - float(window)
        with self._lock:
            entries = list(self._entries.values())
            for stored in self._load_store_entries():
                sid = str(stored.get("id"))
                if sid not in self._entries:
                    entries.append(stored)
        items: List[Dict[str, Any]] = []
        for entry in entries:
            item = dict(entry)
            if mine and not self._visible(item, owner=owner, tenant=tenant):
                continue
            if tenant is not None and item.get("tenant") not in (None, tenant):
                continue
            item_status = str(item.get("status") or "")
            ts = float(item.get("finished_at") or item.get("updated_at") or item.get("created_at") or 0.0)
            if item_status in TERMINAL_STATUSES and ts < cutoff:
                continue
            if statuses and item_status not in statuses:
                continue
            items.append(item)

        for exp in experiment_entries or []:
            if not isinstance(exp, dict):
                continue
            item = self.experiment_as_operation(exp)
            if mine and not self._visible(item, owner=owner, tenant=tenant):
                continue
            if tenant is not None and item.get("tenant") not in (None, tenant):
                continue
            item_status = str(item.get("status") or "")
            ts = float(item.get("finished_at") or item.get("updated_at") or item.get("created_at") or 0.0)
            if item_status in TERMINAL_STATUSES and ts < cutoff:
                continue
            if statuses and item_status not in statuses:
                continue
            items.append(item)

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in items:
            dedup[str(item.get("id"))] = item
        out = list(dedup.values())
        out.sort(key=lambda x: float(x.get("updated_at") or x.get("created_at") or 0.0), reverse=True)
        return out[: max(1, int(limit))]

    @staticmethod
    def experiment_as_operation(exp: Dict[str, Any]) -> Dict[str, Any]:
        status = str(exp.get("status") or STATUS_RUNNING)
        return {
            "id": str(exp.get("id")),
            "request_id": str(exp.get("id")),
            "kind": "experiment",
            "status": status,
            "created_at": exp.get("created_at"),
            "started_at": exp.get("created_at"),
            "finished_at": exp.get("finished_at"),
            "updated_at": exp.get("finished_at") or exp.get("created_at"),
            "stage": status,
            "progress": {"stage": status, "message": status.capitalize()},
            "owner": exp.get("owner"),
            "tenant": exp.get("tenant"),
            "workspace": exp.get("workspace"),
            "app": exp.get("app"),
            "result": exp.get("result"),
            "error": exp.get("error"),
            "failure_type": exp.get("failure_type"),
            "failure_tags": list(exp.get("failure_tags") or []),
        }
