#!/usr/bin/env bash
set -euo pipefail

# launchd sessions often lack Homebrew paths.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB_DIR="${OLLAMA_LIBRARIAN_LIBRARY_DIR:-$HOME/Documents/LLM Library}"
STATE_DIR="${OLLAMA_LIBRARIAN_STATE_DIR:-$HOME/Library/Application Support/ollama-librarian}"
WEB_HOST="${OLLAMA_WEB_HOST:-127.0.0.1}"
WEB_PORT="${OLLAMA_WEB_PORT:-8088}"
WEB_ALLOW_INSECURE_BIND="${OLLAMA_WEB_ALLOW_INSECURE_BIND:-0}"
LOG_DIR="$STATE_DIR/logs"
RUN_DIR="$STATE_DIR/run"
OLLAMA_PID_FILE="$RUN_DIR/ollama.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || true)}"

mkdir -p "$LIB_DIR" "$LOG_DIR" "$RUN_DIR" "$STATE_DIR"

PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python venv at $PYTHON_BIN"
  echo "Run Setup Guides/MAC-SETUP.md first."
  exit 1
fi

if [[ -z "$OLLAMA_BIN" ]]; then
  echo "Could not find 'ollama' in PATH ($PATH)"
  exit 1
fi

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

http_ok() {
  local url="$1"
  curl -fsS "$url" >/dev/null 2>&1
}

if http_ok "http://127.0.0.1:11434/api/tags"; then
  echo "Ollama already running."
else
  echo "Starting Ollama..."
  nohup env OLLAMA_HOST=127.0.0.1:11434 "$OLLAMA_BIN" serve >"$LOG_DIR/ollama.log" 2>&1 &
  echo $! >"$OLLAMA_PID_FILE"
fi

for _ in {1..30}; do
  if http_ok "http://127.0.0.1:11434/api/tags"; then
    break
  fi
  sleep 1
done
if ! http_ok "http://127.0.0.1:11434/api/tags"; then
  echo "Ollama did not become ready. Check $LOG_DIR/ollama.log"
  exit 1
fi

if http_ok "http://127.0.0.1:${WEB_PORT}/api/pdf/status"; then
  echo "Web app already running."
else
  echo "Starting web app..."
  nohup env \
    OLLAMA_WEB_HOST="$WEB_HOST" \
    OLLAMA_WEB_PORT="$WEB_PORT" \
    OLLAMA_WEB_ALLOW_INSECURE_BIND="$WEB_ALLOW_INSECURE_BIND" \
    OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    OLLAMA_WEB_PDF_SOURCE="$LIB_DIR" \
    OLLAMA_WEB_PDF_INDEX_DB="$STATE_DIR/pdf-rag.sqlite" \
    OLLAMA_WEB_HISTORY_PATH="$STATE_DIR/ollama-web-chat-history.json" \
    OLLAMA_WEB_STASH_PATH="$STATE_DIR/ollama-response-stash.json" \
    OLLAMA_WEB_PDF_OCR_ON_SYNC=1 \
    OLLAMA_WEB_PDF_OCR_LANG=eng \
    OLLAMA_WEB_PDF_OCR_JOBS=4 \
    OLLAMA_WEB_PDF_OCR_TIMEOUT=3600 \
    "$PYTHON_BIN" "$REPO_DIR/scripts/ollama-web-chat.py" >"$LOG_DIR/web.log" 2>&1 &
  echo $! >"$WEB_PID_FILE"
fi

for _ in {1..30}; do
  if http_ok "http://127.0.0.1:${WEB_PORT}/api/pdf/status"; then
    break
  fi
  sleep 1
done

if http_ok "http://127.0.0.1:${WEB_PORT}/api/pdf/status"; then
  echo "Librarian is running at http://${WEB_HOST}:${WEB_PORT}"
else
  echo "Web app did not become ready. Check $LOG_DIR/web.log"
  exit 1
fi
