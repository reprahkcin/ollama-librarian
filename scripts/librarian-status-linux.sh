#!/usr/bin/env bash
set -euo pipefail

WEB_HOST="${OLLAMA_WEB_HOST:-127.0.0.1}"
WEB_PORT="${OLLAMA_WEB_PORT:-8088}"

http_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

if http_ok "http://127.0.0.1:11434/api/tags"; then
  echo "Ollama: running"
else
  echo "Ollama: stopped"
fi

if http_ok "http://${WEB_HOST}:${WEB_PORT}/api/pdf/status"; then
  echo "Web UI: running (http://${WEB_HOST}:${WEB_PORT})"
else
  echo "Web UI: stopped"
fi
