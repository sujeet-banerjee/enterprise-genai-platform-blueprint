# Comparison with alternatives

> **Status:** reference implementation and config-driven control plane, not a drop-in
> replacement for a managed AI platform or a production-certified product. This page
> states where the repository overlaps with other tools, where those tools are stronger,
> and what evidence backs each claim. Sources were accessed on **2026-11-14**; review
> quarterly or when a major capability lands (see [Maintenance](#maintenance)).

This is the companion to the capability-status audit (#191):

- **That audit** states what this repository implements and where the code lives.
- **This page** states how it differs from other tools, and where it is not a substitute.

## How to read this comparison

- Claims describe **shipped capabilities**, not measured quality. Retrieval quality,
  cost and latency numbers live in [docs/benchmarks/README.md](benchmarks/README.md)
  and are reproducible reference-CPU runs, not vendor benchmarks.
- Every capability claim below maps to a code path, config file or document in the
  evidence table. Every external claim links to a vendor or project source with an
  access date.
- Comparative statements name their **criterion** (feature presence, deployment model,
  licence, operational burden) and cite evidence. There are no unqualified "better
  than" claims, and the section [Where alternatives are stronger](#where-alternatives-are-stronger)
  is deliberate.
- Categories are not interchangeable: an orchestration library, a managed cloud
  platform, an evaluation product and an enterprise search product solve different
  problems. Rows only compare like with like.

## At a glance

| Dimension | This repository | Orchestration frameworks (LangChain, LlamaIndex) | Managed cloud AI platforms (Bedrock, Vertex AI, Azure AI Foundry, Databricks) | Evaluation / observability products (RAGAS, LangSmith, Langfuse, Arize, TruLens) | Enterprise search (Glean) |
| --- | --- | --- | --- | --- | --- |
| Config-driven vendor neutrality | Interfaces plus registries selected from `config/*.yaml`; provider swap is a config edit | Provider adapters exist, but pipeline wiring is code | Platform-specific model, retrieval and agent APIs | Product-specific SDKs and data models | SaaS product, not a framework |
| Reference RAG pipeline | Retrieval, chunking, reranking, query expansion, grounded generation, citations | Yes, as composable building blocks | Managed knowledge bases and agents | Not the product focus | Prebuilt search and assistant |
| Evaluation | Embedding metrics, LLM judge, labelled datasets, regression gates, parameter sweeps, published reports | Left to integrations and separate libraries | Varies by platform; often bolted on | Core product, broader metric libraries | Limited / usage analytics |
| Governance and guardrails | Guardrail framework, injection and PII guardrails, policy engine, HITL approvals, budgets | Compose from third-party libraries | Cloud-native guardrails and content safety per platform | Not the product focus | DLP and permissions within the SaaS |
| Observability | OTel spans, Prometheus metrics, in-process traces, audit trail | Optional via LangSmith or other integrations | Platform-native monitoring | Core product, mature UIs | Vendor-hosted analytics |
| Deployment | Docker, Compose, Helm, Kustomize, Argo CD example, Codespaces | Deploy yourself | Fully managed or vendor-operated | SaaS or self-hosted depending on product | SaaS |
| Console | Streamlit console (12 screens) over the public HTTP API | None built in | Platform console | Product console | Product console |
| Multi-tenancy and identity | Tenants, OIDC/JWKS, SCIM, RBAC, attribution, permission-aware retrieval | None built in | Cloud IAM and org/project models | Org/workspace models per product | Built-in, SaaS |
| Persistence | `BaseStore` with memory, SQLite and Postgres backends | None built in | Managed stores per platform | Managed by product | Managed by product |
| Licence | MIT | MIT / Apache-2.0 depending on project | Proprietary service terms | Mixed open source and commercial | Commercial |

## What this repository implements (evidence)

Each row is a capability claim and the shipped artefact that backs it. Test references
point at the guards that keep the claim honest.

| Capability claim | Shipped evidence |
| --- | --- |
| Interfaces and registries select implementations from YAML instead of code | `core/interfaces/`, `core/registry/model_registry.py`, `core/registry/retriever_registry.py`, `core/registry/reranker_registry.py`, `core/registry/evaluator_registry.py`, `core/registry/guardrail_registry.py`, `app/bootstrap.py` |
| Retrieval providers include FAISS, simple, hybrid keyword+vector, knowledge graph and dummy | `core/registry/retriever_registry.py`, `core/implementations/faiss_retriever.py`, `core/implementations/simple_retriever.py`, `core/implementations/hybrid_retriever.py`, `core/implementations/kg_retriever.py`, `config/retrieval.yaml` |
| Chunking, reranking, query expansion and response caching are configurable stages | `core/implementations/chunker.py`, `core/implementations/cross_encoder_reranker.py`, `core/implementations/query_expanders.py`, `core/services/response_cache.py`, `app/pipeline.py` |
| Evaluation covers embedding metrics, an LLM judge, labelled datasets, CI gates and sweeps | `core/evaluation/metrics.py`, `core/implementations/semantic_evaluator.py`, `core/implementations/llm_judge_evaluator.py`, `core/evaluation/eval_datasets.py`, `core/evaluation/regression_gate.py`, `core/evaluation/config_sweep.py`, `app/eval_gate.py`, `config/eval_datasets.yaml`, `config/optimization.yaml` |
| Guardrails cover deny-lists, JSON schema checks, prompt injection and PII | `core/interfaces/guardrail.py`, `core/implementations/guardrails.py`, `core/implementations/injection_guardrail.py`, `core/implementations/pii_detector.py`, `core/implementations/pii_guardrail.py`, `config/guardrails.yaml`, `tests/test_injection_defense.py`, `tests/test_pii_dlp.py` |
| Governance includes cost budgets, a policy engine, policy bundles and human approvals | `core/services/cost_governor.py`, `core/services/cost_tracker.py`, `core/services/policy_engine.py`, `core/services/approval.py`, `app/approval_api.py`, `config/governance.yaml`, `config/policies.yaml`, `config/policies/` |
| Observability exports OTel spans, Prometheus metrics, request traces and a hash-chained audit trail | `core/services/observability.py`, `core/services/telemetry.py`, `core/services/audit_log.py`, `core/services/audit_store.py`, `config/observability.yaml`, `config/audit.yaml`, `deployment/observability/` |
| Identity, tenancy, RBAC, attribution and permission-aware retrieval are enforced at the API edge | `core/services/identity.py`, `core/services/tenancy.py`, `core/services/access_control.py`, `core/services/attribution.py`, `core/services/acl.py`, `config/identity.yaml`, `config/tenants.yaml`, `config/access_control.yaml`, `config/attribution.yaml`, `config/acl.yaml` |
| Persistence is pluggable across memory, SQLite and Postgres | `core/services/base_store.py`, `core/services/store_backends.py`, `config/persistence.yaml` |
| Resilience includes retries, circuit breakers and provider failover | `core/services/resilience.py`, `config/resilience.yaml` |
| The API exposes 40 routes over HTTP, including query, evaluation, experiments, rebuild, ops and admin | `app/main.py`, `app/approval_api.py`, `app/audit_api.py`, `app/evaluation_api.py`, `app/ops_api.py`, `app/whatif_api.py`, `docs/ux-and-api.md`, `tests/test_api_contract.py` |
| The console is HTTP-only and covers 12 operational screens | `ui/app.py`, `ui/client.py`, `tests/test_ui_console.py` |
| Deployment artefacts include Docker, Compose, Helm, Kustomize, an Argo CD example and a Codespace | `deployment/Dockerfile`, `deployment/docker-compose.yml`, `deployment/helm/`, `deployment/kustomize/`, `deployment/gitops/`, `.devcontainer/devcontainer.json`, `docs/deployment.md` |
| Ingestion connectors are an extension point with a built-in service | `core/interfaces/connector.py`, `core/implementations/connectors/`, `core/services/ingestion_service.py`, `config/ingestion.yaml` |
| Benchmark and load numbers are reproducible, not hand-edited | `core/evaluation/showcase_report.py`, `core/evaluation/load_harness.py`, `app/benchmark_report.py`, `benchmarks/load/run_load.py`, `docs/benchmarks/README.md`, `docs/benchmarks/load.md` |

## Where alternatives are stronger

This is the honest side of the comparison. Each statement names its criterion.

- **Managed platforms (Bedrock, Vertex AI, Azure AI Foundry, Databricks) reduce
  operational burden.** Criterion: who runs the infrastructure. They provide managed
  model access, autoscaling, SLA-backed availability, regional failover and compliance
  certifications that this repository does not claim.
- **Managed platforms and Glean have far broader connector coverage.** Criterion:
  number and maintenance of source integrations. This repository ships a connector
  interface and a small built-in ingestion service; managed platforms and enterprise
  search products maintain hundreds of connectors, schedulers and auth flows.
- **Managed platforms provide cloud-native identity and data governance.** Criterion:
  depth of integration with existing cloud IAM, catalog and lineage. This repository
  implements OIDC, SCIM, RBAC, tenancy and ACL-aware retrieval, but it is not a
  replacement for an organisation's IAM or data catalog.
- **Glean is turnkey for enterprise search.** Criterion: time-to-value and
  permission-aware indexing at SaaS scale. It includes prebuilt connectors, a
  maintained index and an end-user assistant; this repository is a blueprint you
  operate.
- **LangChain and LlamaIndex have a much larger integration ecosystem.** Criterion:
  breadth of adapters, community examples and third-party tooling. They are libraries
  designed to compose with anything; this repository deliberately standardises a
  smaller set of interfaces.
- **RAGAS has a broader, research-oriented evaluation metric library.** Criterion:
  metric coverage. This repository implements embedding metrics, an LLM judge,
  IR metrics and gated datasets, not the full RAGAS metric catalogue.
- **LangSmith, Langfuse, Arize and TruLens provide mature evaluation and observability
  products.** Criterion: tracing UI, dataset management, annotation workflows and
  production-scale ingestion. This repository emits OTel and Prometheus data and ships
  a console, but it is not a dedicated LLM observability product.
- **Databricks is stronger when the data already lives in a lakehouse.** Criterion:
  co-location with data engineering and Unity Catalog governance. This repository is
  storage-agnostic and expects you to integrate your own data estate.
- **None of these alternatives are drop-in swaps for each other.** Choosing between
  them is a build-versus-buy and operating-model decision, not a feature checklist.

## Alternatives

### LangChain

- **What it is:** an open-source framework for composing LLM applications, with
  provider integrations, chains, agents and retrieval helpers.
- **Overlap:** both build RAG applications and support multiple model and vector-store
  providers.
- **Where it is stronger:** integration breadth, community examples and higher-level
  agent abstractions.
- **Source:** https://python.langchain.com/docs/introduction/ (accessed 2026-11-14)

### LlamaIndex

- **What it is:** an open-source data framework for RAG and agent workflows, with
  connectors, indexes and query engines.
- **Overlap:** document ingestion, indexing, retrieval and response synthesis.
- **Where it is stronger:** data connectors and advanced indexing patterns, plus a
  managed LlamaCloud offering for parsing and retrieval.
- **Source:** https://docs.llamaindex.ai/en/stable/ (accessed 2026-11-14)

### RAGAS

- **What it is:** an open-source evaluation framework for RAG pipelines, with
  reference-free and reference-based metrics.
- **Overlap:** evaluating retrieval and answer quality.
- **Where it is stronger:** metric breadth and research alignment; it is used as an
  evaluation library alongside an application rather than as a control plane.
- **Source:** https://docs.ragas.io/en/stable/ (accessed 2026-11-14)

### Amazon Bedrock

- **What it is:** a managed AWS service for foundation models, knowledge bases,
  agents and guardrails.
- **Overlap:** model access, managed RAG, guardrails and agent orchestration.
- **Where it is stronger:** managed scale, AWS IAM integration, regional services and
  vendor support; it is a hosted service rather than a self-hostable blueprint.
- **Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html (accessed 2026-11-14)

### Google Cloud Vertex AI

- **What it is:** a managed ML platform with model access, RAG Engine, agent tooling
  and evaluation features.
- **Overlap:** model hosting, retrieval augmentation, evaluation and agent workflows.
- **Where it is stronger:** managed infrastructure, Google Cloud IAM, and integration
  with BigQuery and other Google Cloud data services.
- **Source:** https://cloud.google.com/vertex-ai/docs (accessed 2026-11-14)

### Azure AI Foundry

- **What it is:** Microsoft's managed platform for building, evaluating and operating
  generative AI applications and agents.
- **Overlap:** model catalogue, agent service, evaluation and content safety.
- **Where it is stronger:** Azure identity, networking and compliance integration, and
  a managed operating model.
- **Source:** https://learn.microsoft.com/en-us/azure/ai-foundry/ (accessed 2026-11-14)

### Databricks (Mosaic AI)

- **What it is:** a data and AI platform with foundation model APIs, vector search and
  agent/evaluation tooling inside the lakehouse.
- **Overlap:** retrieval, evaluation and agent development.
- **Where it is stronger:** co-location with data engineering, Unity Catalog
  governance and lakehouse-scale processing.
- **Source:** https://docs.databricks.com/aws/en/machine-learning/foundation-models/ (accessed 2026-11-14)

### Glean

- **What it is:** an enterprise search and assistant product with prebuilt connectors
  and permission-aware indexing.
- **Overlap:** retrieval over enterprise content and an assistant experience.
- **Where it is stronger:** connector breadth, turnkey deployment and end-user search
  UX; it is a commercial SaaS product, not a framework.
- **Source:** https://docs.glean.com/ (accessed 2026-11-14)

### LangSmith

- **What it is:** a commercial platform for tracing, evaluating and monitoring LLM
  applications, with close LangChain integration.
- **Overlap:** tracing, evaluation datasets, experiment comparison and monitoring.
- **Where it is stronger:** a mature tracing and annotation UI, hosted ingestion and
  team workflows.
- **Source:** https://docs.smith.langchain.com/ (accessed 2026-11-14)

### Langfuse

- **What it is:** an open-source LLM observability and evaluation platform that can be
  self-hosted or used as a managed service.
- **Overlap:** traces, evaluation, prompt management and cost analytics.
- **Where it is stronger:** dedicated observability UI, prompt versioning and
  self-hostable product maturity.
- **Source:** https://langfuse.com/docs (accessed 2026-11-14)

### Arize

- **What it is:** an AI observability and evaluation platform (with the open-source
  Phoenix project) covering LLM, ML and retrieval monitoring.
- **Overlap:** evaluation, tracing, drift and production monitoring.
- **Where it is stronger:** production monitoring depth, drift detection and
  established dashboards.
- **Source:** https://docs.arize.com/arize (accessed 2026-11-14)

### TruLens

- **What it is:** an open-source evaluation and tracking library for LLM applications,
  with feedback functions and dashboards.
- **Overlap:** evaluation metrics, experiment tracking and RAG triads.
- **Where it is stronger:** feedback-function library and experiment tracking focused
  on evaluation rather than platform operations.
- **Source:** https://www.trulens.org/ (accessed 2026-11-14)

## When to choose what

| If your priority is... | Reasonable default | Why |
| --- | --- | --- |
| Fastest path to a managed RAG assistant on one cloud | Bedrock, Vertex AI, Azure AI Foundry or Databricks | Managed infrastructure, IAM and support; accept platform coupling |
| Maximum integration and agent-framework flexibility in code | LangChain or LlamaIndex | Broad adapters and community patterns; you own assembly, governance and operations |
| Deep RAG metric research | RAGAS plus a tracing product | Specialised metric library rather than a control plane |
| Turnkey enterprise search with prebuilt connectors | Glean | Commercial SaaS with maintained connectors and permission-aware index |
| A dedicated LLM observability UI | LangSmith, Langfuse, Arize or TruLens | Product-grade tracing, annotation and monitoring |
| A vendor-neutral, self-hostable control plane you can extend | This repository | Config-driven registries, governance, evaluation and deployment artefacts; you operate it and own the hardening |

## What this repository is not

- **Not a drop-in replacement** for a managed AI platform, an orchestration library,
  an evaluation product or an enterprise search SaaS.
- **Not production-certified.** It ships reference deployment artefacts and honest
  reference numbers; it does not claim SLAs, certifications or vendor-scale
  throughput. See [docs/deployment.md](deployment.md) for deployment guidance and
  [#192](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/192)
  for the production-readiness gap assessment.
- **Not a model provider.** It integrates local and hosted models through interfaces;
  it does not train or serve foundation models.
- **Not a connector catalogue.** The connector interface and ingestion service are an
  extension point, not hundreds of maintained integrations.
- **Not a benchmark authority.** Published numbers are reproducible reference-CPU
  measurements on synthetic corpora, regenerated from committed JSON reports.

## Maintenance

- Review this page quarterly, or when a major capability lands, whichever comes first.
- Re-check every external source and update the access date; remove or correct links
  that no longer describe the product.
- Keep the evidence table aligned with the code paths that actually ship. The
  structural guards in `tests/test_comparison_docs.py` fail when a cited path
  disappears, a source loses its access date, or a local link breaks.
