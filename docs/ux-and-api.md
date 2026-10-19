# UX & API Architecture — Fronting UI Plan

> **Status: DRAFT for review (2026-10-18 retrospective).** No code and no GitHub issues
> have been created from this document yet. The issue list in §7 is a proposal only —
> it becomes actionable after this plan, the API matrix, and the UX flows are approved.

## 1. Purpose

Define (a) the public API surface that makes this backend usable by **any enterprise
architect** integrating the blueprint, and (b) the UX architecture for a fronting UI
built on top of it — in that order. The API is the contract; the UI is its first
non-trivial consumer and living proof that the contract is sufficient.

## 2. Personas & jobs-to-be-done

| Persona | Job to be done | Primary surfaces |
|---|---|---|
| **Enterprise architect** | Evaluate: what is pluggable, what does a request cost/latency, how do I swap vendor/model? | Introspection endpoints, `/docs` (OpenAPI), config viewer, governance status |
| **RAG/ML engineer** | Experiment: prompt, `top_k`, chunking, metric, model — compare outcomes quickly | `POST /v1/query`, experiments, evaluation, Query Studio UI |
| **Platform/ops engineer** | Operate: health, budgets, traces, failure rates, deploys | `/health`, `/ready`, governance, traces, Prometheus metrics |
| **Evaluator/analyst** | Measure: run evaluations/benchmarks, track regressions | `POST /v1/evaluate`, experiments, comparison tables |

## 3. Principles & the hard rule

1. **API-first.** FastAPI + Pydantic request/response models are the contract;
   OpenAPI (`/docs`, `/openapi.json`) is generated, never hand-maintained.
2. **UI over HTTP only.** The fronting UI must call the REST API — it must **never
   import `app.pipeline`, `core.*`, or build a pipeline itself.** If the UI cannot
   be built purely on the public API, the API is incomplete and must be extended
   first. This is the acceptance test for "usable by any enterprise architect".
3. **Versioned surface** (`/v1/...`), with the legacy `POST /query` kept as an alias
   during transition (existing tests depend on it).
4. **One error envelope** reusing the existing `FailureType` taxonomy
   (`core/services/failure_classifier.py`, 13 values: `embedding_failure`,
   `dimension_mismatch`, `retrieval_failure`, `no_documents_retrieved`,
   `low_retrieval_score`, `reranking_failure`, `token_budget_exceeded`,
   `cost_limit_exceeded`, `retrieval_policy_failure`, `prompt_construction_failure`,
   `llm_failure`, `evaluation_failure`, `unknown_failure`) + `request_id` + `failure_tags`.
5. **Redaction at the edge**: any config/trace text leaving the API passes through
   `SensitiveDataRedactor` (same rule the logs already follow).
6. **No import-time side effects**: `pipeline = build_pipeline()` at module import
   (app/main.py:135) moves to FastAPI lifespan/startup, so a failed model load fails
   the container loudly instead of crashing every import (part of issue #30).

## 4. Current state (ground truth)

- API: exactly one endpoint — `POST /query` (app/main.py:142), request
  `{query: str (min_length=1)}`, response = `RAGPipeline.run()` result dict:
  `response`, `error`, `failure_type`, `failure_tags`, `retrieved_docs`,
  `retrieval_scores`, `metrics`, `cost` (`model`, `latency_ms`, `estimated_cost_usd`,
  `input_tokens`, `output_tokens`, `input_cost_per_1k`, `output_cost_per_1k`),
  `token_budget`, `latency` (per-stage report), `observability` (redacted trace with
  `request_id`, `failed_stage`, `llm_model`, `retriever`, `reranking_enabled`, ...).
- Registries with ready-made listing/introspection: `RetrieverRegistry`,
  `RerankerRegistry`, `EvaluatorRegistry` (each has `list_providers()`, `list_*()`,
  and `is_enabled()` where applicable), `ModelRegistry` (`list_models()`,
  `list_embedding_models()`, `get_active_model_config()`).
- Experimentation: `ExperimentRunner.run_single_experiment()`,
  `compare_embedding_models()`, `compare_chunking_strategies()`
  (core/services/experiment_runner.py).
- Governance: `CostGovernor`, `CostTracker`, `TokenBudgetService`,
  `RetrievalPolicyService` — all wired in `build_pipeline()`, gated by
  `governance.enabled`.
- Observability: `PipelineObservabilityTracker` (stage latencies, failure tags,
  redacted traces keyed by `request_id`).
- Known gap tracked as issue **#30**: minimal API surface, import-time pipeline
  construction, no health/readiness, no introspection.

## 5. API surface v1 — endpoint matrix

Legend: **[E]**xisting · **[N]**ew

| # | Method & path | Group | Backed by (exists unless noted) | |
|---|---|---|---|---|
| 1 | `POST /v1/query` | Core | `RAGPipeline.run` (+ opts: `top_k`, `include_trace`) | [N] |
| 2 | `POST /v1/query:batch` | Core | sequential/async loop over #1 (new logic) | [N] |
| 3 | `POST /query` | Core | legacy alias of #1 | [E] |
| 4 | `GET /health` | Ops | liveness: process up | [N] |
| 5 | `GET /ready` | Ops | readiness: pipeline built, model loaded, index populated (new checks) | [N] |
| 6 | `GET /v1/config` | Introspection | loaders + `SensitiveDataRedactor` (redacted effective config) | [N] |
| 7 | `GET /v1/models`, `/v1/embedding-models` | Introspection | `ModelRegistry.list_models()/list_embedding_models()` + active flags | [N] |
| 8 | `GET /v1/retrievers`, `/v1/rerankers`, `/v1/evaluators` | Introspection | registry `list_providers()`/`list_*()`/`is_enabled()` | [N] |
| 9 | `POST /v1/evaluate` | Evaluation | active `BaseEvaluator` (semantic / llm_judge / engine) over query+docs+response | [N] |
| 10 | `POST /v1/experiments` | Evaluation | `ExperimentRunner.run_single_experiment` / `compare_*` | [N] |
| 11 | `GET /v1/experiments/{id}` | Evaluation | experiment status/result store (new, minimal in-memory ok to start) | [N] |
| 12 | `POST /v1/pipeline:rebuild` | What-if | `build_pipeline()` with config-path/overrides — swap model, retriever, metric at runtime | [N] |
| 13 | `GET /v1/governance/status` | Governance | limits from config + spend window from `CostTracker` accumulation (new accumulator) | [N] |
| 14 | `GET /v1/traces/{request_id}` | Observability | last-trace store from `PipelineObservabilityTracker` (new, bounded LRU) | [N] |
| 15 | `GET /v1/metrics` | Observability | aggregate stage latencies + cost/failure counters (new) | [N] |
| 16 | `GET /metrics` | Ops | Prometheus exposition of #15 (optional; only if prometheus-client adopted) | [N] |

Cross-cutting (same effort, all endpoints): `/v1` prefix, error envelope per §3.4,
`X-Request-ID` echo, API-key auth **stub** (config-driven middleware, disabled by
default — placeholder for #29 RBAC later), Pydantic response models so `/docs` is
self-describing.

## 6. UX architecture — Streamlit console (`ui/`)

**Choice: Streamlit for v1.** Pure Python (no JS toolchain), fast iteration, and its
widget strengths (sliders, tables, plots) match the experimentation persona. Gradio is
narrower (single-model demos), Dash/NiceGUI are not better here, and a
React/Next.js frontend is the *production product* path — deferred to a later phase
because it is only justified once the API is stable. Constraint from §3.2 applies to
every UI: HTTP only, no `core.*` imports.

### Page map → endpoint mapping

| Screen | User interactions | Endpoints |
|---|---|---|
| **Overview / Health** | status, active model/retriever/reranker/evaluator, version, last failures | #4, #5, #7, #8 |
| **Query Studio** | enter query; sliders for `top_k`, temperature/max_tokens override, rerank toggle; view answer, retrieved docs + scores, per-stage latency, cost, failure tags, raw redacted trace | #1, #6 |
| **Compare (what-if)** | pick config overrides (metric cosine/l2, chunk strategy, model); run A/B queries side-by-side | #1, #12, #15 |
| **Evaluation** | run evaluator on query/response (optional ground truth); launch experiment comparisons; result tables | #9, #10, #11 |
| **Governance & Cost** | budget limits, spend window, per-request cost history | #13, #15 |
| **Traces** | look up `request_id`, stage latencies, failure taxonomy | #14, #15 |
| **Settings (read-only v1)** | effective config viewer (redacted), model/provider lists | #6, #7, #8 |

No config-editing UI in v1 (write path = files in `config/`); `pipeline:rebuild` in the
UI is expressed as preset "what-if" selections, keeping humans as the owners of YAML.

## 7. Proposed GitHub issues (NOT created yet — for review)

Suggested split; `#30` stays the umbrella and gets scoped down to group (A).

| Proposed | Title | Type / labels | Depends on |
|---|---|---|---|
| **A** (= reshape #30) | API foundation: app factory + lifespan (no import-time build), `/health`, `/ready`, `/v1` prefix, error envelope + request IDs, auth-stub middleware | bug/enhancement, architecture | — |
| **B** | Introspection endpoints: redacted `/v1/config`, models/embedding-models, retrievers/rerankers/evaluators listings | enhancement, config-driven | A |
| **C** | Evaluation & experiment endpoints (`/v1/evaluate`, `/v1/experiments` + id store) | enhancement | A |
| **D** | What-if `POST /v1/pipeline:rebuild` (runtime component swap via config) | enhancement, plug-and-play | A, B |
| **E** | Governance & observability endpoints (`/v1/governance/status`, `/v1/traces/{id}`, `/v1/metrics`, optional Prometheus) | enhancement, security | A |
| **F** | Batch query endpoint (`/v1/query:batch`) | enhancement | A |
| **G** | Streamlit console `ui/` (page map §6, HTTP-only rule, README quickstart section) | enhancement, documentation | A–E (min. B + query) |
| **H** | Contract tests: OpenAPI snapshot + response-model tests locking the error envelope/taxonomy | test, architecture | A |

Issue labels to reuse: `enhancement`, `architecture`, `config-driven`,
`plug-and-play`, `documentation`, `security`, `test`.

## 8. Delivery plan

- **P0 (this document)** — retrospective artifact; review gate. Nothing created
  until approved.
- **P1 — Phase-2 completion (queue unchanged):** #16 (in progress, design recorded
  in memory) → #17 → #18 → #1 → #34. The API/UX work does **not** interrupt these;
  Phase-2 closes the behavioral gaps first so the API exposes honest behavior.
- **P2 — API expansion:** issues A–F above (A first; B–F can interleave per
  dependency table). Each follows the standing rule: one commit+push, ≥6 tests, full
  suite green; API work also needs contract tests (H) because CI gates coverage ≥78%.
- **P3 — UX console:** issue G, built strictly over the API (§3.2), plus README
  quickstart ("run backend, open console").
- **P4 (optional, later):** React/Next.js product frontend reusing the same OpenAPI
  contract; justified only if a multi-user product surface becomes a goal.

Sequencing note: of the options considered — (a) interleave UX/API docs now,
(b) finish Phase-2 first, (c) produce this plan/doc for review first — **(c) was
chosen**; the build order between P1 and P2 is re-decided after review, with the
default being P1 → P2 as written above.
