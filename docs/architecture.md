# Enterprise-Grade GenAI Platform Blueprint

## Reusable Platform for Enterprise-grade LLM evaluation and governance

---

# 1. Objective

Enterprises struggle to operationalize GenAI systems due to:

* Lack of measurable evaluation
* Vendor lock-in risk
* Unpredictable cost behavior
* Absence of quality gates
* Poor observability into LLM outputs

This blueprint demonstrates how to architect a **modular, vendor-neutral, evaluation-aware
GenAI platform**. Its central promise is that **behaviour is configuration-driven**: components
can be swapped, quality gates toggled, and cost/observability policies tuned **without editing
the orchestration layer or the API layer**.

## 1.1 What we are NOT building

- A chatbot.
- A LangChain demo.
- A vertical solution.
- A SaaS platform.
- A plug-and-play marketplace.
- A zero-code system.
- A runtime-extensible dynamic plugin system.

## 1.2 What we are building

A reusable enterprise AI platform core — a reference architecture showing how to build a
modular, enterprise-grade GenAI platform, which allows:

* Swap models without rewriting code.
* Swap embedding models without breaking retrieval.
* Turn evaluation on/off.
* Capture cost + metadata.
* Logging, metadata-capture, id-tracing.
* Deploy as a service.

## 1.3 Who would be using it

**AI Platform Engineer (Primary Persona)**

* Fork the repo.
* Extend it.
* Implement vendor integrations.
* Own infra.
* Comfortable writing Python.

---

# 2. System Overview

This is a reference architecture with services, contracts, and deployment models that can be
extended to suit enterprise needs.

## 2.1 Layered view

The system is composed of four layers. Lower layers never reach up; upper layers depend on
lower layers only through **interfaces/contracts** and are wired together by the **composition
root** (see §6).

| Layer | Responsibility | Examples |
|-------|----------------|----------|
| Client Layer | Callers of the platform (apps, CI gates, shadow harness) | HTTP clients |
| API Layer (FastAPI) | HTTP surface, request validation, wiring to the pipeline | `app/main.py` |
| Orchestration Layer | Executes the request lifecycle, enforces stage ordering, emits structured traces | `app/pipeline.py` (`RAGPipeline`) |
| Service Interfaces (contracts) | Stable, swappable contracts for each capability | `core/interfaces/*` |
| Implementation Layer (extension points) | Concrete, replaceable vendors/backends | `core/implementations/*` |
| Registries & Services | Config-driven factories + orthogonal utilities (governance, observability) | `core/registry/*`, `core/services/*` |

## 2.2 Component diagram

```mermaid
flowchart TD
    Client[Client Layer] --> API[API Layer: FastAPI app.main]
    API --> Pipeline[Orchestration: RAGPipeline]

    subgraph Generation["Generation Layer"]
        Embedder[BaseEmbedder]
        Retriever[BaseRetriever]
        Reranker[BaseReranker]
        Chunker[BaseChunker]
        Guardrail[BaseGuardrail]
        LLM[BaseLLM]
    end

    subgraph Governance["Governance Layer"]
        TokenBudget[TokenBudgetService]
        RetrievalPolicy[RetrievalPolicyService]
        CostGovernor[CostGovernor]
    end

    subgraph Observability["Observability Layer"]
        Eval[BaseEvaluator / EvaluationEngine]
        Metrics[Metrics]
        CostTracker[CostTracker]
        Tracker[PipelineObservabilityTracker]
        Failures[FailureClassifier]
    end

    Pipeline --> Embedder
    Pipeline --> Retriever
    Pipeline --> Reranker
    Pipeline --> Guardrail
    Pipeline --> LLM
    Pipeline --> TokenBudget
    Pipeline --> RetrievalPolicy
    Pipeline --> CostGovernor
    Pipeline --> Eval
    Pipeline --> CostTracker
    Pipeline --> Tracker
    Pipeline --> Failures

    subgraph Registries["Config-driven Registries / Factories"]
        ModelRegistry[ModelRegistry: LLM + Embedder]
        RetrieverRegistry[RetrieverRegistry]
        EvaluatorRegistry[EvaluatorRegistry]
        ChunkerFactory[ChunkerFactory]
        GuardrailRegistry[GuardrailRegistry]
    end

    ModelRegistry --> Embedder
    ModelRegistry --> LLM
    RetrieverRegistry --> Retriever
    EvaluatorRegistry --> Eval
    ChunkerFactory --> Chunker
    GuardrailRegistry --> Guardrail
```

## 2.3 Interface Contracts

Each contract is an abstract base class in `core/interfaces/`. Implementations must satisfy the
contract; the orchestration layer depends only on these contracts.

### Embedder Contract (`core/interfaces/embedder.py`)

* Input: `str`
* Output: `List[float]`
* Must expose `dimension` metadata.
* Must expose `model_name` (identifier of the underlying model) so the pipeline can report
  `embedding_model` in traces.
* Optional `embed_batch(texts) -> List[List[float]]` for single-pass multi-text embedding
  (roadmap #27). The default loops `embed`, so batch output is always equivalent to
  `[embed(t) for t in texts]` and providers stay interchangeable.

### Retriever Contract (`core/interfaces/retriever.py`)

* Input: embedding vector
* Output: `List[Document]`
* Must expose `index_dimension`.
* Optional: `retrieve_with_scores(...) -> List[ScoredDocument]` to surface per-document
  similarity scores without altering the base `retrieve(...)` contract.

Supporting types:

* `Document(content, metadata, score)` — a retrieved unit of context. `score` is populated
  after retrieval/reranking; `to_dict()` produces a serializable view.
* `ScoredDocument(Document)` — structured `(document, score)` pair supporting attribute access
  (`.document`, `.score`), tuple unpacking `(doc, score)`, and key/index lookup (`["score"]`).

### LLM Contract (`core/interfaces/llm.py`)

* Input: prompt string + `GenerationConfig`
* Output: generated string
* Must expose `context_window` metadata.
* Must expose `model_name` for cost attribution and observability.
* Optional `generate_batch(prompts, config) -> List[str]` for single-pass multi-prompt
  generation (roadmap #27). The default loops `generate`, so output is equivalent to
  `[generate(p, config) for p in prompts]`, in the same order.

### Evaluator Contract (`core/interfaces/evaluator.py`)

* Input: `query`, `retrieved_docs`, `response`
* Output: `metrics` dict (e.g. `context_precision`, `answer_relevance`, `faithfulness`).

### Reranker Contract (`core/interfaces/reranker.py`)

* `rerank(query, documents, top_k) -> List[Document]`
* `rerank_with_scores(query, documents, top_k) -> List[ScoredDocument]`
* `reranker_name` property.

### Chunker Contract (`core/interfaces/chunker.py`)

* `chunk_text(text, metadata) -> List[Document]`
* `chunk_documents(docs) -> List[Document]`
* `chunk(docs_or_text) -> List[Document]`
* `chunk_size`, `chunk_overlap`, `strategy_name` properties.

### Guardrail Contract (`core/interfaces/guardrail.py`)

* `check(text, context) -> GuardrailResult` — the sole abstract method.
* `check_input(text, context?) / check_output(text, context?)` — edge conveniences.
* `GuardrailResult` carries `allowed` / `decision` (`allow` / `redact` / `block`),
  optional rewritten `text`, `reason`, and machine-readable `labels`.
* `GuardrailContext` carries the `stage` (`input` / `output`) and a free-form
  `metadata` bag (e.g. `top_k`, `llm_model`).
* `name` / `stage` attributes identify the guardrail in traces.
* `describe() -> {provider, type, stage, options}` is a read-only introspection
  view (roadmap #86). The base implementation covers every provider; concrete
  guardrails override `_options()` to expose effective settings (masks, terms,
  sensitivity, classes) and never request data or secrets.
* Built-ins (`core/implementations/guardrails.py`): `NoopGuardrail`,
  `DenyListGuardrail` (block or redact via `mask`), `SchemaValidatorGuardrail`.

## 2.4 Structured response

Every request returns a JSON-serializable report. Beyond the baseline contract, the pipeline
adds retrieval scores, latency, failure tags, and an observability trace:

```json
{
  "response": "...",
  "retrieved_docs": ["..."],
  "retrieved_docs_with_scores": [{"content": "...", "score": 0.82, "metadata": {}}],
  "retrieval_scores": [0.82, 0.61],
  "metrics": {
    "context_precision": 0.75,
    "answer_relevance": 0.8,
    "faithfulness": 0.9
  },
  "cost": {
    "model": "dummy",
    "latency_ms": 12.4,
    "estimated_cost_usd": 0.001
  },
  "token_budget": { "budget_mode": "strict", "allowed_output_tokens": 512, "...": "..." },
  "latency": { "embedding": 0.3, "retrieval": 0.2, "total_ms": 12.4 },
  "failure_tags": [],
  "observability": { "request_id": "...", "status": "success", "...": "..." }
}
```

---

# 3. Request Lifecycle (Data Flow)

The `RAGPipeline.run()` method executes ordered stages. Each stage is timed and each failure is
classified (see §8). When `raise_on_failure` is `True` (default), a stage failure raises; when
`False`, a structured degraded response is returned (`status: "failed"`).

```mermaid
sequenceDiagram
    participant A as API (FastAPI)
    participant P as RAGPipeline
    participant RP as RetrievalPolicyService
    participant E as Embedder
    participant R as Retriever
    participant RK as Reranker
    participant GR as Guardrails (BaseGuardrail)
    participant T as TokenBudgetService
    participant PB as PromptBuilder
    participant L as LLM
    participant EV as Evaluator
    participant CT as CostTracker
    participant CG as CostGovernor

    A->>P: run(query, top_k?)
    P->>RP: compute_top_k(query_tokens, avg_chunk_tokens)
    RP-->>P: governed top_k
    P->>E: embed(query)
    E-->>P: embedding vector
    P->>R: retrieve_with_scores(embedding, top_k)
    R-->>P: ScoredDocument[]
    P->>RK: rerank_with_scores(query, docs, top_k)
    RK-->>P: reordered ScoredDocument[]
    P->>GR: check_input(query, docs)  (ordered chain, optional)
    GR-->>P: allow / redact / block
    P->>T: compute_budget(query, docs, system_prompt, context_window, max_tokens)
    T-->>P: retained_docs + allowed_output_tokens
    P->>PB: build(query, docs)
    PB-->>P: prompt
    P->>L: generate(prompt, generation_config)
    L-->>P: response
    P->>GR: check_output(response)  (ordered chain, optional)
    GR-->>P: allow / redact / block
    P->>EV: evaluate(query, docs, response)
    EV-->>P: metrics
    P->>CT: compute(model_name, start_time)
    CT-->>P: cost
    P->>CG: check_cost(estimated_cost_usd)
    CG-->>P: ok / raise
    P-->>A: structured response + observability trace
```

**Stage order:** Query-length guard → Retrieval depth governance → Embedding → Retrieval → Reranking
→ Input redaction → Input guardrails → Token Budget → Prompt Construction → LLM Generation → Output
guardrails → Evaluation → Cost computation → Cost governance.

Note: Reranking is skipped when no reranker is supplied; Evaluation is skipped (empty metrics)
when the evaluator is a no-op/`NullEvaluator`. When a query expander is configured
(`query_expansion.enabled`), the Retrieval stage embeds and retrieves over each query variant and
merges the results (de-duplicated, highest score wins) before Reranking (roadmap #23). Input
redaction (#72) and the input/output guardrail chains (#52) are no-ops unless configured.

---

# 4. Interface Changes / Extensions

To preserve the existing architecture, all pre-existing interface method signatures remain
intact and backward-compatible. New methods and abstractions are additive. (See also
`INTERFACE_CHANGES.md`.)

| Contract | Added | Purpose |
|----------|-------|---------|
| `Document` | `score`, `to_dict()` | carry/emit relevance score |
| `BaseRetriever` | `retrieve_with_scores()` | expose per-document scores |
| `BaseEmbedder` | `model_name` | observability + registry resolution |
| `BaseReranker` | new interface | pluggable reranking |
| `BaseChunker` | new interface | pluggable chunking strategies |
| `PromptBuilder` | `set_profile()`, `get_system_prompt()`, `list_profiles()` | config-driven prompts |
| `TokenBudgetService` | `strict`/`truncate` modes, retained_docs + counters | explicit budget policy |
| `ModelRegistry` | `register_*`, `get_model`, `get_embedder`, `get_active_embedder` | plug-and-play providers |
| `RAGPipeline` | `reranker`, `top_k`, `config_path`, `raise_on_failure`, governance hooks; richer return | observability + governance |

---

# 5. Separation of Concerns

These layers do not depend on each other and interact only through the pipeline:

### Generation layer
- Embedder
- Retriever
- Reranker
- Chunker
- LLM

### Governance layer
- TokenBudgetService
- RetrievalPolicyService
- CostGovernor

### Observability layer
- EvaluationEngine / Evaluator
- Metrics
- CostTracker
- PipelineObservabilityTracker
- FailureClassifier

```mermaid
flowchart LR
    Pipeline --> Generation
    Pipeline --> Governance
    Pipeline --> Observability
    subgraph Generation[Generation Layer]
      Embedder
      Retriever
      Reranker
      LLM
    end
    subgraph Governance[Governance Layer]
      TokenBudget[TokenBudgetService]
      RetrievalPolicy[RetrievalPolicyService]
      CostGovernor
    end
    subgraph Observability[Observability Layer]
      EvaluationEngine
      Metrics
      CostTracker
    end
```

## Why this matters

Each layer looks after its own concern, avoiding cross-dependencies. Enterprises can swap
components such as:

```
OpenAI  -> vLLM
Milvus  -> Pinecone
RAGAS   -> internal evaluator
```

without touching the pipeline. That is the whole point of the architecture.

---

# 6. Config-driven Behavior

All runtime behaviour is resolved from `config/*.yaml` at the **composition root**
(`app/main.py`) and inside the pipeline/services. Swapping a component or toggling a policy is a
**config-only** change.

## 6.1 Composition root

`app/main.py` is the composition root. It reads configuration and resolves components through
registries/factories, then injects them into `RAGPipeline`. The intended contract is that the
API/composition layer imports **only interfaces, registries, and factories** — never concrete
implementation classes:

* Embedder: `ModelRegistry.get_active_embedder()` reads `models.active_embedding_model`.
* LLM: `ModelRegistry.get_active_model()` reads `models.active_model`.
* Retriever: `RetrieverRegistry.create()` reads `retrieval.default_retriever` + options.
* Evaluator: `EvaluatorRegistry.create()` reads `evaluation.enabled` + `evaluation.active_evaluator`.
* Reranker/Chunker: resolved from `reranking.*` and `chunking.*` respectively.
* Query expander: `QueryExpanderRegistry.create()` reads `query_expansion.enabled` +
  `query_expansion.active_expander` (roadmap #23).

> **Roadmap note (tracked):** Historically `app/main.py` constructed concrete classes directly
> (e.g. `DummyEmbedder()`, `DummyRetriever()`, `SimpleReranker(...)`). This is being migrated to
> full registry resolution so that config alone selects every component. See issues #5–#10.

## 6.2 Registry / Factory pattern

```mermaid
flowchart TD
    Config[config/*.yaml] --> CR[Composition Root: app.main]
    CR --> MR[ModelRegistry]
    CR --> RR[RetrieverRegistry]
    CR --> ER[EvaluatorRegistry]
    CR --> CF[ChunkerFactory]
    CR --> QX[QueryExpanderRegistry]
    MR --> |active_embedding_model| Emb[BaseEmbedder]
    MR --> |active_model| LLMp[BaseLLM]
    RR --> |default_retriever + similarity_metric| Ret[BaseRetriever]
    ER --> |evaluation.enabled/active_evaluator| Eval[BaseEvaluator]
    CF --> |chunking.active_strategy| Chk[BaseChunker]
    QX --> |query_expansion.enabled/active_expander| QE[BaseQueryExpander]
```

Each registry follows the same shape:

1. Load its config section.
2. Maintain a `{provider_name: factory}` map (built-ins + `register(...)` for extension).
3. `resolve(name)` → `(key, provider, provider_config)` from config.
4. `create(name?)` → constructed instance (or a Null implementation when disabled).

This is what makes the "add a component, change config, done" workflow possible.

## 6.3 Configuration mapping (reference)

### `config/models.yaml`

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `active_model` | `ModelRegistry.get_active_model()` | Selects the active LLM |
| `models.<name>.provider` | `ModelRegistry` provider map | `dummy` / `local` / `openai` |
| `models.<name>.context_window` | LLM + `RetrievalPolicyService` | Context budget for retrieval depth |
| `models.<name>.temperature` / `max_tokens` | `GenerationConfig` | Generation parameters (roadmap #12) |
| `models.<name>.input_cost_per_1k` / `output_cost_per_1k` | `CostTracker` | Cost computation (roadmap #14) |
| `active_embedding_model` | `ModelRegistry.get_active_embedder()` | Selects the active embedder |
| `embedding_models.<name>` | `ModelRegistry` embedder map | `model_name`, `provider` |

### `config/prompt_config.yaml`

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `active_prompt_profile` | `PromptBuilder` | Selects the default prompt profile |
| `profiles.<name>.system_prompt` | `PromptBuilder` / pipeline | System role for the LLM and token accounting |
| `profiles.<name>.context_separator` | `PromptBuilder` | Joins retrieved documents |
| `profiles.<name>.empty_context_message` | `PromptBuilder` | Fallback when no context is retrieved |
| `profiles.<name>.template` | `PromptBuilder` | Final prompt layout |

### `config/retrieval.yaml`

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `retrieval.default_retriever` | `RetrieverRegistry` | Selects retrieval backend (`faiss`/`simple`/`dummy`/`kg`/`hybrid`) |
| `retrieval.top_k` | `RAGPipeline` | Default number of documents to retrieve |
| `retrieval.similarity_metric` | `RetrieverRegistry` → `FAISSRetriever` | `cosine` / `l2` index selection (roadmap #15) |
| `retrieval.low_score_threshold` | `FailureClassifier` | Flags low-quality retrieval |
| `retrieval.retrievers.<key>` | `RetrieverRegistry` | Provider + options (`documents_path`, `graph_path`, ...) |
| `retrieval.retrievers.kg.graph_path` | `KGRetriever` | Triple store JSON (roadmap #24) |
| `retrieval.retrievers.kg.expansion_hops` | `KGRetriever` | One-hop expansion over shared entities |
| `retrieval.retrievers.hybrid.keyword_weight` | `HybridRetriever` | BM25 lexical weight in fusion (roadmap #25) |
| `retrieval.retrievers.hybrid.vector_weight` | `HybridRetriever` | Vector weight in fusion |
| `evaluation.enabled` | `EvaluatorRegistry` | Toggles evaluation (NullEvaluator when off) |
| `evaluation.active_evaluator` | `EvaluatorRegistry` | Selects evaluator |
| `evaluation.evaluators.<key>` | `EvaluatorRegistry` | Provider mapping |
| `reranking.enabled` | composition root | Enables/disables the reranking stage (roadmap #8) |
| `reranking.strategy` / weights / `top_k` | `SimpleReranker` | Reranking behaviour |
| `chunking.active_strategy` | `ChunkerFactory` | `small` / `large` / custom (roadmap #9) |
| `chunking.strategies.<name>` | `ChunkerFactory` | `chunk_size`, `chunk_overlap`, `separator` |
| `query_expansion.enabled` | `QueryExpanderRegistry` | Enables multi-query retrieval (roadmap #23; default off) |
| `query_expansion.active_expander` | `QueryExpanderRegistry` | Selects expander (`synonym` / `llm` / `noop`) |
| `query_expansion.max_variants` | expanders | Cap on query variants (original always included) |
| `query_expansion.expanders.<key>` | `QueryExpanderRegistry` | Provider mapping (+ `synonyms` for `synonym`) |
| `token_budget.default_mode` | `TokenBudgetService` | `strict` / `truncate` (roadmap #11) |
| `token_budget.max_output_cap` | `TokenBudgetService` | Hard output cap (roadmap #11) |
| `token_budget.min_output_tokens` | `TokenBudgetService` | Minimum reserved output |
| `token_budget.chars_per_token` | `TokenBudgetService` | Token estimation ratio |
| `cache.enabled` | composition root → `ResponseCache` | Enables exact-match response cache (roadmap #26; default off) |
| `cache.max_entries` | `ResponseCache` | LRU bound on cached responses |
| `cache.ttl_seconds` | `ResponseCache` | Per-entry time-to-live |
| `guardrails.max_query_chars` | `RAGPipeline` | Upper bound on query length before token budgeting (roadmap #73; disabled when unset) |
| `audit.enabled` | composition root → `AuditLogger` | Enables append-only audit trail (roadmap #28; default off) |
| `audit.path` | `AuditLogger` | JSONL destination for durable audit records |
| `audit.max_entries` | `AuditLogger` | Bounded in-memory ring size (backing `GET /v1/audit`) |
| `access_control.enabled` | composition root → `AccessController` | Enables RBAC/persona enforcement (roadmap #29; default off) |
| `access_control.roles.<role>` | `AccessController` | Per-role capabilities + `top_k_max` / `allowed_models` caps |
| `access_control.api_keys` | `AccessController` | API-key → role mapping |

Each concern has its own file (like `models.yaml` / `prompt_config.yaml`); the
composition root loads them by explicit path. Legacy deployments that still
carry inline `governance` / `observability` sections inside `retrieval.yaml`
keep working via a fallback (roadmap #34).

### `config/governance.yaml`

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `enabled` | composition root | Gates cost/retrieval-policy enforcement (roadmap #10) |
| `max_cost_per_request_usd` | `CostGovernor` | Cost cap per request |
| `safety_margin_tokens` | `RetrievalPolicyService` | Token safety margin |
| `avg_chunk_tokens` | `RetrievalPolicyService`, pipeline | Chunk size estimate for depth |

### `config/observability.yaml`

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `log_level` | `PipelineObservabilityTracker` | Log verbosity |
| `redact_sensitive_data` | `PipelineObservabilityTracker` | Toggle redaction (roadmap #16) |
| `low_retrieval_score_threshold` | pipeline | Low-score flagging |
| `sensitive_patterns` | `PipelineObservabilityTracker` | Redaction patterns (roadmap #16) |
| `pii` | `PiiRegistry` → redactor | PII/DLP scrubbing policy (roadmap #54) |
| `otel` | `PipelineObservabilityTracker` | OTel trace export (roadmap #47) |

The `otel` block (disabled by default) enables OTLP trace export:

| Sub-key | Default | Effect |
|---------|---------|--------|
| `enabled` | `false` | Build the tracer exporter (no-op when off → zero overhead) |
| `endpoint` | `http://localhost:4318/v1/traces` | OTLP/HTTP collector endpoint |
| `service_name` | `enterprise-genai-platform` | `service.name` resource attribute |
| `sample_ratio` | `1.0` | Head sampling ratio (0.0–1.0) |

### `config/guardrails.yaml`

The guardrail framework (roadmap #52, workstream B1) is a pluggable,
**config-driven** interception point on both edges of `RAGPipeline.run`.
**Disabled by default** — when `enabled: false` no guardrail runs and the data
path is byte-identical to before.

| Key | Consumed by | Effect |
|-----|-------------|--------|
| `enabled` | `GuardrailRegistry` | Master toggle (default `false`) |
| `input` | `GuardrailRegistry` → pipeline | **Ordered** list of guardrails on the query + retrieved docs (pre-prompt) |
| `output` | `GuardrailRegistry` → pipeline | **Ordered** list of guardrails on the generated response (pre-return) |
| `<entry>.provider` | `GuardrailRegistry` | Provider factory (`noop` / `deny_list` / `schema_validator` / `injection` / `pii`) |
| `<entry>.stage` | `GuardrailRegistry` | Optional per-entry edge override (`input` / `output`) |
| `<entry>.*` | provider | Provider-specific options (e.g. `terms`, `mask`, `regex`, `required_keys`, `expect_json`, `sensitivity`, `trust_retrieved_documents`, `classes`, `mode`) |

Guardrails run top-to-bottom; a **block** stops the chain (governed failure
`guardrail_input_blocked` / `guardrail_output_blocked` → HTTP **403**), while a
**redact** decision rewrites the text and the chain continues. Decisions
(guardrail name, decision, reason, labels) are recorded on the trace
(`guardrail_decisions`) and — with audit enabled — in the audit trail. Adding a
vendor guardrail is: implement `BaseGuardrail` → register a factory → add a
config entry; the composition root never imports a concrete guardrail.

`GET /v1/guardrails` (roadmap #86) returns the resolved chains — `enabled`,
registered `providers`, and each entry's provider/type/edge/effective options —
so you can preview what enabling the feature would run. Chains are reported even
while `enabled: false`; an invalid provider in a disabled config is returned in
`errors` instead of failing the request.

#### Prompt-injection / jailbreak defense (`injection`, roadmap #53, B2)

The `injection` provider detects instruction-override, role-play/jailbreak,
delimiter-escape and exfiltration patterns using curated heuristics (weighted
regexes) plus an **optional** pluggable classifier (`classifier`, default
`none` — heuristics always run, so the guardrail works offline).

* **Direct injection** in the user query is **blocked** (governed input failure).
* **Indirect injection** embedded in retrieved documents — which are untrusted by
  default — is **neutralized** (masked + framed with provenance markers,
  "spotlighting") rather than blocked, unless `trust_retrieved_documents: true`.
* `sensitivity` (`low` / `medium` / `high`) sets the score threshold;
  `neutralize_mode` (`delimit` / `strip` / `mask`) controls how indirect hits are
  rewritten. The red-team corpus in `tests/test_injection_defense.py` guards the
  block rate and holds a false-positive check over benign inputs.

#### PII / DLP (`pii`, roadmap #54, B3)

The `pii` provider detects personal data with deterministic regexes (email,
phone, credit card — **Luhn validated**, national id, IPv4/IPv6) and an
**optional** NER detector (`ner.enabled`, e.g. spaCy) for names and addresses.
Overlaps are resolved by class priority, so a card number is never split into
phone-like fragments.

* `classes` (default: all standard classes) is a per-class toggle.
* `mode: redact` masks each span (`[REDACTED_EMAIL]`, or a custom `mask`) and
  continues; `mode: block` fails the request with the governed guardrail
  failure. **Only the class and a count** ever leave the guardrail
  (`pii:<class>`, `details.classes`) — the matched value is never recorded.
* The `pii:` block of `config/observability.yaml` is the independent
  **scrubbing** policy: it strips the same classes from traces, logs and the
  query handed to the model (default `enabled: false`). When a `pii` guardrail
  is configured, traces/logs are scrubbed for its classes too, without
  pre-empting an input-side `block` decision.


---

# 7. Vendor Neutrality

Vendor neutrality is achieved by keeping **product-specific code behind interfaces** and
selecting it by configuration:

* Every capability has an abstract contract in `core/interfaces/`.
* Concrete vendors live in `core/implementations/` and expose no vendor types across the
  boundary.
* Registries map a **config key** (e.g. `faiss`, `openai`, `sentence_transformers`) to a
  provider factory. Adding a vendor is: implement the interface → register a factory (or add a
  built-in) → add a config entry.
* The orchestration layer never imports a concrete vendor.

Because of this, swaps that would normally ripple through the codebase become one-line config
changes:

| From | To | Change |
|------|----|--------|
| OpenAI | vLLM / local | `models.active_model` |
| Milvus / Simple | Pinecone / FAISS | `retrieval.default_retriever` |
| Sentence-Transformers | vendor embedding API | `models.active_embedding_model` |
| RAGAS / LLM-judge | internal evaluator | `evaluation.active_evaluator` |

---

# 8. Failure Modes and Policies

The pipeline classifies failures rather than leaking raw exceptions. `FailureClassifier` maps
exceptions and low-quality retrieval to a `FailureType` tag, which is attached to the stage and
recorded in the trace.

## 8.1 Failure taxonomy

| Class | Examples | Failure tags | Mitigation |
|-------|----------|--------------|------------|
| Upstream dependency failure | LLM outage, embedding API failure, vector DB down | `upstream_error` | Fail fast; structured error response; (optional) fallback provider |
| Configuration violation | embedding dimension mismatch, model context overflow, missing config | `dimension_mismatch`, `config_error` | Startup-time validation; hard fail at init (`_validate_contracts`) |
| Retrieval quality | no documents, low similarity scores | `no_documents`, `low_retrieval_score` | Flag as `degraded`; log alert; quality gate (active mode) |
| Policy violation | evaluation below threshold, cost cap exceeded | `cost_exceeded` | Quality gate enforcement (active) / logged alert (passive) |
| Input validation | over-long query | `query_too_long` | Reject before embedding (HTTP 400); tune `guardrails.max_query_chars` (#73) |
| Guardrail block | configured input/output policy denies | `guardrail_input_blocked`, `guardrail_output_blocked` | Governed failure envelope (HTTP 403); review `config/guardrails.yaml` (#52) |

## 8.2 Behaviour on failure

* `raise_on_failure=True` (default): exception is tagged and re-raised.
* `raise_on_failure=False`: a **degraded** structured response is returned with `status:
  "failed"`, `failed_stage`, `error_message`, empty results, and the recorded `failure_tags`.
* Low-quality retrieval does not fail the request; it marks the trace `degraded` with a
  `low_retrieval_score` tag.

---

# 9. Observability Strategy

Each request produces a structured trace via `PipelineObservabilityTracker`, including:

* `request_id`
* `model_version` / `llm_model`
* `embedding_version` / `embedding_model` + `embedding_dimension`
* `retriever`, `top_k`, `reranker`
* `retrieval_k`, `initial_retrieval_scores`, `retrieval_scores`
* `latency` (per-stage ms + total)
* `cost`
* `evaluation_scores` (`metrics`)
* `failure_tags` and overall `status` (`success` / `degraded` / `failed`)

`SensitiveDataRedactor` scrubs secrets (API keys, tokens, passwords) from traces before they
are logged. Redaction patterns and the enable flag are intended to be config-driven
(`observability.sensitive_patterns`, `observability.redact_sensitive_data`) — currently
hardcoded (roadmap #16).

## 9.1 Prometheus metrics (`GET /metrics`)

`GET /metrics` exposes the same aggregates as `GET /v1/metrics` in the **Prometheus text
exposition** format, for scraping by Prometheus/Grafana (roadmap issue #44). The collector
(`core/services/telemetry.py::PrometheusCollector`) is fed from the run result next to
`RunHistory`, so there is no duplicate bookkeeping. Series:

| Metric | Type | Labels |
|--------|------|--------|
| `genai_requests_total` | counter | `status` (success/failed) |
| `genai_failures_total` | counter | `failure_type` |
| `genai_failure_tags_total` | counter | `tag` |
| `genai_stage_latency_ms` | histogram | `stage` (embedding/retrieval/reranking/generation/total) |
| `genai_cost_usd_total` | counter | — |
| `genai_model_cost_usd_total` | counter | `model` |
| `genai_cache_events_total` | counter | `event` (hit/miss) |
| `genai_governance_denials_total` | counter | `reason` |
| `genai_in_flight_requests` | gauge | — |

`prometheus-client` is an **optional extra** (`pip install -e ".[observability]"`); when it is
absent the endpoint returns a 503 envelope (`prometheus_not_installed`) and the core install is
unaffected. A turnkey stack ships in `deployment/observability/` (Prometheus scrape config +
alert rules, Grafana datasource/dashboard provisioning, a `GenAI Platform Overview` dashboard);
bring it up with `docker compose --profile observability up`. Multi-tenant labels (`tenant`,
`app`) are added later by H1-A3 attribution without renaming any series.

## 9.2 Provider resilience (retries, circuit breaker, failover)

Provider resilience is a set of **transparent wrappers** around the LLM/embedder interfaces
(`core/services/resilience.py`, roadmap issue #45), so concrete providers in
`core/implementations/` stay untouched. It is **disabled by default** — with
`resilience.enabled: false` (the shipped default) the composition root uses the raw providers
and current behaviour is unchanged.

| Building block | Purpose |
|----------------|---------|
| `RetryPolicy` | bounded exponential backoff + jitter for transient errors (timeouts, 429, 5xx), injectable sleeper for tests |
| `CircuitBreaker` | closed/open/half-open breaker so a down provider fails fast instead of amplifying latency |
| `ResilientEmbedder` | retry + breaker around a single embedder |
| `ResilientLLM` | retry + per-provider breaker + an ordered **failover chain** of LLMs |

Transient errors are classified by `is_transient_error` (an exception's `retryable` attribute
or `status_code` overrides the heuristic). When every provider (and every retry) fails, the
wrapper raises `RetryExhaustedError` tagged `upstream_retry_exhausted`; a short-circuited call
raises `CircuitOpenError` tagged `provider_circuit_open`. The wrapper records which provider
actually served the request (`served_by`) and the retry/failover counts; the pipeline copies
this into `trace["resilience"]` when present.

Configuration lives in `config/resilience.yaml` (`resilience.enabled`, `max_attempts`,
`backoff_initial_ms`, `backoff_max_ms`, `jitter`, `breaker_threshold`, `breaker_reset_ms`,
`fallback_models`, `fallback_embedders`). `fallback_models` names keys in `models.yaml`; the
primary is always `active_model`. Identity (`model_name`, `context_window`) is taken from the
primary so cost accounting and prompt budgeting are unaffected by failover.

## 9.3 OpenTelemetry tracing (OTLP export)

Pipeline tracing is **OTel-native** (roadmap issue #47): when enabled, every request exports a
root `pipeline.run` span with one child span per stage (`pipeline.embedding`,
`pipeline.retrieval`, `pipeline.reranking`, `pipeline.token_budget`,
`pipeline.prompt_construction`, `pipeline.llm_generation`, `pipeline.evaluation`,
`pipeline.cost_governance`, `pipeline.retrieval_policy`) over **OTLP**, so traces land in an
existing Jaeger/Tempo/Grafana/Datadog/New Relic stack.

The in-process trace (`PipelineObservabilityTracker`, surfaced at `/v1/traces/{request_id}`)
remains the **source of truth** — OTel is a pure exporter and the pipeline contract is
unchanged. Integration is transparent: `measure_stage` opens a child span, and span attributes
(`request_id`, `top_k`, `retriever`, `llm_model`, `embedding_model`, `failure_tags`) are set on
the root span. Logs are correlated by prefixing the trace/span id. It is **disabled by
default** (`observability.otel.enabled: false`) — with tracing off no tracer provider is built
and nothing changes.

`opentelemetry-*` is an **optional extra** shared with Prometheus
(`pip install -e ".[observability]"`). A turnkey backend ships in
`deployment/observability/otel-collector/config.yml` (OTLP receiver → Jaeger exporter);
`docker compose --profile observability up` starts the collector and Jaeger (UI at
`http://localhost:16686`).

---

# 10. Evaluation-first Design

Evaluation is a first-class, **pluggable** capability. The `EvaluationEngine` orchestrates a set
of `Metrics`, which declare *how* each metric is computed. Different metric mixes can be
injected per environment.

```mermaid
flowchart TD
    Pipeline --> EE[EvaluationEngine]
    EE --> M[Metrics]
    M --> CP[context_precision]
    M --> AR[answer_relevance]
    M --> FF[faithfulness]
```

```python
class LLMJudgeMetrics:      # calls an LLM judge
    def faithfulness(...): ...

class EmbeddingMetrics:     # cosine similarity
    def answer_relevance(...): ...

class HybridMetrics: ...
```

**Pattern:** Strategy + Dependency Injection.

Evaluation can be toggled off via `evaluation.enabled: false`, in which case the
`EvaluatorRegistry` returns a `NullEvaluator` that emits empty metrics at zero cost. This keeps
the pipeline fully functional in passive/shadow mode.

---

# 11. Cost Transparency

Cost is a governance concern surfaced on every response and enforced by `CostGovernor`.

* `CostTracker.compute(model_name, start_time)` returns latency and `estimated_cost_usd`.
* `CostGovernor.check_cost(cost)` raises when `cost > governance.max_cost_per_request_usd`,
  which the pipeline converts into a `cost_exceeded` policy failure.

```mermaid
flowchart LR
    LLM --> CT[CostTracker]
    CT -->|estimated_cost_usd| CG[CostGovernor]
    CG -->|> cap| Fail[Policy failure]
    CG -->|<= cap| OK[Response]
```

> **Roadmap note (tracked):** cost is currently a constant stub; the target is to compute cost
> from input/output token counts × per-model `input_cost_per_1k` / `output_cost_per_1k` from
> `models.yaml`. See issue #14. This is required for `CostGovernor` to be meaningful.

---

# 12. Fail-fast Configuration Validation

The blueprint requires invalid configuration to fail **at startup**, not at request time:

* **Startup-time validation:** the composition root resolves every component and validates
  contracts before serving traffic.
* **Hard fail during initialization:** e.g. `RAGPipeline._validate_contracts()` raises a tagged
  `dimension_mismatch` error when `embedder.dimension != retriever.index_dimension`.
* **Model loading:** a missing/unloadable configured model should fail fast with a structured
  error rather than silently falling back to fabricated behaviour.

> **Roadmap notes (tracked):**
> * `SimpleEmbedder` currently falls back to synthetic embeddings on load failure; it should
>   fail fast (opt-in offline fallback only). See issue #18.
> * Config keys that are declared but not yet honored (§6.3 "roadmap" rows) must either be
>   enforced or removed so the contract is truthful.

## 12.1 Config schemas, validation and secrets (issue #46)

Every shipped `config/*.yaml` has a typed Pydantic schema in `core/config/schema.py`
(`SCHEMAS` maps the file stem to its model). Top-level keys are **strict**
(`extra="forbid"`) so typos and wrong types are caught with a precise message; nested
provider registries are **permissive** because provider entries legitimately carry
vendor-specific options. Every field has a default, so a minimal partial config still
validates (backward compatible).

Validation (`core/config/validator.py`) runs three checks: **schema** (parse + typed model),
**secrets** (every reference must resolve), and **version drift** (`config_version` newer
than the build is a warning, not a failure). The composition root validates the primary
configs before building any component (`_validate_startup_configs`), so an invalid config
fails fast at startup with `ConfigValidationError`.

Operators and CI can validate ahead of deploy:

```bash
python -m app.config_validate          # all schema-backed config/*.yaml; exit 0/1/2
python -m app.config_validate config/api.yaml --json
```

**Secrets** are never stored in config. Files reference environment-backed secrets as
`${ENV_VAR}` or `env:ENV_VAR`; values are resolved at load time (`core/config/secrets.py`)
and a missing reference fails fast (`SecretResolutionError`). Resolved values are kept in
memory only — the introspection layer runs configs through `SensitiveDataRedactor` (issue
#16), so a resolved secret is never emitted by `/v1/config`, traces or logs. In production,
Vault (Agent Injector) or a Kubernetes `secretKeyRef` injects the value into the process
environment, so the same `${ENV_VAR}` mechanism works unchanged.

---

# 13. Deployment Modes

You can use the deployed stack as **active** (a gate) or **passive** (an evaluator) mode. The
architecture supports cut-over from one mode to another.

## Mode 1 — Shadow / Evaluation Mode

Safer; good for early stages. The system:

* Replays queries
* Evaluates responses
* Computes cost
* Logs metrics
* Does **not** block live traffic

Used when the organization is experimenting, governance is not yet enforced, trust is not yet
high, or compliance review is ongoing. Common in BFSI / Healthcare.

## Mode 2 — Inline Gateway Mode

The system acts as an API gateway and blocks traffic that does not meet thresholds:

* Runs retrieval
* Runs evaluation
* Applies quality gates
* Enforces cost thresholds
* Blocks bad responses

This is production-grade governance. Policies and thresholds are configurable and preconfigured
(see §8). The toggle between modes is a matter of whether governance gates raise/block
(`raise_on_failure=True`) or merely log (`raise_on_failure=False`).

---

# 14. Operational Maturity Path

Operationalization is staged — start basic, then level up.

## Stage 1 — Passive Evaluation
Deploy in shadow mode. Replay production queries, evaluate, compute cost, and log
metrics/traces without affecting live traffic. Goal: establish a baseline and trust.

## Stage 2 — Threshold-Based Enforcement
Switch to active governance with conservative thresholds. Enable `CostGovernor` and quality
gates; block only clear violations. Goal: introduce guardrails with minimal business risk.

## Stage 3 — Inline AI Gateway
Act as an inline gateway for production traffic. Enforce quality and cost gates on every
request; emit full observability traces for decision-making. Goal: production-grade governance.

## Stage 4 — Centralized AI Governance Layer
Centralize policy, evaluation, and cost reporting across multiple services. Model swaps and
benchmark updates become routine config/report operations. Goal: platform-wide, explainable AI
governance.

---

# 15. Development & Customization

This is a reference implementation — clone it and use it with little modification. Example: add
a new retriever.

1. Create a new Python file:

   ```
   core/implementations/pinecone_retriever.py
   ```

2. Implement the contract:

   ```python
   class PineconeRetriever(BaseRetriever):
       ...
   ```

3. Register a provider factory (one line) and add a config entry in `retrieval.yaml`
   (`retrieval.retrievers.<key>`).

4. (Advanced) Configure governance/observability hooks (§6.3, §8, §9).

5. Deploy as a Docker container that brings the services up with API endpoints you can plug
   into live production systems for evaluation and report generation (see §13).

Done.

You do **NOT**:

* Call a special API to register.
* Modify docker-compose.
* Modify registry logic (for an existing provider family).
* Touch the orchestration layer.

## 15.1 Adding other components

The same recipe applies to every capability:

| To add a… | Implement | Select via config |
|-----------|-----------|-------------------|
| Retriever | `BaseRetriever` in `core/implementations` | `retrieval.default_retriever` |
| Embedder | `BaseEmbedder` | `models.active_embedding_model` |
| LLM | `BaseLLM` | `models.active_model` |
| Evaluator | `BaseEvaluator` | `evaluation.active_evaluator` |
| Reranker | `BaseReranker` | `reranking.strategy` |
| Chunker | `BaseChunker` | `chunking.active_strategy` |

---

# 16. Repository Layout

```
app/                 API + orchestration (main.py, pipeline.py, bootstrap.py)
config/              models.yaml, prompt_config.yaml, retrieval.yaml,
                     governance.yaml, observability.yaml, guardrails.yaml, ...
core/
  interfaces/        contracts (embedder, retriever, llm, evaluator, reranker, chunker, guardrail)
  implementations/   vendor/backend implementations
  registry/          config-driven registries (model, retriever, evaluator, guardrail)
  services/          governance + observability + prompt/token/cost services
  evaluation/        EvaluationEngine + Metrics
  config/            generation config
data/                sample documents
deployment/          Dockerfile + docker-compose
tests/               unit + integration tests
docs/                architecture.md (this document)
```

---

# 17. Tasks — Broad Level

## Phase 1 — Foundational Blueprint

Focus:
* Abstraction boundaries
* Single-path working reference
* Dockerized API
* Structured JSON response
* Evaluation placeholder
* Cost estimation

Non-goals:
* Production-grade hallucination detection
* Distributed vector DB scaling
* Advanced observability stack

## Phase 2 — Config-driven completion & hardening

Focus:
* Full config-driven composition root (every component resolved from config)
* Honor every declared config flag (reranking/governance/evaluation/token-budget/observability)
* Provider parity: OpenAI honors model + `GenerationConfig`; real cost from token counts
* Fail-fast startup validation and truthful "declared = honored" configs
* Ingestion/chunking stage wired to `chunking.active_strategy`

Tracked via repository issues (#5–#18).

## Phase 3 — Roadmap extensions

Focus:
* Truthful evaluation & benchmarking: real metrics + labeled ground-truth dataset (#21, #22)
* Retrieval breadth: query expansion / multi-query (#23), knowledge-graph retrieval (#24), hybrid keyword + vector (#25)
* Runtime economics: response / prefix caching (#26), batching / parallel inference (#27)
* Governance & platform: audit logging (#28), RBAC / persona control (#29), API hardening (#30)
* Showcase & hygiene: runnable examples + README quickstart (#31), remove dead code (#32)

Derived from the repo's `Daywise-4hourly-execution-plan.csv` (Hour 2-3 build column).

Tracked via repository issues (#21–#32).

---

# 18. References

## Repo

[https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint)

## Interface changelog

`INTERFACE_CHANGES.md`
