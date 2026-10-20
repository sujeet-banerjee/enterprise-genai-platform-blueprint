# Enterprise-Grade GenAI Platform Blueprint

A modular, vendor-neutral, evaluation-aware GenAI platform reference implementation. Behaviour is configuration-driven - models, retrievers, rerankers, evaluators, chunking, token budgets, governance, and observability can be toggled or swapped without modifying orchestration or API code.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture, principles, composition root, registries, and contracts.

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

## API

The FastAPI app is created by `app/main.py::create_app()`; the pipeline is built in
the lifespan startup hook (not at import). Endpoints:

- `GET /health` - liveness (always 200)
- `GET /ready` - readiness + active pipeline summary (503 until ready)
- `POST /v1/query` - run a query; body `{query, top_k?, include_trace?}`
- `POST /query` - legacy alias of `/v1/query`
- `POST /v1/query:batch` - run several queries sequentially; per-query envelopes + summary
- `GET /v1/config` - redacted effective configuration
- `GET /v1/models`, `/v1/embedding-models`, `/v1/retrievers`, `/v1/rerankers`, `/v1/evaluators` - introspection
- `POST /v1/evaluate` - run an evaluator on a query/response
- `POST /v1/experiments` / `GET /v1/experiments/{id}` - launch and poll experiments
- `POST /v1/pipeline:rebuild` - runtime component swap via config overrides (gated by `api.allow_rebuild`)
- `GET /v1/governance/status`, `GET /v1/traces/{request_id}`, `GET /v1/metrics` - governance & observability
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
shown. Open **Traces** with the returned `request_id` to see the same trace the server logs;
**Governance & Cost** shows the spend window and metrics; **Compare (what-if)** rebuilds the
pipeline with overrides when `api.allow_rebuild=true`. API failures render as the failure
taxonomy (`failure_type` + `failure_tags`), not stack traces.

## Configuration

All behaviour is driven by YAML in config/:

- config/models.yaml - active LLM/embedding models, per-model params, provider mappings
- config/retrieval.yaml - retriever, similarity metric, reranking, chunking strategies, token budget
- config/governance.yaml - cost/retrieval-policy governance (enabled, cost cap, safety margin)
- config/observability.yaml - logging, redaction toggle and sensitive patterns
- config/prompt_config.yaml - prompt profiles
- config/api.yaml - API key stub, rebuild gate, batch/store limits (all disabled/lean by default)

The composition root (`app/main.py::build_pipeline()`) reads these configs and wires
components via registries:

- `governance.enabled` gates `CostGovernor`/`RetrievalPolicyService` (default `true`).
- `reranking.enabled` controls whether the reranking stage runs.
- `evaluation.enabled` controls whether an evaluator is attached.
- `chunking.active_strategy` drives `ChunkerFactory`.

## Development notes

### Project layout

```text
app/        FastAPI surface: create_app(), pipeline, introspection, evaluation/ops/what-if APIs
core/       interfaces/ (contracts), implementations/ (backends), registry/ (factories), services/
config/     YAML configuration - the single source of truth for behaviour
ui/         Streamlit console (HTTP-only client of the public API)
tests/      pytest suite (behavioural tests drive real local models)
data/       sample corpus (data/docs.json)
docs/       architecture.md, ux-and-api.md, INTERFACE_CHANGES.md
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

### How to run the frontend (Streamlit console)

Install the UI-only dependencies and point the console at the backend:

```bash
pip install -r requirements-ui.txt
streamlit run ui/app.py -- --api-base http://localhost:8000
```

If the backend has API-key auth enabled, paste the key into the console sidebar
("API key (optional)"). The console is a pure HTTP client; if a screen needs data that
is not exposed, add an endpoint rather than importing backend code.

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
  default_retriever: faiss   # faiss | simple | dummy
  similarity_metric: cosine  # cosine | l2
  top_k: 3
```

**Toggle reranking** - edit `config/retrieval.yaml`:

```yaml
reranking:
  enabled: true
  active_reranker: cross_encoder
```

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

## License

MIT
