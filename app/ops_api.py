"""Governance status, trace lookup and metrics endpoints (issue #38).

A bounded in-memory ``RunHistory`` is fed from each ``RAGPipeline.run`` result by
the query endpoint. It backs a spend window (governance status), a LRU of
redacted traces and aggregate latency/failure/cost metrics.
"""

import math
import threading
import time
import uuid
from collections import Counter, OrderedDict, deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.schemas import (
    AttributionReportResponse,
    GovernanceStatusResponse,
    MetricsResponse,
)
from core.registry.pii_registry import PiiRegistry
from core.services.attribution import AttributionContext, current_attribution
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
        store: Optional[Any] = None,
    ):
        self.max_runs = int(max_runs)
        self.max_traces = int(max_traces)
        self._runs: Deque[Dict[str, Any]] = deque(maxlen=self.max_runs)
        self._traces: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        if redactor is None:
            redactor = _build_redactor(observability_config_path)
        self._redactor = redactor
        self._store = store
        self._store_prefix = "runs"

    @property
    def redactor(self) -> SensitiveDataRedactor:
        return self._redactor

    def redact(self, obj: Any) -> Any:
        return self._redactor.redact_obj(obj)

    # -- ingestion --------------------------------------------------------

    def record(
        self,
        request_id: str,
        result: Dict[str, Any],
        tenant: Optional[str] = None,
        attribution: Optional[Dict[str, Any]] = None,
    ) -> None:
        cost = result.get("cost") or {}
        latency = {
            key: float(value)
            for key, value in (result.get("latency") or {}).items()
            if isinstance(value, (int, float))
        }
        failure_type = result.get("failure_type")
        failure_tags = [str(tag) for tag in (result.get("failure_tags") or [])]
        guardrail_decisions: List[Dict[str, str]] = []
        # Cache hits replay the original decisions without running a guardrail
        # (issue #87), so they are excluded from hit-rate aggregation.
        if result.get("cache_hit") is not True:
            for decision in result.get("guardrail_decisions") or []:
                if not isinstance(decision, dict):
                    continue
                guardrail_decisions.append(
                    {
                        "guardrail": str(decision.get("guardrail") or "unknown"),
                        "decision": str(decision.get("decision") or "allow"),
                        "stage": str(decision.get("stage") or ""),
                    }
                )
        raw_attribution = attribution
        if raw_attribution is None:
            raw_attribution = result.get("attribution")
        if isinstance(raw_attribution, dict):
            dimensions = AttributionContext.from_values(
                tenant=raw_attribution.get("tenant"),
                workspace=raw_attribution.get("workspace"),
                app=raw_attribution.get("app"),
                user=raw_attribution.get("user"),
                cost_center=raw_attribution.get("cost_center"),
            ).dimensions()
        else:
            context = current_attribution() or AttributionContext()
            dimensions = context.dimensions()
        entry = {
            "request_id": request_id,
            "timestamp": round(float(time.time()), 6),
            "tenant": tenant if tenant is not None else result.get("tenant"),
            "attribution": dimensions,
            "success": not result.get("error") and not failure_type,
            "failure_type": failure_type,
            "failure_tags": failure_tags,
            "cost_usd": float(cost.get("estimated_cost_usd") or 0.0),
            "latency": latency,
            "guardrail_decisions": guardrail_decisions,
        }
        trace = result.get("observability")
        with self._lock:
            self._runs.append(entry)
            if isinstance(trace, (dict, list)) and request_id:
                self._traces[request_id] = self._redactor.redact_obj(trace)
                self._traces.move_to_end(request_id)
                while len(self._traces) > self.max_traces:
                    self._traces.popitem(last=False)
            if self._store is not None:
                try:
                    self._store.set(f"{self._store_prefix}:run:{request_id}", entry)
                    tr = self._traces.get(request_id)
                    if tr is not None:
                        self._store.set(f"{self._store_prefix}:trace:{request_id}", tr)
                except Exception:
                    pass

    # -- reads ------------------------------------------------------------

    def trace(self, request_id: str, tenant: Optional[str] = None) -> Optional[Any]:
        with self._lock:
            trace = self._traces.get(request_id)
            if (
                trace is not None
                and tenant is not None
                and isinstance(trace, dict)
                and trace.get("tenant") not in (None, tenant)
            ):
                return None
            if trace is None:
                return None
            return dict(trace) if isinstance(trace, dict) else trace

    def run_count(self) -> int:
        with self._lock:
            return len(self._runs)

    def trace_count(self) -> int:
        with self._lock:
            return len(self._traces)

    def _runs_for(self, tenant: Optional[str]) -> List[Dict[str, Any]]:
        with self._lock:
            runs = list(self._runs)
        if tenant is None:
            return runs
        return [entry for entry in runs if entry.get("tenant") == str(tenant)]

    def spend_window(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        runs = self._runs_for(tenant)
        costs = [entry["cost_usd"] for entry in runs]
        total = sum(costs)
        payload: Dict[str, Any] = {
            "window_size": self.max_runs,
            "requests": len(runs),
            "total_cost_usd": round(total, 6),
            "mean_cost_usd": round(total / len(runs), 6) if runs else 0.0,
        }
        if tenant is not None:
            payload["tenant"] = str(tenant)
        return payload

    def attribution_report(
        self,
        window_seconds: Optional[float] = None,
        tenant: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Aggregate spend + request counts by attribution dimension (#50).

        ``window_seconds`` filters on the recorded timestamp; omitted means the
        whole retained history. Dimensions are always present, defaulting to
        ``default`` so single-tenant deployments still produce a report.
        """
        runs = self._runs_for(tenant)
        cutoff: Optional[float] = None
        if window_seconds is not None:
            cutoff = float(now if now is not None else time.time()) - max(
                0.0, float(window_seconds)
            )
            runs = [entry for entry in runs if float(entry.get("timestamp", 0.0)) >= cutoff]

        groups: Dict[str, Dict[str, Dict[str, Any]]] = {
            "by_tenant": {},
            "by_workspace": {},
            "by_app": {},
            "by_user": {},
            "by_cost_center": {},
        }
        keys = {
            "by_tenant": "tenant",
            "by_workspace": "workspace",
            "by_app": "app",
            "by_user": "user",
            "by_cost_center": "cost_center",
        }

        def _bump(bucket: Dict[str, Dict[str, Any]], name: str, entry: Dict[str, Any]) -> None:
            stats = bucket.setdefault(
                name, {"requests": 0, "failures": 0, "cost_usd": 0.0}
            )
            stats["requests"] += 1
            if not entry.get("success", True):
                stats["failures"] += 1
            stats["cost_usd"] += float(entry.get("cost_usd") or 0.0)

        for entry in runs:
            dimensions = entry.get("attribution") or {}
            for group_name, dimension in keys.items():
                value = str(dimensions.get(dimension) or "default")
                _bump(groups[group_name], value, entry)

        for bucket in groups.values():
            for stats in bucket.values():
                stats["cost_usd"] = round(stats["cost_usd"], 6)

        total_cost = round(sum(float(entry.get("cost_usd") or 0.0) for entry in runs), 6)
        payload: Dict[str, Any] = {
            "window_seconds": float(window_seconds) if window_seconds is not None else None,
            "since": round(cutoff, 6) if cutoff is not None else None,
            "total_requests": len(runs),
            "total_cost_usd": total_cost,
            **groups,
        }
        if tenant is not None:
            payload["tenant"] = str(tenant)
        return payload

    def metrics(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        runs = self._runs_for(tenant)

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

        by_guardrail: Dict[str, Dict[str, int]] = {}
        for entry in runs:
            for decision in entry.get("guardrail_decisions") or []:
                counts = by_guardrail.setdefault(
                    decision["guardrail"], {"allow": 0, "redact": 0, "block": 0}
                )
                outcome = decision["decision"]
                counts[outcome] = counts.get(outcome, 0) + 1
        by_decision = {
            name: sum(counts.get(name, 0) for counts in by_guardrail.values())
            for name in ("allow", "redact", "block")
        }

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
            "guardrails": {
                "by_guardrail": {name: by_guardrail[name] for name in sorted(by_guardrail)},
                "by_decision": by_decision,
                "total_decisions": sum(by_decision.values()),
                "total_blocks": by_decision["block"],
            },
            **({"tenant": str(tenant)} if tenant is not None else {}),
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

    def _tenant_scope(request: Request, requested: Optional[str]):
        """Resolve the tenant filter for an ops read (issue #48).

        With tenancy enabled a caller can only read its own tenant; asking for a
        different tenant yields a 403 envelope. Disabled tenancy keeps the legacy
        behavior (no filter unless ``tenant`` is explicitly provided).
        """
        resolver = getattr(request.app.state, "tenants", None)
        caller = getattr(request.state, "tenant_id", None)
        if resolver is not None and getattr(resolver, "enabled", False):
            if requested is not None and str(requested) != str(caller):
                return None, JSONResponse(
                    status_code=403,
                    content=error_envelope(
                        f"Tenant scope '{requested}' is not permitted.",
                        FailureType.FORBIDDEN.value,
                        ["forbidden_tenant_scope"],
                        _request_id(request),
                    ),
                )
            return str(caller) if caller is not None else None, None
        return (str(requested) if requested is not None else None), None

    @application.get("/v1/governance/status", response_model=GovernanceStatusResponse)
    def governance_status(request: Request, tenant: Optional[str] = None):
        history, error = _history(request)
        if error is not None:
            return error
        scope, scope_error = _tenant_scope(request, tenant)
        if scope_error is not None:
            return scope_error
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
            window=history.spend_window(scope),
            request_id=request_id,
        )

    @application.get("/v1/traces/{request_id}")
    def trace_lookup(request: Request, request_id: str, tenant: Optional[str] = None):
        history, error = _history(request)
        if error is not None:
            return error
        scope, scope_error = _tenant_scope(request, tenant)
        if scope_error is not None:
            return scope_error
        trace = history.trace(request_id, tenant=scope)
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

    @application.get("/v1/attribution", response_model=AttributionReportResponse)
    def attribution_endpoint(
        request: Request,
        tenant: Optional[str] = None,
        window_seconds: Optional[float] = None,
    ):
        """Spend + request counts grouped by tenant/app/user over a window (#50)."""
        history, error = _history(request)
        if error is not None:
            return error
        scope, scope_error = _tenant_scope(request, tenant)
        if scope_error is not None:
            return scope_error
        payload = history.attribution_report(
            window_seconds=window_seconds, tenant=scope
        )
        payload["request_id"] = _request_id(request)
        return AttributionReportResponse(**payload)

    @application.get("/v1/metrics", response_model=MetricsResponse)
    def metrics_endpoint(request: Request, tenant: Optional[str] = None):
        history, error = _history(request)
        if error is not None:
            return error
        scope, scope_error = _tenant_scope(request, tenant)
        if scope_error is not None:
            return scope_error
        payload = history.metrics(scope)
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
