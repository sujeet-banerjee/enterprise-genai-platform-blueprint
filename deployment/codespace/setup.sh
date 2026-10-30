#!/usr/bin/env bash
#
# Codespaces one-time setup (issue #105): install runtime, UI and observability
# dependencies, validate the shipped config, and seed an optional .env file.
#
# Invoked by .devcontainer/devcontainer.json -> postCreateCommand.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "[codespace] installing Python dependencies (runtime + UI + observability)"
PYTHON_BIN="${GENAI_DEMO_PYTHON:-python}"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "[codespace] creating workspace virtualenv at .venv"
  "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
VENV_PY="$ROOT/.venv/bin/python"

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install \
  -r requirements.txt \
  -r requirements-ui.txt \
  -r requirements-observability.txt

echo "[codespace] validating shipped config"
"$VENV_PY" -m app.config_validate --config-dir config

ENV_FILE="$ROOT/deployment/codespace/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/deployment/codespace/.env.example" "$ENV_FILE"
  echo "[codespace] created deployment/codespace/.env (optional secrets; gitignored)"
fi

echo "[codespace] setup complete"
echo "[codespace] start the demo with: bash deployment/codespace/start.sh"
