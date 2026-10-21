"""Provider resilience: retries, circuit breakers and failover (issue #45).

These are **decorators/wrappers around the interfaces** so concrete providers
(``core/implementations/*``) stay untouched and the orchestration layer is
unchanged. Wrapping is applied by the composition root and is **disabled by
default**: with no ``resilience`` config every wrapper is a transparent
pass-through, so existing behaviour and tests are unaffected.

Included:
- :class:`RetryPolicy` - bounded exponential backoff + jitter for transient
  upstream errors (timeouts, 429, 5xx), with an injectable sleeper/clock for
  deterministic tests.
- :class:`CircuitBreaker` - closed/open/half-open breaker so a down provider
  fails fast instead of amplifying latency.
- :class:`ResilientLLM` / :class:`ResilientEmbedder` - apply retry + breaker and
  (for the LLM) a config-declared **failover chain**; the wrapper records which
  provider actually served the request.

Failures are classified with :class:`FailureType`; an exhausted retry chain adds
the ``upstream_retry_exhausted`` tag.
"""

import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.config.generation_config import GenerationConfig
from core.interfaces.embedder import BaseEmbedder
from core.interfaces.llm import BaseLLM
from core.services.failure_classifier import FailureType

RETRY_EXHAUSTED_TAG = "upstream_retry_exhausted"
BREAKER_OPEN_TAG = "provider_circuit_open"
FAILOVER_TAG = "provider_failover"


class RetryExhaustedError(RuntimeError):
    """Raised when every retry attempt (and any failover) failed."""

    failure_type = FailureType.UNKNOWN_FAILURE.value

    def __init__(self, attempts: int, last_error: Exception, *, tags: Optional[List[str]] = None):
        self.attempts = attempts
        self.last_error = last_error
        self.failure_tags = list(tags or []) or [RETRY_EXHAUSTED_TAG]
        super().__init__(
            f"upstream call failed after {attempts} attempt(s): {last_error}"
        )


class CircuitOpenError(RuntimeError):
    """Raised when a call is short-circuited because the breaker is open."""

    failure_type = FailureType.UNKNOWN_FAILURE.value

    def __init__(self, provider: str):
        self.provider = provider
        self.failure_tags = [BREAKER_OPEN_TAG]
        super().__init__(f"circuit breaker is open for provider '{provider}'")


def is_transient_error(exc: Exception) -> bool:
    """Heuristic: is this error likely to succeed on retry?

    True for timeouts, HTTP 429 (rate limit) and 5xx server errors, plus a few
    common transient message shapes. A ``retryable`` attribute on the exception
    overrides the heuristic.
    """
    override = getattr(exc, "retryable", None)
    if isinstance(override, bool):
        return override

    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    msg = str(exc).lower()
    for needle in (
        "timeout",
        "timed out",
        "rate limit",
        "too many requests",
        "429",
        "500",
        "502",
        "503",
        "504",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "overloaded",
    ):
        if needle in msg:
            return True
    return False


class RetryPolicy:
    """Bounded exponential backoff with optional jitter."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_initial_ms: float = 100.0,
        backoff_max_ms: float = 2000.0,
        jitter: bool = True,
        sleeper: Optional[Callable[[float], None]] = None,
        rng: Optional[random.Random] = None,
    ):
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_initial_ms = float(backoff_initial_ms)
        self.backoff_max_ms = float(backoff_max_ms)
        self.jitter = bool(jitter)
        self._sleep = sleeper or time.sleep
        self._rng = rng or random.Random()

    def backoff_seconds(self, attempt: int) -> float:
        """Backoff (in seconds) before ``attempt`` (1-based, so attempt 0 = first retry)."""
        raw = self.backoff_initial_ms * (2 ** max(0, attempt - 1))
        raw = min(raw, self.backoff_max_ms)
        if self.jitter:
            raw = raw * (0.5 + self._rng.random() * 0.5)
        return raw / 1000.0

    def execute(self, func: Callable[[], Any]) -> Any:
        """Run ``func`` with retries. Raises :class:`RetryExhaustedError` on give-up."""
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - re-classified below
                last_error = exc
                if attempt >= self.max_attempts or not is_transient_error(exc):
                    break
                self._sleep(self.backoff_seconds(attempt))
        assert last_error is not None
        raise RetryExhaustedError(self.max_attempts, last_error) from last_error


class CircuitBreaker:
    """A minimal closed/open/half-open breaker with an injectable clock."""

    def __init__(
        self,
        threshold: int = 5,
        reset_ms: float = 30000.0,
        clock: Optional[Callable[[], float]] = None,
    ):
        self.threshold = max(1, int(threshold))
        self.reset_seconds = float(reset_ms) / 1000.0
        self._clock = clock or time.monotonic
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._half_open = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if self._half_open:
                return "half_open"
            if self._clock() - self._opened_at >= self.reset_seconds:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        """True if a call may proceed (closed, or half-open probe)."""
        with self._lock:
            if self._opened_at is None:
                return True
            if self._half_open:
                return True
            if self._clock() - self._opened_at >= self.reset_seconds:
                self._half_open = True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._half_open or self._failures >= self.threshold:
                self._opened_at = self._clock()
                self._half_open = False
                self._failures = 0


class _ResilienceMixin:
    """Shared retry/breaker bookkeeping and trace metadata."""

    def _init_resilience(
        self,
        *,
        retry: Optional[RetryPolicy],
        breaker: Optional[CircuitBreaker],
        provider_name: str,
    ) -> None:
        self._retry = retry
        self._breaker = breaker
        self._provider_name = provider_name
        self._events: List[Dict[str, Any]] = []
        self._events_lock = threading.Lock()

    def _record_event(self, **event: Any) -> None:
        with self._events_lock:
            self._events.append(event)

    def pop_resilience(self) -> Dict[str, Any]:
        """Return (and clear) the resilience events accumulated since the last call."""
        with self._events_lock:
            events = self._events
            self._events = []
        if not events:
            return {}
        return {
            "attempts": sum(e.get("attempts", 1) for e in events),
            "retries": sum(max(0, e.get("attempts", 1) - 1) for e in events),
            "failovers": sum(1 for e in events if e.get("failover")),
            "breaker_opens": sum(1 for e in events if e.get("breaker_open")),
            "served_by": events[-1].get("served_by"),
            "tags": sorted({t for e in events for t in e.get("tags", [])}),
        }

    def _run_with_resilience(self, func: Callable[[], Any]) -> Any:
        breaker = self._breaker
        if breaker is not None and not breaker.allow():
            self._record_event(breaker_open=True, provider=self._provider_name)
            raise CircuitOpenError(self._provider_name)

        attempts = 0

        def _attempt() -> Any:
            nonlocal attempts
            attempts += 1
            return func()

        try:
            if self._retry is not None:
                value = self._retry.execute(_attempt)
            else:
                value = _attempt()
        except Exception:
            if breaker is not None:
                breaker.record_failure()
            self._record_event(attempts=attempts, provider=self._provider_name)
            raise
        if breaker is not None:
            breaker.record_success()
        self._record_event(attempts=attempts, provider=self._provider_name)
        return value


class ResilientLLM(_ResilienceMixin, BaseLLM):
    """Wraps one or more LLMs with retry, breaker and failover (issue #45).

    ``providers`` is an ordered chain: the first entry is primary, the rest are
    failover targets. Each provider has its own breaker; a provider whose
    breaker is open is skipped in favour of the next.
    """

    def __init__(
        self,
        providers: Sequence[BaseLLM],
        *,
        retry: Optional[RetryPolicy] = None,
        breakers: Optional[Sequence[Optional[CircuitBreaker]]] = None,
    ):
        if not providers:
            raise ValueError("ResilientLLM requires at least one provider")
        self._providers = list(providers)
        self._breakers = list(breakers) if breakers else [None] * len(self._providers)
        self._init_resilience(
            retry=retry,
            breaker=None,
            provider_name=_provider_name(self._providers[0]),
        )

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        last_error: Optional[Exception] = None
        all_breaker_open = True
        for index, provider in enumerate(self._providers):
            breaker = self._breakers[index]
            try:
                attempts = 0

                def _attempt(_provider=provider) -> Any:
                    nonlocal attempts
                    attempts += 1
                    return getattr(_provider, method)(*args, **kwargs)

                if breaker is not None and not breaker.allow():
                    self._record_event(
                        breaker_open=True, provider=_provider_name(provider)
                    )
                    raise CircuitOpenError(_provider_name(provider))

                if self._retry is not None:
                    value = self._retry.execute(_attempt)
                else:
                    value = _attempt()

                if breaker is not None:
                    breaker.record_success()
                self._record_event(
                    attempts=attempts,
                    provider=_provider_name(provider),
                    served_by=_provider_name(provider),
                    failover=index > 0,
                )
                return value
            except Exception as exc:  # noqa: BLE001 - try the next provider
                if breaker is not None:
                    breaker.record_failure()
                if not isinstance(exc, CircuitOpenError):
                    all_breaker_open = False
                last_error = exc
                continue

        # If every provider was short-circuited by its breaker, surface that
        # directly (the caller can then fail fast) rather than masking it as a
        # generic retry-exhaustion.
        if all_breaker_open and isinstance(last_error, CircuitOpenError):
            self._record_event(breaker_open=True, provider="all")
            raise last_error

        tags = [RETRY_EXHAUSTED_TAG]
        if len(self._providers) > 1:
            tags.append(FAILOVER_TAG)
        self._record_event(attempts=1, provider="none", tags=tags)
        raise RetryExhaustedError(1, last_error or RuntimeError("no provider"), tags=tags)

    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        return self._call("generate", prompt, config)

    def generate_batch(
        self, prompts: List[str], config: Optional[GenerationConfig] = None
    ) -> List[str]:
        return self._call("generate_batch", prompts, config)

    @property
    def context_window(self) -> int:
        return self._providers[0].context_window

    @property
    def model_name(self) -> str:
        return self._providers[0].model_name


class ResilientEmbedder(_ResilienceMixin, BaseEmbedder):
    """Wraps an embedder with retry + breaker (issue #45)."""

    def __init__(
        self,
        embedder: BaseEmbedder,
        *,
        retry: Optional[RetryPolicy] = None,
        breaker: Optional[CircuitBreaker] = None,
    ):
        self._embedder = embedder
        self._init_resilience(
            retry=retry, breaker=breaker, provider_name=_provider_name(embedder)
        )

    def embed(self, text: str) -> List[float]:
        return self._run_with_resilience(lambda: self._embedder.embed(text))

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self._run_with_resilience(lambda: self._embedder.embed_batch(texts))

    @property
    def dimension(self) -> int:
        return self._embedder.dimension

    @property
    def model_name(self) -> str:
        return getattr(self._embedder, "model_name", self._embedder.__class__.__name__)


def _provider_name(provider: Any) -> str:
    return str(getattr(provider, "model_name", None) or provider.__class__.__name__)


def build_resilient_llm(
    providers: Sequence[BaseLLM],
    config: Optional[Dict[str, Any]],
    *,
    sleeper: Optional[Callable[[float], None]] = None,
    clock: Optional[Callable[[], float]] = None,
) -> BaseLLM:
    """Wrap ``providers`` per a ``resilience`` config block (no-op when disabled)."""
    cfg = config or {}
    if not providers or not _enabled(cfg):
        return providers[0] if providers else providers  # type: ignore[return-value]
    retry = _retry_from_config(cfg, sleeper=sleeper)
    breakers = [_breaker_from_config(cfg, clock=clock) for _ in providers]
    return ResilientLLM(providers, retry=retry, breakers=breakers)


def build_resilient_embedder(
    embedder: BaseEmbedder,
    config: Optional[Dict[str, Any]],
    *,
    sleeper: Optional[Callable[[float], None]] = None,
    clock: Optional[Callable[[], float]] = None,
) -> BaseEmbedder:
    """Wrap ``embedder`` per a ``resilience`` config block (no-op when disabled)."""
    cfg = config or {}
    if not _enabled(cfg):
        return embedder
    return ResilientEmbedder(
        embedder,
        retry=_retry_from_config(cfg, sleeper=sleeper),
        breaker=_breaker_from_config(cfg, clock=clock),
    )


def _enabled(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("enabled", False))


def _retry_from_config(
    cfg: Dict[str, Any], *, sleeper: Optional[Callable[[float], None]] = None
) -> Optional[RetryPolicy]:
    max_attempts = int(cfg.get("max_attempts", cfg.get("retries", 3)))
    if max_attempts <= 1:
        return None
    return RetryPolicy(
        max_attempts=max_attempts,
        backoff_initial_ms=float(cfg.get("backoff_initial_ms", 100.0)),
        backoff_max_ms=float(cfg.get("backoff_max_ms", 2000.0)),
        jitter=bool(cfg.get("jitter", True)),
        sleeper=sleeper,
    )


def _breaker_from_config(
    cfg: Dict[str, Any], *, clock: Optional[Callable[[], float]] = None
) -> Optional[CircuitBreaker]:
    threshold = int(cfg.get("breaker_threshold", 5))
    if threshold <= 0:
        return None
    return CircuitBreaker(
        threshold=threshold,
        reset_ms=float(cfg.get("breaker_reset_ms", 30000.0)),
        clock=clock,
    )
