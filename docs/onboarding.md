# Onboarding guide (issue #129)

> Get from a clean checkout to a running, validated RAG service in about ten
> minutes, then learn where to change things. If you already know the project,
> jump to [First changes](#4-first-changes-you-will-likely-make).

The platform is **config-driven**: you select and tune components in YAML, the
composition root resolves them through registries, and every config file has a
typed schema that is validated at startup. You do not edit `app/pipeline.py` to
swap a vendor.

```
config/*.yaml
   -> core/config/schema.py + validator (+ ${ENV} secrets)
   -> registries (models, retrievers, rerankers, evaluators, guardrails, ...)
   -> app/bootstrap.py::assemble_components
   -> app/pipeline.py  (retrieve -> rerank -> guardrails -> prompt -> LLM -> eval)
   -> app/main.py      (FastAPI)
   -> ui/              (Streamlit console, HTTP-only)
```

## 1. Five-minute path

```bash
git clone https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint
cd enterprise-genai-platform-blueprint
python -m venv .venv && . .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .

genai init my-app                     # recommended golden path (rag-assistant)
genai validate my-app/config          # exit 0 = every file matches its schema
export GENAI_CONFIG_DIR="$PWD/my-app/config"
uvicorn app.main:app                  # http://localhost:8000/docs
```

Ask a question against the scaffolded corpus:

```bash
curl -s http://localhost:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What is machine learning?", "top_k": 3}'
```

Optional console (a pure HTTP client, no backend imports):

```bash
pip install -r requirements-ui.txt
streamlit run ui/app.py -- --api-base http://localhost:8000
```

The default/recommended path downloads small open models on first run
(Qwen2.5-0.5B-Instruct and `all-MiniLM-L6-v2`) into the HuggingFace cache. For a
zero-download smoke test use `genai init my-app --template local-demo` (dummy
providers).

## 2. Choose a golden path

| Template | Use it when | What you get |
|---|---|---|
| `rag-assistant` **(default, recommended)** | you are building a real retrieval-augmented assistant | local Qwen2.5-0.5B + MiniLM, FAISS, chunking, lexical rerank, semantic evaluation, benchmark dataset, cost governance, `standard` guardrails |
| `local-demo` | you want an instant, offline, deterministic API | dummy LLM/embedder/retriever; evaluation/reranking/guardrails off |
| `governed-enterprise` | you need regulated or multi-team operation | RBAC + tenancy + attribution + ACL retrieval + strict guardrails + audit + provider failover + response cache (dummy providers for a fast, deterministic boot) |

```bash
genai templates                                        # list paths
genai init my-app --template governed-enterprise        # scaffold a different path
genai init my-app --force                              # overwrite matching config files
genai init my-app --no-data                            # skip the sample corpus
```

Each template is a **portable config set** (`deployment/templates/<name>/`).
Only the files that define its posture are shipped; an absent file means the
documented safe default (feature off).

## 3. What the generated files mean

`genai init` creates `<target>/config` and `<target>/data`. The files you will
touch most:

| File | Controls | Ships |
|---|---|---|
| `models.yaml` | active LLM + embedding model, per-model params, provider mappings | `rag-assistant`: `local_hf` Qwen + `sentence_transformers` MiniLM |
| `retrieval.yaml` | retriever, `top_k`, similarity metric, chunking, reranking, query expansion, cache, query length limit | FAISS + chunking + lexical rerank |
| `prompt_config.yaml` | system prompt + prompt profiles | grounded "answer only from context" prompt |
| `governance.yaml` | per-request cost cap, token safety margin | enabled with a small cap |
| `observability.yaml` | logging, redaction, PII/DLP, OTel | redaction on, PII/OTel off |
| `guardrails.yaml` | input/output guardrail chains + `standard`/`strict` profiles | enabled `standard` |
| `eval_datasets.yaml` | evaluation datasets + regression thresholds | benchmark wired, regression gate off |
| `api.yaml` | API-key stub, rebuild gate, batch/history limits | conservative (governed path) |
| `access_control.yaml` | RBAC roles, capabilities, per-role `top_k_max` | enabled (governed path) |
| `tenants.yaml` | tenants/workspaces, policy overlays, API-key mapping | enabled (governed path) |
| `acl.yaml` | permission-aware retrieval (`open`/`deny`, over-fetch, bypass roles) | enabled, `open` default |
| `attribution.yaml` | user/cost-center attribution on traces, metrics, cost | enabled (governed path) |
| `audit.yaml` | append-only audit trail (+ optional immutable hash chain) | enabled, in-memory (governed path) |
| `resilience.yaml` | retries, circuit breaker, model failover chain | enabled with a fallback (governed path) |
| `persistence.yaml` | memory / SQLite / Postgres store backend | `memory` (governed path) |

The sample corpus is `data/docs.json`; `documents_path: data/docs.json` resolves
relative to the **parent of the config directory**, which is why `genai init`
places `data/` next to `config/`.

## 4. First changes you will likely make

**Swap a model or provider.** Edit `models.yaml` and point `active_model` /
`active_embedding_model` at an entry. For OpenAI, set `provider: openai` and
reference a secret (never commit a key):

```yaml
models:
  gpt:
    provider: openai
    model_name: gpt-4o-mini
    context_window: 128000
    temperature: 0.2
    api_key: ${OPENAI_API_KEY}      # or: env:OPENAI_API_KEY
```

**Use your own documents.** Replace `data/docs.json` (the JSON list of
`{"content": ...}` objects) or point `retrieval.retrievers.<name>.documents_path`
at another file. For enterprise sources, see the ingestion framework
(`config/ingestion.yaml`, disabled by default) rather than hand-copying files.

**Tune retrieval.** In `retrieval.yaml`: `top_k`, `similarity_metric`,
`chunking.active_strategy`, `reranking.enabled`, `query_expansion.enabled`,
`cache.enabled`, and `guardrails.max_query_chars`. Retriever providers include
`faiss`, `simple`, `hybrid`, `kg` and `dummy`.

**Turn on evaluation.** `evaluation.enabled: true` attaches the active
evaluator; `eval_datasets.yaml` registers the built-in benchmark and (optionally)
regression thresholds that gate CI via `python -m app.eval_gate`.

**Adopt a guardrail profile.** `guardrails.yaml` ships `standard` and `strict`.
Adopting a policy is a single edit (`enabled: true` plus `profile: standard`); a
non-empty explicit `input`/`output` list overrides that edge's profile chain.

**Add teams and policy.** Enable `tenants.yaml`, `access_control.yaml`,
`attribution.yaml` and `acl.yaml` (all off by default). `governed-enterprise`
shows a working combination; keys are supplied via your secret manager, not YAML.

## 5. Validate before you deploy

The same schema stack runs at startup, in the CLI, and in CI:

```bash
genai validate my-app/config                              # this project's CLI
python -m app.config_validate --config-dir my-app/config  # explicit directory
python -m app.config_validate config/api.yaml --json      # one file, machine-readable
python -m app.config_validate                             # repo config/ (checkout)
```

- An unknown key, wrong type or unresolved `${ENV_VAR}` fails fast with a precise
  message.
- Missing optional files are intentional and fall back to safe defaults.
- `config_version: 1` pins the schema; a newer file version warns (with a
  migration note) instead of failing.

CI additionally validates every golden path
(`python -m app.config_validate deployment/templates/*/*.yaml`), boots each
template, and runs the eval regression gates when enabled. Nothing merges unless
lint, types, tests, deploy smoke and those gates are green.

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `No relevant context available` / empty sources | `documents_path` does not resolve or corpus is empty | keep `data/` beside `config/`, or use an absolute path; re-run `genai validate` |
| Startup fails with a schema error | unknown/wrong-typed key or unresolved secret | read the precise message, fix the YAML, re-run `genai validate` |
| Model download fails / air-gapped | no network and no cache | pre-populate `HF_HOME`, set `HF_TOKEN` for gated models, or use `--template local-demo` |
| `403 guardrail_input_blocked` | the query (or a retrieved doc) tripped a guardrail | expected for injections; inspect `guardrail_decisions` / `GET /v1/guardrails` |
| `402` / `cost_limit_exceeded` | per-request or per-tenant budget cap | raise the cap in `governance.yaml` / tenant policy |
| `503 not_ready` | the app has not finished its lifespan startup | wait for `/ready` to report `status: ready` |
| Port already in use | another server is bound | `uvicorn app.main:app --port 8010` and point the console at it |

## 7. Where to go next

- [`README.md`](../README.md) — features, API surface, console walkthrough.
- [`docs/architecture.md`](architecture.md) — contracts, stage order, failure taxonomy, config reference.
- [`docs/deployment.md`](deployment.md) — Compose, Kubernetes/Helm, Kustomize, GitOps, secrets, DR.
- [`docs/ux-and-api.md`](ux-and-api.md) — every endpoint and console screen.
- [`deployment/templates/README.md`](../deployment/templates/README.md) — golden path details.
- [`docs/enterprise-roadmap.md`](enterprise-roadmap.md) — what is planned next.
