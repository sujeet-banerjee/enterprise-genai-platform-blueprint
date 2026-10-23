# Enterprise-Grade GenAI Platform Blueprint

A modular, vendor-neutral, evaluation-aware GenAI platform reference implementation. Behaviour is configuration-driven - models, retrievers, rerankers, evaluators, query expanders, chunking, token budgets, governance, and observability can be toggled or swapped without modifying orchestration or API code.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture, principles, composition root, registries, and contracts. To run it (Docker Compose, Kubernetes, air-gapped, BYO-model, embedded), see the [deployment playbook](docs/deployment.md).

## Quickstart

### 1) Clone and setup

Create and activate a virtual environment first (recommended). On Windows (PowerShell):

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Then install the project. `pip install -e .` installs the runtime dependencies (including
`uvicorn`):

```bash
git clone https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
cd enterprise-genai-platform-blueprint
pip install -e .
```

If you use the classic requirements flow instead, install the runtime requirements plus the
dev tooling:

```bash
pip install -r requirements-dev.txt
```

The default config uses local HuggingFace models (Qwen2.5-0.5B + MiniLM), so no API
keys are required. Models are downloaded to the HuggingFace cache on first run. Set a
`HF_TOKEN` environment variable only if you need gated models.

Optional extras are available via `pip install -e ".[dev]"` (pytest/ruff/mypy) and
`pip install -e ".[ui]"` (Streamlit console).

### 2) Run tests

```bash
python -m pytest -v
```

The first run downloads the local models and is slow (~30 min cold, ~7-10 min warm).
To run a fast subset while iterating:

```bash
python -m pytest tests/test_composition_root.py tests/test_api_foundation.py -q
```

### 3) Lint, typecheck, coverage

```bash
python -m ruff check .
python -m mypy app core
python -m pytest --cov=app --cov=core --cov-fail-under=78
```

### 4) Run the API

```bash
uvicorn app.main:app --reload
```

The pipeline is built in the lifespan startup hook, so the server fails loudly on
startup (rather than on first request) if a model or config is invalid.

Example request:
```bash
curl -X 'POST' \
  'http://localhost:8010/v1/query' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "query": "What is AI?",
  "top_k": 1,
  "include_trace": true
}'
```

Example evaluation request (runs the active evaluator on a query/response; `retrieved_docs`
is optional and auto-retrieved from the live pipeline when omitted):
```bash
curl -X 'POST' \
  'http://localhost:8010/v1/evaluate' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
  -d '{
  "query": "What is AI?",
  "response": "AI is the simulation of human intelligence by machines.",
  "ground_truth": "Artificial intelligence is intelligence demonstrated by machines.",
  "top_k": 3
}'
```

### 5) Run the examples (no API server needed)

The [`examples/`](examples/) directory has standalone, runnable scripts that call the
same composition root as the API:

```bash
python examples/run_query.py "What is machine learning?"
python examples/swap_components.py
```

`run_query.py` builds the pipeline from config and prints the response, sources and
scores. `swap_components.py` demonstrates swapping a retriever (and optionally the LLM)
purely by editing YAML - no code change. See [`examples/README.md`](examples/README.md).


## API

The FastAPI app is created by `app/main.py::create_app()`; the pipeline is built in
the lifespan startup hook (not at import). Endpoints:

- `GET /health` - liveness (always 200)
- `GET /ready` - readiness + active pipeline summary (503 until ready)
- `POST /v1/query` - run a query; body `{query, top_k?, include_trace?}`
- `POST /query` - legacy alias of `/v1/query`
- `POST /v1/query:batch` - run several queries sequentially or in parallel (`parallel: true`); per-query envelopes + summary
- `GET /v1/config` - redacted effective configuration
- `GET /v1/models`, `/v1/embedding-models`, `/v1/retrievers`, `/v1/rerankers`, `/v1/evaluators` - introspection
- `GET /v1/guardrails` - resolved input/output guardrail chains (previewable while disabled)
- `POST /v1/evaluate` - run an evaluator on a query/response
- `POST /v1/experiments` / `GET /v1/experiments/{exp_id}` - launch and poll experiments
- `POST /v1/pipeline:rebuild` - runtime component swap via config overrides (gated by `api.allow_rebuild`)
- `GET /v1/governance/status`, `GET /v1/traces/{request_id}`, `GET /v1/metrics` - governance & observability
- `GET /metrics` - Prometheus exposition (requires the optional `observability` extra; 503 otherwise)
- `GET /v1/audit` - read the redacted append-only audit trail (`event_type`/`limit` filters)
- `GET /v1/access` - report the calling persona's role and effective permissions
- `GET /v1/tenants` - resolved tenant/workspace/app identity and per-tenant policy
- `GET /v1/attribution` - request/spend totals grouped by tenant/workspace/app/user/cost_center (`tenant`, `window_seconds` filters)
- Interactive docs at `/docs`

Every response carries `request_id`, `error`, `failure_type` and `failure_tags`, and the
`X-Request-ID` header is echoed (or generated) per request. An optional API-key check
(config/api.yaml: `require_api_key`, `api_key`) is a config-driven stub, disabled by default.

## Streamlit console (UX)

A v1 console lives in `ui/` and consumes **only** the public HTTP API - it never imports
`app.*` or `core.*` (enforced by a test). Start the backend first, then the console:

```bash
# terminal 1 - backend
uvicorn app.main:app --reload

# terminal 2 - console (UI-only deps)
pip install -r requirements-ui.txt
streamlit run ui/app.py -- --api-base http://localhost:8000
```

Walkthrough: open **Query Studio**, enter a question with `top_k=3`, and the answer,
retrieved docs + scores, per-stage latency, cost, failure tags and the redacted trace are
shown - plus flags for response-cache hits, guardrails, input redaction and query expansion,
the `guardrail_decisions` table, the provider-`resilience` block and OTel `trace_id`/`span_id`.
Open **Traces** with the returned `request_id` to see the same trace the server logs;
**Governance & Cost** shows the spend window, metrics, the guardrail hit-rate breakdown and a
raw Prometheus `/metrics` panel. **Compare (what-if)** rebuilds the
pipeline with overrides when `api.allow_rebuild=true`. **Guardrails** previews the resolved
input/output chains (and the selected `profile`), runs a probe query to show per-request
decisions, and reports hit-rate. **Audit** reads the redacted trail (`limit`/`event_type`
filters) and **Access / RBAC** shows the calling persona's role/capabilities. API failures
render as the failure taxonomy (`failure_type` + `failure_tags`), not stack traces.

First-time users: click **Take the tour** in the sidebar for a guided, step-by-step
walkthrough of every screen (Back / Next / Skip), or open the always-available
**Help & tour guide** expander for the same reference at any time.

## End-to-end scenario: real retrieval + all metrics via the console

This walkthrough uses the **Streamlit console** entirely through clicks - no `curl` - to run
one real retrieval-augmented query and then score it with every available metric, including
the genuine LLM-as-judge. It assumes the backend and console are already running (see
[Streamlit console](#streamlit-console-ux) above).

Optional prep: to let the judge model actually run, make sure the local judge model is
available (it downloads on first use, no API key needed). The active evaluator is configured
in `config/retrieval.yaml` under `evaluation.active_evaluator`.

1. **Open the console** at `http://localhost:8501` (the URL Streamlit prints on start).
   In the sidebar, set **API base URL** to where the backend runs (default
   `http://localhost:8000`). Leave **API key (optional)** blank unless auth is enabled.
   Click **Take the tour** if this is your first time.

2. **Overview / Health** (sidebar `Screen` = *Overview / Health*).
   Confirm the tiles read `Health: ok`, `Ready: ready`, and that the four metrics show
   **Active model**, **Retriever**, **Reranker**, **Evaluator**. Note the evaluator tile
   value - that is your *active* evaluator for step 4.

3. **Run a real retrieval** (sidebar `Screen` = *Query Studio*).
   - **Query**: `What is retrieval augmented generation?`
   - **top_k**: `3`
   - Keep **Include redacted trace** checked.
   - Click **Run query**.
   You should see an **Answer**, the **Retrieved documents** table (3 rows with `score` +
   `content`), a **Per-stage latency** table, cost/latency/failure tiles, the **raw redacted
   trace**, and a `request_id` caption. Copy that `request_id` - you will use it in step 6.

4. **Score it with the LLM-as-judge** (sidebar `Screen` = *Evaluation*).
   - **Query**: `What is retrieval augmented generation?`
   - **Response**: paste the answer from step 3 (or type
     `RAG grounds an LLM on retrieved documents that are fetched for the question.`).
   - **Evaluator**: choose `llm_judge` from the dropdown (blank/`(active)` reuses the active
     evaluator). This is the genuine LLM-as-judge: it calls the local Qwen model, so it takes
     noticeably longer than the embedding-based `semantic` evaluator - that is expected.
   - **Ground truth (optional)**: `Retrieval augmented generation combines a retriever with a
     language model so answers are grounded in retrieved documents.`
   - Click **Evaluate**.
   The screen shows the **evaluator** used, a caption with `docs_source` (should be
   `retrieval`, since docs are auto-fetched from the live pipeline), `num_retrieved_docs`,
   and `ground_truth_used`. The **metrics** table then shows the judge scores
   (`llm_judge_score`, `answer_relevance`, and - because a ground truth was supplied -
   `answer_correctness`, each 0-1).

   Note on ground truth: the `semantic` and `llm_judge` evaluators consume the reference
   answer and report a `ground_truth_used` of `true` (semantic adds an embedding-based
   `ground_truth_similarity` + `answer_correctness`; llm_judge adds a judged
   `answer_correctness`). Other evaluators (e.g. `dummy`) cannot use a reference, so the
   value is echoed for traceability with `ground_truth_used=false` - the console tells you
   this explicitly.

5. **Compare embedding models / chunking** (same *Evaluation* screen, **Launch experiment**).
   - **kind**: `compare_embedding_models` (or `compare_chunking_strategies`).
   - Click **Launch**. An experiment id appears (runs asynchronously).
   - Paste the id into **Experiment id** and click **Poll experiment** until its status is
     `completed`, then inspect the per-variant metrics.

6. **Inspect the trace & governance** (sidebar `Screen` = *Traces*, then *Governance & Cost*).
   - *Traces*: paste the `request_id` from step 3 and click **Look up trace** to see the exact
     redacted trace the server logged plus a per-stage latency table.
   - *Governance & Cost*: confirm **Governance** = `enabled`, the **Max cost / request** cap,
     and the rolling **spend window**; the **Metrics** block shows the running totals
     (`Total runs`, `Successes`, `Failures`, `Failure rate`) and `Failures by type`.

7. **Read back the effective config** (sidebar `Screen` = *Settings (read-only)*).
   Expand **Evaluators** to confirm `llm_judge` is configured and that secrets render as
   `[REDACTED]`. YAML files in `config/` remain the source of truth.

### Every metric you just saw (and where it comes from)

- **`llm_judge_score` / `answer_relevance`** - genuine LLM-as-judge grading (`llm_judge`
  evaluator, 0-1 normalized from a 0-10 judge score).
- **`context_precision`, `faithfulness`, `answer_relevance`** - embedding-based metrics
  (`semantic` evaluator).
- **`answer_correctness` / `ground_truth_similarity`** - ground-truth-aware scores, only
  when a `ground_truth` reference is supplied: `llm_judge` returns a judged
  `answer_correctness`; `semantic` returns an embedding-based `ground_truth_similarity`
  plus a derived `answer_correctness`.
- **Retrieval** - `retrieved_docs_with_scores` (per-doc `score`), `top_k`, `similarity_metric`.
- **Cost** - `estimated_cost_usd` per request (per-model pricing) and aggregated spend window.
- **Latency** - per-stage and total (`total_ms`) plus p50/p95 in the metrics endpoint.
- **Failure taxonomy** - `failure_type` + `failure_tags` on any error envelope.

To run the same evaluation without the console, `POST /v1/evaluate` accepts
`{query, response, retrieved_docs?, ground_truth?, evaluator?, top_k?}` - see the
[API](#api) section for a `curl` example.

## Configuration

All behaviour is driven by YAML in config/:

- config/models.yaml - active LLM/embedding models, per-model params, provider mappings
- config/retrieval.yaml - retriever, similarity metric, reranking, query expansion, chunking strategies, token budget
- config/governance.yaml - cost/retrieval-policy governance (enabled, cost cap, safety margin)
- config/observability.yaml - logging, redaction toggle, sensitive patterns, PII/DLP scrubbing (`pii:` block) and OTel tracing (`otel:` block), all disabled by default
- config/prompt_config.yaml - prompt profiles
- config/api.yaml - API key stub, rebuild gate, batch/store limits (all disabled/lean by default)
- config/audit.yaml - append-only audit trail (disabled by default; optional JSONL `path`)
- config/access_control.yaml - RBAC roles/personas, capabilities and request caps (disabled by default)
- config/resilience.yaml - provider retries, circuit breaker and LLM failover (disabled by default)
- config/guardrails.yaml - pluggable input/output guardrail chains, incl. `injection` and `pii` providers, plus adoptable `standard`/`strict` profiles (disabled by default)
- config/tenants.yaml - tenant/workspace model: identity, per-tenant budget caps/retrieval depth/model allow-lists, config overlays (disabled by default => implicit `default` tenant)
- config/identity.yaml - OIDC/OAuth2 JWT bearer auth, IdP-group -> RBAC role mapping, SCIM provisioning; SAML via OIDC bridge (disabled by default => API-key stub)
- config/attribution.yaml - request attribution dimensions (tenant/workspace/app/user/cost_center) on traces, metrics and cost records; per-user/cost-center reporting is opt-in (disabled by default => privacy-preserving default)

The composition root (`app/main.py::build_pipeline()`) reads these configs and wires
components via registries:

- `governance.enabled` gates `CostGovernor`/`RetrievalPolicyService` (default `true`).
- `reranking.enabled` controls whether the reranking stage runs.
- `evaluation.enabled` controls whether an evaluator is attached.
- `chunking.active_strategy` drives `ChunkerFactory`.
- `query_expansion.enabled` (default `false`) turns on multi-query retrieval: the
  active expander (`synonym` or `llm`) produces query variants, each is retrieved and
  the results are merged/de-duplicated before reranking.

### Validate config & manage secrets

Every config file has a typed schema and is validated **at startup** (split into its own
file too): an unknown key or wrong type fails fast with a precise message instead of
surfacing late at request time. Validate manually before deploying:

```bash
python -m app.config_validate            # all config/*.yaml (exit 0 valid, 1 invalid, 2 unreadable)
python -m app.config_validate config/api.yaml --json
```

Never put secrets in config. Reference environment-backed secrets and they are resolved at
load time (and redacted from `/v1/config`, traces and logs):

```yaml
api:
  api_key: ${OPENAI_API_KEY}      # or: env:OPENAI_API_KEY
```

A missing referenced secret fails fast. In production, mount secrets with Vault (Agent
Injector) or a Kubernetes `secretKeyRef` so the value is present in the process environment
— the same `${ENV_VAR}` syntax works unchanged. Set `config_version` at the top of a file to
pin the schema; a newer version warns (with migration note) rather than failing.

## Development notes

### Project layout

```text
app/        FastAPI surface: create_app(), pipeline, introspection, evaluation/ops/what-if APIs
core/       interfaces/ (contracts), implementations/ (backends), registry/ (factories), services/
config/     YAML configuration - the single source of truth for behaviour
ui/         Streamlit console (HTTP-only client of the public API)
tests/      pytest suite (behavioural tests drive real local models)
data/       sample corpus (data/docs.json)
docs/       architecture.md, deployment.md, ux-and-api.md, enterprise-roadmap.md
```

### How to run the backend

Start a dev server with autoreload:

```bash
uvicorn app.main:app --reload
```

Run on a different host/port (for example to expose it to the console on another host):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run with the API-key stub enabled by editing `config/api.yaml` first:

```yaml
require_api_key: true
api_key: "my-secret"
```

Then every request must send `X-API-Key: my-secret` (except `/health`, `/ready`, `/docs`).

### Deploy to Kubernetes (Helm or Kustomize)

```bash
# Helm: API Deployment/Service/PVC with probes; values per environment.
helm upgrade --install genai deployment/helm/genai-platform \
  -n genai-platform --create-namespace -f deployment/helm/genai-platform/values.staging.yaml

# Kustomize: base + dev/staging/prod overlays; config comes from the real config/ dir.
kubectl kustomize --load-restrictor LoadRestrictionsNone deployment/kustomize/overlays/prod \
  | kubectl apply -f -
```

A minimal Argo CD `Application` lives in `deployment/gitops/argocd/`. CI runs `helm lint`/`template`,
renders every Kustomize overlay, builds the image and asserts `/health` + `/ready` in the
**Deploy smoke** job. Details, modes and tradeoffs: [docs/deployment.md](docs/deployment.md).

### How to run the frontend (Streamlit console)

Install the UI-only dependencies and point the console at the backend:

```bash
pip install -r requirements-ui.txt
streamlit run ui/app.py -- --api-base http://localhost:8000
```

If the backend has API-key auth enabled, paste the key into the console sidebar
("API key (optional)"). The console is a pure HTTP client; if a screen needs data that
is not exposed, add an endpoint rather than importing backend code.

First-time users can click **Take the tour** in the sidebar (a guided Back/Next/Skip
walkthrough) or open the **Help & tour guide** expander at any time. See
[End-to-end scenario](#end-to-end-scenario-real-retrieval--all-metrics-via-the-console)
for a click-by-click example that runs a real retrieval and scores it with every metric.

### How to run a test suite subset

The suite is organised by concern, so you can target one area:

```bash
# configuration-driven wiring + composition root
python -m pytest tests/test_composition_root.py tests/test_retriever_registry.py -q

# API surface (fast, uses a fake pipeline)
python -m pytest tests/test_api_foundation.py tests/test_api_introspection.py tests/test_api_contract.py -q

# governance, traces, metrics, batch
python -m pytest tests/test_ops_api.py tests/test_batch_query_api.py -q

# genuine model inference (slow)
python -m pytest tests/test_prompt_chunking_embeddings.py -q
```

### How to try the configs manually

The repo ships with working defaults. You can exercise behaviour changes purely by
editing YAML and restarting the server (or calling `/v1/pipeline:rebuild`).

**Swap the retriever / similarity metric** - edit `config/retrieval.yaml`:

```yaml
retrieval:
  default_retriever: faiss   # faiss | simple | dummy | kg | hybrid
  similarity_metric: cosine  # cosine | l2
  top_k: 3
```

**Toggle reranking** - edit `config/retrieval.yaml`:

```yaml
reranking:
  enabled: true
  active_reranker: cross_encoder
```

**Enable query expansion (multi-query retrieval)** - edit `config/retrieval.yaml`:

```yaml
query_expansion:
  enabled: true
  active_expander: synonym   # synonym | llm | noop
  max_variants: 3
  expanders:
    synonym:
      synonyms:
        ai: [artificial intelligence]
```

**Enable response caching** - edit `config/retrieval.yaml`:

```yaml
cache:
  enabled: true        # off by default
  max_entries: 128     # LRU bound
  ttl_seconds: 300     # per-entry TTL
```

Identical `(query, top_k)` pairs are then served from an in-process LRU cache
(scoped to the active model/retriever/embedder so a rebuild never returns stale
answers). Cache hits skip embedding, retrieval and generation, and surface
`cache_hit: true` in the result and its `observability` block.

**Enable the audit trail** - edit `config/audit.yaml`:

```yaml
enabled: true
path: "audit.jsonl"   # optional JSONL output; empty = in-memory only
max_entries: 1000
```

When enabled, governance denials, retrieval-policy degradation and pipeline
rebuilds are appended to a structured, append-only trail (redacted via the
observability redactor) and exposed at `GET /v1/audit`. Off by default.

**Enable RBAC / personas** - edit `config/access_control.yaml`:

```yaml
enabled: true
default_role: admin
roles:
  viewer:
    capabilities: ["query", "introspect"]
    top_k_max: 3
api_keys:
  "viewer-key": viewer
```
Each request resolves its API key to a role; capabilities gate endpoints
(e.g. `rebuild`, `audit`, `governance`), `top_k_max` caps retrieval depth for a
persona, and `GET /v1/access` reports the caller's effective permissions. Off by
default (all callers get every capability).

**Enable SSO (OIDC) + SCIM provisioning** - edit `config/identity.yaml`:

```yaml
enabled: true
issuer: https://idp.example.com/
audience: genai-platform
jwks_uri: https://idp.example.com/.well-known/jwks.json
group_claim: groups
group_role_map:
  platform-admins: admin
  genai-analysts: analyst
default_role: viewer
cost_center_claim: cost_center
scim:
  enabled: true
  tokens: ["env:SCIM_BEARER_TOKEN"]
```

Callers send `Authorization: Bearer <JWT>`; groups map to roles from
`config/access_control.yaml`, and SCIM user/group pushes change capabilities on
the next request. A `tenant` claim supplies the tenant when no `X-Tenant-ID`
header is present. Service-account keys from `access_control.api_keys` still
work for machine callers. SAML is supported via an OIDC bridge (direct SAML SP
is deliberately not built in). Off by default (API-key stub unchanged).

**Report spend per user / cost center (attribution)** - edit
`config/attribution.yaml`:

```yaml
enabled: true
include_user: true
include_cost_center: true
```

Every trace, metric, audit event and cost record always carries the
`tenant`/`workspace`/`app`/`user`/`cost_center` dimensions. With `enabled:
false` (the default) the user and cost-center dimensions collapse to `default`
so no personal identifiers land in telemetry; tenancy and the identity claim
still supply the other dimensions. `GET /v1/attribution` returns request and
spend totals grouped by each dimension over a rolling window
(`?window_seconds=`), and `/metrics` exposes `genai_attributed_requests_total`
and `genai_attributed_cost_usd_total` labelled by tenant/app/user.

**Toggle governed retrieval / cost caps** - edit `config/governance.yaml`:

```yaml
enabled: true
max_cost_per_request_usd: 0.05
safety_margin_tokens: 200
```

**Switch generation parameters** - edit the active model in `config/models.yaml`:

```yaml
active_model: local-qwen
active_embedding_model: all-MiniLM-L6-v2
models:
  local-qwen:
    provider: local_hf
    model_name: Qwen/Qwen2.5-0.5B-Instruct
    context_window: 32768
    max_new_tokens: 128
```

**Enable the what-if rebuild endpoint** - edit `config/api.yaml`:

```yaml
allow_rebuild: true
max_batch_size: 25
history_max_runs: 1000
trace_store_max: 500
```

**Enable Prometheus metrics + the Grafana pack** - install the optional extra, then scrape
`/metrics` (the endpoint returns a 503 envelope until the extra is installed):

```bash
pip install -e ".[observability]"   # or: pip install -r requirements-observability.txt
docker compose -f deployment/docker-compose.yml --profile observability up
```

The shipped dashboard includes a **guardrail decisions / hit-rate** row (allow/redact/block per
guardrail, plus a sustained-block alert), fed by `genai_guardrail_decisions_total` and
`genai_guardrail_blocks_total`. The same breakdown is on `GET /v1/metrics` under `guardrails`.

**Harden against provider outages** (retries + circuit breaker + failover) - edit
`config/resilience.yaml`. Disabled by default; the primary model is `active_model` and
`fallback_models` names other keys in `models.yaml`:

```yaml
resilience:
  enabled: true
  max_attempts: 3
  breaker_threshold: 5
  fallback_models: [openai-gpt-4o-mini]   # used only if the primary keeps failing
```

The wrapper is transparent (`model_name`/cost still reflect the primary); the request trace
gains a `resilience` block with `served_by`, `retries` and `failovers`.

**Adopt the recommended guardrail profile** - the shipped `config/guardrails.yaml` already selects
`profile: standard` (prompt-injection defense on input, instruction-leak scrubbing on output), so a
meaningful policy is one edit away:

```yaml
enabled: true          # ships as false
```

Leave `input`/`output` empty to inherit the profile. A **non-empty** explicit list replaces that
profile chain for the edge, and `profile: none` runs only explicit chains - the preset lives in
config, not code. The same file ships a tighter `strict` preset (higher injection sensitivity, PII
blocked on input and masked on output):

```yaml
profile: strict        # or standard (default), none
```

**Custom input/output guardrails** - edit the same file. `input` runs on the query + retrieved docs
before prompt construction, `output` runs on the generated response before it is returned. Each is
an **ordered** list and a block stops the chain:

```yaml
profile: none
input:
  - provider: deny_list                 # block obvious injection phrases
    terms: ["ignore previous instructions", "disregard all prior"]
output:
  - provider: deny_list                 # or mask instead of block
    terms: ["api_key", "password"]
    mask: "[REDACTED]"
```

A **block** returns a governed failure (`guardrail_input_blocked` / `guardrail_output_blocked`,
HTTP 403); a **redact** (when `mask` is set) rewrites the text and lets the chain continue.
Decisions appear on the trace (`guardrail_decisions`) and in the audit trail. `GET /v1/guardrails`
shows the resolved chains and the selected `profile` (previewable while disabled). Add a custom
guardrail by implementing `BaseGuardrail` (`core/interfaces/guardrail.py`), registering a factory
in `GuardrailRegistry`, and adding a config entry - no orchestration changes.

Shipped providers: `noop`, `deny_list`, `schema_validator`, **`injection`** (prompt-injection /
jailbreak defense, #53), and **`pii`** (personal-data / DLP enforcement, #54). The `injection`
provider blocks direct injections in the query and neutralizes indirect injections embedded in
retrieved (untrusted) documents:

```yaml
input:
  - provider: injection
    sensitivity: medium              # low | medium | high
    trust_retrieved_documents: false # default: treat retrieved docs as untrusted
```

The `pii` provider detects email, phone, credit card (Luhn validated), national id and IP
addresses, plus optional NER classes (names, addresses), and either **redacts** or **blocks**:

```yaml
output:
  - provider: pii
    classes: [email, phone, credit_card, national_id, ip_address]  # default: all
    mode: redact                     # redact | block
    mask: "[REDACTED]"               # optional per-class default override
```

Only the PII **class** and a **count** are recorded (`pii:<class>`, `details.classes`) - never the
matched value. Independent of the guardrail, the `pii:` block in `config/observability.yaml`
scrubs the same classes from traces, logs and the query handed to the model (default off):

```yaml
# config/observability.yaml
pii:
  enabled: true
  classes: [email, phone, credit_card, national_id, ip_address]
  mode: redact                       # redact | block
  # ner: {enabled: true, model: en_core_web_sm, classes: [person_name, address]}
```


**Export traces to Jaeger/Tempo/Datadog** (OTel-native, OTLP) - enable the `otel` block in
`config/observability.yaml` and start the collector + Jaeger (same `observability` profile;
Jaeger UI at http://localhost:16686). Disabled by default:

```yaml
# config/observability.yaml
otel:
  enabled: true
  endpoint: "http://localhost:4318/v1/traces"
  service_name: "enterprise-genai-platform"
  sample_ratio: 1.0
```

Each request emits a root `pipeline.run` span with one child span per stage, carrying
`request_id`, `top_k`, `retriever`, `llm_model`, `embedding_model` and `failure_tags`; the
structured logs are correlated with the trace/span id. The in-process trace remains the source
of truth (`GET /v1/traces/{request_id}`).

With rebuild enabled you can swap the live pipeline without restarting:

```bash
curl -X POST http://localhost:8000/v1/pipeline:rebuild \
  -H "Content-Type: application/json" \
  -d '{"overrides":{"default_retriever":"simple","similarity_metric":"l2","top_k":5}}'
```

**Inspecting the effective configuration** (redacted, secrets never returned):

```bash
curl http://localhost:8000/v1/config
curl http://localhost:8000/v1/models
curl http://localhost:8000/v1/metrics
curl http://localhost:8000/v1/governance/status
```

**Batch query and trace lookup**:

```bash
curl -X POST http://localhost:8000/v1/query:batch \
  -H "Content-Type: application/json" \
  -d '{"queries":["What is RAG?","What is an embedding?"],"top_k":3}'

# use the returned request_id from any query/batch item
curl http://localhost:8000/v1/traces/<request_id>
```

### How to redact secrets / control logging

Edit `config/observability.yaml`:

```yaml
log_level: INFO
redact_sensitive_data: true
low_retrieval_score_threshold: 0.25
sensitive_patterns:
  - "sk-[A-Za-z0-9]{16,}"
```

With `redact_sensitive_data: true`, API responses and traces replace secret values
(and known secret-looking keys such as `api_key`, `access_token`) with `[REDACTED]`.

## Key Concepts

- **Interfaces/contracts**: stable, swappable (core/interfaces/)
- **Implementations**: concrete backends (core/implementations/)
- **Registries**: config-driven factories (ModelRegistry, RetrieverRegistry, RerankerRegistry, EvaluatorRegistry, CostTracker)
- **Composition root**: wiring from config (`app/main.py::build_pipeline()`)
- **Services**: orthogonal utilities (observability, token budget, failure classification, experiments)
- **Evaluation-first**: semantic and LLM-as-judge evaluators; toggled via config
- **Governance & cost**: budgets, policies, redaction

## Development

- Follow config-driven, vendor-neutral design
- Add tests for new behaviour
- Ensure lint, mypy, and tests pass locally before pushing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the trunk-based workflow (protected `main`,
`feature/<issue>-<slug>` branches, PR checklist, release tags) and
[`docs/enterprise-roadmap.md`](docs/enterprise-roadmap.md) for the post-blueprint roadmap
tracked by milestones `H0`-`H3` (umbrella issue #43).

## License

MIT
