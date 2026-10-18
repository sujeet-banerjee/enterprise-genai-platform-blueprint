# Enterprise-Grade GenAI Platform Blueprint

A modular, vendor-neutral, evaluation-aware GenAI platform reference implementation. Behaviour is configuration-driven - models, retrievers, rerankers, evaluators, chunking, token budgets, governance, and observability can be toggled or swapped without modifying orchestration or API code.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture, principles, composition root, registries, and contracts.

## Quickstart

### 1) Clone and setup

`ash
git clone https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
cd enterprise-genai-platform-blueprint
pip install -e .
`

### 2) Run tests

`ash
python -m pytest -v
`

### 3) Lint, typecheck, coverage

`ash
python -m ruff check .
python -m mypy app core
python -m pytest --cov=app --cov=core --cov-fail-under=78
`

### 4) Run the API

`ash
uvicorn app.main:app --reload
`

Example request:
`ash
curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d '{"query":"What is AI?"}'
`

## Configuration

All behaviour is driven by YAML in config/:
- config/models.yaml - active LLM/embedding models, per-model params, provider mappings
- config/retrieval.yaml - retriever, similarity metric, reranking, chunking strategies, token budget, observability, governance
- config/prompt_config.yaml - prompt profiles

The composition root (pp/main.py::build_pipeline()) reads these configs and wires components via registries. governance.enabled gates CostGovernor/RetrievalPolicyService (default true). eranking.enabled controls reranking. evaluation.enabled controls evaluation. chunking.active_strategy drives ChunkerFactory.

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
