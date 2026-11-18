"""Config-driven API rate limits and in-flight caps (issue #224)."""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

REQUEST_RATE = "request_rate"
IN_FLIGHT = "in_flight"
VALID_SCOPES = frozenset({"auto", "key", "tenant", "role", "subject", "ip"})


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class RateLimitSettings:
    enabled: bool = False
    requests_per_minute: int = 60
    burst: int = 10
    scope: str = "auto"
    in_flight_max: int = 4

    @classmethod
    def from_config(cls, data: Mapping[str, Any]) -> "RateLimitSettings":
        block_value = data.get("rate_limit") or {}
        if not isinstance(block_value, Mapping):
            raise ValueError("api.rate_limit must be a mapping")
        block = dict(block_value)
        enabled = bool(block.get("enabled", False))
        requests_per_minute = int(block.get("requests_per_minute", 60))
        burst_value = block.get("burst")
        burst = int(burst_value) if burst_value is not None else min(10, requests_per_minute)
        in_flight_max = int(block.get("in_flight_max", 4))
        scope = str(block.get("scope", "auto")).strip().lower()
        if requests_per_minute <= 0:
            raise ValueError("api.rate_limit.requests_per_minute must be positive")
        if burst <= 0:
            raise ValueError("api.rate_limit.burst must be positive")
        if in_flight_max <= 0:
            raise ValueError("api.rate_limit.in_flight_max must be positive")
        if scope not in VALID_SCOPES:
            raise ValueError(f"unknown api.rate_limit.scope: {scope}")
        return cls(
            enabled=enabled,
            requests_per_minute=requests_per_minute,
            burst=burst,
            scope=scope,
            in_flight_max=in_flight_max,
        )


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str = ""
    retry_after: int = 0
    scope: str = ""
    key_digest: str = ""


class RateLimiter:
    def __init__(self, settings: RateLimitSettings, clock: Optional[Any] = None):
        self.settings = settings
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}
        self._in_flight: dict[str, int] = {}
        self._rate = settings.requests_per_minute / 60.0

    def acquire(self, raw_key: str, scope: str = "auto") -> RateLimitDecision:
        if not self.settings.enabled:
            return RateLimitDecision(allowed=True, scope=scope)
        key = _digest(raw_key or "anonymous")
        now = float(self._clock())
        with self._lock:
            if self._in_flight.get(key, 0) >= self.settings.in_flight_max:
                return RateLimitDecision(
                    allowed=False,
                    reason=IN_FLIGHT,
                    retry_after=1,
                    scope=scope,
                    key_digest=key,
                )
            tokens, last = self._buckets.get(key, (float(self.settings.burst), now))
            elapsed = max(0.0, now - last)
            tokens = min(
                float(self.settings.burst), tokens + elapsed * self._rate
            )
            if tokens < 1.0:
                retry_after = max(1, math.ceil((1.0 - tokens) / self._rate))
                self._buckets[key] = (tokens, now)
                return RateLimitDecision(
                    allowed=False,
                    reason=REQUEST_RATE,
                    retry_after=retry_after,
                    scope=scope,
                    key_digest=key,
                )
            self._buckets[key] = (tokens - 1.0, now)
            self._in_flight[key] = self._in_flight.get(key, 0) + 1
            return RateLimitDecision(allowed=True, scope=scope, key_digest=key)

    def release(self, decision: RateLimitDecision) -> None:
        if not self.settings.enabled or not decision.allowed or not decision.key_digest:
            return
        with self._lock:
            current = self._in_flight.get(decision.key_digest, 0)
            if current <= 1:
                self._in_flight.pop(decision.key_digest, None)
            else:
                self._in_flight[decision.key_digest] = current - 1

    def snapshot(self, raw_key: str) -> tuple[float, int]:
        key = _digest(raw_key or "anonymous")
        with self._lock:
            tokens, _ = self._buckets.get(key, (float(self.settings.burst), 0.0))
            return tokens, self._in_flight.get(key, 0)


def resolve_rate_key(
    scope: str,
    *,
    api_key: Optional[str],
    subject: Optional[str],
    tenant: Optional[str],
    role: Optional[str],
    client_host: Optional[str],
    tenancy_enabled: bool,
) -> tuple[str, str]:
    host = client_host or "unknown"
    if scope == "key":
        return scope, api_key or host
    if scope == "tenant":
        return scope, tenant or "default"
    if scope == "role":
        return scope, role or "anonymous"
    if scope == "subject":
        return scope, subject or host
    if scope == "ip":
        return scope, host
    if subject:
        return "subject", subject
    if api_key:
        return "key", api_key
    if tenancy_enabled and tenant and tenant != "default":
        return "tenant", tenant
    if role:
        return "role", role
    return "ip", host
