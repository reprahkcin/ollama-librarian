# Ollama Librarian

Local-first document Q&A stack using Ollama, a Python web UI, and a local retrieval index.

## What Is Included

- Web interface: `scripts/ollama-web-chat.py`
- Indexer/CLI: `scripts/pdf_library_rag.py`
- Python deps: `scripts/pdf-rag-requirements.txt`
- Vendored frontend math assets (offline): `scripts/assets/katex/*`
- Setup guides:
  - `Setup Guides/MAC-SETUP.md`
  - `Setup Guides/WINDOWS-SETUP.md`
  - `Setup Guides/PYTHON-SETUP.md`
  - `Setup Guides/RESEARCHER-QUICKSTART.md`
- Optional bootstrap scripts:
  - `scripts/bootstrap-macos.sh`
  - `scripts/bootstrap-windows.ps1`

## Quick Start

Pick your platform guide and follow it end-to-end:

- macOS: [Setup Guides/MAC-SETUP.md](Setup%20Guides/MAC-SETUP.md)
- Windows: [Setup Guides/WINDOWS-SETUP.md](Setup%20Guides/WINDOWS-SETUP.md)
- Python setup/troubleshooting: [Setup Guides/PYTHON-SETUP.md](Setup%20Guides/PYTHON-SETUP.md)

For non-technical users, use:

- [Setup Guides/RESEARCHER-QUICKSTART.md](Setup%20Guides/RESEARCHER-QUICKSTART.md)

## Supported Document Types

- `.pdf`
- `.txt`
- `.md`
- `.html`
- `.htm`
- `.epub`

## Notes

- OCR fallback applies to PDFs.
- The web UI requires Python 3.10+.
- Math rendering is fully offline via vendored KaTeX files served from `/assets`.

## Security Defaults

- Web UI binds to localhost by default (`127.0.0.1`).
- API routes support optional API-key auth with header `X-API-Key` (or `Authorization: Bearer <key>`).
- Request body size is capped by default (1 MB) for POST endpoints.
- The server includes baseline hardening headers (CSP, frame deny, no-sniff, no-referrer).

## Runtime Environment Variables

Core network/auth:

- `OLLAMA_WEB_HOST` (default: `127.0.0.1`)
- `OLLAMA_WEB_PORT` (default: `8088`)
- `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `OLLAMA_WEB_API_KEY` (default: empty)
- `OLLAMA_WEB_ALLOW_INSECURE_BIND` (default: off)
- `OLLAMA_WEB_MAX_BODY_BYTES` (default: `1048576`)

Content/index paths and OCR:

- `OLLAMA_WEB_PDF_SOURCE`
- `OLLAMA_WEB_PDF_INDEX_DB`
- `OLLAMA_WEB_HISTORY_PATH`
- `OLLAMA_WEB_STASH_PATH`
- `OLLAMA_WEB_PDF_OCR_ON_SYNC`
- `OLLAMA_WEB_PDF_OCR_LANG`
- `OLLAMA_WEB_PDF_OCR_JOBS`
- `OLLAMA_WEB_PDF_OCR_TIMEOUT`

## On/Off Controls

macOS:

- Start: `scripts/librarian-start-macos.sh`
- Stop: `scripts/librarian-stop-macos.sh`
- Status: `scripts/librarian-status-macos.sh`
- Open UI: `scripts/librarian-open-ui-macos.sh`
- Auto-start at login (optional): `scripts/librarian-install-login-macos.sh`

Windows (PowerShell):

- Start: `scripts/librarian-start-windows.ps1`
- Stop: `scripts/librarian-stop-windows.ps1`
- Status: `scripts/librarian-status-windows.ps1`
- Open UI: `scripts/librarian-open-ui-windows.ps1`
- Auto-start at login (optional): `scripts/librarian-install-login-windows.ps1`
