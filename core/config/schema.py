"""Typed config schemas (issue #46, workstream E2).

Pydantic models for every shipped ``config/*.yaml`` file. The schemas are the
single source of truth for what a valid config looks like:

- **top-level keys are strict** (``extra="forbid"``) so typos are caught at
  validation time with a precise message,
- **nested provider registries are permissive** (``extra="allow"``) because
  provider entries legitimately carry vendor-specific options that the
  registries read directly,
- every field has a default, so a minimal partial config still validates
  (backward compatible with the existing test suite and shipped configs).

A top-level ``config_version`` is optional and defaults to the current schema
version; unknown future values are accepted with a migration note handled by the
validator (see :mod:`core.config.validator`).
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

CURRENT_CONFIG_VERSION = 1


class _StrictModel(BaseModel):
    """Top-level file model: reject unknown keys, allow a version field."""

    model_config = ConfigDict(extra="forbid")

    config_version: Optional[int] = Field(default=None)


class _OpenModel(BaseModel):
    """Per-provider entry: vendor options are open-ended."""

    model_config = ConfigDict(extra="allow")

    provider: Optional[str] = None


# -- models.yaml ---------------------------------------------------------


class ModelEntry(_OpenModel):
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_new_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[List[str]] = None
    input_cost_per_1k: Optional[float] = None
    output_cost_per_1k: Optional[float] = None
    model_name: Optional[str] = None


class EmbeddingModelEntry(_OpenModel):
    model_name: Optional[str] = None
    dimension: Optional[int] = None


class ModelsConfig(_StrictModel):
    active_model: Optional[str] = None
    active_embedding_model: Optional[str] = None
    models: Dict[str, ModelEntry] = Field(default_factory=dict)
    embedding_models: Dict[str, Union[EmbeddingModelEntry, str]] = Field(default_factory=dict)


# -- prompt_config.yaml --------------------------------------------------


class PromptProfile(_OpenModel):
    system_prompt: Optional[str] = None
    context_separator: Optional[str] = None
    empty_context_message: Optional[str] = None
    template: Optional[str] = None


class PromptConfig(_StrictModel):
    active_prompt_profile: Optional[str] = None
    profiles: Dict[str, PromptProfile] = Field(default_factory=dict)


# -- retrieval.yaml ------------------------------------------------------


class RetrieverEntry(_OpenModel):
    documents_path: Optional[str] = None
    graph_path: Optional[str] = None
    expansion_hops: Optional[int] = None
    keyword_weight: Optional[float] = None
    vector_weight: Optional[float] = None


class RerankerEntry(_OpenModel):
    model_name: Optional[str] = None
    top_k: Optional[int] = None


class EvaluatorEntry(_OpenModel):
    model_name: Optional[str] = None
    max_new_tokens: Optional[int] = None
    top_k: Optional[int] = None


class RetrievalSection(_StrictModel):
    default_retriever: Optional[str] = None
    top_k: Optional[int] = None
    similarity_metric: Optional[str] = None
    low_score_threshold: Optional[float] = None
    avg_chunk_tokens: Optional[int] = None
    retrievers: Dict[str, RetrieverEntry] = Field(default_factory=dict)


class EvaluationSection(_StrictModel):
    enabled: Optional[bool] = None
    active_evaluator: Optional[str] = None
    evaluators: Dict[str, EvaluatorEntry] = Field(default_factory=dict)


class RerankingSection(_StrictModel):
    enabled: Optional[bool] = None
    strategy: Optional[str] = None
    lexical_weight: Optional[float] = None
    initial_score_weight: Optional[float] = None
    top_k: Optional[int] = None
    active_reranker: Optional[str] = None
    rerankers: Dict[str, RerankerEntry] = Field(default_factory=dict)


class QueryExpansionSection(_StrictModel):
    enabled: Optional[bool] = None
    active_expander: Optional[str] = None
    max_variants: Optional[int] = None
    expanders: Dict[str, _OpenModel] = Field(default_factory=dict)


class ChunkingStrategy(_OpenModel):
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    separator: Optional[str] = None


class ChunkingSection(_StrictModel):
    enabled: Optional[bool] = None
    active_strategy: Optional[str] = None
    strategies: Dict[str, ChunkingStrategy] = Field(default_factory=dict)


class TokenBudgetSection(_StrictModel):
    default_mode: Optional[str] = None
    max_output_cap: Optional[int] = None
    min_output_tokens: Optional[int] = None
    chars_per_token: Optional[Union[int, float]] = None


class CacheSection(_StrictModel):
    enabled: Optional[bool] = None
    max_entries: Optional[int] = None
    ttl_seconds: Optional[float] = None


class GuardrailsSection(_StrictModel):
    max_query_chars: Optional[int] = None


class RetrievalConfig(_StrictModel):
    retrieval: Optional[RetrievalSection] = None
    evaluation: Optional[EvaluationSection] = None
    reranking: Optional[RerankingSection] = None
    query_expansion: Optional[QueryExpansionSection] = None
    chunking: Optional[ChunkingSection] = None
    token_budget: Optional[TokenBudgetSection] = None
    cache: Optional[CacheSection] = None
    guardrails: Optional[GuardrailsSection] = None
    # Legacy inline sections kept for backward compatibility (issue #34).
    governance: Optional["GovernanceConfig"] = None
    observability: Optional["ObservabilityConfig"] = None


# -- governance.yaml -----------------------------------------------------


class GovernanceConfig(_StrictModel):
    enabled: Optional[bool] = None
    max_cost_per_request_usd: Optional[float] = None
    safety_margin_tokens: Optional[int] = None
    avg_chunk_tokens: Optional[int] = None


# -- observability.yaml --------------------------------------------------


class OtelSection(_StrictModel):
    enabled: Optional[bool] = None
    endpoint: Optional[str] = None
    service_name: Optional[str] = None
    sample_ratio: Optional[float] = None


class PiiSection(_StrictModel):
    """PII / DLP scrubbing policy (issue #54)."""

    enabled: Optional[bool] = None
    classes: Optional[List[str]] = None
    mode: Optional[str] = None
    mask: Optional[str] = None
    ner: Optional[Dict[str, Any]] = None
    national_id_patterns: Optional[List[str]] = None
    extra_patterns: Optional[Dict[str, List[str]]] = None


class ObservabilityConfig(_StrictModel):
    log_level: Optional[str] = None
    redact_sensitive_data: Optional[bool] = None
    low_retrieval_score_threshold: Optional[float] = None
    sensitive_patterns: Optional[List[str]] = None
    otel: Optional[OtelSection] = None
    pii: Optional[PiiSection] = None


# -- api.yaml ------------------------------------------------------------


class ApiConfig(_StrictModel):
    require_api_key: Optional[bool] = None
    api_key: Optional[str] = None
    allow_rebuild: Optional[bool] = None
    history_max_runs: Optional[int] = None
    trace_store_max: Optional[int] = None
    max_batch_size: Optional[int] = None
    batch_max_workers: Optional[int] = None


# -- audit.yaml ----------------------------------------------------------


class AuditConfig(_StrictModel):
    enabled: Optional[bool] = None
    path: Optional[str] = None
    max_entries: Optional[int] = None


# -- access_control.yaml -------------------------------------------------


class RoleEntry(_OpenModel):
    capabilities: Optional[List[str]] = None
    top_k_max: Optional[int] = None
    allowed_models: Optional[List[str]] = None


class AccessControlConfig(_StrictModel):
    enabled: Optional[bool] = None
    default_role: Optional[str] = None
    roles: Dict[str, RoleEntry] = Field(default_factory=dict)
    api_keys: Dict[str, str] = Field(default_factory=dict)


# -- tenants.yaml --------------------------------------------------------


class TenantEntry(_OpenModel):
    workspace: Optional[str] = None
    app: Optional[str] = None
    cost_center: Optional[str] = None
    budget_cap_usd: Optional[float] = None
    top_k_max: Optional[int] = None
    allowed_models: Optional[List[str]] = None
    overrides: Dict[str, Any] = Field(default_factory=dict)


class TenantsConfig(_StrictModel):
    enabled: Optional[bool] = None
    default_tenant: Optional[str] = None
    tenants: Dict[str, TenantEntry] = Field(default_factory=dict)
    api_keys: Dict[str, str] = Field(default_factory=dict)


# -- resilience.yaml -----------------------------------------------------


class ResilienceSection(_StrictModel):
    enabled: Optional[bool] = None
    max_attempts: Optional[int] = None
    backoff_initial_ms: Optional[float] = None
    backoff_max_ms: Optional[float] = None
    jitter: Optional[bool] = None
    breaker_threshold: Optional[int] = None
    breaker_reset_ms: Optional[float] = None
    fallback_models: Optional[List[str]] = None
    fallback_embedders: Optional[List[str]] = None


class ResilienceConfig(_StrictModel):
    resilience: Optional[ResilienceSection] = None


# -- guardrails.yaml -----------------------------------------------------


class GuardrailEntry(_OpenModel):
    """A single ordered guardrail entry; options are provider-specific."""

    stage: Optional[str] = None


class GuardrailsConfig(_StrictModel):
    enabled: Optional[bool] = None
    #: Named preset declared under ``profiles`` (issue #88); ``none`` = explicit chains only.
    profile: Optional[str] = None
    profiles: Dict[str, Any] = Field(default_factory=dict)
    input: List[Union[GuardrailEntry, str]] = Field(default_factory=list)
    output: List[Union[GuardrailEntry, str]] = Field(default_factory=list)


RetrievalConfig.model_rebuild()


# -- identity.yaml -------------------------------------------------------


class IdentityScimSection(_StrictModel):
    enabled: Optional[bool] = None
    tokens: List[str] = Field(default_factory=list)


class IdentitySamlSection(_StrictModel):
    enabled: Optional[bool] = None
    entity_id: Optional[str] = None
    metadata_url: Optional[str] = None


class IdentityConfig(_StrictModel):
    enabled: Optional[bool] = None
    issuer: Optional[str] = None
    jwks_uri: Optional[str] = None
    audience: Optional[str] = None
    algorithms: List[str] = Field(default_factory=list)
    secret: Optional[str] = None
    leeway_seconds: Optional[int] = None
    group_claim: Optional[str] = None
    role_claim: Optional[str] = None
    tenant_claim: Optional[str] = None
    cost_center_claim: Optional[str] = None
    group_role_map: Dict[str, str] = Field(default_factory=dict)
    default_role: Optional[str] = None
    allow_anonymous: Optional[bool] = None
    allow_api_keys: Optional[bool] = None
    scim: Optional[IdentityScimSection] = None
    saml: Optional[IdentitySamlSection] = None


# -- attribution.yaml ----------------------------------------------------


class AttributionConfig(_StrictModel):
    enabled: Optional[bool] = None
    include_user: Optional[bool] = None
    include_cost_center: Optional[bool] = None
    default_dimension: Optional[str] = None


# -- acl.yaml ------------------------------------------------------------


class AclConfig(_StrictModel):
    enabled: Optional[bool] = None
    default_policy: Optional[str] = None
    overfetch_factor: Optional[int] = None
    bypass_roles: List[str] = Field(default_factory=list)



#: Map of config file stem -> (schema, human label).
SCHEMAS: Dict[str, Any] = {
    "models": ModelsConfig,
    "prompt_config": PromptConfig,
    "retrieval": RetrievalConfig,
    "governance": GovernanceConfig,
    "observability": ObservabilityConfig,
    "api": ApiConfig,
    "audit": AuditConfig,
    "access_control": AccessControlConfig,
    "resilience": ResilienceConfig,
    "guardrails": GuardrailsConfig,
    "tenants": TenantsConfig,
    "identity": IdentityConfig,
    "attribution": AttributionConfig,
    "acl": AclConfig,
}
