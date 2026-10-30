#!/usr/bin/env bash
#
# Start the Codespaces demo (issue #105): FastAPI on 8000, Streamlit on 8501.
#
# Invoked by .devcontainer/devcontainer.json -> postStartCommand (idempotent:
# an already-healthy process is left alone). Safe to run manually.
#
# Environment overrides (mainly for tests/CI):
#   GENAI_DEMO_API_PORT     backend port (default 8000)
#   GENAI_DEMO_UI_PORT      console port (default 8501)
#   GENAI_DEMO_START_UI     "0" to skip the console (default 1)
#   GENAI_DEMO_START_TIMEOUT seconds to wait for health (default 300)
#   GENAI_DEMO_LOG_DIR      log/pid directory (default /tmp/genai-codespace)
#   GENAI_DEMO_PYTHON       interpreter used for `-m uvicorn`/`-m streamlit`
#   GENAI_CONFIG_DIR        config directory (default <repo>/config)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ -n "${GENAI_DEMO_PYTHON:-}" ]; then
  PYTHON_BIN="$GENAI_DEMO_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="python"
fi
API_PORT="${GENAI_DEMO_API_PORT:-8000}"
UI_PORT="${GENAI_DEMO_UI_PORT:-8501}"
START_UI="${GENAI_DEMO_START_UI:-1}"
START_TIMEOUT="${GENAI_DEMO_START_TIMEOUT:-300}"
LOG_DIR="${GENAI_DEMO_LOG_DIR:-/tmp/genai-codespace}"

ENV_FILE="$ROOT/deployment/codespace/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

export GENAI_CONFIG_DIR="${GENAI_CONFIG_DIR:-$ROOT/config}"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$LOG_DIR" "$HF_HOME"

api_healthy() {
  curl -fsS --max-time 2 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1
}

ui_healthy() {
  curl -fsS --max-time 2 "http://127.0.0.1:${UI_PORT}/_stcore/health" >/dev/null 2>&1
}

if api_healthy; then
  echo "[codespace] API already healthy on :${API_PORT}"
else
  echo "[codespace] starting API on :${API_PORT} (config: ${GENAI_CONFIG_DIR})"
  nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" \
    >"$LOG_DIR/api.log" 2>&1 &
  echo $! >"$LOG_DIR/api.pid"

  for _ in $(seq 1 "$START_TIMEOUT"); do
    if api_healthy; then
      break
    fi
    sleep 1
  done

  if ! api_healthy; then
    echo "[codespace] API failed to become healthy within ${START_TIMEOUT}s" >&2
    echo "[codespace] see $LOG_DIR/api.log (first start downloads ~1.5 GB of models)" >&2
    tail -n 40 "$LOG_DIR/api.log" >&2 || true
    exit 1
  fi
fi

if [ "$START_UI" = "1" ]; then
  if ui_healthy; then
    echo "[codespace] console already healthy on :${UI_PORT}"
  else
    echo "[codespace] starting Streamlit console on :${UI_PORT}"
    nohup "$PYTHON_BIN" -m streamlit run ui/app.py \
      --server.address 0.0.0.0 \
      --server.port "$UI_PORT" \
      --server.headless true \
      -- --api-base "http://localhost:${API_PORT}" \
      >"$LOG_DIR/ui.log" 2>&1 &
    echo $! >"$LOG_DIR/ui.pid"

    for _ in $(seq 1 "$START_TIMEOUT"); do
      if ui_healthy; then
        break
      fi
      sleep 1
    done

    if ! ui_healthy; then
      echo "[codespace] console failed to become healthy within ${START_TIMEOUT}s" >&2
      tail -n 40 "$LOG_DIR/ui.log" >&2 || true
      exit 1
    fi
  fi
else
  echo "[codespace] GENAI_DEMO_START_UI=0 - skipping console"
fi

echo "[codespace] demo ready"
echo "[codespace]   API:     http://localhost:${API_PORT} (docs at /docs)"
if [ "$START_UI" = "1" ]; then
  echo "[codespace]   Console: http://localhost:${UI_PORT}"
fi
echo "[codespace]   Logs:    ${LOG_DIR}"
