# Mac Setup Guide (Ollama Librarian)

## Goal

Set up a standalone local LLM system on macOS using this repo:

- Local Ollama runtime
- Qwen models
- Local document library
- Local web interface

Default access model:

- This standard setup is local-only on one machine (`127.0.0.1`).
- LAN access is an advanced exception and is intentionally not enabled by default.

## What This Runs

- Web interface: scripts/ollama-web-chat.py
- Retrieval indexer: scripts/pdf_library_rag.py

## Requirements

- macOS
- Git
- Python 3.10+
- Ollama

If Python install or venv commands fail, use:

- [PYTHON-SETUP.md](PYTHON-SETUP.md)

## 1) Install Prerequisites

Install Homebrew (if needed):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Install dependencies:

```bash
brew update
brew install git python ollama ocrmypdf tesseract
```

Verify installs:

```bash
git --version
python3 --version
ollama --version
```

## 2) Clone This Repo

```bash
mkdir -p ~/GIT
cd ~/GIT
git clone https://github.com/reprahkcin/ollama-librarian.git
cd ollama-librarian
git checkout main
git pull --ff-only origin main
```

## 3) Start Ollama and Download Models

In Terminal #1:

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

In Terminal #2:

```bash
ollama pull qwen2.5:14b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Check Ollama:

```bash
curl http://127.0.0.1:11434/api/tags
```

## 4) Create Python Environment

```bash
cd ~/GIT/ollama-librarian
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r scripts/pdf-rag-requirements.txt
```

## 5) Create Local Data Paths

```bash
mkdir -p "$HOME/Documents/LLM Library"
mkdir -p "$HOME/Library/Application Support/ollama-librarian"
```

Put your documents in:

```text
$HOME/Documents/LLM Library
```

Supported source file types:

- .pdf
- .txt
- .md
- .html
- .htm
- .epub

## 6) Launch the Web Interface

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate

OLLAMA_WEB_HOST=127.0.0.1 \
OLLAMA_WEB_PORT=8088 \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_WEB_PDF_SOURCE="$HOME/Documents/LLM Library" \
OLLAMA_WEB_PDF_INDEX_DB="$HOME/Library/Application Support/ollama-librarian/pdf-rag.sqlite" \
OLLAMA_WEB_HISTORY_PATH="$HOME/Library/Application Support/ollama-librarian/ollama-web-chat-history.json" \
OLLAMA_WEB_STASH_PATH="$HOME/Library/Application Support/ollama-librarian/ollama-response-stash.json" \
OLLAMA_WEB_PDF_OCR_ON_SYNC=1 \
OLLAMA_WEB_PDF_OCR_LANG=eng \
OLLAMA_WEB_PDF_OCR_JOBS=4 \
OLLAMA_WEB_PDF_OCR_TIMEOUT=3600 \
./scripts/ollama-web-chat.py
```

Open:

```text
http://127.0.0.1:8088
```

## 7) Build/Refresh the Index

From the UI:

1. Enable Use PDF-grounded answers
2. Add documents by either:
  - Copying files into your library folder, or
  - Clicking Upload Documents in the sidebar
3. Click Sync New PDFs

Optional CLI sync with prune:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python scripts/pdf_library_rag.py \
  --ollama-base http://127.0.0.1:11434 \
  --embed-model nomic-embed-text \
  --index-db "$HOME/Library/Application Support/ollama-librarian/pdf-rag.sqlite" \
  index --source "$HOME/Documents/LLM Library" --prune --ocr-missing --ocr-lang eng --ocr-jobs 4 --ocr-timeout 3600
```

## 8) Verify Index Health

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python scripts/pdf_library_rag.py --index-db "$HOME/Library/Application Support/ollama-librarian/pdf-rag.sqlite" status
python scripts/pdf_library_rag.py --index-db "$HOME/Library/Application Support/ollama-librarian/pdf-rag.sqlite" verify --list-limit 10
```

## Troubleshooting

Port 8088 already in use:

```bash
lsof -nP -iTCP:8088 -sTCP:LISTEN
kill <PID>
```

Ollama not reachable:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Daily Use (Non-Technical)

After initial setup, users only need these commands:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-macos.sh
./scripts/librarian-open-ui-macos.sh
```

When done for the day:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-macos.sh
```

Check status anytime:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-status-macos.sh
```

Enable automatic start at login (optional):

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-install-login-macos.sh
```

Disable automatic start at login:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-uninstall-login-macos.sh
```
