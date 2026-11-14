# Capability status

> Canonical, evidence-based matrix of what this repository actually implements.
> It exists so the README, [roadmap](enterprise-roadmap.md) and
> [architecture](architecture.md) can be read without guessing which capabilities
> are real. Reconciled **2026-11-14**.

## How to read the status

| Status | Meaning |
| --- | --- |
| **Tested** | Implemented, wired through config/registries, and covered by automated tests that exercise the real path (or a structural guard where a browser/CLI is unavailable). |
| **Implemented** | Shipped and selectable, but coverage is structural or not exercised in CI (for example optional extras, no browser E2E). |
| **Partial** | A meaningful subset works; named gaps remain and are linked. |
| **Planned** | Not implemented. Tracked by an open issue or the roadmap umbrella; not claimed. |
| **External** | Provided by a system this repository integrates with but does not operate. |

Two rules keep this honest:

1. **An interface or stub is not a capability.** Status reflects wired, observable
   behaviour, not the existence of a contract.
2. **Implemented is not production-validated.** Passing tests prove behaviour on a
   single reference node, not capacity, security certification or regulatory
   fitness. See the [production-readiness gap assessment](production-readiness.md).

## Platform core

| Capability | Status | Evidence | Notes / gaps |
| --- | --- | --- | --- |
| Config-driven composition root + registries | Tested | `app/bootstrap.py`, `core/registry/`, `tests/test_composition_root.py` | Experiments reuse the same assembler (`tests/test_experiment_shared_assembly.py`). |
| Config schema validation + secret interpolation | Tested | `core/config/schema.py`, `core/config/validator.py`, `core/config/secrets.py`, `tests/test_config_validation.py` | `${VAR}` / `env:VAR`; `python -m app.config_validate` CLI. |
| LLM providers (local HF, OpenAI, dummy) | Tested | `core/implementations/hf_local_llm.py`, `core/implementations/openai_llm.py`, `tests/test_local_hf_llm.py`, `tests/test_openai_llm.py` | OpenAI tests self-skip without `OPENAI_API_KEY`. |
| Embedding models (MiniLM/mpnet, OpenAI, dummy) | Tested | `core/implementations/simple_embedder.py`, `core/implementations/openai_embedder.py`, `tests/test_openai_embedder.py` | Fail-fast when a model cannot load (`tests/test_embedder_fail_fast.py`). |
| Retrieval backends (FAISS, simple, hybrid BM25+vector, knowledge graph) | Tested | `core/implementations/faiss_retriever.py`, `core/implementations/hybrid_retriever.py`, `core/implementations/kg_retriever.py`, `tests/test_hybrid_retriever.py`, `tests/test_kg_retriever.py` | In-process indexes only; no production vector DB (see *Planned*). |
| Chunking strategies | Tested | `core/implementations/chunker.py`, `tests/test_chunking_wiring.py` | Word/fixed/token/small/large via `chunking.active_strategy`. |
| Reranking (cross-encoder, toggle) | Tested | `core/implementations/cross_encoder_reranker.py`, `tests/test_reranking_toggle.py` | `reranking.enabled` honored by the composition root. |
| Query expansion (noop/synonym/LLM) | Tested | `core/implementations/query_expanders.py`, `tests/test_query_expansion.py` | Default off; merged results de-duplicated. |
| Prompt construction + token budget | Tested | `core/services/prompt_builder.py`, `core/services/token_budget_service.py`, `tests/test_token_budget.py` | Modes `strict`/`truncate`, hard output cap. |
| Response cache (exact match, per-tenant namespace) | Tested | `core/services/response_cache.py`, `tests/test_response_cache.py` | **Process-local, single replica.** Semantic/prefix caching is Partial (see *Planned*). |
| Batching / parallel inference + `query:batch` | Tested | `app/pipeline.py`, `app/main.py`, `tests/test_batch_inference.py`, `tests/test_batch_query_api.py` | Bounded worker pool; order preserved. |

## Evaluation, experiments and gating

| Capability | Status | Evidence | Notes / gaps |
| --- | --- | --- | --- |
| Evaluators (semantic, LLM judge, dummy) + ground-truth scoring | Tested | `core/implementations/semantic_evaluator.py`, `core/implementations/llm_judge_evaluator.py`, `tests/test_ground_truth_scoring.py` | `answer_correctness` / `ground_truth_similarity` when references are supplied. |
| Benchmark datasets, IR metrics (precision/recall/MRR/nDCG), showcase reports | Tested | `core/evaluation/metrics.py`, `core/evaluation/showcase_report.py`, `tests/test_showcase_report.py` | Published reference numbers in [benchmarks](benchmarks/README.md). |
| Experiment runner + cost/latency comparison | Tested | `core/services/experiment_runner.py`, `tests/test_experiment_cost_latency.py` | Shares the composition root (#75). |
| Config sweep + Pareto recommendation | Tested | `core/evaluation/config_sweep.py`, `app/optimize.py`, `tests/test_config_sweep.py` | Budget-constrained recommendation + gate. |
| Regression gates (quality min, cost/latency max) | Tested | `core/evaluation/regression_gate.py`, `app/eval_gate.py`, `tests/test_budget_regression_gate.py` | Advisory CI job `Eval regression gates` (not a required status check). |
| Behavioral metrics (hallucination rate, drift time series) | Partial | `core/evaluation/eval_datasets.py`, `tests/test_eval_dashboard.py` | Eval trend/alerts exist; production-traffic sampling and hallucination/drift scoring are not implemented. Candidate follow-up under #43. |
| Prompt/model lifecycle + experiment registry | Partial | `config/prompt_config.yaml`, `core/config/generation_config.py`, `docs/engineering-lifecycle.md` | GitOps for config/policies and benchmark provenance exist; no MLflow-style prompt/model versioning or rollback UI. Candidate follow-up under #43. |
| FinOps chargeback / unit economics | Partial | `core/services/cost_tracker.py`, `core/services/attribution.py`, `tests/test_attribution.py` | Per-request cost, spend windows and attributed counters exist; no chargeback/ROI reporting view. Candidate follow-up under #43. |

## Governance, identity and safety

| Capability | Status | Evidence | Notes / gaps |
| --- | --- | --- | --- |
| Cost governance (budget caps, per-model pricing) | Tested | `core/services/cost_governor.py`, `core/services/cost_tracker.py`, `tests/test_cost_governor.py` | Denials surfaced in traces, metrics and the error envelope. |
| Guardrail framework + registry + profiles | Tested | `core/interfaces/guardrail.py`, `core/registry/guardrail_registry.py`, `tests/test_guardrail_framework.py`, `tests/test_guardrail_profiles.py` | `standard`/`strict` profiles; default off. |
| Prompt-injection / jailbreak defense | Tested | `core/implementations/injection_guardrail.py`, `tests/test_injection_defense.py` | Blocks direct injection, neutralizes untrusted retrieved docs. |
| PII / DLP | Tested | `core/implementations/pii_detector.py`, `core/implementations/pii_guardrail.py`, `tests/test_pii_dlp.py` | Regex classes + optional NER (extra model); **per-tenant PII policy is Partial**. |
| Policy-as-code (CEL bundles) + approval queue | Partial | `core/services/policy_engine.py`, `core/services/approval.py`, `tests/test_cel_policy_bundles.py`, `tests/test_hitl_approvals.py` | Engine, bundles and approvals API/queue are tested; **automatic in-pipeline blocking of `require_approval` decisions is not wired**. HITL console is #163/#164 (bot-win). |
| Immutable audit (hash chain, evidence, export, purge, regional routing) | Tested | `core/services/audit_store.py`, `tests/test_immutable_audit.py` | WORM-style chain with verify/export/purge endpoints. |
| Identity (OIDC/JWKS, SCIM, service accounts) | Tested | `core/services/identity.py`, `tests/test_identity.py` | Native SAML is **not** implemented; `identity.saml.enabled` fails fast to the OIDC bridge. |
| RBAC / access control | Tested | `core/services/access_control.py`, `tests/test_rbac_access_control.py` | Capability map per role; default-off preserves legacy behaviour. |
| Tenancy + request attribution | Tested | `core/services/tenancy.py`, `core/services/attribution.py`, `tests/test_tenancy.py`, `tests/test_attribution.py` | Budget caps, top_k/overlay policy, tenant-scoped ops; per-user dimensions opt-in. |
| Permission-aware retrieval (document ACL) | Tested | `core/services/acl.py`, `tests/test_acl_retrieval.py` | Over-fetch then filter before reranking/prompting; leak tests across backends. |
| Input redaction (query + docs before prompt) | Tested | `app/pipeline.py`, `tests/test_input_redaction.py` | Closes the raw-egress gap (#72). |
| Query-length guard | Tested | `core/services/guardrails.py`, `tests/test_query_length_guard.py` | `retrieval.guardrails.max_query_chars`; HTTP 400. |

## Observability and operations

| Capability | Status | Evidence | Notes / gaps |
| --- | --- | --- | --- |
| In-process traces, failure taxonomy, `/v1/metrics` | Tested | `core/services/observability.py`, `app/ops_api.py`, `tests/test_ops_api.py` | Source record for traces; bounded run/trace history. |
| Prometheus `/metrics` + Grafana pack + alerts | Tested | `core/services/telemetry.py`, `deployment/observability/`, `tests/test_prometheus_metrics.py` | Requires the `[observability]` extra. |
| OpenTelemetry tracing (OTLP) | Implemented | `core/services/telemetry.py`, `config/observability.yaml`, `tests/test_otel_tracing.py` | Optional `[observability]` extra; span tests skip in CI when absent. |
| Provider resilience (retries, circuit breaker, failover) | Tested | `core/services/resilience.py`, `tests/test_resilience.py` | Default off; chain configured in `config/resilience.yaml`. |
| Persistence (`BaseStore`: memory/SQLite/Postgres) + backup/restore | Implemented | `core/services/base_store.py`, `core/services/store_backends.py`, `tests/test_backup_restore.py` | Memory/SQLite tested; Postgres backend requires a server (not exercised in CI). |
| Durable shared state for traces/experiments/approvals | Partial | `core/services/audit_store.py`, `app/ops_api.py`, `app/evaluation_api.py` | Audit store is pluggable; run history, traces, experiment store and approvals are process-local by default. Tracked by **#192** and **#206**. |
| Ingestion pipeline + connectors (S3/GCS/Azure Blob/Confluence/SharePoint) | Tested | `core/services/ingestion_service.py`, `core/implementations/connectors/`, `tests/test_ingestion_framework.py`, `tests/test_connectors_object_storage.py` | Connectors use vendor SDKs/HTTP; incremental/CDC sync is **Partial**. |

## Console and delivery

| Capability | Status | Evidence | Notes / gaps |
| --- | --- | --- | --- |
| Streamlit console (HTTP-only, 11 screens) | Implemented | `ui/app.py`, `ui/client.py`, `tests/test_ui_console.py` | Structural/client tests only (no browser E2E); UX tranche #157/#158 open (bot-win). |
| Hardened container + Compose single node | Tested | `deployment/Dockerfile`, `deployment/docker-compose.yml`, `tests/test_deployment_artifacts.py` | Non-root, healthcheck, resource limits, config mount. |
| Helm chart + Kustomize overlays + GitOps example + deploy smoke | Tested | `deployment/helm/`, `deployment/kustomize/`, `deployment/gitops/`, `tests/test_deployment_gitops.py` | Advisory CI job `Deploy smoke (chart + image)`. |
| HA / autoscaling (HPA + KEDA) | Tested | `deployment/helm/genai-platform/templates/hpa.yaml`, `deployment/helm/genai-platform/templates/keda-scaledobject.yaml`, `tests/test_deployment_ha.py` | Depends on durable state for correctness (see *Partial* above). |
| Progressive delivery (Argo Rollouts canary/blue-green) | Tested | `deployment/helm/genai-platform/templates/rollout.yaml`, `tests/test_deployment_progressive_delivery.py` | Rollback runbooks in `docs/deployment.md`. |
| Multi-region / residency / DR + Terraform | Tested | `config/residency.yaml`, `config/dr.yaml`, `docs/dr-runbook.md`, `tests/test_multi_region_dr.py` | Operational DR execution/drills remain **Partial** (#118-#120 landed tooling; execution is a practice, not a test). |
| GitOps at scale (ArgoCD app-of-apps, Flux, promotion) | Tested | `deployment/gitops/`, `deployment/terraform/`, `tests/test_gitops_scale.py` | — |
| Codespaces devcontainer | Tested | `.devcontainer/devcontainer.json`, `deployment/codespace/`, `tests/test_codespace_deployment.py` | Boots API + console; no model downloads in the default smoke. |
| Reference load/latency harness + published numbers | Tested | `core/evaluation/load_harness.py`, `benchmarks/load/run_load.py`, `tests/test_load_harness.py` | Single-node reference CPU numbers, not capacity guarantees. |

## Planned or unqualified (not claimed)

| Capability | Status | Tracked by | Notes |
| --- | --- | --- | --- |
| Production-readiness gap assessment | Implemented | [production-readiness.md](production-readiness.md) | Published; separates implemented from production-validated and prioritizes gaps by operational risk. |
| Durable multi-replica deployment profile | Planned | #206 | Requires shared persistence, coordination and failover validation. |
| Independent security validation (threat model, adversarial testing) | Planned | #205 | Unit tests are not a penetration test. |
| Engineering-team adoption / pilot kit | Planned | #204 | Onboarding guide and golden paths exist; a packaged pilot kit does not. |
| Semantic / prefix caching | Planned | #43 | Exact-match cache only; process-local. |
| Async pipeline + token streaming (SSE/WebSocket) | Planned | #43 | The API is request/response only. |
| Production vector backends (pgvector/Qdrant/Milvus/Weaviate) | Planned | #43 | Retrieval is FAISS/in-process today. |
| Native SAML 2.0 SSO | Planned | #43 | OIDC is supported; SAML is bridged via the IdP, not implemented here. |

## Where the gaps are tracked

- **[Production-readiness gap assessment](production-readiness.md)** - the operational-risk view of where this matrix's *Partial*/*Implemented* rows fall short of a production deployment.
- **[#204](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/204)** / **[#205](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/205)** / **[#206](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/206)** - adoption kit, security qualification, durable multi-replica profile.
- **[#43](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/43)** - roadmap umbrella; carries roadmap-level candidates (semantic cache, streaming, real vector backends, behavioral metrics, prompt/model lifecycle, chargeback) until they are prioritized into dedicated issues.
- **[#157](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/157)** / **[#158](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/158)** - remaining UX tranche (bot-win).
- **[#163](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/163)** / **[#164](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/164)** - HITL console on the #123 approval contract (bot-win).

## Maintenance

- Update a row when behaviour, wiring or coverage changes; move a capability out of
  *Planned* only when it is implemented **and** has evidence.
- Keep the evidence paths real - `tests/test_capability_status.py` fails if a cited
  path or an unknown status appears.
- When a gap gets its own issue, replace the `#43` reference with the issue link.
