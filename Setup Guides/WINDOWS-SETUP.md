# Windows Setup Guide (Ollama Librarian)

## Goal

Set up a standalone local LLM system on Windows using this repo:

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

- Windows 10/11
- Git
- Python 3.10+
- Ollama
- PowerShell

If Python install or venv commands fail, use:

- [PYTHON-SETUP.md](PYTHON-SETUP.md)

## 1) Install Prerequisites

Open PowerShell as Administrator:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id Ollama.Ollama -e
```

Reopen PowerShell and verify:

```powershell
git --version
py --version
ollama --version
```

## 2) Clone This Repo

```powershell
New-Item -ItemType Directory -Path "$HOME\GIT" -Force | Out-Null
Set-Location "$HOME\GIT"
git clone https://github.com/reprahkcin/ollama-librarian.git
Set-Location .\ollama-librarian
git checkout main
git pull --ff-only origin main
```

## 3) Start Ollama and Download Models

In PowerShell #1:

```powershell
$env:OLLAMA_HOST="127.0.0.1:11434"
ollama serve
```

In PowerShell #2:

```powershell
ollama pull qwen2.5:14b
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Check Ollama:

```powershell
curl http://127.0.0.1:11434/api/tags
```

## 4) Create Python Environment

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r scripts\pdf-rag-requirements.txt
```

## 5) Create Local Data Paths

```powershell
New-Item -ItemType Directory -Path "$HOME\Documents\LLM Library" -Force | Out-Null
New-Item -ItemType Directory -Path "$env:APPDATA\ollama-librarian" -Force | Out-Null
```

Put your documents in:

```text
%USERPROFILE%\Documents\LLM Library
```

Supported source file types:

- .pdf
- .txt
- .md
- .html
- .htm
- .epub

## 6) Launch the Web Interface

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\.venv\Scripts\Activate.ps1

$env:OLLAMA_WEB_HOST="127.0.0.1"
$env:OLLAMA_WEB_PORT="8088"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:OLLAMA_WEB_PDF_SOURCE="$HOME\Documents\LLM Library"
$env:OLLAMA_WEB_PDF_INDEX_DB="$env:APPDATA\ollama-librarian\pdf-rag.sqlite"
$env:OLLAMA_WEB_HISTORY_PATH="$env:APPDATA\ollama-librarian\ollama-web-chat-history.json"
$env:OLLAMA_WEB_STASH_PATH="$env:APPDATA\ollama-librarian\ollama-response-stash.json"
$env:OLLAMA_WEB_PDF_OCR_ON_SYNC="1"
$env:OLLAMA_WEB_PDF_OCR_LANG="eng"
$env:OLLAMA_WEB_PDF_OCR_JOBS="4"
$env:OLLAMA_WEB_PDF_OCR_TIMEOUT="3600"

python scripts\ollama-web-chat.py
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

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\.venv\Scripts\Activate.ps1
python scripts\pdf_library_rag.py `
  --ollama-base http://127.0.0.1:11434 `
  --embed-model nomic-embed-text `
  --index-db "$env:APPDATA\ollama-librarian\pdf-rag.sqlite" `
  index --source "$HOME\Documents\LLM Library" --prune --ocr-missing --ocr-lang eng --ocr-jobs 4 --ocr-timeout 3600
```

## 8) Verify Index Health

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\.venv\Scripts\Activate.ps1
python scripts\pdf_library_rag.py --index-db "$env:APPDATA\ollama-librarian\pdf-rag.sqlite" status
python scripts\pdf_library_rag.py --index-db "$env:APPDATA\ollama-librarian\pdf-rag.sqlite" verify --list-limit 10
```

## Troubleshooting

Port 8088 already in use:

```powershell
Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue
```

Kill a blocking process:

```powershell
Stop-Process -Id <PID> -Force
```

Ollama not reachable:

```powershell
curl http://127.0.0.1:11434/api/tags
```

## Daily Use (Non-Technical)

After initial setup, users only need these commands in PowerShell:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-start-windows.ps1
.\scripts\librarian-open-ui-windows.ps1
```

When done for the day:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-stop-windows.ps1
```

Check status anytime:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-status-windows.ps1
```

Enable automatic start at login (optional):

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-install-login-windows.ps1
```

Disable automatic start at login:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-uninstall-login-windows.ps1
```
