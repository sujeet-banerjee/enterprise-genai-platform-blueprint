# Enterprise Roadmap — From Reference Blueprint to Production AI Platform

> **Status: proposal for review (2026-10-20).** No issues have been created from this document
> yet. It is a *broad-level* north star, deliberately beyond a single sprint commit. It maps the
> current reference blueprint to what an enterprise actually needs to run GenAI in production,
> and proposes a UI roadmap that removes the operational pain points teams hit after the demo.

---

## 1. Where we are today (honest self-assessment)

This branch grew in three deliberate phases (`git log`):

| Phase | What landed | Commits |
|---|---|---|
| **Foundations** | Pluggable vendor registry, `ScoredDocument`, reranking, FAISS, token budgets, observability, CI (ruff/mypy/pytest + coverage gate) | `e32e433` → `b0e091b` |
| **Phase 2 — config-driven completion** | Every component resolved from config via registries; every declared flag honored (reranking/governance/evaluation/token-budget/similarity-metric/chunking); OpenAI + real cost from tokens; fail-fast embedder; split governance/observability configs | `1158333` → `908b432` (issues #1, #5–#19, #34) |
| **Phase 3 — API, UX, extensions** | App factory + lifespan + error envelope; introspection/evaluate/experiments/rebuild/governance/traces/metrics/batch endpoints; Streamlit console (HTTP-only); query expansion, KG + hybrid retrieval, cache, batching, audit log, RBAC, ground-truth scoring, benchmark runner, examples | `431fa3b` → `c5724e2` (issues #21–#42) |

**What we have now (genuinely strong):**

- A **config-driven composition root**: swapping model/embedder/retriever/reranker/evaluator/
  expander is a YAML change; `app/main.py` imports only interfaces/registries.
- **Vendor neutrality** behind stable contracts (`core/interfaces/*`) with registries
  (`core/registry/*`) and 15+ concrete providers.
- **Evaluation-first** design: semantic, LLM-judge, ground-truth scoring, benchmark runner,
  true IR metrics (`context_precision_at_ids`, `context_recall_at_ids`).
- **Governance/economics**: token budget modes, per-model pricing, cost governor, spend
  windows, retrieval policy.
- **Observability**: structured per-request traces, failure taxonomy (20 classes), redaction,
  audit log, `/v1/metrics`.
- **Safety**: input/doc redaction (#72), query-length bound (#73), and a pluggable
  input/output guardrail framework (#52).
- **API + a proof-of-contract UI**: 20+ endpoints, OpenAPI, error envelope, RBAC, and a
  Streamlit console that talks *only* HTTP.
- **Engineering hygiene**: 507 tests + 2 skipped, coverage gate ≥78%, green CI on 3.11/3.13,
  runnable examples.

**What we do *not* yet have (the enterprise gap):** everything below is about the distance
between "credible reference blueprint" and "a platform an enterprise can run, govern, and
trust at scale." The reference intentionally stopped short of these (see architecture §1.1);
this roadmap is the bridge.

---

## 2. The pain points we are solving (grounded in the field)

Across AWS's Generative AI Lifecycle Operational Excellence (GLOE) framework, the InfoQ
*Platform Engineering Playbook for Production LLMs*, Futurum's 2026 platform-engineering
study, and the pilot-to-production failure analyses, the same failure pattern recurs. It is
**never the model** — it is the operational scaffolding:

1. **Demo-to-production gap.** PoCs run on clean data and manual steps; production hits
   scaling, security, and real-world data variability.
2. **No behavioral observability.** Latency/error dashboards look healthy while output quality
   silently drifts. Traditional APM cannot see hallucination rate, prompt drift, grounding
   failures, or tool-call patterns.
3. **Unbounded / unattributable cost.** Without per-team, per-app, per-use-case token
   attribution, the monthly bill is one opaque line item.
4. **Missing evaluation & regression gates.** Subjective demo judgment; no automated,
   objective, continuous evaluation; no golden sets; no prompt-version regression detection.
5. **Absent governance & guardrails.** No prompt-injection/jailbreak defense, no PII/DLP at the
   edge, no policy-as-code, weak audit trails.
6. **Permission-unaware retrieval.** Vector search leaks documents a user should not see.
7. **Fragmented, duplicated stacks ("Shadow AI").** Every team rebuilds the same scaffolding;
   model APIs are procured outside IT controls.
8. **No clear ROI story** connecting AI quality to business and operational metrics.
9. **New threat landscape**: prompt injection, jailbreaking, data poisoning.
10. **Deterministic vs stochastic engineering mismatch**: existing CI/CD, rollback, and
    change-management disciplines don't cover prompts, models, and retrieval configs.

**The differentiator we already own:** most "enterprise GenAI platforms" (Bedrock, Vertex AI,
Azure AI Foundry, Databricks, LangSmith/LangFuse, W&B Weave, Galileo, Arize, TruLens, RAGAS
Cloud, Vectara, Glean) are **opinionated, cloud-bound, or single-concern** (either tracing-only,
eval-only, or gateway-only). They tend to fail enterprises on **vendor lock-in**, **bring-your-
own-model/vector-store neutrality**, **policy portability**, and **the ability to run entirely
inside the enterprise boundary**. Our blueprint's config-driven vendor neutrality is exactly the
counter-position — but it needs the surrounding platform maturity to be taken seriously.

---

## 3. North star

> **A vendor-neutral, self-hostable AI control plane**: any team can onboard a RAG/agent
> workload, get evaluation + guardrails + cost attribution + full traces by default, swap any
> vendor by config, and prove to risk/compliance that every answer is governed — without
> leaving the enterprise boundary and without rebuilding scaffolding.

Guiding principles (extend the existing ones):

- **Neutral by construction** — no single cloud/model/vector store is privileged.
- **GitOps + policy-as-code** — prompts, models, retrieval, and guardrails are versioned
  artifacts; governance is declarative, not a separate function.
- **Observability is a product, not a log** — traces/metrics/evals feed the UI and the gates.
- **Config-driven, still** — every new capability lands behind an interface + registry + flag.
- **Attribution from request one** — team/app/use-case/cost must exist on the *first* call.

---

## 4. Capability roadmap (broad level)

Organized as **workstreams**. Each is independent enough to parallelize; sequencing is in §7.
Issue IDs are placeholders (`E-*`) — not yet created.

### Workstream A — Multi-tenancy, identity & attribution

*Pain: Shadow AI, unattributed cost, fragmented governance, permission-unaware retrieval.*

- **A1. Tenant/workspace model** — first-class `tenant`/`workspace`/`app` on every request;
  namespace config, cache, audit, spend, and vector indexes per tenant.
- **A2. Real identity** — replace the API-key stub with **OIDC/OAuth2 (JWT)**, SAML for SSO,
  SCIM for provisioning; map IdP groups → RBAC roles; service accounts + scoped API keys.
- **A3. Attribution pipeline** — propagate `tenant/app/user/cost-center` via request context
  into every trace, audit event, and metric from call one (the InfoQ "team dimension" rule).
- **A4. Permission-aware retrieval (document-level ACL)** — carry caller identity into
  retrieval; filter chunks by ACL at query time; per-tenant index isolation; leak tests.

### Workstream B — Safety, security & governance guardrails

*Pain: prompt injection, jailbreak, PII/DLP, compliance, red teaming.*

> **Audit note (2026-10-21):** tracing the end-to-end `RAGPipeline.run` path showed that today
> **only observability output is redacted** — the query and retrieved docs reach the model
> provider and the client **raw**. This is a real egress gap. It is tracked as **#72 (input-side
> redaction, H0)** and the surrounding gaps as umbrella **#73** (injection, PII/DLP, framework,
> query-length bounds). #72 is implemented first as the lowest-risk slice; the rest plug into B1-B3.
>
> **Progress (2026-10-21):** **#72 input/doc redaction (H0, PR #76)** and the **#52 `BaseGuardrail`
> framework + registry (B1, PR #79)** are landed; the query-length bound slice of #73 is also done
> (PR #78). Remaining B-slices: **#53 injection/jailbreak defense (B2)** and **#54 PII/DLP (B3)**,
> which plug into the same `guardrail_input`/`guardrail_output` seam.

- **B1. Guardrail framework** — pluggable pre/post stages behind a new `BaseGuardrail`
  interface + registry: input classifier, output classifier, schema/format validation.
  **Landed (#52, PR #79):** `core/interfaces/guardrail.py` + `core/registry/guardrail_registry.py`
  + `config/guardrails.yaml` (default off); ordered input/output chains; block → governed failure,
  redact rewrites text.
- **B2. Prompt-injection & jailbreak defense** — input sanitization + injection heuristics +
  optional classifier model; adversarial test suite (red teaming in CI).
- **B3. Data privacy / DLP** — PII detection & redaction at ingress/egress (extend the existing
  `SensitiveDataRedactor` from regex to NER-based detection); configurable per-tenant policy.
  **#72 (input/doc redaction before prompt construction) is the first slice of this.**
- **B4. Policy-as-code engine** — declarative policies (OPA/Rego or an embedded rule DSL) that
  gate ingress, retrieval, generation, and egress; versioned and testable.
- **B5. Audit & compliance exports** — immutable (append-only/WORM) audit trail, retention
  policies, SOC2/EU-AI-Act/GDPR evidence packs, data-residency controls.
- **B6. Human-in-the-loop (HITL) review** — queue + UI for flagging/escalating low-confidence
  or high-risk answers; approval workflow before release.

### Workstream C — Observability & evaluation as a product

*Pain: no behavioral observability, silent drift, no regression gates, no ROI link.*

- **C1. OpenTelemetry-native tracing** — emit spans/metrics/logs via OTLP so traces land in
  Jaeger/Tempo/Grafana/Datadog; keep the in-process trace as the source record.
- **C2. Prometheus + Grafana stack** — `/metrics` Prometheus exposition (deferred in #38),
  ship a **Grafana dashboard pack** (latency p50/p95/p99, cost, failure taxonomy, cache hit
  rate, guardrail blocks) and **alert rules**; optional `docker-compose` profile for the stack.
- **C3. Behavioral quality metrics** — hallucination rate (schema + grounding failures),
  **prompt/model drift** across versions, groundedness, answer-relevance distributions,
  tool-call patterns; sampled offline evaluation of production traffic vs a golden set.
- **C4. Continuous evaluation & regression gates** — scheduled eval runs against golden
  sets/benchmarks; **CI gate**: a prompt/model/config change that regresses a metric beyond a
  threshold fails the pipeline; leaderboards per use case.
- **C5. Prompt/model lifecycle & experiment registry (MLflow-style)** — version, diff, and
  roll back prompts, generation configs, and model routing; tie every eval/trace to a version;
  **GitOps** for AI assets.
- **C6. FinOps & ROI** — token/cost showback & chargeback per tenant/app/use-case; budget
  alerts; unit economics per accepted answer; a business-impact view in the UI.

### Workstream D — Serving, scale & reliability

*Pain: latency blow-ups, throttling, throughput, resilience.*

- **D1. Provider resilience** — retries with backoff + jitter, circuit breakers, **multi-provider
  failover/routing** (cost/latency/capability-aware), rate-limit handling.
- **D2. Semantic + exact caching tiers** — extend the exact-match `ResponseCache` with
  embedding/prefix-semantic caching and per-tenant cache namespaces; KV/prompt-cache affinity.
- **D3. Async & streaming** — async pipeline path, token **streaming** (SSE/WebSocket) end to
  end including the UI; backpressure and queueing.
- **D4. Real vector scale** — production vector backends (pgvector, Qdrant, Milvus, Weaviate,
  Pinecone) behind the existing `BaseRetriever`; index lifecycle (build/refresh/reindex),
  hybrid at scale, metadata filtering.
- **D5. Ingestion pipeline** — real document ingestion → parsing → chunking → embedding →
  indexing, with incremental/CDC sync, connectors (S3/SharePoint/Confluence/DB), and lineage.
- **D6. Deployment & ops maturity** — hardened container (non-root, `pip install .`), Helm
  chart, Kubernetes deployment + HPA/KEDA autoscaling, health/readiness/liveness, graceful
  shutdown, blue-green/canary rollouts, rollback incl. model/prompt versions.

### Workstream E — Platform engineering

*Pain: fragmented stacks, reproducibility, change management.*

- **E1. Plugin/extension SDK** — a stable, documented way for teams to add providers,
  guardrails, evaluators, and connectors without forking core (formalize the registry `register`).
- **E2. Config schema & validation** — JSON Schema/Pydantic for every `config/*.yaml`; typed
  settings, `config validate` command, migration/versioning, env/secret interpolation.
- **E3. Secrets management** — Vault / cloud secret managers / K8s secrets; no secrets in YAML;
  rotation.
- **E4. State & persistence** — move run/trace/experiment/audit stores from in-memory to a
  pluggable persistence layer (Postgres) so they survive restarts and scale horizontally.
- **E5. GitOps delivery** — IaC (Terraform/Helm) + ArgoCD/Flux reconciliation for config,
  prompts, and policies; environment promotion (dev→staging→prod).
- **E6. Multi-region/residency & DR** — data-residency routing, backup/restore, disaster
  recovery, HA topology.

### Workstream F — UI/UX: the enterprise console

*Pain: operators/analysts are forced into YAML and CLI; no visual way to reason about quality,
cost, and behavior; no drag-and-drop composition; no topology visibility.*

The current Streamlit console proves the API contract but is deliberately read-mostly and
single-user. The enterprise console is a **product surface** with distinct jobs for distinct
personas. Two-track plan: **evolve Streamlit first** (fast, Python-only) then **graduate to a
React/Next.js product frontend** (reusing the same OpenAPI), justified once multi-user RBAC and
real-time visualization become must-haves.

**F0. Personas → screens (target information architecture)**

| Persona | Job | Screens |
|---|---|---|
| Platform admin | Onboard teams, set budgets/policies, manage models/retrievers | Admin, Tenancy, Policy, Model Registry, Providers |
| AI/RAG engineer | Build & tune pipelines, compare variants, debug | **Pipeline Composer (drag-and-drop)**, Query Studio, Playground, Experiments, Traces |
| Evaluator/analyst | Measure, benchmark, detect regressions, prove ROI | Evaluation, Benchmarks, Leaderboards, Quality, ROI/FinOps |
| Risk/compliance | Prove governance, review incidents, export evidence | Governance, Guardrails, Audit, HITL Review, Compliance Reports |
| Ops/SRE | Health, latency, cost, incidents | Overview, Dashboards (embedded), Incidents, Alerts |

**F1. Drag-and-drop pipeline composer** — visual canvas where a user assembles a pipeline from
palette nodes (Embedder → Retriever → Reranker → Guardrails → Prompt Builder → LLM → Evaluators
→ Governance) and **exports the equivalent per-tenant YAML** (`pipeline:rebuild`/`config`
endpoints already exist). Node settings surface the real config schema (E2). Validation runs
live (dimension/context mismatches fail fast). Versioned, diffable, promotable via GitOps (E5).

**F2. Dynamic graph visualizations**
- **Retrieval provenance graph** — a D3/Cytoscape query→reranked-docs→answer graph with edge
  weights = scores; click a node to inspect the chunk and its source.
- **Knowledge-graph explorer** — visualize entity/triple neighborhoods (builds on #24).
- **Pipeline topology graph** — live node graph annotated with per-stage latency, cost, failure
  tags, and health; the *operational* twin of the composer.
- **Eval/drift time series** — quality metrics per prompt/model version with regression markers.
- **Cost/attribution sunburst** — tenant → app → use-case → model cost breakdown.
- **Trace waterfall** — span timeline (OTel) with drill-down (C1).

**F3. Experiment & comparison UX** — side-by-side A/B of models/chunking/top_k/rerankers with
metric deltas, statistical notes, and "promote winner" → config change; leaderboards.

**F4. Governance & guardrail console** — policy editor (policy-as-code with validation), 
guardrail hit-rate dashboards, **HITL review queue**, audit search, and one-click compliance
evidence export.

**F5. Multi-tenant admin & RBAC UI** — tenant/team/user management (fed by OIDC, A2), budget
assignment, quota views, per-tenant config editing (write path — the current UI is read-only by
design; this is the deliberate upgrade, gated by approval/GitOps).

**F6. Real-time & collaboration** — live streaming answers, shared saved queries/dashboards,
comments on traces, notifications/alerts.

**F7. Design & accessibility** — enterprise design system, WCAG 2.2 AA, keyboard-first
composer, light/dark, i18n; embeddable widgets (dashboards in the customer's own portal).

### Workstream G — Deployment & delivery

*Pain: an enterprise cannot answer "how do we run this next to production RAG/agentic workloads?" — the container is naive, and deployment modes/processes/tools are undocumented.*

A blueprint is only adoptable if it is **deployable**. This workstream makes the platform genuinely
runnable beside production, **cloud-agnostic first** (Kubernetes/Helm primary, Docker Compose
supported), with cloud-specific IaC as a long-term goal. Agentic workflows are **bring-your-own**:
we ship the *seams* (worker/queue topology, checkpointing, per-tool egress) rather than an agent
framework (§8 non-goal).

- **G0. Hardened container + single-node reference** — multi-stage, non-root, healthchecked image
  built from the real dependency files; `.dockerignore`; a backward-compatible **config-path env
  seam**; a genuine Docker Compose single-node reference (config mounts, volumes, limits, probes).
- **G1. Deployment playbook (`docs/deployment.md`)** — deployment **modes** (local, Compose,
  Kubernetes, air-gapped/on-prem, managed-cloud/BYO-model, embedded/sidecar), **processes**
  (config/prompt/model promotion, versioning, migration, rollback, blue-green/canary, backup/restore),
  **tools** (Helm/Kustomize, ArgoCD/Flux, KEDA/HPA, Secrets/External Secrets), and agentic/RAG
  topology seams.
- **G2. Reference delivery artifacts** — a lean **Helm chart** + Kustomize overlays, a GitOps
  example, and a CI build+`/health` smoke test so "deployable" is verified, not asserted.
- **G3. Multi-replica / HA + autoscaling** — replication with shared state, HPA/KEDA. *Depends on
  E4 (persistence).*
- **G4. Progressive delivery** — canary/blue-green, versioned config/prompt/model rollback, upgrade
  migrations, runbooks.
- **G5. GitOps at scale** — ArgoCD/Flux reconciliation, environment promotion pipelines, IaC.
- **G6. Multi-region / residency / DR + cloud-specific IaC** — the deferred long-term depth.



## 5. How this maps onto the existing architecture (minimal blast radius)

The good news: **the blueprint's separation of concerns is exactly right for this.** Each new
capability slots in behind an existing pattern:

- Guardrails → `core/interfaces/guardrail.py` + `core/registry/guardrail_registry.py`
  (mirrors reranker/evaluator). **Implemented (#52).**
- Identity/tenancy → middleware + `AccessController` extension (already request-scoped).
- OTel/Prometheus → a new `core/services/telemetry.py` alongside
  `PipelineObservabilityTracker`; nothing in the pipeline changes.
- Persistence → swap the in-memory stores (`RunHistory`, experiment store, `AuditLogger`) behind
  a `BaseStore` interface.
- Vector scale → new `BaseRetriever` providers (already the extension recipe, architecture §15).
- UI composer → consumes existing `/v1/config`, `/v1/pipeline:rebuild`, `/v1/*introspection`;
  exports YAML, never imports `core.*` (the standing HTTP-only rule).
- Deployment → packaging/docs/chart are **additive** under `deployment/` + `docs/`; the only code
  change is a small, backward-compatible config-path env seam in the composition root.

This is the payoff of the config-driven investment: **the roadmap is additive, not a rewrite.**

---

## 6. What "enterprise-grade" means as acceptance criteria

A capability is only "done" when it is:

1. **Pluggable** — behind an interface + registry + config flag (default-safe).
2. **Attributable** — carries tenant/app/user/cost context.
3. **Observable** — emits traces + metrics; surfaces in the UI.
4. **Governed** — enforceable, auditable, policy-controllable.
5. **Tested** — unit + integration/e2e with real components; contract tests; ≥ coverage gate.
6. **Documented** — architecture + config mapping + README + example.
7. **Deployable** — produces a hardened container + Helm chart (or Compose) with health/readiness
   probes and a rollback path; `docs/deployment.md` covers the deployment mode; CI builds the image
   and verifies `/health`. (Not just "it runs on my machine.")

---

## 7. Suggested sequencing (broad level)

| Horizon | Theme | Workstreams | Outcome |
|---|---|---|---|
| **H0 — Now (0–1 mo)** | Finish the foundation & make it operable | C2 (Prometheus/Grafana + dashboard pack), D1 (resilience/failover), E2 (config schema/validation), E3 (secrets), C1 (OTel), **G0 (hardened container + Compose), G1 (deployment playbook), B3-slice #72 (input/doc redaction before prompt)** | The platform is observable, hardened, **deployable**, and no longer leaks raw secrets in the query/doc path; ops can adopt it. |
| **H1 (1–3 mo)** | Multi-tenant & governed | A1–A4, B1–B3, B5, E1, E4, F5 (admin), **G2 (Helm + Kustomize + GitOps example + CI deploy smoke)** — *B1 (#52) landed* | Teams can onboard safely; access and cost are attributable; guardrails + audit are real; it installs on Kubernetes. |
| **H2 (3–6 mo)** | The product surface | C3–C6, D2–D5, F1–F4 (composer, graphs, experiments, governance console), **G3 (HA/autoscale), G4 (progressive delivery)** | This becomes a *platform teams want to use*: visual, measurable, ROI-provable, safely rollout-able. |
| **H3 (6–12 mo)** | Enterprise scale & compliance | B4, B6, D6, E5, E6, F6, F7, **G5 (GitOps at scale), G6 (multi-region/DR + cloud IaC)** | Runs at scale, in-region, GitOps-managed, compliance-evidenced, multi-team. |

**Dependency notes:** A (identity) unblocks B/C attribution and F5; E2 unblocks F1 (schema-driven
composer); C1 unblocks the trace-waterfall graph (F2); E4 should precede C5/C6 production use **and
G3 (multi-replica) — do not scale out before persistence lands**. G0/G1 are prerequisites for every
later deployment item.

---

## 8. Explicit non-goals (keep the blueprint honest)

- Not a managed SaaS or a model marketplace.
- Not a general-purpose agent framework (though agent observability hooks fit C/D).
- Not a fine-tuning/training platform.
- Not a proprietary cloud lock-in play — self-hostable and BYO-everything stay first-class.

---

## 9. Open questions for the next review

1. **Frontend graduation**: when do we move Streamlit → React/Next.js (F-track)? Trigger =
   multi-user RBAC + real-time graphs become must-haves.
2. **Persistence default**: Postgres as the first-class store, or keep pluggable with SQLite for
   dev? (Leaning: `BaseStore` interface, Postgres reference impl.)
3. **Policy engine**: OPA/Rego (industry standard, external) vs an embedded Python rule DSL
   (simpler, no sidecar)? 
4. **First real vector backend** to feature: pgvector (lowest ops cost) vs Qdrant/Milvus?
5. **Prometheus vs OTel-only**: expose both, or OTel collector as the single exporter?
6. Which workstream is the **next concrete PR** after approval? (Recommendation: **H0 / C2 +
   D1**, since they extend existing services and deliver immediate ops value.)

---

## 10. Relationship to existing docs

- `docs/architecture.md` — current architecture + Phase 1–3 history (#5–#42).
- `docs/ux-and-api.md` — API-first rule + Streamlit v1 plan (this doc's F-track is its P4/P5).
- `Daywise-4hourly-execution-plan.csv` — the original 30-day build plan (fully landed).
- This document — the **post-blueprint** enterprise bridge.

## 11. How this roadmap is tracked

- Umbrella issue: **#43** (`[Roadmap] Enterprise platform bridge`).
- Deployment is a first-class workstream: umbrella **#64** (`[Roadmap] Workstream G - Deployment & delivery`).
- Security audit follow-ups: **#72** (input-side redaction, H0) + umbrella **#73** (guardrail gaps
  across the RAG invocation flow) — #72, the query-length bound, and the **#52** `BaseGuardrail`
  framework are landed; **#53** (injection) and **#54** (PII/DLP) remain.
- Reconciliation & console-coverage follow-ups: **#81** (reconcile `docs/**` with the shipped
  surface, H1) and **#82** (surface audit/RBAC/guardrails/resilience/OTel/cache + `/metrics` in the
  Streamlit console, H2).
- Horizons are GitHub **milestones**: `H0 - Observability & hardening`,
  `H1 - Multi-tenant & governed`, `H2 - Product surface`,
  `H3 - Enterprise scale & compliance`.
- Horizons are opened **lazily**: H0 (#44–#47, **#65 G0, #66 G1**), H1 (#48–#57, **#67 G2**) are
  opened now; H2/H3 items (incl. **#68 G3, #69 G4, #70 G5, #71 G6**) are filed but stay the
  checklist in #43/#64 until their horizon activates.
- The Project v2 board (**#8**) carries a **Workstream** field (A–G + Cross-cutting) for slicing.
- Contribution workflow (branching, PR checklist, release tags) is in
  [`CONTRIBUTING.md`](../CONTRIBUTING.md).
