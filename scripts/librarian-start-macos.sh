#!/usr/bin/env bash
set -euo pipefail

# launchd sessions often lack Homebrew paths.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_lib_dir() {
  local candidates=(
    "$HOME/pdf_library"
    "$HOME/Documents/LLM Library"
    "/Volumes/shared/LLM Library"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  printf '%s\n' "$HOME/Documents/LLM Library"
}

LIB_DIR="${OLLAMA_LIBRARIAN_LIBRARY_DIR:-$(default_lib_dir)}"
STATE_DIR="${OLLAMA_LIBRARIAN_STATE_DIR:-$HOME/Library/Application Support/ollama-librarian}"
WEB_HOST="${OLLAMA_WEB_HOST:-127.0.0.1}"
WEB_PORT="${OLLAMA_WEB_PORT:-8088}"
OCR_ON_SYNC="${OLLAMA_WEB_PDF_OCR_ON_SYNC:-1}"
OCR_LANG="${OLLAMA_WEB_PDF_OCR_LANG:-eng}"
OCR_JOBS="${OLLAMA_WEB_PDF_OCR_JOBS:-1}"
OCR_TIMEOUT="${OLLAMA_WEB_PDF_OCR_TIMEOUT:-3600}"
EMBED_NUM_THREAD="${OLLAMA_WEB_PDF_EMBED_NUM_THREAD:-2}"
EMBED_DELAY_MS="${OLLAMA_WEB_PDF_EMBED_DELAY_MS:-200}"
DOC_COOLDOWN_SECONDS="${OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS:-10}"
DYNAMIC_THROTTLE="${OLLAMA_WEB_PDF_DYNAMIC_THROTTLE:-1}"
DYNAMIC_TARGET_EMBED_MS="${OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS:-1400}"
DYNAMIC_MAX_DELAY_MS="${OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS:-2000}"
DYNAMIC_DELAY_STEP_MS="${OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS:-50}"
DYNAMIC_MIN_THREADS="${OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS:-1}"
DYNAMIC_MAX_THREADS="${OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS:-3}"
SAFE_MODE="${OLLAMA_WEB_SAFE_MODE:-1}"
ALLOW_UNSAFE_MODEL="${OLLAMA_WEB_ALLOW_UNSAFE_MODEL:-0}"
MAX_CONCURRENT_GENERATIONS="${OLLAMA_WEB_MAX_CONCURRENT_GENERATIONS:-1}"
FORCE_PRESSURE="${OLLAMA_WEB_FORCE_PRESSURE:-}"
ANSWER_KEEP_ALIVE="${OLLAMA_WEB_ANSWER_KEEP_ALIVE:-60s}"
SAFE_ANSWER_KEEP_ALIVE="${OLLAMA_WEB_SAFE_ANSWER_KEEP_ALIVE:-15s}"
RESOURCE_MONITOR="${OLLAMA_WEB_RESOURCE_MONITOR:-1}"
RESOURCE_MONITOR_POLL_SECONDS="${OLLAMA_WEB_RESOURCE_MONITOR_POLL_SECONDS:-5}"
RESOURCE_MONITOR_CRITICAL_SAMPLES="${OLLAMA_WEB_RESOURCE_MONITOR_CRITICAL_SAMPLES:-2}"
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

web_ok() {
  http_ok "http://${WEB_HOST}:${WEB_PORT}/api/pdf/status" || http_ok "http://127.0.0.1:${WEB_PORT}/api/pdf/status"
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

if web_ok; then
  echo "Web app already running."
else
  echo "Starting web app..."
  nohup env \
    OLLAMA_WEB_HOST="$WEB_HOST" \
    OLLAMA_WEB_PORT="$WEB_PORT" \
    OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    OLLAMA_WEB_PDF_SOURCE="$LIB_DIR" \
    OLLAMA_WEB_PDF_INDEX_DB="$STATE_DIR/pdf-rag.sqlite" \
    OLLAMA_WEB_HISTORY_PATH="$STATE_DIR/ollama-web-chat-history.json" \
    OLLAMA_WEB_STASH_PATH="$STATE_DIR/ollama-response-stash.json" \
    OLLAMA_WEB_PDF_OCR_ON_SYNC="$OCR_ON_SYNC" \
    OLLAMA_WEB_PDF_OCR_LANG="$OCR_LANG" \
    OLLAMA_WEB_PDF_OCR_JOBS="$OCR_JOBS" \
    OLLAMA_WEB_PDF_OCR_TIMEOUT="$OCR_TIMEOUT" \
    OLLAMA_WEB_PDF_EMBED_NUM_THREAD="$EMBED_NUM_THREAD" \
    OLLAMA_WEB_PDF_EMBED_DELAY_MS="$EMBED_DELAY_MS" \
    OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS="$DOC_COOLDOWN_SECONDS" \
    OLLAMA_WEB_PDF_DYNAMIC_THROTTLE="$DYNAMIC_THROTTLE" \
    OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS="$DYNAMIC_TARGET_EMBED_MS" \
    OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS="$DYNAMIC_MAX_DELAY_MS" \
    OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS="$DYNAMIC_DELAY_STEP_MS" \
    OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS="$DYNAMIC_MIN_THREADS" \
    OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS="$DYNAMIC_MAX_THREADS" \
    OLLAMA_WEB_SAFE_MODE="$SAFE_MODE" \
    OLLAMA_WEB_ALLOW_UNSAFE_MODEL="$ALLOW_UNSAFE_MODEL" \
    OLLAMA_WEB_MAX_CONCURRENT_GENERATIONS="$MAX_CONCURRENT_GENERATIONS" \
    OLLAMA_WEB_FORCE_PRESSURE="$FORCE_PRESSURE" \
    OLLAMA_WEB_ANSWER_KEEP_ALIVE="$ANSWER_KEEP_ALIVE" \
    OLLAMA_WEB_SAFE_ANSWER_KEEP_ALIVE="$SAFE_ANSWER_KEEP_ALIVE" \
    OLLAMA_WEB_RESOURCE_MONITOR="$RESOURCE_MONITOR" \
    OLLAMA_WEB_RESOURCE_MONITOR_POLL_SECONDS="$RESOURCE_MONITOR_POLL_SECONDS" \
    OLLAMA_WEB_RESOURCE_MONITOR_CRITICAL_SAMPLES="$RESOURCE_MONITOR_CRITICAL_SAMPLES" \
    "$PYTHON_BIN" "$REPO_DIR/scripts/ollama-web-chat.py" >"$LOG_DIR/web.log" 2>&1 &
  echo $! >"$WEB_PID_FILE"
fi

for _ in {1..30}; do
  if web_ok; then
    break
  fi
  sleep 1
done

if web_ok; then
  echo "Librarian is running at http://${WEB_HOST}:${WEB_PORT}"
else
  echo "Web app did not become ready. Check $LOG_DIR/web.log"
  exit 1
fi
