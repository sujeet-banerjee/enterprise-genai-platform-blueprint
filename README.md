# Enterprise-Grade GenAI Platform Blueprint

A modular, vendor-neutral, evaluation-aware GenAI platform reference implementation. Behaviour is configuration-driven - models, retrievers, rerankers, evaluators, chunking, token budgets, governance, and observability can be toggled or swapped without modifying orchestration or API code.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture, principles, composition root, registries, and contracts.

## Quickstart

### 1) Clone and setup

```bash
git clone https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
cd enterprise-genai-platform-blueprint
pip install -e .
```

### 2) Run tests

```bash
python -m pytest -v
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

Example request:
```bash
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{"query":"What is AI?"}'
```

## API

The FastAPI app is created by `app/main.py::create_app()`; the pipeline is built in
the lifespan startup hook (not at import). Endpoints:

- `GET /health` - liveness (always 200)
- `GET /ready` - readiness (503 until the pipeline is built)
- `POST /v1/query` - run a query; body `{query, top_k?, include_trace?}`
- `POST /query` - legacy alias of `/v1/query`
- Interactive docs at `/docs`

Every response carries `request_id`, `error`, `failure_type` and `failure_tags`, and the
`X-Request-ID` header is echoed (or generated) per request. An optional API-key check
(config/api.yaml: `require_api_key`, `api_key`) is a config-driven stub, disabled by default.

## Configuration

All behaviour is driven by YAML in config/:
- config/models.yaml - active LLM/embedding models, per-model params, provider mappings
- config/retrieval.yaml - retriever, similarity metric, reranking, chunking strategies, token budget
- config/governance.yaml - cost/retrieval-policy governance (enabled, cost cap, safety margin)
- config/observability.yaml - logging, redaction toggle and sensitive patterns
- config/prompt_config.yaml - prompt profiles
- config/api.yaml - API key stub (disabled by default)

The composition root (pp/main.py::build_pipeline()) reads these configs and wires components via registries. governance.enabled gates CostGovernor/RetrievalPolicyService (default true). 
eranking.enabled controls reranking. evaluation.enabled controls evaluation. chunking.active_strategy drives ChunkerFactory.

## Key Concepts

- **Interfaces/contracts**: stable, swappable (core/interfaces/)
- **Implementations**: concrete backends (core/implementations/)
- **Registries**: config-driven factories (ModelRegistry, RetrieverRegistry, RerankerRegistry, EvaluatorRegistry, CostTracker)
- **Composition root**: wiring from config (pp/main.py::build_pipeline())
- **Services**: orthogonal utilities (observability, token budget, failure classification, experiments)
- **Evaluation-first**: semantic and LLM-as-judge evaluators; toggled via config
- **Governance & cost**: budgets, policies, redaction

## Development

- Follow config-driven, vendor-neutral design
- Add tests for new behaviour
- Ensure lint, mypy, and tests pass locally before pushing

## License

MIT
