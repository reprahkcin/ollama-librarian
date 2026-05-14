# Linux Setup Guide (Ollama Librarian)

## Goal

Set up a standalone local LLM system on Linux using this repo:

- Local Ollama runtime
- Qwen models
- Local document library
- Local web interface

Default access model:

- This standard setup is local-only on one machine (`127.0.0.1`).
- Non-loopback/LAN binding is intentionally unsupported.

## What This Runs

- Web interface: scripts/ollama-web-chat.py
- Retrieval indexer: scripts/pdf_library_rag.py

## Requirements

- Linux (Ubuntu/Debian, Fedora, or similar)
- Git
- Python 3.10+
- Ollama
- curl

If Python install or venv commands fail, use:

- [PYTHON-SETUP.md](PYTHON-SETUP.md)

## 1) Install Prerequisites

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl jq ocrmypdf tesseract-ocr poppler-utils
```

Fedora:

```bash
sudo dnf install -y git python3 python3-pip python3-virtualenv curl jq ocrmypdf tesseract
```

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
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
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian"
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
./scripts/librarian-start-linux.sh
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

1. Click Sync New PDFs

Optional CLI sync with prune:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python scripts/pdf_library_rag.py \
  --ollama-base http://127.0.0.1:11434 \
  --embed-model nomic-embed-text \
  --index-db "${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian/pdf-rag.sqlite" \
  index --source "$HOME/Documents/LLM Library" --prune --ocr-missing --ocr-lang eng --ocr-jobs 4 --ocr-timeout 3600
```

## 8) Verify Index Health

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
python scripts/pdf_library_rag.py --index-db "${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian/pdf-rag.sqlite" status
python scripts/pdf_library_rag.py --index-db "${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian/pdf-rag.sqlite" verify --list-limit 10
```

## Troubleshooting

Port 8088 already in use:

```bash
ss -ltnp | grep ':8088'
./scripts/librarian-stop-linux.sh
./scripts/librarian-start-linux.sh
```

If another app is using 8088, choose a different port when starting:

```bash
OLLAMA_WEB_PORT=8090 ./scripts/librarian-start-linux.sh
```

Ollama not reachable:

```bash
curl http://127.0.0.1:11434/api/tags
```

Check app status quickly:

```bash
./scripts/librarian-status-linux.sh
```

## Daily Use (Non-Technical)

After initial setup, users only need these commands:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-linux.sh
./scripts/librarian-open-ui-linux.sh
```

When done for the day:

```bash
./scripts/librarian-stop-linux.sh
```
