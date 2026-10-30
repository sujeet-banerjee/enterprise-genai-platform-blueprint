#!/usr/bin/env bash
#
# Stop the Codespaces demo processes started by start.sh (issue #105).
set -euo pipefail

LOG_DIR="${GENAI_DEMO_LOG_DIR:-/tmp/genai-codespace}"

declare -a pids=()
for name in ui api; do
  pid_file="$LOG_DIR/$name.pid"
  [ -f "$pid_file" ] || continue
  pid="$(cat "$pid_file")"
  rm -f "$pid_file"
  if kill -0 "$pid" 2>/dev/null; then
    echo "[codespace] stopping $name (pid $pid)"
    kill "$pid" 2>/dev/null || true
    pids+=("$pid:$name")
  fi
done

for _ in $(seq 1 10); do
  alive=0
  for entry in "${pids[@]:-}"; do
    pid="${entry%%:*}"
    kill -0 "$pid" 2>/dev/null && alive=1
  done
  [ "$alive" = "0" ] && break
  sleep 1
done

for entry in "${pids[@]:-}"; do
  pid="${entry%%:*}"
  name="${entry##*:}"
  if kill -0 "$pid" 2>/dev/null; then
    echo "[codespace] force-killing $name (pid $pid)"
    kill -9 "$pid" 2>/dev/null || true
  fi
done

echo "[codespace] demo stopped"
