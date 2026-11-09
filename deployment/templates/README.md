# Golden path templates (issue #127)

Opinionated, schema-validated config starting points for common deployments.
Each directory is a **portable config set**: copy it to a config directory (for
example `config/`) and point the service at it with `GENAI_CONFIG_DIR`.

```bash
# Scaffold a project (recommended path by default) without touching config/
genai init my-app                    # rag-assistant
genai init my-app --template local-demo
export GENAI_CONFIG_DIR="$PWD/my-app/config"
uvicorn app.main:app
```

`genai init` (issue #128) copies the template into `<target>/config`, copies the
sample corpus into `<target>/data` (so `documents_path: data/docs.json` resolves),
validates every file, and prints the next commands. Use `--force` to overwrite an
existing config directory and `--no-data` to skip the corpus.

Missing files are intentional: the platform treats an absent config file as the
safe default (feature off). A template only ships the files that define its
posture. Validate a template exactly like any other config set:

```bash
python -m app.config_validate deployment/templates/*/*.yaml
```

CI runs that validation on every push, and `tests/test_golden_path_templates.py`
boots each template and exercises `/health`, `/ready` and `/v1/query`.

## Which path should I start from?

| Template | Use it when | Models | Posture |
|---|---|---|---|
| [`local-demo`](local-demo) | You want a zero-download, zero-network smoke test or a first look | `dummy` LLM + embedder, dummy retriever | Minimal. Governance/guardrails/eval off. |
| [`rag-assistant`](rag-assistant) **(recommended)** | You are building a real retrieval-augmented assistant | Local Qwen2.5-0.5B + MiniLM, FAISS, lexical rerank | Governance on, standard guardrails on, semantic evaluation on, benchmark dataset wired, response cache off. |
| [`governed-enterprise`](governed-enterprise) | You need multi-team policy, audit and resilience wiring | `dummy` providers (fast, deterministic) | Tenancy + RBAC + attribution + ACL + audit + strict guardrails + retries/circuit-breaker + response cache all on. |

`governed-enterprise` intentionally uses dummy providers so it boots instantly
in CI. Replace `models.yaml`/retrieval with your vendor configs and keep the
policy files; the posture is what the template is demonstrating.

## Files per template

Only the relevant files are included; everything else falls back to safe
defaults.

- `local-demo`: `models.yaml`, `prompt_config.yaml`, `retrieval.yaml`.
- `rag-assistant`: `models.yaml`, `prompt_config.yaml`, `retrieval.yaml`,
  `governance.yaml`, `observability.yaml`, `guardrails.yaml`, `eval_datasets.yaml`.
- `governed-enterprise`: `models.yaml`, `prompt_config.yaml`, `retrieval.yaml`,
  `governance.yaml`, `observability.yaml`, `guardrails.yaml`, `api.yaml`,
  `audit.yaml`, `access_control.yaml`, `tenants.yaml`, `acl.yaml`,
  `attribution.yaml`, `resilience.yaml`, `persistence.yaml`.

## Conventions

- These templates never contain secrets. Add provider keys through environment
  variables (`OPENAI_API_KEY`, `HF_TOKEN`) or `${ENV_VAR}` / `env:VAR` refs in
  your copy; the validator checks that every reference resolves.
- `config_version: 1` is the current schema version; set it explicitly so a
  future upgrade can flag drift.
- Data paths (`data/docs.json`, `data/benchmark.json`) resolve relative to the
  repository root, which is the parent of the directory that contains
  `retrieval.yaml`. Copy the `data/` directory alongside your config, or use
  absolute paths.
- `genai init` (issue #128) scaffolds a project from one of these templates; the
  onboarding guide (issue #129) explains the knobs in depth. Run
  `genai templates` to list paths and `genai validate <config-dir>` to check a
  generated set with the same schemas the server enforces.
