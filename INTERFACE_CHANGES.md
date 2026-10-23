# Interface Changes (`INTERFACE_CHANGES.md`)

In accordance with **Rule 1** (*Extend, do not replace the existing architecture; preserve existing method contracts and enlist interface additions*), all pre-existing interface method signatures remain intact and backward-compatible. New methods and abstractions added to fulfill Tasks 1–3 are documented below.

---

## 1. Existing Interfaces & Services Extended

### `core/interfaces/retriever.py`
* **`Document`** (`lines 5–27`):
  * Added optional `score: Optional[float] = None` parameter to `__init__(self, content: str, metadata: dict = None, score: Optional[float] = None)` (backward-compatible with `Document(content, metadata)`).
  * Added `to_dict(self) -> Dict[str, Any]` helper method (`lines 21–27`).
* **`ScoredDocument(Document)`** (`lines 30–73`):
  * Added structured representation subclassing `Document` that exposes `.score`, `.document`, `.content`, `.metadata`, tuple unpacking `(doc, score)`, and dictionary/index lookup (`[0]`, `[1]`, `["score"]`, `["document"]`).
* **`BaseRetriever`** (`lines 76–97`):
  * Preserved abstract method `retrieve(self, embedding: List[float], top_k: int = 3) -> List[Document]` (`lines 80–82`).
  * Preserved abstract property `index_dimension(self) -> int` (`lines 91–97`).
  * **Added method**: `retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[ScoredDocument]` (`lines 84–89`) to expose similarity/relevance scores per retrieved document without altering `retrieve(...) -> List[Document]`.

### `core/interfaces/embedder.py`
* **`BaseEmbedder`** (`lines 5–30`):
  * Preserved abstract method `embed(self, text: str) -> List[float]` and abstract property `dimension(self) -> int`.
  * **Added property**: `model_name(self) -> str` (`lines 24–30`) with a non-breaking default implementation returning the underlying embedding model identifier.

### `core/services/token_budget_service.py`
* **`TokenBudgetService`** (`lines 18–340`):
  * Preserved `estimate_tokens(self, text: str) -> int` and `compute_budget(self, query, retrieved_docs, system_prompt, context_window, requested_max_tokens, ...)` contract.
  * Extended `__init__` (`lines 29–56`) to accept configurable budget modes (`"strict"` and `"truncate"`) via `policy_mode`, `mode`, `budget_mode`, or `config/retrieval.yaml`.
  * Extended `compute_budget` (`lines 108–340`) to support explicit token count arguments (`system_prompt_tokens`, `user_query_tokens`, `retrieved_context_tokens`, `requested_max_output_tokens`, `mode`) and return `requested_max_tokens`, `allowed_output_tokens`, `available_output_tokens`, `original_context_tokens`, `final_context_tokens`, `documents_removed`, `documents_truncated`, `documents_removed_or_truncated`, `budget_mode`, and `retained_docs`.

### `core/registry/model_registry.py` (and `core/services/model_registry.py`)
* **`ModelRegistry`** (`lines 31–239`):
  * Preserved `get_active_model(self) -> BaseLLM` (`lines 195–196`), `create_llm(self, config=None)` (`lines 220–229`), and `create_embedder(self, config=None)` (`lines 231–239`).
  * **Added methods**:
    * `register_llm_provider(self, provider_name: str, factory: Callable)` (`lines 100–115`)
    * `register_provider(self, provider_name: str, factory: Callable)` (`lines 117–122`)
    * `register_embedder_provider(self, provider_name: str, factory: Callable)` (`lines 124–139`)
    * `register_model(self, model_name: str, model_config: Dict[str, Any], factory: Optional[Callable] = None)` (`lines 141–152`)
    * `register_embedding_model(self, model_name: str, model_config: Dict[str, Any], factory: Optional[Callable] = None)` (`lines 154–165`)
    * `list_models(self) -> List[str]` (`lines 167–168`)
    * `list_embedding_models(self) -> List[str]` (`lines 170–171`)
    * `get_model(self, model_name: Optional[str] = None) -> BaseLLM` (`lines 173–193`)
    * `get_embedder(self, model_name: Optional[str] = None) -> BaseEmbedder` (`lines 198–215`)
    * `get_active_embedder(self) -> BaseEmbedder` (`lines 217–218`)

### `core/services/prompt_builder.py`
* **`PromptBuilder`** (`lines 8–91`):
  * Preserved `build(self, query: str, docs: list, profile: Optional[str] = None) -> str` (`lines 62–91`).
  * **Added methods**:
    * `set_profile(self, profile_name: str) -> None` (`lines 33–43`)
    * `get_system_prompt(self, profile: Optional[str] = None) -> str` (`lines 45–50`)
    * `list_profiles(self) -> List[str]` (`lines 52–53`)

### `app/pipeline.py`
* **`RAGPipeline`** (`lines 13–318`):
  * Preserved `__init__` positional/keyword parameters and added optional `reranker: Optional[BaseReranker] = None`, `top_k: Optional[int] = None`, `config_path: Optional[str] = None`, and `raise_on_failure: bool = True` (`lines 15–56`).
  * Preserved `run(self, query: str, top_k: Optional[int] = None, raise_on_failure: Optional[bool] = None) -> dict` (`lines 150–318`) returning existing keys (`response`, `retrieved_docs`, `metrics`, `cost`, `token_budget`) plus `retrieval_scores`, `retrieved_docs_with_scores`, `latency`, `failure_tags`, and `observability`.

---

## 2. New Pluggable Interfaces Introduced

### `core/interfaces/reranker.py`
* **`BaseReranker(ABC)`** (`lines 6–39`):
  * `rerank(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[Document]` (`lines 12–21`)
  * `rerank_with_scores(self, query: str, documents: List[Document], top_k: Optional[int] = None) -> List[ScoredDocument]` (`lines 23–34`)
  * `reranker_name(self) -> str` (`lines 36–39`)

### `core/interfaces/chunker.py`
* **`BaseChunker(ABC)`** (`lines 6–58`):
  * `chunk_text(self, text: str, metadata: Optional[dict] = None) -> List[Document]` (`lines 11–16`)
  * `chunk_documents(self, docs: List[Union[dict, Document, str]]) -> List[Document]` (`lines 18–39`)
  * `chunk(self, docs_or_text)` (`lines 41–44`)
  * `chunk_size(self) -> int` (`lines 46–49`), `chunk_overlap(self) -> int` (`lines 51–53`), `strategy_name(self) -> str` (`lines 55–58`)

---

## 3. Later additions (post-Phase 2)

Sections 1–2 are a historical snapshot of the Phase-1/2 extensions; their line numbers
refer to that revision. Later phases added the following contracts without breaking
the ones above. The current source of truth is
[`docs/architecture.md`](docs/architecture.md) and the README.

- **Query expansion** — `core/interfaces/query_expander.py::BaseQueryExpander.expand(query) -> List[str]`
  (original first) with `noop` / `synonym` / `llm` providers and `query_expansion` config.
- **Retriever extensions** — optional
  `BaseRetriever.retrieve_with_query(query, query_embedding, top_k)` hook (used by the
  hybrid retriever, which degrades to vector-only when absent); new `hybrid` and `kg`
  providers registered alongside `simple`/`faiss`/`dummy`.
- **Batching** — non-abstract `BaseEmbedder.embed_batch(texts)` and
  `BaseLLM.generate_batch(prompts, config)` defaults (loop), with real batched
  overrides in `SimpleEmbedder`, `OpenAIEmbedder` and `LocalHFLLM`.
- **Guardrails** — `core/interfaces/guardrail.py`: `GuardrailContext`,
  `GuardrailResult` (`allow`/`redact`/`block` + labels/details),
  `BaseGuardrail.check/check_input/check_output/describe`; providers `injection`,
  `pii`, `deny_list`, `schema_validator`; `GuardrailRegistry` with profiles and
  resolved-chain introspection.
- **PII** — `core/interfaces/pii.py`: `PiiMatch`, `PiiDetector`, class constants and
  mask/resolve/summarize helpers; regex backend plus an injectable NER seam.
- **Resilience** — `core/services/resilience.py`: `RetryPolicy`, `CircuitBreaker`,
  `ResilientLLM`/`ResilientEmbedder` (ordered failover), structured
  `RetryExhaustedError`/`CircuitOpenError`, `pop_resilience()` metadata.
- **Evaluation** — `BaseEvaluator.supports_ground_truth` +
  `evaluate_with_ground_truth(...)` (non-abstract default delegates to `evaluate`) and
  shared `normalize_references()`; `EvaluationEngine` delegates to the semantic
  evaluator; benchmark runner adds true IR metrics.
- **Observability & governance** — `OtelTracer`, `PrometheusCollector`,
  `AuditLogger`, `ResponseCache`, plus app-level `RunHistory`, `IntrospectionService`,
  `EvaluationService` and `PipelineRebuildService`.
- **Identity & tenancy** — `core/services/identity.py`: `JwtVerifier` (OIDC/OAuth2),
  `Principal`, `IdentityResolver` (IdP group → RBAC role, service accounts) and
  `ScimDirectory`; `/scim/v2/Users` + `/scim/v2/Groups`; `TenantResolver` plus
  tenant-scoped cache/audit/spend/trace attribution.
- **Config** — per-concern YAML files (`models`, `prompt_config`, `retrieval`,
  `governance`, `observability`, `guardrails`, `audit`, `resilience`, `api`,
  `access_control`, `tenants`, `identity`) validated by strict schemas with
  `${VAR}`/`env:` secret resolution at load time.

Nothing above replaced an existing method contract; additions are optional parameters,
new defaulted methods, or new interfaces/registries selected by configuration.

