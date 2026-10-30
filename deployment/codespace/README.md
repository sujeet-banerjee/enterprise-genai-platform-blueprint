# GitHub Codespaces demo (issue #105)

Run the full blueprint - FastAPI backend plus the Streamlit console - in a
throwaway GitHub Codespace, with both ports forwarded and no local setup.

## Launch

1. Open the repository on GitHub.
2. **Code -> Codespaces -> Create codespace on `main`** (pick a 4-core machine
   if you can; the default 2-core works but the first query is slower).
3. Wait for the container build and `postCreateCommand` to finish. It creates a
   workspace virtualenv (`.venv`), installs `requirements.txt`, `requirements-ui.txt`
   and `requirements-observability.txt` into it, validates the shipped config, and
   seeds `deployment/codespace/.env`.
4. `postStartCommand` starts both processes. Open the **Ports** panel or the
   browser tab that Codespaces opens automatically.

| Port | Process | Visibility | URL |
|------|---------|------------|-----|
| 8000 | FastAPI (`uvicorn app.main:app`) | private | `https://<codespace>-8000.app.github.dev` |
| 8501 | Streamlit console (`ui/app.py`) | public | `https://<codespace>-8501.app.github.dev` |

The console talks to the API server-side (`--api-base http://localhost:8000`),
so the private API port is enough for the demo. To explore `/docs` or `curl`
the API from your browser, change port 8000 to **Public** in the Ports panel
(and stop the codespace when you are done).

> Running instances are listed at <https://github.com/codespaces>. The repo page
> `settings/codespaces` only holds repo-level settings (secrets, prebuilds,
> retention) - it does not list or create instances.

## Creating a Codespace from the CLI (optional)

The web UI path above needs no extra permissions. The GitHub CLI can also
create/manage codespaces, but it requires the **`codespace` OAuth scope**. The
default `gh` login (repo/workflow/project) does not include it, so
`gh codespace list` fails with `HTTP 404 ... needs the "codespace" scope`.

### 1. Grant the scope (one-time, device flow)

```bash
gh auth refresh -h github.com -s codespace
```

On this WSL setup, use the Windows GitHub CLI binary:

```bash
"/mnt/c/Program Files/GitHub CLI/gh.exe" auth refresh -h github.com -s codespace
```

The command prints a one-time code and waits:

1. Copy the code shown as `First copy your one-time code: XXXX-XXXX`.
2. Open <https://github.com/login/device> in any browser (from WSL, Windows or
   your phone) and sign in as `sujeet-banerjee`.
3. Enter the code and approve the requested access for **GitHub CLI**.
4. Return to the terminal; it finishes with `Authentication complete`.

The refresh keeps your existing scopes and adds `codespace`. Verify with:

```bash
gh auth status
# Token scopes: 'codespace', 'gist', 'project', 'read:org', 'repo', 'workflow'
```

### 2. Create and open a codespace

```bash
# default machine; uses .devcontainer/devcontainer.json and branch main
gh codespace create -R sujeet-banerjee/enterprise-genai-platform-blueprint -b main

# optional: 4-core machine (names vary by plan) and a shorter idle timeout
gh codespace create -R sujeet-banerjee/enterprise-genai-platform-blueprint -b main \
  --machine standardLinux32gb --idle-timeout 30m
```

The command prints the codespace name. Then:

```bash
gh codespace list                       # name, repo, branch, state, machine
gh codespace code -c <name>             # open in VS Code desktop
gh codespace ssh -c <name>              # shell inside the container
```

The devcontainer `postCreateCommand`/`postStartCommand` run automatically, so
the API (`:8000`) and console (`:8501`) come up as in the UI flow. The first boot
takes a few minutes (image + dependency install + model download).

### 3. Stop or delete

```bash
gh codespace stop -c <name>             # stop billing for compute, keep disk
gh codespace delete -c <name>           # remove it (prompts for confirmation)
```

CLI-created codespaces consume the same Codespaces quota as UI-created ones.
Stopped codespaces are retained for the repo/user retention period (30 days by
default); delete them when you are done with the demo.

## First run downloads the models

The shipped config uses local HuggingFace models (Qwen2.5-0.5B + MiniLM), so no
API key is required. The first start downloads roughly 1.5 GB into
`/home/vscode/.cache/huggingface`; `start.sh` waits up to 300 seconds for
`/health`. On a 2-core codespace this can be tight - if it times out:

```bash
tail -n 100 /tmp/genai-codespace/api.log
bash deployment/codespace/start.sh   # safe to re-run; it waits again
```

Optionally warm the cache in a terminal before opening the console:

```bash
python examples/run_query.py "What is retrieval augmented generation?"
```

## Secrets (optional)

No secret is required for the default local-model demo. If you want to use an
OpenAI model or a gated HuggingFace model:

- **Preferred:** add Codespaces secrets named `OPENAI_API_KEY` / `HF_TOKEN`
  (GitHub -> Settings -> Codespaces -> Secrets). They are injected as
  environment variables and never committed.
- **Manual:** uncomment the placeholders in `deployment/codespace/.env`
  (created from `.env.example` by `setup.sh`; gitignored) and restart:

```bash
bash deployment/codespace/stop.sh
bash deployment/codespace/start.sh
```

Switch the active model in `config/models.yaml` (for example `active_model:
openai`), exactly as you would locally - no code changes.

## What to try

- **Query Studio**: ask a question, inspect retrieved docs, scores, latency,
  cost, cache/guardrail/redaction flags, the resilience block and the OTel ids.
- **Guardrails / Audit / Access / Governance & Cost**: the observability extra is
  installed, so `/metrics` and the Prometheus panels work out of the box.
- **Compare (what-if)**: enable `api.allow_rebuild: true` in `config/api.yaml`
  and restart to try runtime pipeline swaps.
- **Tests**: `python -m pytest -q` (the full suite needs the local models and
  takes a while; start with `tests/test_composition_root.py`).

## Lifecycle

```bash
bash deployment/codespace/start.sh   # idempotent
bash deployment/codespace/stop.sh    # stops both processes
```

Logs and pid files live in `/tmp/genai-codespace` (`api.log`, `ui.log`).
Stopping or deleting the codespace removes them; the HuggingFace cache survives
stop/start but not a rebuild.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Console shows "API unreachable" | `tail -n 100 /tmp/genai-codespace/api.log`; rerun `start.sh` |
| `start.sh` times out on first boot | Model download still running - wait and rerun, or use a 4-core machine |
| Port not opening | Ports panel -> set 8501 to Public, 8000 to Private/Public as needed |
| `streamlit: command not found` | Re-run `bash deployment/codespace/setup.sh` (rebuilds `.venv`) |
| Changed config not picked up | Restart with `stop.sh` then `start.sh` |

## Artifact layout

GitHub only reads `.devcontainer/devcontainer.json` from the repository root, so
that file is a thin manifest (compose path, ports, lifecycle commands). Every
other Codespaces artifact is kept in this directory:

```
.devcontainer/devcontainer.json        # required root manifest (pointer)
deployment/codespace/
  docker-compose.yml                   # dev workspace image + repo mount
  setup.sh                             # postCreate: deps, config validation, .env
  start.sh                             # postStart: API + console (idempotent)
  stop.sh                              # stop both processes
  .env.example                         # commented secret placeholders
  README.md                            # this file
```

The scripts are plain bash and also work in any Linux devcontainer, WSL, or
macOS shell; they do not require Codespaces-specific tooling.
