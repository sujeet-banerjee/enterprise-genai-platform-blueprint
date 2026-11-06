"""Backup/restore automation + verification for BaseStore (#119).

Exports store records to a portable JSON payload with checksum; restores with
verification. Intended for run history, traces, experiments, and audit state
when backed by a BaseStore.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.services.base_store import BaseStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum(payload: Dict[str, Any]) -> str:
    # checksum over canonical records
    data = json.dumps(payload.get("records", []), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def export_store(store: BaseStore, path: str | Path, prefixes: Optional[List[str]] = None, limit: int = 100000) -> Dict[str, Any]:
    """Export store records to JSON file and return a manifest."""
    prefixes = prefixes or [""]
    records: List[Dict[str, Any]] = []
    for prefix in prefixes:
        items = store.list(prefix=prefix, limit=limit)
        for item in items:
            records.append({"prefix": prefix, "record": item})
    payload: Dict[str, Any] = {
        "format": "genai-store-backup",
        "version": 1,
        "created_at": _now_iso(),
        "health": store.health(),
        "prefixes": prefixes,
        "records": records,
    }
    payload["checksum"] = _checksum(payload)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return {"path": str(p), "count": len(records), "checksum": payload["checksum"]}


def verify_backup(path: str | Path) -> Tuple[bool, Dict[str, Any]]:
    """Verify backup file checksum and format."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("format") != "genai-store-backup":
        return False, {"error": "invalid format"}
    expected = payload.get("checksum")
    actual = _checksum(payload)
    ok = expected == actual
    return ok, {"ok": ok, "expected": expected, "actual": actual, "count": len(payload.get("records") or [])}


def restore_store(store: BaseStore, path: str | Path, clear: bool = False, verify: bool = True) -> Dict[str, Any]:
    """Restore records into store. Optionally verify checksum before restore."""
    if verify:
        ok, meta = verify_backup(path)
        if not ok:
            return {"restored": 0, "ok": False, "verification": meta}
    else:
        meta = {"ok": True, "skipped": True}
    if clear and hasattr(store, "clear"):
        store.clear()
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    restored = 0
    for entry in payload.get("records") or []:
        rec = entry.get("record") if isinstance(entry, dict) else None
        if not isinstance(rec, dict):
            continue
        key = rec.get("key") or rec.get("id") or rec.get("request_id")
        if key is None:
            # best-effort: generate stable key from prefix+index
            key = f"{entry.get('prefix','')}:{restored}"
        store.set(str(key), rec)
        restored += 1
    return {"restored": restored, "ok": True, "verification": meta, "backup": str(p)}
