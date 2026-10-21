"""Tests for issue #45: provider resilience (retries, breaker, failover).

Acceptance:
- a provider that fails transiently N times then succeeds is retried,
- retries are bounded and exponential backoff is applied (deterministic via an
  injected sleeper),
- the circuit breaker opens after a threshold and half-opens/recovers after its
  reset window (injected clock),
- a config-declared fallback provider serves the request when the primary fails,
- the wrapper is transparent when resilience is disabled (existing behaviour).

These are unit-level (no real model inference) so they run fast and
deterministically; the composition-root wiring is covered separately.
"""

import random
from typing import List, Optional

import pytest

from core.config.generation_config import GenerationConfig
from core.interfaces.embedder import BaseEmbedder
from core.interfaces.llm import BaseLLM
from core.services.resilience import (
    BREAKER_OPEN_TAG,
    RETRY_EXHAUSTED_TAG,
    CircuitBreaker,
    CircuitOpenError,
    ResilientEmbedder,
    ResilientLLM,
    RetryExhaustedError,
    RetryPolicy,
    build_resilient_embedder,
    build_resilient_llm,
    is_transient_error,
)


class _FlakyLLM(BaseLLM):
    """Fails ``fail_times`` times (transient) then returns a fixed response."""

    def __init__(self, name="flaky", fail_times=1, error=None, response="ok"):
        self._name = name
        self.fail_times = fail_times
        self.calls = 0
        self._error = error or TimeoutError("upstream timeout")
        self._response = response

    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self._error
        return f"{self._response}:{prompt}"

    @property
    def context_window(self) -> int:
        return 4096

    @property
    def model_name(self) -> str:
        return self._name


class _FailingLLM(BaseLLM):
    def __init__(self, name="dead"):
        self._name = name
        self.calls = 0

    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        self.calls += 1
        raise RuntimeError("permanent upstream 500 error")

    @property
    def context_window(self) -> int:
        return 4096

    @property
    def model_name(self) -> str:
        return self._name


class _FlakyEmbedder(BaseEmbedder):
    def __init__(self, name="emb", fail_times=1):
        self._name = name
        self.fail_times = fail_times
        self.calls = 0

    def embed(self, text: str) -> List[float]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TimeoutError("timeout")
        return [float(len(text))]

    @property
    def dimension(self) -> int:
        return 1

    @property
    def model_name(self) -> str:
        return self._name


class _Recorder:
    def __init__(self):
        self.slept: List[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# -- transient classification --------------------------------------------


def test_is_transient_error_heuristic():
    assert is_transient_error(TimeoutError("x")) is True
    assert is_transient_error(RuntimeError("503 service unavailable")) is True
    assert is_transient_error(RuntimeError("rate limit exceeded")) is True
    assert is_transient_error(RuntimeError("invalid api key")) is False

    class _Http(Exception):
        def __init__(self, status_code):
            self.status_code = status_code
            super().__init__(f"http {status_code}")

    assert is_transient_error(_Http(429)) is True
    assert is_transient_error(_Http(503)) is True
    assert is_transient_error(_Http(400)) is False


# -- retry -----------------------------------------------------------------


def test_retry_then_success():
    recorder = _Recorder()
    policy = RetryPolicy(max_attempts=3, sleeper=recorder)
    provider = _FlakyLLM(fail_times=2)
    llm = ResilientLLM([provider], retry=policy)

    assert llm.generate("hi") == "ok:hi"
    assert provider.calls == 3  # two failures + one success
    assert len(recorder.slept) == 2  # slept between attempts


def test_retry_exhausted_raises_with_tag():
    recorder = _Recorder()
    policy = RetryPolicy(max_attempts=3, sleeper=recorder)
    provider = _FlakyLLM(fail_times=99)
    llm = ResilientLLM([provider], retry=policy)

    with pytest.raises(RetryExhaustedError) as excinfo:
        llm.generate("hi")
    assert provider.calls == 3
    assert RETRY_EXHAUSTED_TAG in excinfo.value.failure_tags


def test_non_transient_error_is_not_retried():
    recorder = _Recorder()
    policy = RetryPolicy(max_attempts=5, sleeper=recorder)
    provider = _FlakyLLM(fail_times=99, error=ValueError("bad request"))

    with pytest.raises(RetryExhaustedError):
        ResilientLLM([provider], retry=policy).generate("hi")
    assert provider.calls == 1  # permanent error -> gave up immediately
    assert recorder.slept == []


def test_backoff_is_bounded_and_exponential():
    policy = RetryPolicy(
        max_attempts=5,
        backoff_initial_ms=100,
        backoff_max_ms=800,
        jitter=False,
    )
    # attempt 1 -> 100ms, 2 -> 200ms, 3 -> 400ms, 4 -> 800ms, capped thereafter.
    assert policy.backoff_seconds(1) == pytest.approx(0.1)
    assert policy.backoff_seconds(2) == pytest.approx(0.2)
    assert policy.backoff_seconds(3) == pytest.approx(0.4)
    assert policy.backoff_seconds(4) == pytest.approx(0.8)
    assert policy.backoff_seconds(10) == pytest.approx(0.8)

    jittered = RetryPolicy(
        max_attempts=3, backoff_initial_ms=100, jitter=True, rng=random.Random(0)
    )
    value = jittered.backoff_seconds(1)
    assert 0.05 <= value <= 0.1


# -- circuit breaker -------------------------------------------------------


def test_breaker_opens_then_half_opens_and_recovers():
    clock = _Clock()
    breaker = CircuitBreaker(threshold=3, reset_ms=1000, clock=clock)

    assert breaker.state == "closed"
    for _ in range(3):
        assert breaker.allow() is True
        breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False  # short-circuits while open

    clock.advance(1.0)
    assert breaker.state == "half_open"
    assert breaker.allow() is True  # one probe allowed

    breaker.record_success()
    assert breaker.state == "closed"


def test_breaker_half_open_failure_reopens():
    clock = _Clock()
    breaker = CircuitBreaker(threshold=2, reset_ms=1000, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "open"

    clock.advance(1.0)
    assert breaker.allow() is True  # half-open probe
    breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False


def test_breaker_short_circuits_resilient_llm():
    clock = _Clock()
    breaker = CircuitBreaker(threshold=2, reset_ms=1000, clock=clock)
    llm = ResilientLLM([_FailingLLM()], retry=None, breakers=[breaker])

    for _ in range(2):
        with pytest.raises(Exception):
            llm.generate("hi")

    with pytest.raises(CircuitOpenError) as excinfo:
        llm.generate("hi")
    assert BREAKER_OPEN_TAG in excinfo.value.failure_tags


# -- failover --------------------------------------------------------------


def test_failover_to_secondary_provider():
    primary = _FailingLLM("primary")
    secondary = _FlakyLLM("secondary", fail_times=0, response="secondary")
    llm = ResilientLLM([primary, secondary], retry=None)

    assert llm.generate("q") == "secondary:q"
    assert primary.calls == 1
    assert secondary.calls == 1
    # Primary identity is preserved for cost/context purposes.
    assert llm.model_name == "primary"


def test_failover_reports_served_by_in_resilience_events():
    primary = _FailingLLM("primary")
    secondary = _FlakyLLM("secondary", fail_times=0, response="secondary")
    llm = ResilientLLM([primary, secondary], retry=None)

    llm.generate("q")
    events = llm.pop_resilience()
    assert events["failovers"] == 1
    assert events["served_by"] == "secondary"


def test_all_providers_down_raises_exhausted():
    llm = ResilientLLM([_FailingLLM("a"), _FailingLLM("b")], retry=None)
    with pytest.raises(RetryExhaustedError) as excinfo:
        llm.generate("q")
    assert RETRY_EXHAUSTED_TAG in excinfo.value.failure_tags


# -- embedder --------------------------------------------------------------


def test_resilient_embedder_retries():
    recorder = _Recorder()
    embedder = _FlakyEmbedder(fail_times=1)
    wrapped = ResilientEmbedder(
        embedder, retry=RetryPolicy(max_attempts=3, sleeper=recorder)
    )
    assert wrapped.embed("abc") == [3.0]
    assert embedder.calls == 2
    assert wrapped.dimension == 1


# -- config-driven factory + defaults --------------------------------------


def test_build_helpers_are_noop_when_disabled():
    provider = _FlakyLLM("p")
    embedder = _FlakyEmbedder("e")

    assert build_resilient_llm([provider], {"enabled": False}) is provider
    assert build_resilient_embedder(embedder, {}) is embedder
    assert build_resilient_llm([provider], None) is provider


def test_build_helpers_wrap_when_enabled():
    recorder = _Recorder()
    config = {
        "enabled": True,
        "max_attempts": 3,
        "backoff_initial_ms": 1,
        "backoff_max_ms": 2,
        "jitter": False,
    }
    provider = _FlakyLLM("p", fail_times=1)
    # sleeper is threaded through the factory via the policy for determinism.
    llm = build_resilient_llm([provider], config, sleeper=recorder)
    assert isinstance(llm, ResilientLLM)
    assert llm.generate("x") == "ok:x"

    embedder = build_resilient_embedder(_FlakyEmbedder("e", fail_times=1), config, sleeper=recorder)
    assert isinstance(embedder, ResilientEmbedder)


def test_retry_disabled_but_breaker_kept():
    config = {"enabled": True, "max_attempts": 1, "breaker_threshold": 1}
    provider = _FlakyLLM("p", fail_times=1)
    llm = build_resilient_llm([provider], config)
    assert isinstance(llm, ResilientLLM)
    # max_attempts=1 -> no retry; the first failure exhausts the single attempt.
    with pytest.raises(RetryExhaustedError):
        llm.generate("x")
