#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${OLLAMA_LIBRARIAN_STATE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian}"
RUN_DIR="$STATE_DIR/run"
OLLAMA_PID_FILE="$RUN_DIR/ollama.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"

stop_pid_file() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}

http_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

echo "Stopping web app and Ollama (if running)..."
stop_pid_file "$WEB_PID_FILE"
stop_pid_file "$OLLAMA_PID_FILE"

pkill -f "scripts/ollama-web-chat.py" >/dev/null 2>&1 || true
pkill -f "ollama serve" >/dev/null 2>&1 || true

if http_ok "http://127.0.0.1:11434/api/tags"; then
  echo "Note: Ollama is still running (possibly managed by another user/service)."
fi

echo "Stopped."
