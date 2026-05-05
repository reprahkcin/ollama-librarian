#!/usr/bin/env bash
set -euo pipefail

http_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

if http_ok "http://127.0.0.1:11434/api/tags"; then
  echo "Ollama: running"
else
  echo "Ollama: stopped"
fi

if http_ok "http://127.0.0.1:8088/api/pdf/status"; then
  echo "Web UI: running (http://127.0.0.1:8088)"
else
  echo "Web UI: stopped"
fi
