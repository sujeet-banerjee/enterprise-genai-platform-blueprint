"""Typed response models for the introspection API (issue #35).

Every endpoint in `app/main.py` declares a `response_model` from this module so
the OpenAPI schema in `/docs` is self-describing.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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
