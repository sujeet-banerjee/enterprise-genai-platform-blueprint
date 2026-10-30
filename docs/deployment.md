# Deployment Playbook

Operational guide for running the platform beside production RAG / agentic workloads:
deployment **modes**, **processes** (promotion, upgrades, rollback, backup), **tools** and the
**agentic seams**. Conceptual deployment patterns (shadow vs. inline gateway) live in
[`architecture.md` §13](architecture.md#13-deployment-modes); this document is about *how to
actually run it*.

Everything here is verified against this repository: paths, environment variables, endpoints and
CLI flags are the ones the code reads. Cloud-specific IaC is deliberately out of scope (roadmap
G6); the guidance stays cloud-agnostic.

---

## 1. Runtime contract (what a deployment must provide)

| Concern | Requirement | Where it is defined |
|---|---|---|
| Process | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | `app/main.py` (`app = create_app()`), `deployment/Dockerfile` |
| Config | A directory of YAML files; discovered from `GENAI_CONFIG_DIR` (default `<repo>/config`) | `app/main.py::_config_dir()` |
| Config validation | Fail-fast at startup (`assemble_components` → `validate_startup_configs`) | `core/config/validator.py` |
| Secrets | Never in YAML; resolved from env at load (`${VAR}` or `env:VAR`) | `core/config/secrets.py` (#46) |
| Health | `GET /health` (liveness, no dependencies); `GET /ready` readiness → `200` with `config_revision` + component summary, `503` until the pipeline is built | `app/main.py` |
| Metrics | `GET /metrics` (Prometheus text) when `prometheus-client` is installed, else `503` `prometheus_not_installed` | `app/ops_api.py` (#44) |
| Traces | OTLP export when the OTel SDK + exporter are installed **and** `observability.otel.enabled: true` | `core/services/telemetry.py` (#47) |
| Model weights | Downloaded into `HF_HOME` (default `~/.cache/huggingface`; the image uses `/app/.cache/huggingface`) | `core/implementations/_local_models.py` |
| Writable paths | `HF_HOME`, the audit JSONL path (if configured), and the system temp dir (runtime pipeline rebuilds use `mkdtemp`) | `core/services/audit_log.py`, `app/whatif_api.py` |
| Shutdown | SIGTERM → uvicorn drains in-flight requests → lifespan closes the evaluation executor, deletes rebuild workspaces and closes the audit log | `app/main.py` lifespan |

In-process state (`/v1/metrics`, `/v1/traces/{id}`, `/v1/audit`, spend window) is **bounded and
per-process**. With more than one replica, a trace/metric lookup only sees the pod that served the
request; ship metrics through Prometheus and audit events through log shipping until the persistent
store lands (roadmap E4 / #56).

### Environment variables (the complete set the app reads)

| Variable | Read by | Effect |
|---|---|---|
| `GENAI_CONFIG_DIR` | `app/main.py` | Root config directory override (empty/whitespace → repo `config/`) |
| `GENAI_MODELS_CONFIG`, `GENAI_RETRIEVAL_CONFIG`, `GENAI_PROMPT_CONFIG` | `examples/*.py` only | Per-file overrides for the runnable examples |
| `OPENAI_API_KEY` | `core/registry/model_registry.py` | Fallback key for `provider: openai` / `openai-compatible` when the model entry has no `api_key` |
| `HF_TOKEN` | `core/implementations/_local_models.py` | Forwarded to the Hugging Face Hub for gated downloads |
| `HF_HOME` | Hugging Face libraries | Weight cache location (mount it) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTel SDK | Collector target when `observability.otel.endpoint` is empty (the shipped default); setting `otel.endpoint` explicitly wins |
| `GENAI_API_KEY` | — (not read directly) | Convenience name: reference it from config as `api_key: env:GENAI_API_KEY` (API key) or in `config/access_control.yaml` `api_keys` |
| `JWT_SECRET` | `core/config/secrets.py` | Example name for `identity.secret: env:JWT_SECRET` (HS256 local/testing only; production uses `jwks_uri`) |
| `SCIM_BEARER_TOKEN` | `core/config/secrets.py` | Example name for `identity.scim.tokens` (IdP provisioning token; never logged) |

Use `${VAR}` (braces, substituted by the loader, also inside larger strings) or `env:VAR` (scheme,
whole value). A missing variable raises `SecretResolutionError` at load time — deployments fail fast
instead of running half-configured.

> There is **no** `GENAI_OBSERVABILITY` switch. `/metrics` availability is determined by whether
> `prometheus-client` is installed (build the image with `INSTALL_EXTRAS=".[observability]"`);
> tracing is enabled in `config/observability.yaml`.

---

## 2. Deployment modes

| Mode | Topology | Config | Secrets | Models | Observability | Tradeoffs |
|---|---|---|---|---|---|---|
| **Local dev** | one process (`--reload`) + optional Streamlit console | repo `config/` | `.env` / shell env | downloaded to `HF_HOME` | console screens; `/metrics` if extra installed | fastest loop; not hardened |
| **Docker Compose (single node)** | `api` container (+ optional `observability` profile) | bind-mounted `../config:/app/config:ro` or baked image config | `env_file: ../.env` | `hf-cache` volume | Prometheus + Grafana + OTel collector + Jaeger profiles | one host, no HA; good for pilots |
| **Kubernetes** | `Deployment` + `Service` (+ HPA/KEDA later) | `ConfigMap` mounted at `/app/config` | `Secret` → env vars (or External Secrets) | PVC / node-local cache / baked image | scrape `/metrics`; OTLP to cluster collector | needs manifests (G2 #67) + capacity planning |
| **Air-gapped / on-prem** | K8s or Compose, no internet egress | `ConfigMap`/mounted dir | K8s `Secret` or vault-injected env | pre-seeded cache or baked into the image; `provider: local` | self-hosted Prometheus/Grafana/Jaeger | model updates are a release event; no external providers |
| **Managed cloud / BYO-model** | K8s/Compose calling a hosted LLM API | same YAML with `provider: openai` / `openai-compatible` | secret manager → env | none locally (or embeddings only) | same `/metrics` + OTLP; add egress rules | data leaves the boundary; per-token cost; latency variance |
| **Embedded / sidecar** | library import inside a service, or a sidecar container next to it | shared config dir | process env | local embeddings, LLM local or remote | OTLP from the host process | no extra network hop; lifecycle tied to the host; upgrade coupling |

### 2.1 Local development

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.config_validate                    # validate every shipped YAML
uvicorn app.main:app --reload
```

Set `OPENAI_API_KEY`/`HF_TOKEN` in the shell if needed. The console (`ui/`) is a pure HTTP client:
`streamlit run ui/app.py -- --api-base http://localhost:8000`.

### 2.2 Docker Compose (single node)

```bash
cp .env.example .env                              # fill in only what you need; .env is gitignored
docker compose -f deployment/docker-compose.yml up --build
# with Prometheus (:9090), Grafana (:3000), OTel collector (:4318) and Jaeger (:16686):
docker compose -f deployment/docker-compose.yml --profile observability up --build
```

- The image is multi-stage, runs as UID/GID `10001`, and has a `HEALTHCHECK` on `/health`
  (`deployment/Dockerfile`). Build variants: `--build-arg INSTALL_EXTRAS=".[observability]"`
  (Prometheus client + OTel), `--build-arg TORCH_INDEX_URL=...` for a CUDA wheel index.
- Config is bind-mounted read-only; the `hf-cache` named volume persists weights.
- To export traces inside Compose, set `observability.otel.enabled: true`; the shipped
  `otel.endpoint: ""` makes the SDK use `OTEL_EXPORTER_OTLP_ENDPOINT` (compose already points it at
  `http://otel-collector:4318/v1/traces`). Browse traces in Jaeger.
- Provider failover/retries: `config/resilience.yaml` (default off).

### 2.3 Kubernetes (recommended production path)

Manifests are delivered by **G2 (#67)** (Helm chart + Kustomize overlays). Until then, the contract
below is what those manifests must satisfy.

```text
Deployment (replicas: N)                     Service :8000
  ├─ envFrom: Secret (OPENAI_API_KEY, HF_TOKEN, GENAI_API_KEY)
  ├─ env: GENAI_CONFIG_DIR=/app/config
  ├─ volumeMounts:
  │    /app/config            <- ConfigMap (all config/*.yaml)      readOnly
  │    /app/.cache/huggingface <- PVC (RWO) or emptyDir per pod
  ├─ readinessProbe:  GET /ready   (503 until the pipeline is built)
  ├─ livenessProbe:   GET /health
  └─ resources: requests/limits; startupProbe for slow model loads
```

Practical notes:

- **Probes.** Use `/ready` for readiness and `/health` for liveness/startup. A cold start downloads
  weights if the cache is empty, so set a generous `startupProbe` (or pre-seed the PVC).
- **Replicas.** The API is stateless for requests; in-memory ops stores are per pod (see §1). Scale
  horizontally for throughput, and remember each pod needs the cache (RWX, baked image, or a
  read-only PVC mounted many times).
- **Config changes.** `ConfigMap` updates do **not** hot-reload: restart the pods (rolling) so the
  lifespan rebuilds the pipeline. `POST /v1/pipeline:rebuild` is a what-if/preview tool, not a
  production config channel (it writes to a temp workspace and is lost on restart).
- **Secrets.** Prefer External Secrets (or your cloud secret manager) projecting into a `Secret`:
  the app only ever reads env vars (via `${VAR}`/`env:VAR`).
- **Rollout.** `RollingUpdate` with `maxUnavailable: 0` works because readiness gates traffic.
  Keep `revisionHistoryLimit` high enough for instant rollback.
- **Autoscaling.** HPA on CPU/latency and KEDA for queue-driven workers are G3 (#68); HPA on custom
  metrics needs a Prometheus adapter pointed at `/metrics`.

### 2.4 Air-gapped / on-prem

- Build the image where the internet is available; either pre-download the active models into
  `HF_HOME` in a build stage or ship a pre-populated PVC. Set `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1` at runtime to prevent phone-home attempts.
- Use `provider: local` / `sentence_transformers` for every model so no provider egress is needed.
  Leave `allow_offline_fallback: false` (default) to fail fast when a model is missing, rather than
  silently degrading.
- Run Prometheus/Grafana/Jaeger on-prem; point `observability.otel.endpoint` at the internal
  collector. Audit events can append to a mounted JSONL file for WORM-style shipping
  (`config/audit.yaml`: `path`, `enabled: true`).
- Model upgrades are releases: bump the image tag or the cache volume in a controlled change.

### 2.5 Managed cloud / BYO-model

- Swap `config/models.yaml` to `provider: openai` (or `openai-compatible` with `base_url`) and keep
  the API key out of git: `api_key: env:OPENAI_API_KEY` or just set `OPENAI_API_KEY` (the provider
  falls back to it). Embeddings can stay local.
- Keep `config/resilience.yaml` on with `fallback_models` so a provider outage degrades to a
  secondary model instead of failing requests.
- Add egress policy for the provider endpoint only; `/metrics` and OTLP stay internal.
- Cost reporting uses the per-model pricing table in `config/models.yaml` (#14).

### 2.6 Embedded / sidecar

- **Library mode:** import the composition root (`from app.bootstrap import build_pipeline`) in your
  service and call `pipeline.run(...)` / `run_batch(...)`. You own the lifecycle, config reload and
  telemetry provider.
- **Sidecar mode:** run the same image as a sidecar and call it over `http://127.0.0.1:8000`; the
  host stays language-agnostic and the API surface is the contract. Watch memory limits — the
  sidecar loads the models.
- Tradeoff: no extra network hop, but upgrades and restarts are coupled to the host workload.

### 2.7 GitHub Codespaces (demo)

- **Topology:** one devcontainer workspace; `postCreateCommand` installs the runtime, UI and
  observability dependencies, validates `config/`, and seeds an optional `.env`;
  `postStartCommand` runs `uvicorn app.main:app` on `:8000` and `streamlit run ui/app.py` on
  `:8501` (idempotent `deployment/codespace/start.sh`).
- **Config/secrets:** identical to local - `GENAI_CONFIG_DIR` points at the repo `config/`;
  Codespaces secrets (`OPENAI_API_KEY`, `HF_TOKEN`) are injected as env vars, or uncomment the
  placeholders in `deployment/codespace/.env`.
- **Tradeoff:** ephemeral, single replica, 2-4 cores; ideal for demos and reviewing the console,
  not a production path. The first start downloads the local models (~1.5 GB).
- **Reference:** [deployment/codespace/README.md](../deployment/codespace/README.md); the root
  `.devcontainer/devcontainer.json` is only the required manifest pointer.

---

## 3. Deployment processes

### 3.1 Config, prompt and model promotion (dev → staging → prod)

Config is code: every promotion is a reviewed commit to `config/**`, validated in CI and shipped as
a `ConfigMap`/mounted directory.

1. **Validate** — `python -m app.config_validate --config-dir config` (exit `0` valid, `1` invalid,
   `2` unreadable; `--json` for machines). Startup runs the same schemas, so an invalid config fails
   the pod instead of serving.
2. **Version** — schema files accept an optional `config_version` (currently `1`); drift produces a
   warning, unknown keys are rejected (top-level `extra="forbid"`).
3. **Promote** — open a PR per environment, let CI run lint/tests + config validation, merge, and
   roll the deployment. Prompt profiles and model entries ride the same pipeline.
4. **Verify** — `GET /ready` returns `config_revision` and a component summary; `/v1/config`,
   `/v1/guardrails`, `/v1/models` show the redacted effective config; `/v1/guardrails` previews the
   resolved guardrail chains even while disabled.

### 3.2 Upgrade, rollback, blue-green / canary

- **Upgrade:** build a new immutable image tag, roll out with `maxUnavailable: 0`; readiness
  (`/ready`) keeps traffic off pods that are still loading models.
- **Rollback:** redeploy the previous image tag and revert the config commit. There is no database
  migration to undo; the only durable artifacts are the model cache (reproducible) and the audit
  JSONL (append-only, keep it).
- **Blue-green:** run two environments sharing the model cache; switch the Service selector after
  `/ready` is green. **Canary:** route a small share of traffic to the new version and compare
  `/metrics` (error rate, p95 latency, guardrail blocks, cost) before promoting.
- **What-if preview:** `POST /v1/pipeline:rebuild` (gated by `api.allow_rebuild: true`) is for
  side-by-side experiments; it does not persist. Never use it as the production change mechanism.

### 3.3 Health, readiness and graceful shutdown

| Probe | Endpoint | Semantics |
|---|---|---|
| Startup/liveness | `GET /health` | process alive; no dependency checks |
| Readiness | `GET /ready` | pipeline built; `503` with `not_ready` before the lifespan completes |
| Metrics scrape | `GET /metrics` | Prometheus exposition (or `503 prometheus_not_installed`) |

On SIGTERM the server stops accepting connections, drains in-flight requests, then the lifespan
closes the evaluation thread pool, removes rebuild temp workspaces and closes the audit log
(flushing JSONL). Give the pod a `terminationGracePeriodSeconds` longer than your slowest request
(LLM generation + rerank).

### 3.4 Backup and restore

- **Config:** in git — the source of truth. Restore by redeploying the commit.
- **Model cache:** reproducible; optionally snapshot the PVC to avoid re-downloading in air-gapped
  environments.
- **Audit trail:** if `config/audit.yaml` sets `path`, ship the JSONL file to durable/WORM storage;
  the in-memory ring is bounded (`max_entries`) and lost on restart.
- **Traces/metrics/spend window:** ephemeral by design; Prometheus is the durable metric store.
  Persistent run/trace history is roadmap E4 (#56).

---

## 4. Tooling and the recommended default path

| Need | Tool | Status |
|---|---|---|
| Packaging | `deployment/Dockerfile` (multi-stage, non-root, healthcheck) | shipped (#65) |
| Local orchestration | `deployment/docker-compose.yml` + `.env.example` | shipped (#65) |
| K8s packaging | Helm chart `deployment/helm/genai-platform/` + Kustomize `deployment/kustomize/` | shipped (#67) |
| GitOps | Argo CD example in `deployment/gitops/argocd/` | shipped (#67); scale-out G5 #70 |
| Autoscaling | HPA (CPU/latency/custom), KEDA for queue workers | G3 #68 |
| Secrets | K8s `Secret` + External Secrets (or cloud secret manager) | guidance here; vault integration E3 |
| Progressive delivery | Argo Rollouts / Flagger (canary, analysis on `/metrics`) | G4 #69 |
| Multi-region / DR | active-passive with shared model cache; config per region | G6 #71 |

**Recommended default:** the Helm chart deployed by Argo CD, one values file per environment,
Secrets from External Secrets, Prometheus Operator scraping `/metrics`, OTLP to the cluster
collector. It keeps config promotion in git, gives rollback for free and avoids bespoke scripts.

### 4.1 Reference artifacts (shipped)

**Helm** — API Deployment (startup `/health`, readiness `/ready`, liveness `/health`), Service,
optional Ingress/HPA, model-cache PVC (or an existing claim), optional ConfigMap mount, existing
Secret → env, optional Prometheus annotations/OTel endpoint, and a disabled-by-default worker
Deployment that **requires `worker.command`** (there is no built-in agent loop).

```bash
helm lint deployment/helm/genai-platform
helm template genai deployment/helm/genai-platform -f deployment/helm/genai-platform/values.prod.yaml
helm upgrade --install genai deployment/helm/genai-platform \
  -n genai-platform --create-namespace -f deployment/helm/genai-platform/values.staging.yaml
```

Config defaults to the copy baked into the image (`/app/config`); set
`config.existingConfigMap` to mount an in-cluster ConfigMap instead. No secret material is rendered
from values — set `secrets.existingSecret`.

**Kustomize** — base manifests + `dev`/`staging`/`prod` overlays. Each overlay's
`configMapGenerator` reads the repository's real `config/` directory (no duplicated YAML); a config
edit changes the ConfigMap hash and rolls the pods. `config/` is above the overlay root, so render
with the relaxed loader:

```bash
kubectl kustomize --load-restrictor LoadRestrictionsNone deployment/kustomize/overlays/prod \
  | kubectl apply -f -
```

**GitOps** — `deployment/gitops/argocd/application.yaml` points Argo CD at the prod overlay with
`buildOptions: --load-restrictor LoadRestrictionsNone`. See `deployment/gitops/README.md` for the
Helm alternative and Secret creation. Promotion = merge a config/manifest PR to `main`; Argo syncs.

**CI guard** — `.github/workflows/ci.yml` job **Deploy smoke (chart + image)** runs `helm lint`,
`helm template` for every values overlay, renders all Kustomize overlays, builds the image, runs the
container with `deployment/smoke/config` (dummy providers, no downloads) and asserts `/health` and
`/ready`. Local equivalent:

```bash
docker build -f deployment/Dockerfile -t genai-platform:smoke .
docker run -d --name genai-smoke -p 8000:8000 \
  -v "$PWD/deployment/smoke/config:/app/config:ro" genai-platform:smoke
curl -fsS http://localhost:8000/health && curl -fsS http://localhost:8000/ready
```

---

## 5. Agentic and RAG topology (BYO framework)

The blueprint ships a **request/response RAG pipeline** and the seams to plug into an agent stack —
not an agent framework. Long-running agent flows belong in workers around the API.

### 5.1 Seams (implement these, keep the composition root config-driven)

| Seam | Interface | Swap via |
|---|---|---|
| LLM / planner model | `core/interfaces/llm.py` (`generate`, `generate_batch`) | `config/models.yaml` |
| Embeddings | `core/interfaces/embedder.py` (`embed`, `embed_batch`) | `config/models.yaml` |
| Retrieval (vector, hybrid, KG) | `core/interfaces/retriever.py` | `config/retrieval.yaml` |
| Reranking | `core/interfaces/reranker.py` | `config/retrieval.yaml` |
| Query expansion | `core/interfaces/query_expander.py` | `config/retrieval.yaml` |
| Guardrails (input/output) | `core/interfaces/guardrail.py` | `config/guardrails.yaml` |
| Evaluation | `core/interfaces/evaluator.py` | `config/retrieval.yaml` |

Registries (`core/registry/*`) resolve these from YAML, so an agent runtime can call the pipeline
over HTTP or embed the composition root without importing concrete providers.

### 5.2 Worker/queue topology for long-running flows

```text
client → API (fast: validate, enqueue) → queue → worker pods → pipeline / tools → durable store
                                             ↳ checkpoints, retries, idempotency keys
```

- The API is synchronous today: `POST /v1/query` and `POST /v1/query:batch` (sequential or bounded
  thread pool). Use them from workers; add a queue in front for multi-step agent loops.
- **Checkpointing/durability:** persist agent state and tool outputs in your store (the platform
  does not own agent memory). Make steps idempotent; a retried step must not duplicate side effects.
- **Per-tool egress control:** default-deny network policy; one allowlist entry per tool endpoint;
  route tool traffic through an egress proxy with logging. LLM provider egress is separate from tool
  egress.
- **Sandboxing:** run tools in isolated containers/VMs with CPU/memory/time limits and no ambient
  credentials. The blueprint ships no shell/code-execution tool by design.
- **Governance:** keep guardrails on the ingress/egress edges (they run inside `RAGPipeline.run`),
  and use `config/resilience.yaml` for provider retries/circuit breakers/failover. Audit and
  Prometheus already record the pipeline calls; instrument the tool layer separately.
- **Timeouts:** set per-request timeouts at the worker level; the pipeline's stages are timed and
  failures are classified, but it does not impose an overall request deadline.

---

## 6. Non-goals

- No cloud-specific Terraform/CDK/ARM templates (roadmap G6).
- No bundled production database, queue or object store; in-memory ops stores are intentionally
  ephemeral until E4 (#56).
- No agent framework, tool catalog or sandbox runtime — only the seams and guidance above.
- No built-in multi-region replication/failover (G6 #71).
- No UI-based config editor: YAML in git remains the write path.
- `POST /v1/pipeline:rebuild` is not a deployment mechanism (no persistence, no rollout).

---

## 7. Related documents

- [`architecture.md`](architecture.md) — contracts, composition root, stages, failure taxonomy,
  observability, config reference.
- [`architecture.md` §12.1](architecture.md#121-config-schemas-validation-and-secrets-issue-46) —
  schemas, validation, secrets interpolation.
- [`architecture.md` §13](architecture.md#13-deployment-modes) — shadow vs. inline gateway patterns.
- [`ux-and-api.md`](ux-and-api.md) — API surface and console.
- [`enterprise-roadmap.md`](enterprise-roadmap.md) — workstreams G (delivery), D (serving) and E
  (platform engineering), including what lands in G2–G6.
- `deployment/Dockerfile`, `deployment/docker-compose.yml`, `.env.example` — the shipped artifacts.
