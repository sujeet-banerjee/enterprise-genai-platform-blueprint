"""Observability export layer (issues #44 + #47).

- :class:`PrometheusCollector` (issue #44) exposes pipeline metrics in the
  Prometheus text exposition format.
- :class:`OtelTracer` (issue #47) exports OpenTelemetry spans over OTLP so traces
  land in an existing Jaeger/Tempo/Grafana/Datadog/New Relic stack.

Both dependencies are **optional** (``pip install -e ".[observability]"``) so the
lean backend/CI install is unchanged; when a library is absent the relevant
:meth:`is_available` returns ``False`` and callers degrade gracefully (the
``/metrics`` endpoint responds with a clear 503; OTel tracing is a no-op).

The collector/tracer are fed from the same run result the ``RunHistory`` store
consumes (``app/ops_api.py``), so there is no duplicate bookkeeping. Metric names
are fixed and carry no tenant labels yet - H1-A3 attribution can add ``tenant`` /
``app`` labels later without renaming the series.
"""

import contextlib
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

try:  # optional dependency
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider as _OtelTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised via monkeypatched import
    _OTEL_AVAILABLE = False
    _otel_trace = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment,misc]
    _OtelTracerProvider = None  # type: ignore[assignment,misc]
    _BatchSpanProcessor = None  # type: ignore[assignment,misc]


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
        self._guardrail_decisions = Counter(
            "genai_guardrail_decisions_total",
            "Guardrail decisions by guardrail and decision.",
            labelnames=("guardrail", "decision"),
            registry=self._registry,
        )
        self._guardrail_blocks = Counter(
            "genai_guardrail_blocks_total",
            "Blocking guardrail decisions by guardrail and pipeline edge.",
            labelnames=("guardrail", "stage"),
            registry=self._registry,
        )
        self._in_flight = Gauge(
            "genai_in_flight_requests",
            "Pipeline requests currently being processed.",
            registry=self._registry,
        )
        # Attribution (issue #50): a dimension-labelled companion series so spend
        # and volume can be reported by tenant/app/user without renaming the
        # existing (unlabelled) metrics. Dimension values are bounded/sanitised
        # by ``core.services.attribution`` before they reach here.
        self._attributed_cost = Counter(
            "genai_attributed_cost_usd_total",
            "Cumulative estimated cost in USD by attribution dimension.",
            labelnames=("tenant", "app", "user"),
            registry=self._registry,
        )
        self._attributed_requests = Counter(
            "genai_attributed_requests_total",
            "Pipeline requests by attribution dimension and status.",
            labelnames=("tenant", "app", "user", "status"),
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

        # Attribution labels (issue #50). ``status`` mirrors genai_requests_total.
        attribution = result.get("attribution")
        if isinstance(attribution, dict):
            labels = {
                "tenant": str(attribution.get("tenant") or "default"),
                "app": str(attribution.get("app") or "default"),
                "user": str(attribution.get("user") or "default"),
            }
            self._attributed_requests.labels(status=status, **labels).inc()
            if isinstance(amount, (int, float)) and amount > 0:
                self._attributed_cost.labels(**labels).inc(float(amount))

        cache_hit = result.get("cache_hit")
        if cache_hit is True:
            self._cache.labels(event="hit").inc()
        elif cache_hit is False:
            self._cache.labels(event="miss").inc()

        for reason in result.get("governance_denials") or []:
            self._governance_denials.labels(reason=str(reason)).inc()

        # Guardrail decisions (issue #87). A cache hit replays the original
        # decisions without running any guardrail, so it must not inflate the
        # counters; the same rule is applied by the in-process /v1/metrics store.
        if result.get("cache_hit") is not True:
            for decision in result.get("guardrail_decisions") or []:
                if not isinstance(decision, dict):
                    continue
                name = str(decision.get("guardrail") or "unknown")
                outcome = str(decision.get("decision") or "allow")
                self._guardrail_decisions.labels(
                    guardrail=name, decision=outcome
                ).inc()
                if outcome == "block":
                    self._guardrail_blocks.labels(
                        guardrail=name, stage=self._guardrail_stage(result, decision)
                    ).inc()

    @staticmethod
    def _guardrail_stage(result: Dict[str, Any], decision: Dict[str, Any]) -> str:
        """Resolve ``input``/``output`` for a block (issue #87)."""
        stage = str(decision.get("stage") or "").strip().lower()
        if stage:
            return stage
        observability = result.get("observability")
        failed_stage = ""
        if isinstance(observability, dict):
            failed_stage = str(observability.get("failed_stage") or "")
        if failed_stage.startswith("guardrail_"):
            return failed_stage[len("guardrail_") :]
        return "unknown"

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


# Stage span names exported to OTLP, in pipeline order.
OTEL_STAGE_SPANS = (
    "retrieval_policy",
    "embedding",
    "retrieval",
    "reranking",
    "token_budget",
    "prompt_construction",
    "llm_generation",
    "evaluation",
    "cost_governance",
)


class OtelTracer:
    """OTel-native tracing exporter (issue #47).

    Wraps a ``TracerProvider`` configured with an OTLP exporter (or an injected
    exporter, e.g. the in-memory exporter used in tests). The in-process trace in
    ``PipelineObservabilityTracker`` remains the source of truth (the UI reads
    ``/v1/traces/{id}``); this is a pure **exporter**, so the pipeline contract is
    unchanged.

    When the OTel SDK is not installed, :meth:`is_available` is ``False`` and
    everything is a no-op. The factory :func:`build_otel_tracer` returns ``None``
    when tracing is disabled, keeping the disabled path zero-overhead.
    """

    def __init__(
        self,
        *,
        service_name: str = "enterprise-genai-platform",
        endpoint: Optional[str] = None,
        sample_ratio: float = 1.0,
        exporter: Optional[Any] = None,
    ):
        self.available = _OTEL_AVAILABLE
        self.service_name = service_name
        self.endpoint = endpoint
        self.sample_ratio = max(0.0, min(1.0, float(sample_ratio)))
        self._provider: Any = None
        self._tracer: Any = None
        if not self.available:
            return

        resource = Resource.create({"service.name": service_name})
        self._provider = _OtelTracerProvider(resource=resource)
        span_exporter = exporter if exporter is not None else self._build_otlp_exporter(endpoint)
        if span_exporter is not None:
            self._provider.add_span_processor(_BatchSpanProcessor(span_exporter))
        self._tracer = self._provider.get_tracer("enterprise_genai.pipeline")

    @staticmethod
    def _build_otlp_exporter(endpoint: Optional[str]) -> Optional[Any]:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except Exception:  # pragma: no cover - only when sdk installed without exporter
            return None
        if endpoint:
            return OTLPSpanExporter(endpoint=endpoint)
        return OTLPSpanExporter()

    def is_available(self) -> bool:
        return self.available and self._tracer is not None

    # -- spans ------------------------------------------------------------

    @contextlib.contextmanager
    def span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Open a span as the current context; a no-op when unavailable."""
        if not self.is_available():
            yield None
            return
        with self._tracer.start_as_current_span(name) as span:
            for key, value in (attributes or {}).items():
                if value is None:
                    continue
                try:
                    span.set_attribute(key, value)
                except Exception:  # pragma: no cover - defensive
                    pass
            yield span

    def current_ids(self) -> Dict[str, Optional[str]]:
        """Return the active ``{trace_id, span_id}`` for log correlation."""
        if not self.is_available():
            return {"trace_id": None, "span_id": None}
        ctx = _otel_trace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return {"trace_id": None, "span_id": None}
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }

    def force_flush(self) -> None:
        if self._provider is not None and hasattr(self._provider, "force_flush"):
            self._provider.force_flush()


def build_otel_tracer(
    otel_config: Optional[Dict[str, Any]],
    *,
    exporter: Optional[Any] = None,
) -> Optional[OtelTracer]:
    """Build an :class:`OtelTracer` from an ``observability.otel`` block.

    Returns ``None`` when tracing is disabled (the default) or the OTel SDK is
    unavailable - so callers can treat ``None`` as "no tracing".
    """
    cfg = otel_config or {}
    if not cfg.get("enabled", False):
        return None
    if not _OTEL_AVAILABLE:
        return None
    return OtelTracer(
        service_name=str(cfg.get("service_name") or "enterprise-genai-platform"),
        endpoint=cfg.get("endpoint"),
        sample_ratio=float(cfg.get("sample_ratio", 1.0)),
        exporter=exporter,
    )

