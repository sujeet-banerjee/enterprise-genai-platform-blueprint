import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.audit_api import register_audit_routes
from app.evaluation_api import EvaluationService, register_evaluation_routes
from app.introspection import IntrospectionService
from app.ops_api import RunHistory, register_ops_routes
from app.pipeline import RAGPipeline
from app.schemas import (
    AccessResponse,
    EffectiveConfigResponse,
    EmbeddingModelsResponse,
    EvaluatorsResponse,
    ModelsResponse,
    RerankersResponse,
    RetrieversResponse,
)
from app.whatif_api import PipelineRebuildService, describe_pipeline, register_whatif_routes
from core.config.generation_config import GenerationConfig
from core.config.schema import SCHEMAS
from core.config.validator import load_and_validate, resolve_config_file
from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.model_registry import ModelRegistry
from core.registry.query_expander_registry import QueryExpanderRegistry
from core.registry.reranker_registry import RerankerRegistry
from core.registry.retriever_registry import RetrieverRegistry
from core.services.access_control import AccessController
from core.services.audit_log import AuditLogger
from core.services.cost_governor import CostGovernor
from core.services.cost_tracker import CostTracker
from core.services.failure_classifier import FailureType
from core.services.prompt_builder import PromptBuilder
from core.services.resilience import build_resilient_embedder, build_resilient_llm
from core.services.retrieval_policy_service import RetrievalPolicyService
from core.services.telemetry import PrometheusCollector
from core.services.token_budget_service import TokenBudgetService

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"
MODELS_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"
RETRIEVAL_CONFIG_PATH = BASE_DIR / "config" / "retrieval.yaml"
GOVERNANCE_CONFIG_PATH = BASE_DIR / "config" / "governance.yaml"
OBSERVABILITY_CONFIG_PATH = BASE_DIR / "config" / "observability.yaml"
API_CONFIG_PATH = BASE_DIR / "config" / "api.yaml"
AUDIT_CONFIG_PATH = BASE_DIR / "config" / "audit.yaml"
ACCESS_CONTROL_CONFIG_PATH = BASE_DIR / "config" / "access_control.yaml"
RESILIENCE_CONFIG_PATH = BASE_DIR / "config" / "resilience.yaml"

# Endpoints that never require an API key (liveness/readiness + OpenAPI docs).
_PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _load_config(config_path: Optional[Path], *, validate: bool = True) -> dict:
    """Load a config file, resolving secret references (issue #46).

    When ``validate`` is true (the default) and the file exists, it is checked
    against its schema first and a hard schema/secret error fails fast with a
    precise message. Missing optional files still yield ``{}`` (backward
    compatible); files whose stem has no registered schema load leniently.
    """
    if config_path is None:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    if validate and path.stem in SCHEMAS:
        return load_and_validate(path)
    return resolve_config_file(path)


def _validate_startup_configs(*paths: Optional[Path]) -> None:
    """Validate each existing schema-backed config, failing fast on errors.

    ``prompt_config.yaml`` uses the ``prompt_config`` schema; its stem already
    matches. Configs without a registered schema (or missing optional files) are
    skipped. Raises :class:`ConfigValidationError` on the first invalid file.
    """
    from core.config.validator import ConfigValidationError, validate_config_file

    for path in paths:
        if path is None:
            continue
        candidate = Path(path)
        if not candidate.exists() or candidate.stem not in SCHEMAS:
            continue
        issues = [i for i in validate_config_file(candidate) if i.kind != "version-warning"]
        if issues:
            raise ConfigValidationError(candidate, issues)


def _generation_config_from_model(model_cfg: dict) -> GenerationConfig:
    """
    Derive GenerationConfig from the active model's configuration so
    temperature / max_tokens / top_p / stop are tunable via models.yaml
    (issue #12). ``max_new_tokens`` (HuggingFace naming) is honored as a
    fallback for ``max_tokens``. Defaults match GenerationConfig's own.
    """
    max_tokens = int(model_cfg.get("max_tokens") or model_cfg.get("max_new_tokens") or 256)
    return GenerationConfig(
        temperature=float(model_cfg.get("temperature", 0.7)),
        top_p=float(model_cfg.get("top_p", 0.9)),
        max_tokens=max_tokens,
        stop=model_cfg.get("stop"),
    )


def build_pipeline(
    models_config_path: Path = MODELS_CONFIG_PATH,
    prompt_config_path: Path = PROMPT_CONFIG_PATH,
    retrieval_config_path: Path = RETRIEVAL_CONFIG_PATH,
    governance_config_path: Optional[Path] = None,
    observability_config_path: Optional[Path] = None,
    resilience_config_path: Optional[Path] = None,
) -> RAGPipeline:
    """
    Composition root: assemble the RAG pipeline by resolving every pluggable
    component from configuration. Embedder/LLM come from ModelRegistry, the
    retriever from RetrieverRegistry, the reranker from RerankerRegistry and the
    evaluator from EvaluatorRegistry — so swapping vendors is a config change and
    this module never imports a concrete implementation.
    """
    model_registry = ModelRegistry(str(models_config_path))
    retriever_registry = RetrieverRegistry(str(retrieval_config_path))
    reranker_registry = RerankerRegistry(str(retrieval_config_path))
    evaluator_registry = EvaluatorRegistry(str(retrieval_config_path))
    query_expander_registry = QueryExpanderRegistry(str(retrieval_config_path))

    # Fail fast on invalid configuration (issue #46): validate every primary
    # config against its schema and resolve secret references before building
    # any component, so a typo or missing secret stops start-up with a precise
    # message instead of surfacing late (or silently).
    _validate_startup_configs(
        models_config_path,
        prompt_config_path,
        retrieval_config_path,
        governance_config_path,
        observability_config_path,
        resilience_config_path,
    )

    retrieval_config = _load_config(retrieval_config_path)
    # Governance lives in its own file (issue #34); fall back to the legacy
    # inline section in retrieval.yaml when no dedicated file is configured.
    governance_config = _load_config(governance_config_path) if governance_config_path else {}
    if not governance_config:
        governance_config = retrieval_config.get("governance") or {}

    active_llm = model_registry.get_active_model()
    embedder = model_registry.get_active_embedder()

    # Provider resilience (issue #45): retries + circuit breaker + failover,
    # applied as wrappers so concrete providers stay untouched. Off by default;
    # with resilience disabled the wrappers are transparent pass-throughs.
    resilience_config = (_load_config(resilience_config_path) or {}).get("resilience") or {}
    if resilience_config.get("enabled", False):
        fallback_models = [
            str(name) for name in (resilience_config.get("fallback_models") or [])
        ]
        llm_chain = [active_llm] + [
            model_registry.get_model(name) for name in fallback_models
        ]
        active_llm = build_resilient_llm(llm_chain, resilience_config)
        embedder = build_resilient_embedder(embedder, resilience_config)

    retriever = retriever_registry.create(embedder=embedder)
    reranker = reranker_registry.create()
    evaluator = evaluator_registry.create()
    # Query expansion is opt-in (query_expansion.enabled). The LLM provider gets
    # the active model injected so it never loads a second copy (issue #23).
    query_expander = query_expander_registry.create(llm=active_llm)

    # Optional response cache (issue #26); off by default. The namespace ties
    # entries to the active component identities so a rebuild can't serve stale
    # answers from a different model/retriever.
    cache = None
    cache_cfg = retrieval_config.get("cache") or {}
    if bool(cache_cfg.get("enabled", False)):
        from core.services.response_cache import ResponseCache

        cache = ResponseCache(
            enabled=True,
            max_entries=int(cache_cfg.get("max_entries", 128)),
            ttl_seconds=cache_cfg.get("ttl_seconds", 300.0),
            namespace=f"{getattr(active_llm, 'model_name', 'llm')}|"
            f"{type(retriever).__name__}|"
            f"{getattr(embedder, 'model_name', 'embedder')}",
        )

    prompt_builder = PromptBuilder(str(prompt_config_path))
    active_model_config = model_registry.get_active_model_config()
    generation_config = _generation_config_from_model(active_model_config)
    token_budget_service = TokenBudgetService(config_path=str(retrieval_config_path))

    # Per-model pricing from models.yaml: the active model's rates are passed
    # explicitly and a keyed map covers models whose model_name differs from
    # their config key (issue #14).
    model_pricing: dict = {}
    for _name, _cfg in (model_registry.config.get("models") or {}).items():
        _cfg = _cfg or {}
        if "input_cost_per_1k" in _cfg or "output_cost_per_1k" in _cfg:
            _entry = {
                "input_cost_per_1k": _cfg.get("input_cost_per_1k"),
                "output_cost_per_1k": _cfg.get("output_cost_per_1k"),
            }
            model_pricing[_name] = _entry
            model_pricing.setdefault(str(_cfg.get("model_name", _name)), _entry)
    cost_tracker = CostTracker(
        input_cost_per_1k=active_model_config.get("input_cost_per_1k"),
        output_cost_per_1k=active_model_config.get("output_cost_per_1k"),
        model_pricing=model_pricing,
    )

    # Governance services wired into the composition root so every request is cost- and
    # token-governed. Both are optional in RAGPipeline, so the pipeline stays vendor-neutral.
    # ``governance.enabled`` gates whether they are attached at all (default: enabled).
    governance_enabled = bool(governance_config.get("enabled", True))
    if governance_enabled:
        cost_governor = CostGovernor(
            max_cost_per_request=float(governance_config.get("max_cost_per_request_usd", 1.0))
        )
        retrieval_policy_service = RetrievalPolicyService(
            context_window=active_llm.context_window,
            system_prompt_tokens=token_budget_service.estimate_tokens(prompt_builder.system_prompt),
            reserved_output_tokens=generation_config.max_tokens,
            safety_margin=int(governance_config.get("safety_margin_tokens", 200)),
        )
    else:
        cost_governor = None
        retrieval_policy_service = None

    return RAGPipeline(
        embedder=embedder,
        prompt_builder=prompt_builder,
        retriever=retriever,
        llm=active_llm,
        evaluator=evaluator,
        token_budget_service=token_budget_service,
        generation_config=generation_config,
        cost_tracker=cost_tracker,
        reranker=reranker,
        config_path=str(retrieval_config_path),
        cost_governor=cost_governor,
        retrieval_policy_service=retrieval_policy_service,
        governance_config_path=str(governance_config_path) if governance_config_path else None,
        observability_config_path=(
            str(observability_config_path) if observability_config_path else None
        ),
        query_expander=query_expander,
        cache=cache,
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

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.pipeline = pipeline_builder(
            models_config_path=models_config_path,
            prompt_config_path=prompt_config_path,
            retrieval_config_path=retrieval_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            resilience_config_path=resilience_config_path,
        )
        application.state.introspect = IntrospectionService(
            models_config_path=models_config_path,
            retrieval_config_path=retrieval_config_path,
            prompt_config_path=prompt_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
            api_config_path=api_config_path,
        )
        application.state.evaluate = EvaluationService(
            models_config_path=models_config_path,
            prompt_config_path=prompt_config_path,
            retrieval_config_path=retrieval_config_path,
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

    def _record_query_audit(request: Request, request_id: str, result: dict) -> None:
        """Emit governance/policy audit events for a completed query (issue #28).

        Cost-governance rejections and retrieval-policy degradation are recorded
        with their failure taxonomy; successful governance-neutral queries are
        not, to keep the trail focused on decisions rather than every request.
        """
        audit = getattr(request.app.state, "audit", None)
        if audit is None or not getattr(audit, "enabled", False):
            return
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
        effective_top_k = payload.top_k
        role_top_k_max = getattr(request.state, "top_k_max", None)
        if role_top_k_max is not None:
            effective_top_k = (
                role_top_k_max
                if effective_top_k is None
                else min(effective_top_k, role_top_k_max)
            )
        try:
            result = pipeline.run(
                payload.query,
                top_k=effective_top_k,
                raise_on_failure=False,
                request_id=request_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return (
                _error_envelope(str(exc), "unknown_failure", [], request_id),
                500,
            )

        history = getattr(request.app.state, "history", None)
        if history is not None:
            history.record(request_id, result)

        telemetry = getattr(request.app.state, "telemetry", None)
        if telemetry is not None:
            telemetry.record(result)

        _record_query_audit(request, request_id, result)

        payload_dict = dict(result)
        payload_dict.setdefault("error", None)
        payload_dict.setdefault("failure_type", None)
        payload_dict["request_id"] = request_id
        if not payload.include_trace:
            payload_dict.pop("observability", None)

        if payload_dict.get("error"):
            status_code = 402 if payload_dict.get("failure_type") == "cost_limit_exceeded" else 500
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
        return AccessResponse(
            enabled=access_controller.enabled,
            role=info["role"],
            capabilities=info["capabilities"],
            top_k_max=info["top_k_max"],
            allowed_models=info["allowed_models"],
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

    register_evaluation_routes(application, _error_envelope)
    register_whatif_routes(application, _error_envelope)
    register_ops_routes(application, _error_envelope)
    register_audit_routes(application, _error_envelope)

    return application


app = create_app()
