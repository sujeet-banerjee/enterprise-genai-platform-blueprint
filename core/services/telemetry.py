"""Prometheus telemetry collector (issue #44).

Exposes pipeline metrics in the Prometheus text exposition format. The
``prometheus-client`` dependency is **optional** (``pip install -e
".[observability]"``) so the lean backend/CI install is unchanged; when it is
absent :meth:`PrometheusCollector.is_available` returns ``False`` and the
``/metrics`` endpoint responds with a clear 503 instead of failing at import.

The collector is fed from the same run result the ``RunHistory`` store consumes
(``app/ops_api.py``), so there is no duplicate bookkeeping. Metric names are
fixed and carry no tenant labels yet - H1-A3 attribution can add ``tenant`` /
``app`` labels later without renaming the series.
"""

from typing import Any, Dict, Optional, Tuple

try:  # optional dependency
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - exercised via monkeypatched import
    _PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

# Logical pipeline stages exposed as latency histograms. ``total`` is tracked
# separately from stage latencies.
STAGES = ("embedding", "retrieval", "reranking", "generation", "total")

# Buckets in milliseconds, spanning fast local models to slow remote calls.
_LATENCY_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


class PrometheusCollector:
    """A self-contained Prometheus registry fed by pipeline run results."""

    def __init__(self, registry: Optional[Any] = None):
        self.available = _PROMETHEUS_AVAILABLE
        self._registry: Any = registry
        if not self.available:
            return
        if self._registry is None:
            self._registry = CollectorRegistry()

        self._requests = Counter(
            "genai_requests_total",
            "Total pipeline requests by status.",
            labelnames=("status",),
            registry=self._registry,
        )
        self._failures = Counter(
            "genai_failures_total",
            "Total failed pipeline requests by failure type.",
            labelnames=("failure_type",),
            registry=self._registry,
        )
        self._failure_tags = Counter(
            "genai_failure_tags_total",
            "Total failure tags emitted across requests.",
            labelnames=("tag",),
            registry=self._registry,
        )
        self._latency = Histogram(
            "genai_stage_latency_ms",
            "Per-stage pipeline latency in milliseconds.",
            labelnames=("stage",),
            buckets=_LATENCY_BUCKETS,
            registry=self._registry,
        )
        self._cost = Counter(
            "genai_cost_usd_total",
            "Cumulative estimated cost in USD.",
            registry=self._registry,
        )
        self._cache = Counter(
            "genai_cache_events_total",
            "Response-cache events.",
            labelnames=("event",),
            registry=self._registry,
        )
        self._governance_denials = Counter(
            "genai_governance_denials_total",
            "Governance/guardrail denials.",
            labelnames=("reason",),
            registry=self._registry,
        )
        self._in_flight = Gauge(
            "genai_in_flight_requests",
            "Pipeline requests currently being processed.",
            registry=self._registry,
        )

    def is_available(self) -> bool:
        return self.available

    # -- ingestion --------------------------------------------------------

    def observe_in_flight(self, delta: int) -> None:
        if not self.available:
            return
        self._in_flight.inc(delta)

    def record(self, result: Dict[str, Any]) -> None:
        """Update counters/histograms from one pipeline run result."""
        if not self.available:
            return

        failure_type = result.get("failure_type")
        error = result.get("error")
        status = "failed" if (error or failure_type) else "success"
        self._requests.labels(status=status).inc()

        if failure_type:
            self._failures.labels(failure_type=str(failure_type)).inc()
        elif error:
            self._failures.labels(failure_type="unknown_failure").inc()

        for tag in result.get("failure_tags") or []:
            self._failure_tags.labels(tag=str(tag)).inc()

        latency = result.get("latency") or {}
        for key, value in latency.items():
            if not isinstance(value, (int, float)):
                continue
            stage = key[:-3] if key.endswith("_ms") else key
            if stage in STAGES:
                self._latency.labels(stage=stage).observe(float(value))

        cost = result.get("cost") or {}
        amount = cost.get("estimated_cost_usd")
        if isinstance(amount, (int, float)) and amount > 0:
            self._cost.inc(float(amount))
            model_name = cost.get("model") or cost.get("model_name")
            if model_name:
                self._per_model_cost().labels(model=str(model_name)).inc(float(amount))

        cache_hit = result.get("cache_hit")
        if cache_hit is True:
            self._cache.labels(event="hit").inc()
        elif cache_hit is False:
            self._cache.labels(event="miss").inc()

        for reason in result.get("governance_denials") or []:
            self._governance_denials.labels(reason=str(reason)).inc()

    def _per_model_cost(self) -> Any:
        # Lazily create the labelled per-model counter (registry-safe).
        if not hasattr(self, "_per_model"):
            self._per_model = Counter(
                "genai_model_cost_usd_total",
                "Cumulative estimated cost in USD per model.",
                labelnames=("model",),
                registry=self._registry,
            )
        return self._per_model

    # -- rendering --------------------------------------------------------

    def render(self) -> Tuple[bytes, str]:
        """Return ``(payload, content_type)`` in Prometheus exposition format."""
        if not self.available:
            raise RuntimeError("prometheus-client is not installed")
        return generate_latest(self._registry), CONTENT_TYPE_LATEST
