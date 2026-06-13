#!/usr/bin/env bash
set -euo pipefail

# One-command reset for repeatable benchmark/test runs.
# Default behavior keeps the index DB but clears chat/output state.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${OLLAMA_LIBRARIAN_STATE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian}"
WEB_HOST="${OLLAMA_WEB_HOST:-127.0.0.1}"
WEB_PORT="${OLLAMA_WEB_PORT:-8088}"
BASE_URL="http://${WEB_HOST}:${WEB_PORT}"
INDEX_DB="${OLLAMA_WEB_PDF_INDEX_DB:-$STATE_DIR/pdf-rag.sqlite}"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

WIPE_INDEX=0
WIPE_LOGS=0
RUN_CMD=()
WARMUP_MODEL=""

usage() {
  cat <<'EOF'
Usage: ./scripts/librarian-reset-linux.sh [options]

Resets app state in one command for consistent test runs.

Options:
  --wipe-index   Remove PDF index DB files (slow next run due to re-index)
  --wipe-logs    Truncate web/ollama logs in state logs dir
  --warmup-model Preload a model after restart (example: --warmup-model qwen2.5:14b)
  -- <command>   Run command after reset (from repo root)
  -h, --help     Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wipe-index)
      WIPE_INDEX=1
      ;;
    --wipe-logs)
      WIPE_LOGS=1
      ;;
    --warmup-model)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Missing value for --warmup-model" >&2
        usage >&2
        exit 2
      fi
      WARMUP_MODEL="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      RUN_CMD=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

api_call() {
  local method="$1"
  local path="$2"
  local data="${3:-}"

  if [[ -n "$data" ]]; then
    curl -fsS -X "$method" "$BASE_URL$path" \
      -H "Content-Type: application/json" \
      -d "$data" >/dev/null
  else
    curl -fsS -X "$method" "$BASE_URL$path" >/dev/null
  fi
}

echo "[1/5] Stopping app services..."
"$SCRIPT_DIR/librarian-stop-linux.sh"

echo "[2/5] Clearing persisted test state files..."
rm -f "$STATE_DIR/ollama-web-chat-history.json"
rm -f "$STATE_DIR/ollama-response-stash.json"
rm -f "$STATE_DIR/update-state.json"

if [[ "$WIPE_INDEX" -eq 1 ]]; then
  echo "      Wiping index DB: $INDEX_DB"
  rm -f "$INDEX_DB" "$INDEX_DB-shm" "$INDEX_DB-wal" "$INDEX_DB-journal"
fi

if [[ "$WIPE_LOGS" -eq 1 ]]; then
  mkdir -p "$STATE_DIR/logs"
  : >"$STATE_DIR/logs/web.log"
  : >"$STATE_DIR/logs/ollama.log"
fi

echo "[3/5] Starting app services..."
"$SCRIPT_DIR/librarian-start-linux.sh"

echo "[4/5] Resetting in-memory API state..."
api_call "POST" "/api/pdf/index/pause" '{}'
api_call "POST" "/api/cooldown" '{"action":"clear"}'
api_call "POST" "/api/metrics/reset" '{}'
api_call "DELETE" "/api/history"
api_call "DELETE" "/api/stash?all=1"
api_call "DELETE" "/api/bibliography?all=1"

echo "[5/5] Verifying readiness..."
curl -fsS "$BASE_URL/api/pdf/status" >/dev/null

if [[ -n "$WARMUP_MODEL" ]]; then
  echo "      Warming model: $WARMUP_MODEL"
  warmup_payload=$(printf '{"model":"%s","prompt":"Respond with OK.","stream":false,"options":{"num_predict":8}}' "$WARMUP_MODEL")
  warmup_ok=0
  for _ in 1 2 3; do
    if curl -fsS -X POST "$BASE_URL/api/generate" \
      -H "Content-Type: application/json" \
      -d "$warmup_payload" >/dev/null; then
      warmup_ok=1
      break
    fi
    sleep 1
  done
  if [[ "$warmup_ok" -eq 0 ]]; then
    echo "      Warning: model warmup failed; continuing without warm cache."
  fi
fi

echo "Reset complete. App ready at $BASE_URL"
echo "Mode: state-cleared$( [[ "$WIPE_INDEX" -eq 1 ]] && printf ', index-wiped' )$( [[ "$WIPE_LOGS" -eq 1 ]] && printf ', logs-truncated' )"

if [[ ${#RUN_CMD[@]} -gt 0 ]]; then
  echo "Executing test command: ${RUN_CMD[*]}"
  cd "$REPO_DIR"
  exec "${RUN_CMD[@]}"
fi
