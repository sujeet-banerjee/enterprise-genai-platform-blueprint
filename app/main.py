import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.evaluation_api import EvaluationService, register_evaluation_routes
from app.introspection import IntrospectionService
from app.pipeline import RAGPipeline
from app.schemas import (
    EffectiveConfigResponse,
    EmbeddingModelsResponse,
    EvaluatorsResponse,
    ModelsResponse,
    RerankersResponse,
    RetrieversResponse,
)
from app.whatif_api import PipelineRebuildService, describe_pipeline, register_whatif_routes
from core.config.generation_config import GenerationConfig
from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.model_registry import ModelRegistry
from core.registry.reranker_registry import RerankerRegistry
from core.registry.retriever_registry import RetrieverRegistry
from core.services.cost_governor import CostGovernor
from core.services.cost_tracker import CostTracker
from core.services.prompt_builder import PromptBuilder
from core.services.retrieval_policy_service import RetrievalPolicyService
from core.services.token_budget_service import TokenBudgetService

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_CONFIG_PATH = BASE_DIR / "config" / "prompt_config.yaml"
MODELS_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"
RETRIEVAL_CONFIG_PATH = BASE_DIR / "config" / "retrieval.yaml"
GOVERNANCE_CONFIG_PATH = BASE_DIR / "config" / "governance.yaml"
OBSERVABILITY_CONFIG_PATH = BASE_DIR / "config" / "observability.yaml"
API_CONFIG_PATH = BASE_DIR / "config" / "api.yaml"

# Endpoints that never require an API key (liveness/readiness + OpenAPI docs).
_PUBLIC_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}


def _load_config(config_path: Path) -> dict:
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


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

    retrieval_config = _load_config(retrieval_config_path)
    # Governance lives in its own file (issue #34); fall back to the legacy
    # inline section in retrieval.yaml when no dedicated file is configured.
    governance_config = _load_config(governance_config_path) if governance_config_path else {}
    if not governance_config:
        governance_config = retrieval_config.get("governance") or {}

    active_llm = model_registry.get_active_model()
    embedder = model_registry.get_active_embedder()
    retriever = retriever_registry.create(embedder=embedder)
    reranker = reranker_registry.create()
    evaluator = evaluator_registry.create()

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
    )


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user query to run through the RAG pipeline.")
    top_k: Optional[int] = Field(None, ge=1, description="Override the number of retrieved documents.")
    include_trace: bool = Field(
        True, description="Include the redacted observability trace in the response."
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

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.pipeline = pipeline_builder(
            models_config_path=models_config_path,
            prompt_config_path=prompt_config_path,
            retrieval_config_path=retrieval_config_path,
            governance_config_path=governance_config_path,
            observability_config_path=observability_config_path,
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

    application = FastAPI(
        title="Enterprise GenAI RAG Platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        if (
            require_api_key
            and expected_api_key
            and request.url.path not in _PUBLIC_PATHS
            and request.headers.get("X-API-Key") != expected_api_key
        ):
            return JSONResponse(
                status_code=401,
                content=_error_envelope(
                    "Missing or invalid API key.",
                    "unauthorized",
                    [],
                    request_id,
                ),
                headers={"X-Request-ID": request_id},
            )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    def _run_query(request: Request, payload: QueryRequest) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline is None:
            return JSONResponse(
                status_code=503,
                content=_error_envelope(
                    "Pipeline is not ready.", "not_ready", [], request_id
                ),
            )
        try:
            result = pipeline.run(
                payload.query,
                top_k=payload.top_k,
                raise_on_failure=False,
                request_id=request_id,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return JSONResponse(
                status_code=500,
                content=_error_envelope(str(exc), "unknown_failure", [], request_id),
            )

        payload_dict = dict(result)
        payload_dict.setdefault("error", None)
        payload_dict.setdefault("failure_type", None)
        payload_dict["request_id"] = request_id
        if not payload.include_trace:
            payload_dict.pop("observability", None)

        if payload_dict.get("error"):
            status_code = 500
            if payload_dict.get("failure_type") == "cost_limit_exceeded":
                status_code = 402
            return JSONResponse(status_code=status_code, content=payload_dict)
        return JSONResponse(status_code=200, content=payload_dict)

    @application.get("/health")
    def health():
        return {"status": "ok"}

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

    def _introspection(request: Request):
        service = getattr(request.app.state, "introspect", None)
        if service is None:
            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return None, JSONResponse(
                status_code=503,
                content=_error_envelope(
                    "Introspection is not ready.", "not_ready", [], request_id
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

    return application


app = create_app()
