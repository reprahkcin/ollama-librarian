# Researcher Quick Start (Minimal Daily Workflow)

This guide is for non-technical users after initial setup is complete.

Default access model:

- The normal workflow is local-only on the same machine (`http://127.0.0.1:8088`).
- Network/LAN access is intentionally unsupported.

## What You Do Each Day

1. Start the system
2. Open the web page
3. Ask questions
4. Sync new documents when needed
5. Stop the system when done

## macOS Daily Use

Start and open:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-macos.sh
./scripts/librarian-open-ui-macos.sh
```

Stop:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-macos.sh
```

Status check:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-status-macos.sh
```

## Windows Daily Use (PowerShell)

Start and open:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-start-windows.ps1
.\scripts\librarian-open-ui-windows.ps1
```

Stop:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-stop-windows.ps1
```

Status check:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-status-windows.ps1
```

## Linux Daily Use

Start Ollama in Terminal #1:

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

Start the web app in Terminal #2:

```bash
cd ~/GIT/ollama-librarian
source .venv/bin/activate
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/ollama-librarian"

OLLAMA_WEB_HOST=127.0.0.1 \
OLLAMA_WEB_PORT=8088 \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_WEB_PDF_SOURCE="$HOME/Documents/LLM Library" \
OLLAMA_WEB_PDF_INDEX_DB="$DATA_HOME/pdf-rag.sqlite" \
OLLAMA_WEB_HISTORY_PATH="$DATA_HOME/ollama-web-chat-history.json" \
OLLAMA_WEB_STASH_PATH="$DATA_HOME/ollama-response-stash.json" \
./scripts/ollama-web-chat.py
```

Open in browser:

```text
http://127.0.0.1:8088
```

Stop:

- Press Ctrl+C in both terminals.

Status check:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Syncing New Documents

1. Copy files into your library folder.
2. Open the web page.
3. Enable Use PDF-grounded answers.
4. Click Sync New PDFs.

Optional in-UI upload flow:

1. Open the web page.
2. Click Upload Documents.
3. Select one or more supported files.
4. The app uploads files into your configured library path; then click Sync New PDFs (or wait if auto-sync is started).

Supported file types:

- .pdf
- .txt
- .md
- .html
- .htm
- .epub

## Optional: Start Automatically at Login

macOS:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-install-login-macos.sh
```

Windows:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-install-login-windows.ps1
```

Linux:

- Create startup entries in your desktop environment for the two daily-use Linux start commands above.

## Resource Behavior (Simple)

- When stopped, it uses no resources.
- When running idle, CPU should be low.
- Memory usage can stay elevated for a while after model use.
