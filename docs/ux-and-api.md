# UX & API Architecture â€” Fronting UI Plan

> **Status: DELIVERED (reconciled 2026-10-22, #81).** The API surface and the Streamlit
> console described here shipped in the P2/P3 series; Â§7 is now a delivery record rather
> than a proposal. The forward-looking roadmap (multi-tenancy, guardrails depth,
> observability, deployment, product UI) lives in
> [enterprise-roadmap.md](enterprise-roadmap.md).

## 1. Purpose

Define (a) the public API surface that makes this backend usable by **any enterprise
architect** integrating the blueprint, and (b) the UX architecture for a fronting UI
built on top of it â€” in that order. The API is the contract; the UI is its first
non-trivial consumer and living proof that the contract is sufficient.

## 2. Personas & jobs-to-be-done

| Persona | Job to be done | Primary surfaces |
|---|---|---|
| **Enterprise architect** | Evaluate: what is pluggable, what does a request cost/latency, how do I swap vendor/model? | Introspection endpoints, `/docs` (OpenAPI), config viewer, governance status |
| **RAG/ML engineer** | Experiment: prompt, `top_k`, chunking, metric, model â€” compare outcomes quickly | `POST /v1/query`, experiments, evaluation, Query Studio UI |
| **Platform/ops engineer** | Operate: health, budgets, traces, failure rates, deploys | `/health`, `/ready`, governance, traces, Prometheus metrics |
| **Evaluator/analyst** | Measure: run evaluations/benchmarks, track regressions | `POST /v1/evaluate`, experiments, comparison tables |
| **Security/compliance reviewer** | Audit: who did what, were guardrails enforced, what PII was scrubbed | `/v1/audit`, `/v1/guardrails`, `/v1/access`, redacted traces |

## 3. Principles & the hard rule

1. **API-first.** FastAPI + Pydantic request/response models are the contract;
   OpenAPI (`/docs`, `/openapi.json`) is generated, never hand-maintained.
2. **UI over HTTP only.** The fronting UI must call the REST API â€” it must **never
   import `app.pipeline`, `core.*`, or build a pipeline itself.** If the UI cannot
   be built purely on the public API, the API is incomplete and must be extended
   first. This is the acceptance test for "usable by any enterprise architect";
   `tests/test_ui_console.py` enforces it with an AST scan.
3. **Versioned surface** (`/v1/...`), with the legacy `POST /query` kept as an alias
   during transition (existing tests depend on it).
4. **One error envelope** reusing the existing `FailureType` taxonomy
   (`core/services/failure_classifier.py`; see architecture Â§8.1 for the current
   members, including the API-level `not_ready`, `unauthorized` and `batch_too_large`,
   the query guard `query_too_long`, and the guardrail `guardrail_input_blocked` /
   `guardrail_output_blocked`) + `request_id` + `failure_tags`.
5. **Redaction at the edge**: any config/trace/audit text leaving the API passes
   through `SensitiveDataRedactor`; `${VAR}`/`env:` references are never resolved in
   responses.
6. **No import-time side effects**: the pipeline is built in the FastAPI lifespan, so
   a failed model load fails startup loudly instead of crashing every import.

## 4. Current state (shipped)

- **HTTP surface** â€” 22 application routes (see Â§5) plus the generated `/docs`,
  `/redoc` and `/openapi.json`, all with typed response models where the payload is
  structured (`app/schemas.py`). Cross-cutting: `/v1` prefix, error
  envelope, `X-Request-ID` echo, optional config-driven API-key stub
  (`config/api.yaml`), `503 not_ready` before the lifespan completes.
- **Readiness** â€” `GET /ready` reports `status`, `config_revision` and a
  `describe_pipeline(...)` component summary; it reflects a successful
  `POST /v1/pipeline:rebuild`.
- **Introspection** â€” redacted effective config (`/v1/config`), models,
  embedding models, retrievers (with the *effective* `similarity_metric`), rerankers,
  evaluators, guardrails (resolved input/output chains, previewable while disabled)
  and the RBAC summary (`/v1/access`).
- **Query** â€” `POST /v1/query` (+ legacy `/query`) and `POST /v1/query:batch`
  (sequential or bounded parallel; per-item envelopes with their own `request_id`,
  cost and latency; one query failing never aborts the batch; `api.max_batch_size`).
- **Evaluation & experiments** â€” `POST /v1/evaluate` (active or named evaluator;
  auto-retrieves through the live pipeline when docs are omitted; ground truth is
  used only when the evaluator advertises `supports_ground_truth`), `POST
  /v1/experiments` (202) and `GET /v1/experiments/{exp_id}` backed by a bounded store and
  a thread pool. Experiments reuse the same composition root as the API (#75).
- **What-if** â€” `POST /v1/pipeline:rebuild`: deep-applies approved overrides to the
  base YAML in a temp workspace, builds everything, then atomically swaps the live
  pipeline (in-flight requests keep the old instance). Gated by
  `api.allow_rebuild`; governance overrides require `allow_governance_override`.
- **Ops** â€” `GET /v1/governance/status` (limits + spend window), `GET
  /v1/traces/{request_id}` (redacted trace from a bounded LRU), `GET /v1/metrics`
  (totals, per-stage p50/p95, failures, cost, guardrail decisions, cache) and
  `GET /metrics` (Prometheus exposition; 503 envelope when the `[observability]`
  extra is absent).
- **Audit** â€” `GET /v1/audit` over a bounded in-memory trail plus an optional
  append-only JSONL file (`config/audit.yaml`, disabled by default).
- **Guardrails** â€” input/output chains built from `config/guardrails.yaml`
  (`injection`, `pii`, `deny_list`, `schema_validator`, plus profiles); blocks return
  **403** with the failure taxonomy, decisions appear in results/traces/metrics/audit.
- **Config & secrets** â€” 10 YAML files with strict Pydantic schemas, `${VAR}` /
  `env:` secret resolution at load time, and fail-fast startup validation; the same
  checks run in CI via `python -m app.config_validate`.
- **Implementations behind the contract** â€” registries/factories for models,
  embedders, retrievers (vector, FAISS, hybrid, knowledge-graph), rerankers,
  evaluators, chunkers, query expanders and guardrails, all selected by config.
- **Console** â€” 10 screens (Â§6), a dependency-free 11-step tour, and a client that
  wraps every documented endpoint (HTTP only).

## 5. API surface v1 â€” endpoint matrix

Legend: **[E]**xisting. Every row is asserted by `tests/test_api_contract.py`
(`EXPECTED_PATHS` equality) and covered by endpoint tests.

| # | Method & path | Group | Notes |
|---|---|---|---|
| 1 | `POST /v1/query` | Core | `RAGPipeline.run`; `top_k`, `include_trace`, optional `documents` |
| 2 | `POST /v1/query:batch` | Core | sequential or parallel loop over #1; per-item envelopes + aggregate `summary`; `api.max_batch_size` |
| 3 | `POST /query` | Core | legacy alias of #1 (same envelope) |
| 4 | `GET /health` | Ops | liveness: process up |
| 5 | `GET /ready` | Ops | readiness: pipeline built; returns `config_revision` + `components` |
| 6 | `GET /v1/config` | Introspection | redacted effective config across all config files |
| 7 | `GET /v1/models`, `/v1/embedding-models` | Introspection | registry listings + active flags + active generation config |
| 8 | `GET /v1/retrievers`, `/v1/rerankers`, `/v1/evaluators` | Introspection | providers, default retriever, effective similarity metric, enabled flags |
| 9 | `GET /v1/guardrails` | Introspection | enabled/profile/providers + resolved input/output chains (previewable while disabled); per-section build errors reported, not raised |
| 10 | `GET /v1/access` | Introspection | RBAC roles/personas, capabilities, request caps (config-driven, disabled by default); includes the caller's resolved tenant |
| 10b | `GET /v1/tenants` | Introspection | tenant/workspace/app identity + per-tenant policy (budget cap, retrieval depth, model allow-list, overlays); caller's resolved tenant + all configured tenants (#48) |
| 11 | `POST /v1/evaluate` | Evaluation | active or named evaluator; auto-retrieval; ground truth only when supported |
| 12 | `POST /v1/experiments` | Evaluation | 202; single run or `compare_embedding_models` / `compare_chunking_strategies` |
| 13 | `GET /v1/experiments/{exp_id}` | Evaluation | status/result from the bounded experiment store |
| 14 | `POST /v1/pipeline:rebuild` | What-if | construct-then-swap overrides; gated by `api.allow_rebuild` |
| 15 | `GET /v1/governance/status` | Governance | limits from config + spend window + counters (reported even when disabled) |
| 16 | `GET /v1/traces/{request_id}` | Observability | last-trace store (bounded LRU); 404 `trace_not_found` |
| 17 | `GET /v1/metrics` | Observability | aggregate stage latencies (mean/p50/p95), failures by type/tag, cost, guardrails, cache |
| 18 | `GET /metrics` | Ops | Prometheus exposition of the same run counters (optional extra) |
| 19 | `GET /v1/audit` | Governance | audit events with `limit`/`event_type` filters; redacted |
| 20 | `GET /docs`, `GET /redoc`, `GET /openapi.json` | Docs | generated from the Pydantic models |

Cross-cutting (all endpoints): `/v1` ordering, error envelope per Â§3.4,
`X-Request-ID` echo, API-key auth **stub** (config-driven middleware, disabled by
default), and Pydantic response models so `/docs` is self-describing. Public paths
(`/health`, `/ready`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`) bypass the key.

## 6. UX architecture â€” Streamlit console (`ui/`)

**Choice: Streamlit for v1.** Pure Python (no JS toolchain), fast iteration, and its
widget strengths (sliders, tables, plots) match the experimentation persona. Gradio is
narrower (single-model demos), Dash/NiceGUI are not better here, and a
React/Next.js frontend is the *production product* path â€” deferred to a later phase
because it is only justified once the API is stable (roadmap workstream F). Constraint
from Â§3.2 applies to every UI: HTTP only, no `core.*` imports.

### Page map â†’ endpoint mapping

| Screen | User interactions | Endpoints |
|---|---|---|
| **Overview / Health** | status, readiness + config revision, active model/retriever/reranker/evaluator | `/health`, `/ready`, `/v1/models`, `/v1/embedding-models`, `/v1/retrievers`, `/v1/rerankers`, `/v1/evaluators` |
| **Query Studio** | enter query (or batch lines); `top_k`, rerank/include-trace; view answer, docs + scores, per-stage latency, cost, cache/guardrail/redaction/query-expansion flags, decisions table, resilience block, OTel ids, raw redacted trace | `/v1/query`, `/v1/query:batch`, `/v1/config` |
| **Compare (what-if)** | pick config overrides (metric, retriever, model); rebuild then run A/B queries | `/v1/pipeline:rebuild`, `/v1/query` |
| **Evaluation** | evaluator dropdown, optional ground truth, auto-retrieved docs; launch + poll experiments | `/v1/evaluators`, `/v1/evaluate`, `/v1/experiments`, `/v1/experiments/{exp_id}` |
| **Governance & Cost** | budget limits, spend window, per-request cost, guardrail hit-rate, raw Prometheus scrape | `/v1/governance/status`, `/v1/metrics`, `/metrics` |
| **Guardrails** | profile/enabled/providers, resolved chains, probe query decisions, hit-rate | `/v1/guardrails`, `/metrics` |
| **Audit** | filter by `limit`/`event_type`; inspect redacted events | `/v1/audit` |
| **Access / RBAC** | roles, capabilities, request caps, allowed models | `/v1/access` |
| **Traces** | look up `request_id`; stage latencies, failure taxonomy, guardrail decisions, resilience, OTel ids, raw trace | `/v1/traces/{request_id}`, `/v1/metrics` |
| **Settings (read-only)** | effective config viewer (redacted), model/provider/guardrail lists | `/v1/config`, `/v1/models`, `/v1/embedding-models`, `/v1/retrievers`, `/v1/rerankers`, `/v1/evaluators`, `/v1/guardrails` |

No config-editing UI in v1 (write path = files in `config/`); `pipeline:rebuild` in the
UI is expressed as preset "what-if" selections, keeping humans as the owners of YAML.
The sidebar also exposes the API base URL and the optional API key, and
`ui/tour.py` guides a first-run user through 11 steps (one per screen + connect).

## 7. Delivery record (was: proposed issues)

| Proposed | Delivered as | Where |
|---|---|---|
| **A** API foundation: lifespan (no import-time build), `/health`, `/ready`, `/v1`, error envelope + request IDs, auth stub | #30 | `431fa3b` |
| **B** Introspection: redacted `/v1/config`, model/retriever/reranker/evaluator listings | #35 (+ `/v1/guardrails` #86, `/v1/access` #54) | `941712c`, `4986daa` |
| **C** Evaluation & experiment endpoints + id store | #36 | `6dbba58` |
| **D** What-if `POST /v1/pipeline:rebuild` | #37 | `aa6b957` |
| **E** Governance/observability endpoints, Prometheus `/metrics` | #38, #44 | `389dbe9`, `14995db` |
| **F** Batch query endpoint | #39 (+ parallel inference #27) | `ca9ecc8`, `dcafc3a` |
| **G** Streamlit console (`ui/`), HTTP-only rule, README quickstart | #40, plus guardrails/audit/access coverage #82 | `fb4f214`, `85c70b0` |
| **H** Contract tests: OpenAPI snapshot + error envelope/taxonomy | #41 | `41caeaf` |
| (added during delivery) | audit trail `GET /v1/audit` | #28 `6b3cb1c` |
| (added during delivery) | guardrail introspection, profiles, hit-rate metrics | #86 `4986daa`, #88 `2b762ae`, #87 `5ab41ee` |
| (added during delivery) | docs reconciliation (this document) | #81 |

The forward roadmap (H0-H3, workstreams A-G) is tracked in
[enterprise-roadmap.md](enterprise-roadmap.md) and the GitHub Project board; API/UX
items beyond v1 (React console, pipeline composer, graph visualizations) are
workstream F there.

## 8. Delivery plan

- **P0 (this document)** â€” retrospective artifact; review gate. Done.
- **P1 â€” Phase-2 completion:** #16, #17, #18, #1, #34. Done.
- **P2 â€” API expansion:** A-F above, plus #42 ground-truth scoring, #21 evaluation
  engine, #22 benchmarks and #23-#29 retrieval/eval/ops features. Done.
- **P3 â€” UX console:** G above, kept strictly over the API (Â§3.2), plus README
  quickstart and a guided tour. Done.
- **P4 (optional, later)** â€” React/Next.js product frontend reusing the same OpenAPI
  contract; tracked as workstream F in the enterprise roadmap (not committed).
