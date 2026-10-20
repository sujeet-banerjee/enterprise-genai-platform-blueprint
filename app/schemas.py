"""Typed response models for the introspection API (issue #35).

Every endpoint in `app/main.py` declares a `response_model` from this module so
the OpenAPI schema in `/docs` is self-describing.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ModelInfo(BaseModel):
    name: str
    active: bool
    provider: Optional[str] = None
    context_window: Optional[int] = None
    input_cost_per_1k: Optional[float] = None
    output_cost_per_1k: Optional[float] = None


class ActiveModelConfig(BaseModel):
    name: str
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    max_new_tokens: Optional[int] = None
    stop: Optional[Any] = None
    input_cost_per_1k: Optional[float] = None
    output_cost_per_1k: Optional[float] = None


class ModelsResponse(BaseModel):
    active: str
    models: List[ModelInfo]
    active_config: ActiveModelConfig


class EmbeddingModelInfo(BaseModel):
    name: str
    active: bool
    provider: Optional[str] = None
    model_name: Optional[str] = None
    dimension: Optional[int] = None


class EmbeddingModelsResponse(BaseModel):
    active: Optional[str] = None
    embedding_models: List[EmbeddingModelInfo]


class RetrieverInfo(BaseModel):
    key: str
    provider: Optional[str] = None
    options: Dict[str, Any] = {}


class RetrieversResponse(BaseModel):
    default_retriever: Optional[str] = None
    similarity_metric: Optional[str] = None
    providers: List[str] = []
    retrievers: List[RetrieverInfo] = []


class RerankerInfo(BaseModel):
    key: str
    provider: Optional[str] = None
    options: Dict[str, Any] = {}


class RerankersResponse(BaseModel):
    enabled: bool = True
    active_reranker: Optional[str] = None
    providers: List[str] = []
    rerankers: List[RerankerInfo] = []


class EvaluatorInfo(BaseModel):
    key: str
    provider: Optional[str] = None
    options: Dict[str, Any] = {}


class EvaluatorsResponse(BaseModel):
    enabled: bool = True
    active_evaluator: Optional[str] = None
    providers: List[str] = []
    evaluators: List[EvaluatorInfo] = []


class EffectiveConfigResponse(BaseModel):
    """Redacted effective configuration."""

    config: Dict[str, Any] = {}


class EvaluateRequest(BaseModel):
    query: str
    response: str
    retrieved_docs: Optional[List[Union[str, Dict[str, Any]]]] = None
    ground_truth: Optional[Union[str, List[str]]] = None
    evaluator: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class EvaluateResponse(BaseModel):
    evaluator: str
    evaluator_key: Optional[str] = None
    metrics: Dict[str, Any] = {}
    ground_truth: Optional[Union[str, List[str]]] = None
    ground_truth_used: bool = False
    num_retrieved_docs: int = 0
    docs_source: str = "request"
    request_id: Optional[str] = None


class ExperimentLaunchRequest(BaseModel):
    kind: Literal["single", "compare_embedding_models", "compare_chunking_strategies"] = "single"
    query: str
    docs: Optional[List[Union[str, Dict[str, Any]]]] = None
    documents_path: Optional[str] = None
    embedding_model: Optional[str] = None
    chunk_strategy: Optional[str] = None
    retriever_backend: Optional[str] = None
    use_reranker: Optional[bool] = None
    top_k: int = Field(default=3, ge=1, le=50)
    strategies: Optional[List[str]] = None
    model_names: Optional[List[str]] = None


class ExperimentLaunchResponse(BaseModel):
    id: str
    kind: str
    status: str
    request_id: Optional[str] = None


class ExperimentStatusResponse(BaseModel):
    id: str
    kind: str
    status: str
    created_at: float
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    failure_type: Optional[str] = None
    request_id: Optional[str] = None


class RebuildOverrides(BaseModel):
    """Candidate configuration deltas for a runtime pipeline rebuild."""

    model_config = ConfigDict(extra="forbid")

    active_model: Optional[str] = None
    active_embedding_model: Optional[str] = None
    default_retriever: Optional[str] = None
    similarity_metric: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class RebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: RebuildOverrides = RebuildOverrides()
    governance: Optional[Dict[str, Any]] = None
    allow_governance_override: bool = False


class RebuildComponents(BaseModel):
    llm: Optional[str] = None
    retriever: Optional[str] = None
    reranker: Optional[str] = None
    evaluator: Optional[str] = None
    query_expander: Optional[str] = None


class RebuildResponse(BaseModel):
    status: str = "rebuilt"
    config_revision: int
    components: RebuildComponents
    applied_overrides: Dict[str, Any] = {}
    governance_overrides_applied: bool = False
    effective_config: Dict[str, Any] = {}
    request_id: Optional[str] = None


class LatencyStat(BaseModel):
    count: int = 0
    mean: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None


class GovernanceStatusResponse(BaseModel):
    enabled: bool = True
    max_cost_per_request_usd: Optional[float] = None
    safety_margin_tokens: Optional[int] = None
    avg_chunk_tokens: Optional[int] = None
    window: Dict[str, Any] = {}
    request_id: Optional[str] = None


class MetricsResponse(BaseModel):
    total_runs: int = 0
    success_count: int = 0
    failure_count: int = 0
    failure_rate: float = 0.0
    latency_ms: Dict[str, LatencyStat] = {}
    total_latency_ms: LatencyStat = LatencyStat()
    failures_by_type: Dict[str, int] = {}
    failures_by_tag: Dict[str, int] = {}
    cost: Dict[str, Any] = {}
    request_id: Optional[str] = None


class AuditEventsResponse(BaseModel):
    enabled: bool = False
    count: int = 0
    total: int = 0
    events: List[Dict[str, Any]] = []
    request_id: Optional[str] = None
