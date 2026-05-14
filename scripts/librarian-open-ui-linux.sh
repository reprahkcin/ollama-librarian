#!/usr/bin/env bash
set -euo pipefail

URL="http://${OLLAMA_WEB_HOST:-127.0.0.1}:${OLLAMA_WEB_PORT:-8088}"

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
else
  echo "Open this URL in your browser: $URL"
fi
