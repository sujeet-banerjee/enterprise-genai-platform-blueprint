import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.audit_api import register_audit_routes
from app.bootstrap import (
    assemble_components,
    generation_config_from_model,
    load_config,
    validate_startup_configs,
)
from app.evaluation_api import EvaluationService, register_evaluation_routes
from app.introspection import IntrospectionService
from app.ops_api import RunHistory, register_ops_routes
from app.pipeline import RAGPipeline
from app.schemas import (
    AccessResponse,
    EffectiveConfigResponse,
    EmbeddingModelsResponse,
    EvaluatorsResponse,
    GuardrailsResponse,
    ModelsResponse,
    RerankersResponse,
    RetrieversResponse,
    TenantInfo,
    TenantsResponse,
)
from app.whatif_api import PipelineRebuildService, describe_pipeline, register_whatif_routes
from core.config.generation_config import GenerationConfig
from core.services.access_control import AccessController
from core.services.audit_log import AuditLogger
from core.services.failure_classifier import FailureType
from core.services.telemetry import PrometheusCollector
from core.services.tenancy import TenantResolver, UnknownTenantError

BASE_DIR = Path(__file__).resolve().parent.parent


def _config_dir() -> Path:
    """Resolve the config directory (issue #65 / G0).

    Defaults to ``<repo>/config`` so behaviour is unchanged. Set
    ``GENAI_CONFIG_DIR`` to point at a mounted config directory (e.g. a
    Kubernetes ConfigMap) - this is the seam every deployment mode relies on.
    """
    override = os.environ.get("GENAI_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return BASE_DIR / "config"


CONFIG_DIR = _config_dir()
PROMPT_CONFIG_PATH = CONFIG_DIR / "prompt_config.yaml"
MODELS_CONFIG_PATH = CONFIG_DIR / "models.yaml"
RETRIEVAL_CONFIG_PATH = CONFIG_DIR / "retrieval.yaml"
GOVERNANCE_CONFIG_PATH = CONFIG_DIR / "governance.yaml"
OBSERVABILITY_CONFIG_PATH = CONFIG_DIR / "observability.yaml"
API_CONFIG_PATH = CONFIG_DIR / "api.yaml"
AUDIT_CONFIG_PATH = CONFIG_DIR / "audit.yaml"
ACCESS_CONTROL_CONFIG_PATH = CONFIG_DIR / "access_control.yaml"
RESILIENCE_CONFIG_PATH = CONFIG_DIR / "resilience.yaml"
GUARDRAILS_CONFIG_PATH = CONFIG_DIR / "guardrails.yaml"
TENANTS_CONFIG_PATH = CONFIG_DIR / "tenants.yaml"

# Endpoints that never require an API key (liveness/readiness + OpenAPI docs).
_PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _load_config(config_path: Optional[Path], *, validate: bool = True) -> dict:
    """Load a config file, resolving secret references (issue #46).

    Thin alias for :func:`app.bootstrap.load_config` (kept for backward
    compatibility with existing importers).
    """
    return load_config(config_path, validate=validate)


def _validate_startup_configs(*paths: Optional[Path]) -> None:
    """Alias for :func:`app.bootstrap.validate_startup_configs` (issue #46)."""
    validate_startup_configs(*paths)


def _generation_config_from_model(model_cfg: dict) -> GenerationConfig:
    """Alias for :func:`app.bootstrap.generation_config_from_model` (issue #12)."""
    return generation_config_from_model(model_cfg)


def build_pipeline(
    models_config_path: Path = MODELS_CONFIG_PATH,
    prompt_config_path: Path = PROMPT_CONFIG_PATH,
    retrieval_config_path: Path = RETRIEVAL_CONFIG_PATH,
    governance_config_path: Optional[Path] = None,
    observability_config_path: Optional[Path] = None,
    resilience_config_path: Optional[Path] = None,
    guardrails_config_path: Optional[Path] = None,
) -> RAGPipeline:
    """
    Composition root: assemble the RAG pipeline by resolving every pluggable
    component from configuration.

    The actual assembly lives in :func:`app.bootstrap.assemble_components` so the
    experiment runner (issue #75) shares the exact same wiring; this function is
    a thin wrapper that also injects the config paths into the pipeline.
    """
    components = assemble_components(
        models_config_path=models_config_path,
        prompt_config_path=prompt_config_path,
        retrieval_config_path=retrieval_config_path,
        governance_config_path=governance_config_path,
        observability_config_path=observability_config_path,
        resilience_config_path=resilience_config_path,
        guardrails_config_path=guardrails_config_path,
    )
    return components.build_pipeline(
        config_path=str(retrieval_config_path),
        governance_config_path=str(governance_config_path) if governance_config_path else None,
        observability_config_path=(
            str(observability_config_path) if observability_config_path else None
        ),
        max_query_chars=components.max_query_chars,
    )


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user query to run through the RAG pipeline.")
    top_k: Optional[int] = Field(None, ge=1, description="Override the number of retrieved documents.")
    include_trace: bool = Field(
        True, description="Include the redacted observability trace in the response."
    )


class BatchQueryRequest(BaseModel):
    queries: list[str] = Field(
        ...,
        min_length=1,
        description="Queries to run through the RAG pipeline (sequential or parallel).",
    )
    top_k: Optional[int] = Field(None, ge=1, description="Override the number of retrieved documents.")
    include_trace: bool = Field(
        True, description="Include the redacted observability trace in each result."
    )
    parallel: bool = Field(
        False,
        description="Run queries concurrently through a thread pool (issue #27). "
        "Results always preserve input order.",
    )
    max_workers: Optional[int] = Field(
        None,
        ge=1,
        description="Concurrency for parallel batches; capped by api.batch_max_workers.",
    )


def _error_envelope(
    error: str,
    failure_type: Optional[str],
    failure_tags: list,
    request_id: str,
) -> dict:
    return {
        "error": error,
        "failure_type": failure_type or "unknown_failure",
        "failure_tags": list(failure_tags or []),
        "request_id": request_id,
    }


def _record_pii_audit(
    audit: Any, request_id: str, result: dict, tenant: Optional[str] = None
) -> None:
    """Record PII / DLP decisions in the audit trail (issue #54).

    Only the **class** and a **count** are stored - the matched value never
    reaches the audit trail, the trace or the response body.
    """
    decisions = result.get("guardrail_decisions") or []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        if decision.get("guardrail") != "pii":
            continue
        outcome = str(decision.get("decision") or "")
        if outcome not in ("redact", "block"):
            continue
        details = decision.get("details") or {}
        counts = details.get("classes") if isinstance(details, dict) else None
        counts = counts if isinstance(counts, dict) else {}
        audit.record(
            "pii",
            "detect",
            "redacted" if outcome == "redact" else "blocked",
            details={
                "classes": sorted(str(name) for name in counts),
                "counts": {str(name): int(value) for name, value in counts.items()},
                "total": int(details.get("total") or 0) if isinstance(details, dict) else 0,
            },
            request_id=request_id,
            tenant=tenant,
        )


def create_app(
    models_config_path: Path = MODELS_CONFIG_PATH,
    prompt_config_path: Path = PROMPT_CONFIG_PATH,
    retrieval_config_path: Path = RETRIEVAL_CONFIG_PATH,
    governance_config_path: Path = GOVERNANCE_CONFIG_PATH,
    observability_config_path: Path = OBSERVABILITY_CONFIG_PATH,
    api_config_path: Path = API_CONFIG_PATH,
    audit_config_path: Path = AUDIT_CONFIG_PATH,
    access_control_config_path: Path = ACCESS_CONTROL_CONFIG_PATH,
    resilience_config_path: Path = RESILIENCE_CONFIG_PATH,
    guardrails_config_path: Path = GUARDRAILS_CONFIG_PATH,
    tenants_config_path: Path = TENANTS_CONFIG_PATH,
    pipeline_builder: Callable[..., RAGPipeline] = build_pipeline,
) -> FastAPI:
    """
    FastAPI application factory (issue #30).

    The pipeline is built in the lifespan startup hook rather than at import
    time, so a failed model load fails the container loudly and importing this
    module stays side-effect free. ``pipeline_builder`` is injectable so tests
    can supply a lightweight pipeline.
    """
    api_config = _load_config(api_config_path)
    require_api_key = bool(api_config.get("require_api_key", False))
    expected_api_key = str(api_config.get("api_key") or "")
    allow_rebuild = bool(api_config.get("allow_rebuild", False))
    max_batch_size = int(api_config.get("max_batch_size", 25))
    batch_max_workers = int(api_config.get("batch_max_workers", 4))

    access_config = _load_config(access_control_config_path) or {}
    access_controller = AccessController.from_config(access_config)
    # Tenant / workspace model (issue #48): off by default -> implicit default.
    tenant_resolver = TenantResolver.from_config(_load_config(tenants_config_path) or {})

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.pipeline = pipeline_builder(
            models_config_path=models_config_path,
            prompt_config_path=prompt_config_path,
            retrieval_config_path=retrieval_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            resilience_config_path=resilience_config_path,
            guardrails_config_path=guardrails_config_path,
        )
        application.state.introspect = IntrospectionService(
            models_config_path=models_config_path,
            retrieval_config_path=retrieval_config_path,
            prompt_config_path=prompt_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            api_config_path=api_config_path,
            guardrails_config_path=guardrails_config_path,
            tenants_config_path=tenants_config_path,
        )
        application.state.evaluate = EvaluationService(
            models_config_path=models_config_path,
            prompt_config_path=prompt_config_path,
            retrieval_config_path=retrieval_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            resilience_config_path=resilience_config_path,
            guardrails_config_path=guardrails_config_path,
        )
        application.state.history = RunHistory(
            max_runs=int(api_config.get("history_max_runs", 1000)),
            max_traces=int(api_config.get("trace_store_max", 500)),
            observability_config_path=observability_config_path,
        )
        # Prometheus collector (issue #44): optional dependency; a no-op when
        # prometheus-client is not installed.
        application.state.telemetry = PrometheusCollector()
        # Audit log (issue #28): structured, append-only, off by default. It
        # reuses the history redactor so the trail never stores secrets.
        audit_config = _load_config(audit_config_path) or {}
        application.state.audit = AuditLogger.from_config(
            audit_config, redactor=application.state.history.redactor
        )
        audit_logger = application.state.audit
        audit_logger.record(
            "config", "startup", "success", details={"config_revision": 0}
        )
        application.state.config_revision = 0
        application.state.rebuild = PipelineRebuildService(
            pipeline_builder=pipeline_builder,
            base_paths={
                "models_config_path": models_config_path,
                "prompt_config_path": prompt_config_path,
                "retrieval_config_path": retrieval_config_path,
                "governance_config_path": governance_config_path,
                "observability_config_path": observability_config_path,
                "api_config_path": api_config_path,
                "resilience_config_path": resilience_config_path,
                "guardrails_config_path": guardrails_config_path,
            },
            allow_rebuild=allow_rebuild,
        )
        application.state.ready = True
        try:
            yield
        finally:
            application.state.ready = False
            evaluation_service = getattr(application.state, "evaluate", None)
            if evaluation_service is not None:
                evaluation_service.shutdown()
            rebuild_service = getattr(application.state, "rebuild", None)
            if rebuild_service is not None:
                rebuild_service.cleanup()
            audit_logger = getattr(application.state, "audit", None)
            if audit_logger is not None:
                audit_logger.close()

    application = FastAPI(
        title="Enterprise GenAI RAG Platform",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.tenants = tenant_resolver
    application.state.access = access_controller

    def _path_capability(path: str) -> Optional[str]:
        """Map a request path to the capability required to access it (issue #29).

        Returns ``None`` for public/unmapped paths (no capability required).
        """
        if path in _PUBLIC_PATHS:
            return None
        if path in ("/query", "/v1/query"):
            return "query"
        if path == "/v1/query:batch":
            return "batch"
        if path == "/v1/evaluate":
            return "evaluate"
        if path == "/v1/experiments" or path.startswith("/v1/experiments/"):
            return "experiment"
        if path == "/v1/pipeline:rebuild":
            return "rebuild"
        if path == "/v1/audit":
            return "audit"
        if path in (
            "/v1/governance/status",
            "/v1/metrics",
        ) or path.startswith("/v1/traces/"):
            return "governance"
        if path in (
            "/v1/access",
            "/v1/config",
            "/v1/models",
            "/v1/embedding-models",
            "/v1/retrievers",
            "/v1/rerankers",
            "/v1/evaluators",
            "/v1/guardrails",
            "/v1/tenants",
        ):
            return "introspect"
        return None

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        provided_key = request.headers.get("X-API-Key")

        if (
            require_api_key
            and expected_api_key
            and request.url.path not in _PUBLIC_PATHS
            and provided_key != expected_api_key
        ):
            return JSONResponse(
                status_code=401,
                content=_error_envelope(
                    "Missing or invalid API key.",
                    FailureType.UNAUTHORIZED.value,
                    [],
                    request_id,
                ),
                headers={"X-Request-ID": request_id},
            )

        # RBAC / persona resolution (issue #29).
        role = access_controller.resolve_role(provided_key)
        request.state.role = role
        request.state.capabilities = access_controller.capabilities(role)
        request.state.top_k_max = access_controller.top_k_max(role)
        request.state.allowed_models = access_controller.allowed_models(role)

        # Tenant resolution (issue #48): header wins over the API-key mapping.
        # An unknown explicit tenant is rejected rather than silently falling
        # back, so a caller can never read another tenant's cached/history data.
        try:
            tenant = tenant_resolver.resolve(
                tenant_header=request.headers.get("X-Tenant-ID"),
                api_key=provided_key,
            )
        except UnknownTenantError as exc:
            return JSONResponse(
                status_code=400,
                content=_error_envelope(
                    str(exc),
                    FailureType.UNKNOWN_TENANT.value,
                    ["unknown_tenant"],
                    request_id,
                ),
                headers={"X-Request-ID": request_id},
            )
        request.state.tenant = tenant
        request.state.tenant_id = tenant.id

        required = _path_capability(request.url.path)
        if required is not None and not access_controller.has_capability(role, required):
            return JSONResponse(
                status_code=403,
                content=_error_envelope(
                    f"Role '{role}' is not permitted to perform '{required}'.",
                    FailureType.FORBIDDEN.value,
                    [f"forbidden_{required}"],
                    request_id,
                ),
                headers={"X-Request-ID": request_id},
            )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def _record_query_audit(
        request: Request, request_id: str, result: dict, tenant: Optional[str] = None
    ) -> None:
        """Emit governance/policy audit events for a completed query (issue #28).

        Cost-governance rejections and retrieval-policy degradation are recorded
        with their failure taxonomy; successful governance-neutral queries are
        not, to keep the trail focused on decisions rather than every request.

        PII / DLP decisions (issue #54) are always recorded - both redaction and
        block - because "personal data left the system" is exactly the kind of
        event an auditor looks for. Only the **class** and a **count** are
        stored; the matched value never reaches the audit trail.
        """
        audit = getattr(request.app.state, "audit", None)
        if audit is None or not getattr(audit, "enabled", False):
            return

        _record_pii_audit(audit, request_id, result, tenant=tenant)

        failure_type = result.get("failure_type")
        failure_tags = list(result.get("failure_tags") or [])
        if not failure_type and not failure_tags:
            return
        cost = result.get("cost") or {}
        audit.record(
            "governance",
            "cost_check",
            "denied" if failure_type else "degraded",
            details={
                "failure_type": failure_type,
                "failure_tags": failure_tags,
                "cost_usd": float(cost.get("estimated_cost_usd") or 0.0),
            },
            request_id=request_id,
            tenant=tenant,
        )

    def _execute_query(
        request: Request,
        payload: QueryRequest,
        request_id: Optional[str] = None,
    ) -> tuple[dict, int]:
        """Run one query and return (result envelope, http status).

        Failures never raise: the caller decides how to present the envelope so
        a batch can keep going after an individual query fails (issue #39).
        """
        request_id = request_id or getattr(request.state, "request_id", None) or str(uuid.uuid4())
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline is None:
            return (
                _error_envelope(
                    "Pipeline is not ready.", FailureType.NOT_READY.value, [], request_id
                ),
                503,
            )
        # RBAC persona cap: clamp retrieval depth to the role's top_k_max (#29).
        role_top_k_max = getattr(request.state, "top_k_max", None)
        tenant = getattr(request.state, "tenant", None)
        tenancy_enabled = bool(getattr(tenant_resolver, "enabled", False))
        tenant_id = getattr(tenant, "id", None) if tenancy_enabled else None
        effective_top_k = payload.top_k
        if effective_top_k is None and tenant_id is not None:
            overlay_top_k = tenant_resolver.overlay(tenant_id, "retrieval").get("top_k")
            if isinstance(overlay_top_k, int):
                effective_top_k = overlay_top_k
        tenant_top_k_max = getattr(tenant, "top_k_max", None) if tenancy_enabled else None
        for cap in (role_top_k_max, tenant_top_k_max):
            if cap is not None:
                effective_top_k = cap if effective_top_k is None else min(effective_top_k, cap)

        history = getattr(request.app.state, "history", None)

        # Per-tenant budget cap (issue #48): how much this tenant has spent in
        # the retained history window. Enforced before spending more.
        budget_cap = getattr(tenant, "budget_cap_usd", None) if tenancy_enabled else None
        if budget_cap is not None and history is not None:
            spent = history.spend_window(tenant_id)["total_cost_usd"]
            if spent >= float(budget_cap):
                envelope = _error_envelope(
                    f"Tenant '{tenant_id}' has reached its budget cap "
                    f"({spent:.6f} >= {float(budget_cap):.6f} USD).",
                    FailureType.COST_LIMIT_EXCEEDED.value,
                    ["tenant_budget_exceeded"],
                    request_id,
                )
                envelope.update(
                    {
                        "tenant": tenant_id,
                        "workspace": getattr(tenant, "workspace", None),
                        "app": getattr(tenant, "app", None),
                    }
                )
                _record_query_audit(request, request_id, envelope, tenant=tenant_id)
                return envelope, 402

        pipeline_kwargs: dict = {}
        if tenancy_enabled:
            pipeline_kwargs = {
                "tenant": tenant_id,
                "workspace": getattr(tenant, "workspace", None),
                "app": getattr(tenant, "app", None),
            }
        try:
            result = pipeline.run(
                payload.query,
                top_k=effective_top_k,
                raise_on_failure=False,
                request_id=request_id,
                **pipeline_kwargs,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return (
                _error_envelope(str(exc), "unknown_failure", [], request_id),
                500,
            )

        if history is not None:
            history.record(request_id, result, tenant=tenant_id)

        telemetry = getattr(request.app.state, "telemetry", None)
        if telemetry is not None:
            telemetry.record(result)

        _record_query_audit(request, request_id, result, tenant=tenant_id)

        payload_dict = dict(result)
        payload_dict.setdefault("error", None)
        payload_dict.setdefault("failure_type", None)
        payload_dict["request_id"] = request_id
        if not payload.include_trace:
            payload_dict.pop("observability", None)

        if payload_dict.get("error"):
            failure_type = payload_dict.get("failure_type")
            if failure_type == FailureType.COST_LIMIT_EXCEEDED.value:
                status_code = 402
            elif failure_type == FailureType.QUERY_TOO_LONG.value:
                status_code = 400
            elif failure_type in (
                FailureType.GUARDRAIL_INPUT_BLOCKED.value,
                FailureType.GUARDRAIL_OUTPUT_BLOCKED.value,
            ):
                status_code = 403
            else:
                status_code = 500
            return payload_dict, status_code
        return payload_dict, 200

    def _run_query(request: Request, payload: QueryRequest) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        body, status_code = _execute_query(request, payload, request_id)
        return JSONResponse(status_code=status_code, content=body)

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/v1/access", response_model=AccessResponse)
    def access_endpoint(request: Request):
        """Report the calling persona's role and effective permissions (#29)."""
        role = getattr(request.state, "role", access_controller.default_role)
        info = access_controller.describe(role)
        tenant = getattr(request.state, "tenant", None)
        return AccessResponse(
            enabled=access_controller.enabled,
            role=info["role"],
            capabilities=info["capabilities"],
            top_k_max=info["top_k_max"],
            allowed_models=info["allowed_models"],
            tenant=(
                TenantInfo(**tenant_resolver.describe(tenant.id))
                if tenant is not None
                else None
            ),
            request_id=getattr(request.state, "request_id", None),
        )

    @application.get("/v1/tenants", response_model=TenantsResponse)
    def tenants_endpoint(request: Request):
        """Introspect tenant configuration and the caller's resolved tenant (#48)."""
        tenant = getattr(request.state, "tenant", None)
        current = TenantInfo(
            **tenant_resolver.describe(tenant.id if tenant is not None else tenant_resolver.default_tenant)
        )
        return TenantsResponse(
            enabled=tenant_resolver.enabled,
            default_tenant=tenant_resolver.default_tenant,
            current=current,
            tenants=[TenantInfo(**item) for item in tenant_resolver.describe_all()],
            request_id=getattr(request.state, "request_id", None),
        )

    @application.get("/ready")
    def ready(request: Request):
        pipeline = getattr(request.app.state, "pipeline", None)
        if getattr(request.app.state, "ready", False) and pipeline is not None:
            return {
                "status": "ready",
                "config_revision": int(getattr(request.app.state, "config_revision", 0)),
                "components": describe_pipeline(pipeline),
            }
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "pipeline not initialised"},
        )

    @application.post("/v1/query")
    def query_v1(request: Request, payload: QueryRequest):
        return _run_query(request, payload)

    @application.post("/query")
    def query_legacy(request: Request, payload: QueryRequest):
        return _run_query(request, payload)

    @application.post("/v1/query:batch")
    def query_batch(request: Request, payload: BatchQueryRequest):
        base_request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())

        if len(payload.queries) > max_batch_size:
            return JSONResponse(
                status_code=400,
                content=_error_envelope(
                    f"Batch size {len(payload.queries)} exceeds max_batch_size {max_batch_size}.",
                    FailureType.BATCH_TOO_LARGE.value,
                    [FailureType.BATCH_TOO_LARGE.value],
                    base_request_id,
                ),
            )

        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline is None:
            return JSONResponse(
                status_code=503,
                content=_error_envelope(
                    "Pipeline is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    base_request_id,
                ),
            )

        results = []
        if payload.parallel and len(payload.queries) > 1:
            # Parallel inference: run all queries through a bounded thread pool,
            # preserving input order (issue #27).
            from concurrent.futures import ThreadPoolExecutor

            workers = min(payload.max_workers or batch_max_workers, len(payload.queries))
            workers = max(1, min(workers, batch_max_workers))

            def _run_one(index: int, query: str):
                item_request = QueryRequest(
                    query=query, top_k=payload.top_k, include_trace=payload.include_trace
                )
                return _execute_query(
                    request, item_request, f"{base_request_id}-{index}"
                )[0]

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_run_one, index, query)
                    for index, query in enumerate(payload.queries)
                ]
                results = [future.result() for future in futures]
        else:
            for index, query in enumerate(payload.queries):
                item_request = QueryRequest(
                    query=query, top_k=payload.top_k, include_trace=payload.include_trace
                )
                body, _status = _execute_query(
                    request, item_request, f"{base_request_id}-{index}"
                )
                results.append(body)

        succeeded = sum(1 for item in results if not item.get("error"))
        by_failure_type: dict = {}
        for item in results:
            failure_type = item.get("failure_type")
            if failure_type:
                by_failure_type[failure_type] = by_failure_type.get(failure_type, 0) + 1

        total_cost = sum(
            float((item.get("cost") or {}).get("estimated_cost_usd") or 0.0)
            for item in results
        )
        total_latency = sum(
            float((item.get("latency") or {}).get("total_ms") or 0.0)
            for item in results
        )

        return JSONResponse(
            status_code=200,
            content={
                "results": results,
                "summary": {
                    "batch_size": len(results),
                    "succeeded": succeeded,
                    "failed": len(results) - succeeded,
                    "by_failure_type": by_failure_type,
                    "total_cost_usd": round(total_cost, 6),
                    "total_latency_ms": round(total_latency, 4),
                },
                "request_id": base_request_id,
            },
        )

    def _introspection(request: Request):
        service = getattr(request.app.state, "introspect", None)
        if service is None:
            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return None, JSONResponse(
                status_code=503,
                content=_error_envelope(
                    "Introspection is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    request_id,
                ),
            )
        return service, None

    @application.get("/v1/config", response_model=EffectiveConfigResponse)
    def config_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return EffectiveConfigResponse(config=service.effective_config())

    @application.get("/v1/models", response_model=ModelsResponse)
    def models_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return ModelsResponse(**service.list_models())

    @application.get("/v1/embedding-models", response_model=EmbeddingModelsResponse)
    def embedding_models_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return EmbeddingModelsResponse(**service.list_embedding_models())

    @application.get("/v1/retrievers", response_model=RetrieversResponse)
    def retrievers_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return RetrieversResponse(**service.list_retrievers())

    @application.get("/v1/rerankers", response_model=RerankersResponse)
    def rerankers_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return RerankersResponse(**service.list_rerankers())

    @application.get("/v1/evaluators", response_model=EvaluatorsResponse)
    def evaluators_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return EvaluatorsResponse(**service.list_evaluators())

    @application.get("/v1/guardrails", response_model=GuardrailsResponse)
    def guardrails_endpoint(request: Request):
        service, error = _introspection(request)
        if error is not None:
            return error
        return GuardrailsResponse(**service.list_guardrails())

    register_evaluation_routes(application, _error_envelope)
    register_whatif_routes(application, _error_envelope)
    register_ops_routes(application, _error_envelope)
    register_audit_routes(application, _error_envelope)

    return application


app = create_app()
