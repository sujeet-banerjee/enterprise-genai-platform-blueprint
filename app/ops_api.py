"""Governance status, trace lookup and metrics endpoints (issue #38).

A bounded in-memory ``RunHistory`` is fed from each ``RAGPipeline.run`` result by
the query endpoint. It backs a spend window (governance status), a LRU of
redacted traces and aggregate latency/failure/cost metrics.
"""

import math
import threading
import uuid
from collections import Counter, OrderedDict, deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.schemas import GovernanceStatusResponse, MetricsResponse
from core.registry.pii_registry import PiiRegistry
from core.services.failure_classifier import FailureType
from core.services.observability import SensitiveDataRedactor

_LATENCY_SUFFIXES = ("_ms",)


def _build_redactor(observability_config_path: Optional[Path]) -> SensitiveDataRedactor:
    config: dict = {}
    if observability_config_path:
        try:
            with open(observability_config_path, "r") as handle:
                loaded = yaml.safe_load(handle) or {}
            config = loaded if isinstance(loaded, dict) else {}
        except OSError:
            config = {}
    # PII / DLP scrubbing (issue #54): traces and metrics must not carry
    # personal data either.
    pii_registry = PiiRegistry(config=config)
    pii_detector = pii_registry.build_detector()
    return SensitiveDataRedactor(
        enabled=bool(config.get("redact_sensitive_data", True)),
        patterns=config.get("sensitive_patterns"),
        pii_detector=pii_detector,
        pii_classes=pii_registry.classes() if pii_detector is not None else None,
    )


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = int(math.ceil((percentile / 100.0) * len(ordered))) - 1
    rank = max(0, min(rank, len(ordered) - 1))
    return round(ordered[rank], 4)


def _latency_stat(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
    }


class RunHistory:
    """Bounded run-history + redacted trace store."""

    def __init__(
        self,
        max_runs: int = 1000,
        max_traces: int = 500,
        redactor: Optional[SensitiveDataRedactor] = None,
        observability_config_path: Optional[Any] = None,
    ):
        self.max_runs = int(max_runs)
        self.max_traces = int(max_traces)
        self._runs: Deque[Dict[str, Any]] = deque(maxlen=self.max_runs)
        self._traces: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        if redactor is None:
            redactor = _build_redactor(observability_config_path)
        self._redactor = redactor

    @property
    def redactor(self) -> SensitiveDataRedactor:
        return self._redactor

    def redact(self, obj: Any) -> Any:
        return self._redactor.redact_obj(obj)

    # -- ingestion --------------------------------------------------------

    def record(self, request_id: str, result: Dict[str, Any]) -> None:
        cost = result.get("cost") or {}
        latency = {
            key: float(value)
            for key, value in (result.get("latency") or {}).items()
            if isinstance(value, (int, float))
        }
        failure_type = result.get("failure_type")
        failure_tags = [str(tag) for tag in (result.get("failure_tags") or [])]
        entry = {
            "request_id": request_id,
            "success": not result.get("error") and not failure_type,
            "failure_type": failure_type,
            "failure_tags": failure_tags,
            "cost_usd": float(cost.get("estimated_cost_usd") or 0.0),
            "latency": latency,
        }
        trace = result.get("observability")
        with self._lock:
            self._runs.append(entry)
            if isinstance(trace, (dict, list)) and request_id:
                self._traces[request_id] = self._redactor.redact_obj(trace)
                self._traces.move_to_end(request_id)
                while len(self._traces) > self.max_traces:
                    self._traces.popitem(last=False)

    # -- reads ------------------------------------------------------------

    def trace(self, request_id: str) -> Optional[Any]:
        with self._lock:
            trace = self._traces.get(request_id)
            return dict(trace) if isinstance(trace, dict) else trace

    def run_count(self) -> int:
        with self._lock:
            return len(self._runs)

    def trace_count(self) -> int:
        with self._lock:
            return len(self._traces)

    def spend_window(self) -> Dict[str, Any]:
        with self._lock:
            runs = list(self._runs)
        costs = [entry["cost_usd"] for entry in runs]
        total = sum(costs)
        return {
            "window_size": self.max_runs,
            "requests": len(runs),
            "total_cost_usd": round(total, 6),
            "mean_cost_usd": round(total / len(runs), 6) if runs else 0.0,
        }

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            runs = list(self._runs)

        total = len(runs)
        success_count = sum(1 for entry in runs if entry["success"])
        failure_count = total - success_count

        by_type: Counter = Counter(
            entry["failure_type"] for entry in runs if entry["failure_type"]
        )
        by_tag: Counter = Counter(
            tag for entry in runs for tag in entry["failure_tags"]
        )

        stage_values: Dict[str, List[float]] = {}
        total_values: List[float] = []
        for entry in runs:
            latency = entry["latency"]
            if "total_ms" in latency:
                total_values.append(latency["total_ms"])
            for key, value in latency.items():
                if key.startswith("total") or key.endswith(_LATENCY_SUFFIXES):
                    continue
                stage_values.setdefault(key, []).append(value)

        costs = [entry["cost_usd"] for entry in runs]
        priced = [value for value in costs if value > 0]

        return {
            "total_runs": total,
            "success_count": success_count,
            "failure_count": failure_count,
            "failure_rate": round(failure_count / total, 6) if total else 0.0,
            "latency_ms": {
                stage: _latency_stat(values) for stage, values in sorted(stage_values.items())
            },
            "total_latency_ms": _latency_stat(total_values),
            "failures_by_type": dict(by_type),
            "failures_by_tag": dict(by_tag),
            "cost": {
                "total_cost_usd": round(sum(costs), 6),
                "mean_cost_usd": round(sum(costs) / total, 6) if total else 0.0,
                "priced_runs": len(priced),
            },
        }


def register_ops_routes(
    application: FastAPI,
    error_envelope: Callable[..., dict],
) -> None:
    def _history(request: Request):
        history = getattr(request.app.state, "history", None)
        if history is None:
            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return None, JSONResponse(
                status_code=503,
                content=error_envelope(
                    "Run history is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    request_id,
                ),
            )
        return history, None

    def _request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())

    @application.get("/v1/governance/status", response_model=GovernanceStatusResponse)
    def governance_status(request: Request):
        history, error = _history(request)
        if error is not None:
            return error
        request_id = _request_id(request)

        governance_config: Dict[str, Any] = {}
        introspect = getattr(request.app.state, "introspect", None)
        if introspect is not None:
            effective = introspect.effective_config()
            governance_config = effective.get("governance") or {}
            if not governance_config:
                retrieval_section = effective.get("retrieval") or {}
                governance_config = retrieval_section.get("governance") or {}

        redacted = history.redact(dict(governance_config))
        if not isinstance(redacted, dict):
            redacted = dict(governance_config)

        return GovernanceStatusResponse(
            enabled=bool(redacted.get("enabled", True)),
            max_cost_per_request_usd=redacted.get("max_cost_per_request_usd"),
            safety_margin_tokens=redacted.get("safety_margin_tokens"),
            avg_chunk_tokens=redacted.get("avg_chunk_tokens"),
            window=history.spend_window(),
            request_id=request_id,
        )

    @application.get("/v1/traces/{request_id}")
    def trace_lookup(request: Request, request_id: str):
        history, error = _history(request)
        if error is not None:
            return error
        trace = history.trace(request_id)
        if trace is None:
            return JSONResponse(
                status_code=404,
                content=error_envelope(
                    f"No trace recorded for request_id '{request_id}'.",
                    FailureType.UNKNOWN_FAILURE.value,
                    ["trace_not_found"],
                    _request_id(request),
                ),
            )
        return JSONResponse(status_code=200, content=trace)

    @application.get("/v1/metrics", response_model=MetricsResponse)
    def metrics_endpoint(request: Request):
        history, error = _history(request)
        if error is not None:
            return error
        payload = history.metrics()
        payload["request_id"] = _request_id(request)
        return MetricsResponse(**payload)

    @application.get("/metrics")
    def prometheus_metrics(request: Request):
        """Prometheus text exposition (issue #44).

        Requires the optional ``prometheus-client`` extra; when it is absent the
        endpoint returns a 503 envelope explaining how to enable it.
        """
        telemetry = getattr(request.app.state, "telemetry", None)
        if telemetry is None or not telemetry.is_available():
            return JSONResponse(
                status_code=503,
                content=error_envelope(
                    "Prometheus metrics are unavailable; install the "
                    "'observability' extra (pip install -e \".[observability]\").",
                    FailureType.NOT_READY.value,
                    ["prometheus_not_installed"],
                    _request_id(request),
                ),
            )
        payload, content_type = telemetry.render()
        return Response(content=payload, media_type=content_type)
