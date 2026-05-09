#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-$HOME/GIT/ollama-librarian}"
default_lib_dir() {
  local candidates=(
    "$HOME/pdf_library"
    "$HOME/Documents/LLM Library"
    "/Volumes/shared/LLM Library"
    "/Volumes/shared/Doomsday School"
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

LIB_DIR="${2:-$(default_lib_dir)}"
STATE_DIR="${3:-$HOME/Library/Application Support/ollama-librarian}"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install from https://brew.sh and rerun."
  exit 1
fi

brew update
brew install git python ollama ocrmypdf tesseract

mkdir -p "$LIB_DIR" "$STATE_DIR"
cd "$REPO_DIR"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/pdf-rag-requirements.txt

echo "Bootstrap complete."
echo "Library path: $LIB_DIR"
echo "State path: $STATE_DIR"
echo "Next: start Ollama (OLLAMA_HOST=127.0.0.1:11434 ollama serve) and run scripts/ollama-web-chat.py"
