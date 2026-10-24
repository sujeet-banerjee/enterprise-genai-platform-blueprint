"""Store backends (memory, SQLite, Postgres).

Memory is default (no new deps). SQLite and Postgres are optional.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from core.services.base_store import BaseStore, StoreBackendError, _serialize_value


class MemoryStore(BaseStore):
    def __init__(self, **config: Any):
        self._lock = RLock()
        self._data: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._ttl: Dict[str, float] = {}
        self._max_entries = int(config.get("max_entries") or config.get("max_runs") or 1000)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._expire()
            item = self._data.get(key)
            if item is None:
                return None
            return json.loads(json.dumps(item))

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: Optional[float] = None) -> None:
        with self._lock:
            self._expire()
            self._data[key] = _serialize_value(value)
            if ttl_seconds is not None and ttl_seconds > 0:
                self._ttl[key] = time.time() + float(ttl_seconds)
            else:
                self._ttl.pop(key, None)
            while len(self._data) > self._max_entries:
                oldest = next(iter(self._data))
                self._data.pop(oldest, None)
                self._ttl.pop(oldest, None)

    def list(self, prefix: str = "", limit: int = 1000, **filters: Any) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire()
            results: List[Dict[str, Any]] = []
            for key, item in self._data.items():
                if prefix and not key.startswith(prefix):
                    continue
                if filters:
                    match = True
                    for k, v in filters.items():
                        if item.get(k) != v:
                            match = False
                            break
                    if not match:
                        continue
                results.append(json.loads(json.dumps(item)))
            return results[:limit]

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = key in self._data
            self._data.pop(key, None)
            self._ttl.pop(key, None)
            return existed

    def health(self) -> Dict[str, Any]:
        with self._lock:
            self._expire()
            return {"status": "ok", "backend": "memory", "entries": len(self._data)}

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._ttl.clear()

    def _expire(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._ttl.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)
            self._ttl.pop(k, None)


class SQLiteStore(BaseStore):
    def __init__(self, **config: Any):
        try:
            import sqlite3
        except Exception as exc:
            raise StoreBackendError(f"sqlite unavailable: {exc}") from exc

        path = config.get("path") or config.get("sqlite_path") or "data/store.db"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._lock = RLock()
        self._init()

    def _init(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ttl REAL,
                updated_at REAL
            )"""
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._expire()
            cur = self._conn.cursor()
            cur.execute("SELECT value FROM store WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return json.loads(row[0])

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: Optional[float] = None) -> None:
        with self._lock:
            self._expire()
            ttl = time.time() + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
            cur = self._conn.cursor()
            cur.execute(
                "REPLACE INTO store(key,value,ttl,updated_at) VALUES(?,?,?,?)",
                (key, json.dumps(_serialize_value(value)), ttl, time.time()),
            )
            self._conn.commit()

    def list(self, prefix: str = "", limit: int = 1000, **filters: Any) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire()
            cur = self._conn.cursor()
            if prefix:
                cur.execute("SELECT key,value FROM store WHERE key LIKE ? ORDER BY key", (prefix + "%",))
            else:
                cur.execute("SELECT key,value FROM store ORDER BY key")
            results: List[Dict[str, Any]] = []
            for _, raw in cur.fetchall():
                item = json.loads(raw)
                if filters:
                    ok = True
                    for k, v in filters.items():
                        if item.get(k) != v:
                            ok = False
                            break
                    if not ok:
                        continue
                results.append(item)
                if len(results) >= limit:
                    break
            return results

    def delete(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM store WHERE key = ?", (key,))
            self._conn.commit()
            return cur.rowcount > 0

    def health(self) -> Dict[str, Any]:
        with self._lock:
            try:
                self._expire()
                cur = self._conn.cursor()
                cur.execute("SELECT COUNT(*) FROM store")
                count = cur.fetchone()[0]
                return {"status": "ok", "backend": "sqlite", "entries": count, "path": str(self._path)}
            except Exception as exc:
                return {"status": "degraded", "backend": "sqlite", "error": str(exc)}

    def clear(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM store")
            self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _expire(self) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("DELETE FROM store WHERE ttl IS NOT NULL AND ttl <= ?", (now,))
        self._conn.commit()


class PostgresStore(BaseStore):
    def __init__(self, **config: Any):
        try:
            import psycopg2  # type: ignore
        except Exception as exc:
            raise StoreBackendError(f"psycopg2 unavailable: {exc}") from exc

        dsn = config.get("dsn") or config.get("database_url") or ""
        if not dsn:
            raise StoreBackendError("Postgres dsn/database_url required")
        self._psycopg2 = psycopg2
        self._dsn = dsn
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True
        self._lock = RLock()
        self._init()

    def _init(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS store (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                ttl DOUBLE PRECISION,
                updated_at DOUBLE PRECISION
            )"""
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_store_key_prefix ON store(key)")
        cur.close()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._expire()
            cur = self._conn.cursor()
            cur.execute("SELECT value FROM store WHERE key = %s", (key,))
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            val = row[0]
            if isinstance(val, str):
                return json.loads(val)
            return val

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: Optional[float] = None) -> None:
        with self._lock:
            self._expire()
            ttl = time.time() + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO store(key,value,ttl,updated_at) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, ttl=EXCLUDED.ttl, updated_at=EXCLUDED.updated_at",
                (key, json.dumps(_serialize_value(value)), ttl, time.time()),
            )
            cur.close()

    def list(self, prefix: str = "", limit: int = 1000, **filters: Any) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire()
            cur = self._conn.cursor()
            if prefix:
                cur.execute("SELECT value FROM store WHERE key LIKE %s ORDER BY key LIMIT %s", (prefix + "%", limit))
            else:
                cur.execute("SELECT value FROM store ORDER BY key LIMIT %s", (limit,))
            results: List[Dict[str, Any]] = []
            for (raw,) in cur.fetchall():
                if isinstance(raw, str):
                    item = json.loads(raw)
                else:
                    item = raw
                if filters:
                    ok = True
                    for k, v in filters.items():
                        if item.get(k) != v:
                            ok = False
                            break
                    if not ok:
                        continue
                results.append(item)
            cur.close()
            return results

    def delete(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM store WHERE key = %s", (key,))
            count = cur.rowcount
            cur.close()
            return count > 0

    def health(self) -> Dict[str, Any]:
        with self._lock:
            try:
                self._expire()
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM store")
                count = cur.fetchone()[0]
                cur.close()
                return {"status": "ok", "backend": "postgres", "entries": count}
            except Exception as exc:
                return {"status": "degraded", "backend": "postgres", "error": str(exc)}

    def clear(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM store")
            cur.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _expire(self) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("DELETE FROM store WHERE ttl IS NOT NULL AND ttl <= %s", (now,))
        cur.close()
