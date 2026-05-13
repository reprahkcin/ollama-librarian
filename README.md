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
- EPUB citations open in an in-app EPUB reader at section-level locations (EPUB does not have universal PDF-style page numbers).
- You can upload supported documents directly from the sidebar with `Upload Documents`, then sync/index from the same UI.

## Security Defaults

- Web UI binds to localhost by default (`127.0.0.1`).
- API routes support optional API-key auth with header `X-API-Key` (or `Authorization: Bearer <key>`).
- Request body size is capped by default (1 MB) for POST endpoints.
- The server includes baseline hardening headers (CSP, frame deny, no-sniff, no-referrer).

Standard install target:

- Single-machine local use only (`127.0.0.1`).
- Non-loopback/LAN binding is intentionally unsupported.
- Updates are always manual: the app checks for latest versions but never auto-applies updates.

## Runtime Environment Variables

Core network/auth:

- `OLLAMA_WEB_HOST` (default: `127.0.0.1`)
- `OLLAMA_WEB_PORT` (default: `8088`)
- `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434`)
- `OLLAMA_WEB_API_KEY` (default: empty)
- `OLLAMA_WEB_MAX_BODY_BYTES` (default: `1048576`)
- `OLLAMA_WEB_MAX_UPLOAD_BYTES` (default: `536870912`)

Content/index paths and OCR:

- `OLLAMA_WEB_PDF_SOURCE`
- `OLLAMA_WEB_PDF_INDEX_DB`
- `OLLAMA_WEB_HISTORY_PATH`
- `OLLAMA_WEB_STASH_PATH`
- `OLLAMA_WEB_PDF_OCR_ON_SYNC`
- `OLLAMA_WEB_PDF_OCR_LANG`
- `OLLAMA_WEB_PDF_OCR_JOBS`
- `OLLAMA_WEB_PDF_OCR_TIMEOUT`

Updater behavior:

- `OLLAMA_WEB_UPDATE_REPO_OWNER` (default: `reprahkcin`)
- `OLLAMA_WEB_UPDATE_REPO_NAME` (default: `ollama-librarian`)
- `OLLAMA_WEB_UPDATE_GITHUB_TOKEN` (default: empty)
- `OLLAMA_WEB_UPDATE_BRANCH` (default: `main`)
- `OLLAMA_WEB_UPDATE_APPLY_MODE` (default: `git`, options: `git` or `script`)
- `OLLAMA_WEB_UPDATE_EVENTS_MAX` (default: `200`)

## Update Flow Smoke Test

Run these endpoint checks from repo root while the app is running on `127.0.0.1:8088`.

1. Check current update state:

```bash
curl -sS http://127.0.0.1:8088/api/update/status | jq .
```

1. Trigger update check:

```bash
curl -sS -X POST http://127.0.0.1:8088/api/update/check | jq .
```

1. Apply in default git mode:

```bash
curl -sS -X POST http://127.0.0.1:8088/api/update/apply \
  -H 'Content-Type: application/json' \
  -d '{"target_version":"main"}' | jq .
```

1. Poll status until running is false:

```bash
while true; do
  out="$(curl -sS http://127.0.0.1:8088/api/update/status)"
  echo "$out" | jq '{state,step,running,message,last_error}'
  test "$(echo "$out" | jq -r '.running')" = "false" && break
  sleep 1
done
```

1. Optional: inspect recent update events (newest first):

```bash
curl -sS "http://127.0.0.1:8088/api/update/events?limit=20" | jq .
```

1. Apply in script mode (macOS):

```bash
./scripts/librarian-stop-macos.sh
OLLAMA_WEB_UPDATE_APPLY_MODE=script ./scripts/librarian-start-macos.sh

target="$(curl -sS -X POST http://127.0.0.1:8088/api/update/check | jq -r '.apply_target // "main"')"

curl -sS -X POST http://127.0.0.1:8088/api/update/apply \
  -H 'Content-Type: application/json' \
  -d "{\"target_version\":\"$target\"}" | jq .
```

1. Optional negative test (git mode rejects targets that differ from `OLLAMA_WEB_UPDATE_BRANCH`):

```bash
./scripts/librarian-stop-macos.sh
OLLAMA_WEB_UPDATE_APPLY_MODE=git ./scripts/librarian-start-macos.sh

curl -sS -X POST http://127.0.0.1:8088/api/update/apply \
  -H 'Content-Type: application/json' \
  -d '{"target_version":"not-main"}' | jq .
```

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

## Security Regression Tests

Run the security-focused regression suite from repo root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Coverage includes:

- Local-only host bind enforcement (non-loopback host rejection)
- Same-origin protection on state-changing API routes
- Citation rendering hardening against HTML injection

CI enforcement:

- GitHub Actions runs this same suite on pushes to `main` and on pull requests via `.github/workflows/security-regressions.yml`.

## Licenses and Third-Party Notices

- Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- Vendored KaTeX MIT license text: [scripts/assets/katex/LICENSE](scripts/assets/katex/LICENSE)

Model and runtime compliance notes:

- This repository does not ship Qwen model weights; models are pulled by users at runtime through Ollama.
- You are responsible for using only models whose licenses and usage terms fit your use case (including commercial, research, and redistribution constraints).
- Before sharing outputs or derived artifacts, verify the model-specific terms from the source model page.
