# Ollama Librarian

Local-first document Q&A stack using Ollama, a Python web UI, and a local retrieval index.

## What Is Included

- Web interface: `scripts/ollama-web-chat.py`
- Indexer/CLI: `scripts/pdf_library_rag.py`
- Python deps: `scripts/pdf-rag-requirements.txt`
- Vendored frontend math assets (offline): `scripts/assets/katex/*`
- Setup guides:
  - `Setup Guides/MAC-SETUP.md`
  - `Setup Guides/LINUX-SETUP.md`
  - `Setup Guides/WINDOWS-SETUP.md`
  - `Setup Guides/PYTHON-SETUP.md`
  - `Setup Guides/RESEARCHER-QUICKSTART.md`
- Optional bootstrap scripts:
  - `scripts/bootstrap-macos.sh`
  - `scripts/bootstrap-windows.ps1`
  - Linux setup is documented in `Setup Guides/LINUX-SETUP.md` (no bootstrap script in this repo yet).

## Quick Start

Pick your platform guide and follow it end-to-end:

- macOS: [Setup Guides/MAC-SETUP.md](Setup Guides/MAC-SETUP.md)
- Linux: [Setup Guides/LINUX-SETUP.md](Setup Guides/LINUX-SETUP.md)
- Windows: [Setup Guides/WINDOWS-SETUP.md](Setup Guides/WINDOWS-SETUP.md)
- Python setup/troubleshooting: [Setup Guides/PYTHON-SETUP.md](Setup Guides/PYTHON-SETUP.md)

For non-technical users, use:

- [Setup Guides/RESEARCHER-QUICKSTART.md](Setup Guides/RESEARCHER-QUICKSTART.md)

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
- PDF indexing controls, document upload, Library Docs, and the processing dashboard are grouped under a `PDF Processing` sidebar section.
- You can set or change the library directory directly in the `PDF Processing` section; the app creates the folder if needed and remembers it for future runs.
- Use `Browse...` to open a folder picker dialog and set the library directory without typing full paths.
- On Linux, the folder picker requires one of: `zenity`, `kdialog`, or `yad`. If none are installed, use the path field and click `Set Directory`.
- `App Updates` is in a collapsed-by-default sidebar section for less frequent use.
- The sidebar includes an `Abstract Screener` that scores an abstract against your research need and recommends whether to download/index the paper.

## Release Status

- Current validated release: `v1.0.5`
- Cross-platform manual validation completed on macOS, Windows, and Linux.
- Source PDF/EPUB citation links were fixed to open correctly again.
- PDF source links now resolve cleanly in Chrome/Firefox without CSP frame errors.
- Added route-level regression coverage for PDF inline serving and source-link route resolution.

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
- `OLLAMA_WEB_GENERATE_TIMEOUT` (default: `90`; per-request timeout for `/api/generate` upstream calls)
- `OLLAMA_WEB_MODEL_FAILURE_THRESHOLD` (default: `2`; failures before temporarily pausing a model)
- `OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS` (default: `180`; cooldown after repeated model failures)
- `OLLAMA_WEB_MONITOR_ENABLED` (default: `1`; enables in-process request/resource monitoring)
- `OLLAMA_WEB_MONITOR_MAX_EVENTS` (default: `1000`; number of recent request events to keep in memory)
- `OLLAMA_WEB_MONITOR_SLOW_MS` (default: `2500`; request latency threshold marked as slow)
- `OLLAMA_WEB_MONITOR_LOG_JSONL` (default: `1`; append monitor events to JSONL log)
- `OLLAMA_WEB_MONITOR_LOG_PATH` (default: state-dir `perf-events.jsonl`; monitor event log file)
- `OLLAMA_WEB_PDF_ANSWER_TIMEOUT` (default: `360`; seconds per model attempt for grounded answers)
Safe-mode startup defaults (non-technical friendly):

- Start scripts use conservative defaults unless you override them:
  - `OLLAMA_WEB_GENERATE_TIMEOUT=60`
  - `OLLAMA_WEB_MODEL_FAILURE_THRESHOLD=1`
  - `OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS=300`
- This means a model is paused quickly after an upstream failure, reducing repeated crash loops.
- If a favorite model gets paused too aggressively, raise `OLLAMA_WEB_MODEL_FAILURE_THRESHOLD` to `2`.

Quick override examples:

- Linux:

```bash
OLLAMA_WEB_MODEL_FAILURE_THRESHOLD=2 ./scripts/librarian-start-linux.sh
```

- macOS:

```bash
OLLAMA_WEB_MODEL_FAILURE_THRESHOLD=2 ./scripts/librarian-start-macos.sh
```

- Windows (PowerShell):

```powershell
$env:OLLAMA_WEB_MODEL_FAILURE_THRESHOLD='2'; .\scripts\librarian-start-windows.ps1
```

One-command test reset (Linux):

```bash
./scripts/librarian-reset-linux.sh
```

Run a test immediately after reset (single command flow):

```bash
./scripts/librarian-reset-linux.sh -- python scripts/run_quality_benchmark.py --limit 1
```

Preload a model during reset to reduce first-query cold-start latency:

```bash
./scripts/librarian-reset-linux.sh --warmup-model qwen2.5:14b
```

Optional hard reset mode (also wipes the PDF index database before restart):

```bash
./scripts/librarian-reset-linux.sh --wipe-index
```

A/B performance benchmark runner (Linux workflow):

```bash
python scripts/run_quality_ab_benchmark.py --warmup --limit 4
```

This runs the benchmark across a fixed profile matrix (`top_k`, `num_predict`, `answer_timeout`) with a full reset between profiles and writes a ranked summary under `tests/quality/results/ab-<timestamp>/`.

To prevent a stuck profile from blocking the full matrix, set a hard profile timeout:

```bash
python scripts/run_quality_ab_benchmark.py --warmup --limit 4 --profile-timeout-seconds 900
```

Content/index paths and OCR:

- `OLLAMA_WEB_PDF_SOURCE`
- `OLLAMA_WEB_PDF_INDEX_DB`
- `OLLAMA_WEB_HISTORY_PATH`
- `OLLAMA_WEB_STASH_PATH`
- `OLLAMA_WEB_PDF_OCR_ON_SYNC`
- `OLLAMA_WEB_PDF_OCR_LANG`
- `OLLAMA_WEB_PDF_OCR_JOBS`
- `OLLAMA_WEB_PDF_OCR_TIMEOUT`
- `OLLAMA_WEB_PDF_EMBED_NUM_THREAD` (default: `2`; lower values reduce CPU/heat during indexing)
- `OLLAMA_WEB_PDF_EMBED_DELAY_MS` (default: `200`; inserts a delay between embedding calls to lower sustained heat)
- `OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS` (default: `10`; sleeps between indexed documents to cool the system)
- `OLLAMA_WEB_PDF_DYNAMIC_THROTTLE` (default: `1`; adaptive throttle that auto-adjusts embed thread count and delay)
- `OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS` (default: `1400`; target average embed latency used by adaptive control)
- `OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS` (default: `2000`; upper bound for adaptive inter-embed delay)
- `OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS` (default: `50`; adaptive delay adjustment increment)
- `OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS` (default: `1`; lower bound for adaptive embed threads)
- `OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS` (default: `3`; upper bound for adaptive embed threads)
- `OLLAMA_WEB_PDF_ANSWER_FALLBACK_MODELS` (default: `qwen2.5:7b,qwen2.5:3b,llama3.2:3b`; comma-separated fallbacks used when heavy answer models fail)

Updater behavior:

- `OLLAMA_WEB_UPDATE_REPO_OWNER` (default: `reprahkcin`)
- `OLLAMA_WEB_UPDATE_REPO_NAME` (default: `ollama-librarian`)
- `OLLAMA_WEB_UPDATE_GITHUB_TOKEN` (default: empty)
- `OLLAMA_WEB_UPDATE_BRANCH` (default: `main`)
- `OLLAMA_WEB_UPDATE_APPLY_MODE` (default: `git`, options: `git` or `script`)
- `OLLAMA_WEB_UPDATE_EVENTS_MAX` (default: `200`)

Performance monitoring endpoints:

- `GET /api/metrics?limit=200`: request counters, hot routes, recent request timings, and latest CPU/RAM/disk snapshot.
- `POST /api/metrics/reset`: clears in-memory monitor counters/events.
- `GET /api/cooldown/status`: current cooldown state (`active`, remaining seconds).
- `POST /api/cooldown`: set or clear cooldown. Examples:
  - Set: `{"minutes":5,"reason":"manual dashboard cooldown"}`
  - Clear: `{"action":"clear"}`
- JSONL event log (`perf-events.jsonl`) is appended automatically when `OLLAMA_WEB_MONITOR_LOG_JSONL=1`.

When cooldown is active, heavy operations are paused/blocked:

- `/api/generate`
- `/api/pdf/ask`
- `/api/pdf/index`
- `/api/abstract/evaluate`

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

Linux:

- Start: `scripts/librarian-start-linux.sh`
- Stop: `scripts/librarian-stop-linux.sh`
- Status: `scripts/librarian-status-linux.sh`
- Open UI: `scripts/librarian-open-ui-linux.sh`

## Super Simple Daily Commands

If setup is already complete, follow these exact steps.

If you do not know what a terminal is:

- macOS: press Command + Space, type Terminal, press Enter.
- Windows: press Windows key, type PowerShell, press Enter.
- Linux: press Ctrl + Alt + T.

macOS:

1. Open Terminal.
2. Copy and paste this to start:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-macos.sh
./scripts/librarian-open-ui-macos.sh
```

1. Copy and paste this to stop when done:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-macos.sh
```

Windows (PowerShell):

1. Open PowerShell.
2. Copy and paste this to start:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-start-windows.ps1
.\scripts\librarian-open-ui-windows.ps1
```

1. Copy and paste this to stop when done:

```powershell
Set-Location "$HOME\GIT\ollama-librarian"
.\scripts\librarian-stop-windows.ps1
```

Linux:

1. Open Terminal.
2. Copy and paste this to start:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-start-linux.sh
./scripts/librarian-open-ui-linux.sh
```

1. Copy and paste this to stop when done:

```bash
cd ~/GIT/ollama-librarian
./scripts/librarian-stop-linux.sh
```

What common messages mean:

- `Librarian is running at http://127.0.0.1:8088`: start worked.
- `Web app already running.`: it was already on; this is okay.
- `Ollama already running.`: the AI engine was already on; this is okay.
- `Missing Python venv ...`: setup is incomplete.
- `Could not find 'ollama' in PATH`: Ollama is not installed correctly.
- `Web UI: stopped` in status output: run the Start block again.

For a non-technical guide, see:

- [Setup Guides/RESEARCHER-QUICKSTART.md](Setup Guides/RESEARCHER-QUICKSTART.md)

## Manual QA Handoff (Agent to Agent)

For reproducible cross-machine manual testing, use:

- [docs/MANUAL-TEST-PLAN.md](docs/MANUAL-TEST-PLAN.md)

Start with the exact replay instructions in:

- [docs/MANUAL-TEST-PLAN.md#11-exact-reproduction-flow-match-prior-agent-run](docs/MANUAL-TEST-PLAN.md#11-exact-reproduction-flow-match-prior-agent-run)

When handing off to another agent, include the required payload format from Section 11.F to preserve command order, UI action order, and observed confirmations.

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
