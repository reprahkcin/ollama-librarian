# Ollama Librarian

Local-first document Q&A stack using Ollama, a Python web UI, and a local retrieval index.

## What Is Included

- Web interface: `scripts/ollama-web-chat.py`
- Indexer/CLI: `scripts/pdf_library_rag.py`
- Python deps: `scripts/pdf-rag-requirements.txt`
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
