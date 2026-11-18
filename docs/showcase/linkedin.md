# LinkedIn showcase package (#193)

> **Draft for review. Not published.** The user approves the wording and publishes through
> the LinkedIn UI; this repository never logs in to LinkedIn or edits the profile.
>
> Status: **awaiting user approval** (reviewed against `main` @ `c8eb3a8`, 2026-11-15).
> Canonical naming, tagline and maturity vocabulary come from
> [positioning.md](../positioning.md). Capability language comes from
> [capability-status.md](../capability-status.md).

Two deliverables, in order:

1. A durable **Projects-section entry** on the LinkedIn profile (the primary deliverable).
2. A separate **announcement post** that points readers at that entry and the repository.

## 1. Profile entry (review-ready)

### Fields

| Field | Proposed value | Status |
| --- | --- | --- |
| Project title | `Enterprise GenAI Platform Blueprint — Reference Architecture` | Recommend; contains the canonical name plus a recruiter-friendly descriptor. Approve final wording. |
| Project URL | `https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint` | Ready |
| Associated with | **Leave blank** (independent portfolio project) | CONFIRM. Do not attach to an employer or client unless the user explicitly confirms it is accurate. |
| Start date | **CONFIRM — user to supply** | Do not infer from git history; the repository history does not prove project start. |
| End date | **Leave empty** while the project is ongoing | CONFIRM |
| Skills | See below (select up to five) | CONFIRM against LinkedIn's current taxonomy |
| Featured media | See below | CONFIRM |

### Description (first person, ready to paste)

> I designed and built this independent, MIT-licensed reference implementation to answer a
> problem I kept running into in enterprise GenAI programmes: retrieval, generation,
> evaluation, governance and operations tend to become shaped around one vendor, so swapping
> a model or an evaluator turns into a rewrite.
>
> The repository is a self-hostable Python platform where configuration selects the LLM,
> embedding model, retriever, reranker, evaluator and guardrails. One HTTP API exposes query
> and batch execution, evaluation and experiments, runtime pipeline rebuild, guardrail
> introspection, tenancy/identity/RBAC, immutable audit, approvals and operational metrics.
> Every request carries a trace, cost record and failure taxonomy, and Prometheus,
> OpenTelemetry and a Streamlit console consume the same public API.
>
> My contribution spans the architecture, interfaces and registries, composition root,
> pipeline, API contracts, guardrails (injection and PII), tenancy, identity, audit,
> deployment artefacts, evaluation and benchmark harness, CI quality gates, and the
> documentation.
>
> It is a reference implementation, not a production-certified product: the capability
> status matrix and production-readiness assessment state, with evidence, what is tested,
> partial or planned.

Character count is checked by `tests/test_showcase_linkedin.py` against LinkedIn's 2,000
character project-description limit.

### Skills (suggest five)

Choose from LinkedIn's own taxonomy when adding the entry; these map to demonstrated work:

| Suggested skill | Evidence |
| --- | --- |
| Generative AI | `core/implementations/`, `config/models.yaml` |
| Retrieval-Augmented Generation (RAG) | `core/implementations/faiss_retriever.py`, `core/implementations/hybrid_retriever.py` |
| Large Language Models (LLMs) | `core/implementations/hf_local_llm.py`, `core/implementations/openai_llm.py` |
| AI Governance | `core/services/policy_engine.py`, `core/services/audit_store.py`, `core/registry/guardrail_registry.py` |
| Software Architecture | `docs/architecture.md`, `docs/architecture-diagram.md`, `app/bootstrap.py` |

Optional sixth if the UI allows: **Python** (`app/`, `core/`), **API Development**
(`app/main.py`, `app/schemas.py`), or **Observability** (`core/services/telemetry.py`).

### Featured section (supporting media)

Link, do not duplicate the description:

| Media | Link |
| --- | --- |
| Architecture diagram | `https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/docs/architecture-diagram.md` |
| Reproducible benchmark results | `https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/docs/benchmarks/README.md` |
| Codespaces demo | `https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/deployment/codespace/README.md` |
| Comparison with alternatives | `https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/docs/comparison.md` |

The end-to-end demo walkthrough (#189, bot-win) is not yet merged. Add it to Featured when
it lands; do not claim a recorded demo exists before then.

## 2. Announcement post (ready to paste)

> I have been building in the open: **Enterprise GenAI Platform Blueprint** — a
> vendor-neutral, self-hostable reference implementation for enterprise GenAI and RAG.
>
> The problem: enterprise GenAI stacks tend to become provider-shaped. Retrieval,
> generation, evaluation, guardrails and observability get glued to one vendor, and swapping
> a model or an evaluator turns into a rewrite.
>
> This project treats those as configurable seams. YAML selects the LLM, embeddings,
> retriever, reranker, evaluator and guardrails; the same HTTP API backs the console, CI
> quality gates and operational review.
>
> What is demonstrable today:
> - config-driven composition root, registries, schema validation and secret interpolation
> - FAISS / simple / hybrid BM25+vector / knowledge-graph retrieval, reranking, query expansion, exact-match cache
> - evaluation: semantic and LLM-judge evaluators, IR metrics, reproducible benchmark reports, cost/latency regression gates and a Pareto config sweep
> - governance: budgets, guardrail profiles, prompt-injection and PII controls, approval queue, hash-chained immutable audit
> - identity (OIDC/JWKS, SCIM), RBAC, tenancy, request attribution and permission-aware retrieval
> - observability: traces, Prometheus/Grafana, OpenTelemetry, runbooks
> - delivery: Docker, Helm, Kustomize, GitOps example and a Codespaces demo
>
> The engineering record is public: issues and PRs, rebase merges, required CI checks
> (ruff, mypy, tests on Python 3.11 and 3.13), plus advisory deploy-smoke and
> eval-regression gates.
>
> Where it stops: this is a reference implementation, not a production-certified platform.
> Shared persistence and multi-replica validation, independent security testing and a
> packaged pilot kit are open, documented work.
>
> Repository: https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
> Architecture: https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/docs/architecture-diagram.md
> Benchmarks: https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/blob/main/docs/benchmarks/README.md
>
> #GenerativeAI #RAG #AIArchitecture #AIGovernance #MLOps

Short variant, if the long post is too dense for the feed:

> Publishing a project I have been building in the open: **Enterprise GenAI Platform
> Blueprint** — a vendor-neutral, self-hostable reference implementation for enterprise
> GenAI and RAG.
>
> Instead of hard-wiring one provider, YAML selects the LLM, embeddings, retriever,
> reranker, evaluator and guardrails. One HTTP API exposes query, evaluation, governance,
> identity, audit and observability, with Prometheus/OpenTelemetry and a console on top.
>
> It is a reference implementation, not a production-certified product: the capability
> matrix and production-readiness assessment document what is tested, partial or planned.
>
> https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
>
> #GenerativeAI #RAG #AIArchitecture #AIGovernance

## 3. Consistency and honesty rules

| Rule | Application |
| --- | --- |
| Canonical name | Use **Enterprise GenAI Platform Blueprint**; add a descriptor only after it. |
| Canonical one-liner | Reuse the opening sentence of the profile description; do not invent a different tagline. |
| Status vocabulary | Copy **Tested / Implemented / Partial / Planned / External** meanings from the capability matrix; do not promote a status. |
| Independent work | State or imply "independent, MIT-licensed reference implementation", never employer-sponsored, customer or commercial. |
| No certification | Say "not a production-certified product"; never "production-ready", "battle-tested" or "proven at scale". |
| No invented numbers | Benchmark and load numbers live in `docs/benchmarks/`; the copy links them instead of quoting fresh figures. |
| No invented demo | The recorded walkthrough (#189) is pending; link the architecture diagram and Codespaces demo instead. |
| Durable entry first | The profile project entry must stand alone after the post leaves the feed. |

## 4. Evidence map

Every substantive claim in this package resolves to a public path or document.

| Claim | Evidence | Status |
| --- | --- | --- |
| Config-driven composition root and registries | `app/bootstrap.py`, `core/registry/`, `tests/test_composition_root.py` | Tested |
| Typed config validation and secret interpolation | `core/config/schema.py`, `core/config/validator.py`, `core/config/secrets.py` | Tested |
| Retrieval: FAISS, simple, hybrid, knowledge graph | `core/implementations/faiss_retriever.py`, `core/implementations/hybrid_retriever.py`, `core/implementations/kg_retriever.py` | Tested |
| Evaluation, benchmark reports, regression gates, Pareto sweep | `core/evaluation/`, `app/eval_gate.py`, `app/optimize.py`, `docs/benchmarks/README.md` | Tested |
| Guardrail profiles, injection and PII controls | `core/registry/guardrail_registry.py`, `core/implementations/injection_guardrail.py`, `core/implementations/pii_guardrail.py` | Tested (default off) |
| Identity (OIDC/JWKS, SCIM), RBAC, tenancy, attribution, ACL retrieval | `core/services/identity.py`, `core/services/access_control.py`, `core/services/tenancy.py`, `core/services/acl.py` | Tested |
| Immutable hash-chained audit | `core/services/audit_store.py`, `tests/test_immutable_audit.py` | Tested |
| Traces, Prometheus/Grafana, OpenTelemetry | `core/services/observability.py`, `core/services/telemetry.py`, `deployment/observability/` | Traces and Prometheus Tested; OTel Implemented (extra) |
| Docker, Helm, Kustomize, GitOps, Codespaces | `deployment/Dockerfile`, `deployment/helm/`, `deployment/kustomize/`, `deployment/gitops/`, `.devcontainer/devcontainer.json` | Tested |
| Console | `ui/app.py`, `ui/client.py` | Implemented (structural/client tests, no browser E2E) |
| Public engineering record and CI gates | `CONTRIBUTING.md`, `docs/engineering-lifecycle.md`, `.github/workflows/ci.yml` | Implemented |
| Shared persistence and bounded two-process qualification | `docs/production-readiness.md`, `config/persistence.yaml`, `deployment/multi-replica/README.md`, `docs/benchmarks/multi-replica.md`, issue #206 | Partial (HA/DR not claimed) |

## 5. User approval checklist

Do not treat this package as complete until the user has confirmed every row.

- [ ] Approve the project title.
- [ ] Supply the real start date (or confirm it should be omitted) and confirm the project is ongoing.
- [ ] Confirm the Experience association is blank, or choose an accurate one.
- [ ] Approve the profile description verbatim.
- [ ] Confirm the five skills against LinkedIn's current taxonomy.
- [ ] Approve the Featured-section links.
- [ ] Add the project entry manually at `https://www.linkedin.com/in/sujeetbanerjee/`.
- [ ] Publish the announcement post only after the profile entry is visible.
- [ ] Re-check the copy against `main` if more than two weeks have passed since 2026-11-15.

## 6. Maintenance

- Regenerate the affected wording when [positioning.md](../positioning.md),
  [capability-status.md](../capability-status.md) or
  [production-readiness.md](../production-readiness.md) change.
- `tests/test_showcase_linkedin.py` guards canonical naming, forbidden maturity claims,
  cited paths, URL allowlisting, description/post length and the approval markers.
- #189 (demo walkthrough) and #204 (pilot kit) are the only pending inputs referenced
  here. Add their links when they land; do not claim them earlier.
