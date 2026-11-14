# Architecture diagram

> **High-level view (#188).** A technical reader should understand the platform's
> layers, component boundaries and key request/data flows in about 30 seconds.
> The diagram is Mermaid source rendered by GitHub; edit it here rather than
> exporting a binary. It reflects the code paths in the map below, not aspirational
> capabilities. This is a reference implementation, **not a production-certified product**.

## Legend

- **Green (solid):** implemented in this repository and exercised by tests.
- **Blue (dashed):** external or optional dependency; not shipped or operated by this
  repository.
- **Orange (dotted):** planned / follow-up work, linked to an open issue.

## Diagram

```mermaid
flowchart TB
    subgraph EB [Enterprise boundary - you operate this]
        subgraph CL [Clients]
            UI["Streamlit console<br/>ui/app.py (HTTP only)"]
            CLIENTS["API clients, CI gates, benchmarks<br/>app/eval_gate.py, benchmarks/"]
        end

        subgraph API [API layer - app/main.py]
            MW["HTTP middleware<br/>request id, identity/SCIM, tenancy,<br/>RBAC, attribution"]
            ROUTES["40 HTTP routes<br/>query, batch, evaluate, experiments,<br/>rebuild, ops, admin, audit, approvals"]
            STATE["Lifespan state<br/>pipeline, config revision, history,<br/>audit, approvals, stores"]
        end

        subgraph COMP [Composition root - app/bootstrap.py]
            CFG["Typed config + secrets<br/>config/*.yaml -> core/config/"]
            REG["Registries<br/>models, retrievers, rerankers,<br/>evaluators, guardrails, policies,<br/>query expansion, PII, connectors"]
            BUILD["assemble_components()<br/>PipelineComponents"]
        end

        subgraph PIPE [RAGPipeline - app/pipeline.py per request]
            VALID["query_validation"]
            CACHE["response cache check"]
            EMB["embedding"]
            EXPAND["query expansion"]
            RETR["retrieval"]
            ACLF["ACL filter"]
            RERANK["reranking"]
            REDACT["input_redaction"]
            GIN["guardrail_input"]
            BUDGET["token_budget"]
            PROMPT["prompt_construction"]
            LLM["llm_generation"]
            GOUT["guardrail_output"]
            EVAL["evaluation"]
        end

        subgraph SVC [Platform services - core/services/]
            COST["cost governor + tracker"]
            GOV["policy engine + approvals"]
            IDENT["identity + RBAC"]
            TEN["tenancy + attribution"]
            AUDIT["hash-chained audit"]
            OBS["observability + OTel + Prometheus"]
            RESIL["resilience + response cache"]
            INGEST["ingestion service"]
            PERSIST["BaseStore + backups"]
        end

        subgraph ADP [Adapters - core/implementations/]
            LLMS["LLM providers<br/>local HF, OpenAI, dummy"]
            EMBEDS["embedders<br/>MiniLM/mpnet, OpenAI, dummy"]
            RETRIEVERS["retrievers<br/>FAISS, simple, hybrid, KG"]
            RERANKERS["rerankers<br/>cross-encoder, simple"]
            EVALS["evaluators<br/>semantic, LLM judge, dummy"]
            GUARDS["guardrails<br/>deny-list, schema, injection, PII"]
            CONNECTORS["connectors<br/>S3, GCS, Azure Blob,<br/>Confluence, SharePoint"]
        end

        subgraph STORES [State and persistence]
            MEM["in-process state<br/>run history, traces, approvals,<br/>experiment store, cache"]
            IMMUT["immutable audit store"]
            STORE["BaseStore<br/>memory | SQLite | Postgres"]
        end

        subgraph DEPLOY [Delivery artefacts]
            DOCKER["Docker / Compose"]
            HELM["Helm chart + Kustomize overlays"]
            GITOPS["GitOps example (Argo CD)"]
            CSPACE["Codespaces devcontainer"]
        end
    end

    subgraph EXT [External or optional - not operated here]
        HF["HuggingFace Hub<br/>model downloads"]
        OPENAI["OpenAI API"]
        OTLP["OTLP collector"]
        JAEGER["Jaeger trace UI"]
        PROM["Prometheus"]
        GRAFANA["Grafana dashboards"]
        PG["Postgres"]
        OBJECT["Cloud object storage"]
    end

    subgraph PLAN [Planned or follow-up]
        HA["Multi-replica HA + autoscale<br/>(#68)"]
        DR["Multi-region / DR<br/>(#71)"]
        SEC["Independent security validation<br/>(#205)"]
    end

    UI --> MW
    CLIENTS --> MW
    MW --> ROUTES
    ROUTES --> STATE
    STATE --> PIPE

    CFG --> BUILD
    REG --> BUILD
    BUILD --> STATE

    VALID --> CACHE --> EMB --> EXPAND --> RETR --> ACLF --> RERANK --> REDACT --> GIN --> BUDGET --> PROMPT --> LLM --> GOUT --> EVAL

    PIPE --> COST
    PIPE --> AUDIT
    PIPE --> OBS
    PIPE --> IDENT
    PIPE --> TEN
    PIPE --> RESIL

    EMB --> EMBEDS
    RETR --> RETRIEVERS
    RERANK --> RERANKERS
    LLM --> LLMS
    EVAL --> EVALS
    GIN --> GUARDS
    GOUT --> GUARDS

    GOV --> ROUTES
    PERSIST --> STORE
    STORE --> MEM
    AUDIT --> IMMUT
    AUDIT --> STORE
    INGEST --> CONNECTORS

    LLMS -.-> HF
    LLMS -.-> OPENAI
    EMBEDS -.-> HF
    OBS -.-> OTLP -.-> JAEGER
    OBS -.-> PROM -.-> GRAFANA
    STORE -.-> PG
    CONNECTORS -.-> OBJECT

    DEPLOY -.-> API
    HA -.-> API
    DR -.-> STORES
    SEC -.-> EB

    classDef implemented fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef external fill:#e3f2fd,stroke:#1565c0,color:#0d47a1,stroke-dasharray:5 5
    classDef planned fill:#fff3e0,stroke:#ef6c00,color:#e65100,stroke-dasharray:2 2

    class UI,CLIENTS,MW,ROUTES,STATE,CFG,REG,BUILD,VALID,CACHE,EMB,EXPAND,RETR,ACLF,RERANK,REDACT,GIN,BUDGET,PROMPT,LLM,GOUT,EVAL,COST,GOV,IDENT,TEN,AUDIT,OBS,RESIL,INGEST,PERSIST,LLMS,EMBEDS,RETRIEVERS,RERANKERS,EVALS,GUARDS,CONNECTORS,MEM,IMMUT,STORE,DOCKER,HELM,GITOPS,CSPACE implemented
    class HF,OPENAI,OTLP,JAEGER,PROM,GRAFANA,PG,OBJECT external
    class HA,DR,SEC planned
```

## How to read it

- **Request path:** clients -> HTTP middleware -> routes -> the lifespan-built
  `RAGPipeline` -> adapters. The `pipeline:rebuild` route swaps the pipeline instance
  under a lock; in-flight requests keep the old instance.
- **Trust boundary:** everything in the green enterprise boundary is code you run
  (API, composition root, pipeline, services, adapters, stores, delivery artefacts).
  Blue nodes are external dependencies you point at, not components this repository
  operates.
- **Control plane:** config + registries resolve every vendor-specific component.
  `app/bootstrap.py::assemble_components` is the single assembly path; experiments
  reuse it rather than building components independently.
- **Data and state:** traces, run history, approvals, experiments and the response
  cache are process-local by default (see #191/#192). The audit trail and `BaseStore`
  can persist to SQLite/Postgres; multi-replica coordination and multi-region DR are
  explicitly planned (#68, #71), not claimed.
- **Governance:** identity, RBAC, tenancy, attribution and approvals sit at the API
  edge; guardrails run inside the pipeline on input and output; audit/observability
  capture every request without exposing secrets.

## Component-to-code map

| Diagram area | Code |
| --- | --- |
| HTTP middleware, routes, lifespan state | `app/main.py` |
| Console | `ui/app.py`, `ui/client.py` |
| Composition root | `app/bootstrap.py` |
| Config validation and secrets | `core/config/schema.py`, `core/config/validator.py`, `core/config/secrets.py` |
| Registries | `core/registry/` |
| Pipeline stages | `app/pipeline.py` |
| Interfaces | `core/interfaces/` |
| Adapters | `core/implementations/` |
| Governance, identity, tenancy, attribution, ACL | `core/services/cost_governor.py`, `core/services/policy_engine.py`, `core/services/identity.py`, `core/services/access_control.py`, `core/services/tenancy.py`, `core/services/attribution.py`, `core/services/acl.py` |
| Audit and observability | `core/services/audit_log.py`, `core/services/audit_store.py`, `core/services/observability.py`, `core/services/telemetry.py` |
| Persistence | `core/services/base_store.py`, `core/services/store_backends.py`, `core/services/backup_restore.py` |
| Ingestion and connectors | `core/services/ingestion_service.py`, `core/implementations/connectors/` |
| Evaluation and experiments | `core/evaluation/`, `core/services/experiment_runner.py`, `app/evaluation_api.py` |
| Delivery artefacts | `deployment/Dockerfile`, `deployment/docker-compose.yml`, `deployment/helm/`, `deployment/kustomize/`, `deployment/gitops/`, `.devcontainer/devcontainer.json` |

## Maintaining the diagram

- Update the Mermaid block when a layer, registry, pipeline stage or external
  dependency changes; keep the component-to-code map in sync.
- Move a node from orange to green only when the capability is implemented and tested,
  not when an interface exists.
- `tests/test_architecture_diagram.py` guards the required layers, legend semantics,
  code-map paths and documentation links.
