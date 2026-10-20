"""Optional response cache for the RAG pipeline (issue #26).

A small, thread-safe, TTL-aware, bounded exact-match cache. It is deliberately
dependency-free: keys are derived from the query, ``top_k`` and a caller-supplied
namespace (typically the active component identities) so a rebuilt pipeline with a
different model/retriever does not serve stale answers.

Disabled by default: the composition root only constructs one when
``cache.enabled`` is true, and the pipeline treats ``None`` as "no caching".
"""

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional


class ResponseCache:
    """Bounded, TTL-aware exact-match cache with simple hit/miss stats."""

    def __init__(
        self,
        enabled: bool = True,
        max_entries: int = 128,
        ttl_seconds: Optional[float] = 300.0,
        namespace: str = "",
        clock: Optional[Callable[[], float]] = None,
    ):
        self.enabled = bool(enabled)
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        self.namespace = str(namespace)
        self._clock = clock or time.monotonic

        self._lock = threading.Lock()
        self._store: "OrderedDict[str, tuple]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    # -- keying ----------------------------------------------------------

    def make_key(self, query: str, top_k: int) -> str:
        raw = f"{self.namespace}\x00{int(top_k)}\x00{query}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -- cache ops -------------------------------------------------------

    def _is_expired(self, stored_at: float) -> bool:
        if self.ttl_seconds is None:
            return False
        return (self._clock() - stored_at) > self.ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, stored_at = entry
            if self._is_expired(stored_at):
                del self._store[key]
                self.misses += 1
                return None
            # LRU: move to the most-recently-used end.
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, self._clock())
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "enabled": self.enabled,
            "entries": len(self._store),
            "max_entries": self.max_entries,
            "ttl_seconds": self.ttl_seconds,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hits / total, 6) if total else 0.0,
        }
