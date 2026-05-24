# Manual Test Plan (Agent-Operable)

Purpose: define a repeatable, low-noise manual test workflow that any agent can execute and hand off.

Scope:

- Platform order: macOS -> Windows -> Linux
- Product surface: startup, UI load, model loading, PDF index visibility, chat flows, upload/index flows, update/status flows, and stop/start scripts
- Excludes: performance benchmarking and deep model-quality evaluation

## 1) Execution Rules

- Only run tests in this plan unless explicitly requested otherwise.
- Record objective evidence for each failed step (command output, API response, or exact UI symptom).
- Do not make speculative code changes during testing.
- For chat/retrieval actions, allow up to 30s before treating a request as potentially hung.
- Do not click `Cancel` before 30s unless the UI is clearly unresponsive.
- If a request is canceled by the tester, mark that attempt as inconclusive (not FAIL) and recheck with a direct endpoint call (`/api/generate` or `/api/pdf/ask`) before filing a defect.
- If a test fails, first isolate whether it is:
  - environment issue
  - stale client/cache issue
  - backend/runtime defect
- Stop broad retesting loops. After a fix, rerun only:
  - the failed test
  - directly adjacent smoke checks
  - one short sanity sweep

## 2) Test Data and Preconditions

Common preconditions (all platforms):

- Repository is available locally.
- Python environment is set up and dependencies installed.
- Ollama is installed and reachable.
- At least these models are available:
  - `qwen2.5:14b`
  - `nomic-embed-text:latest`
- PDF index exists or test docs are available for indexing.

Optional sample docs for upload/index checks:

- 1 small PDF
- 1 EPUB
- 1 markdown or text file

## 3) Result Codes

Use these exact statuses per test item:

- PASS: expected behavior confirmed
- FAIL: behavior incorrect/reproducible
- BLOCKED: cannot execute due to missing prereq/environment limitation
- N/A: not applicable on current platform

## 4) macOS Test Sequence

### A. Startup and Health

1. Start services

- Command:
  - `./scripts/librarian-start-macos.sh`
- Expected:
  - script exits successfully
  - app listening on `http://127.0.0.1:8088`

2. Check service status

- Command:
  - `./scripts/librarian-status-macos.sh`
- Expected:
  - Ollama: running
  - Web UI: running

3. API smoke check

- Commands:
  - `curl -sS -i http://127.0.0.1:8088/api/tags`
  - `curl -sS -i http://127.0.0.1:8088/api/pdf/status`
- Expected:
  - HTTP 200 from both
  - `/api/tags` contains model list
  - `/api/pdf/status` contains JSON with `ok`

### B. Core UI Smoke

4. Load UI

- Action: open `http://127.0.0.1:8088/`
- Expected:
  - page renders with no blocking JS errors
  - model status transitions from checking to online

5. Model dropdown

- Action: click Refresh models
- Expected:
  - model list populated
  - `qwen2.5:14b` available/selectable

6. PDF status panel

- Expected:
  - shows non-error status text
  - if indexed data exists, shows docs/chunks and last indexed time

### C. Chat and Retrieval

7. Basic chat

- Action: send `reply with exactly ok`
- Expected:
  - assistant responds
  - no client-side errors

8. PDF-grounded ask

- Preconditions: `Use PDF-grounded answers` checked
- Action: ask a grounded question about indexed content
- Expected:
  - response returned
  - no route/auth/CSP errors

9. Deep Study toggle sanity

- Action: toggle Deep Study and ask again
- Expected:
  - request succeeds both states

### D. Upload and Index Interaction

10. Upload docs

- Action: click `Upload Documents` and select supported files
- Expected:
  - upload flow completes without JS error
  - status/metadata updates visibly

11. Trigger sync

- Action: click `Sync New PDFs`
- Expected:
  - index job starts or reports already synced
  - status panel updates without error

### E. Stash / Bibliography / History

12. Stash controls

- Actions:
  - stash an assistant response
  - open `View Stash`
  - reload and delete one item
- Expected:
  - CRUD operations succeed

13. Bibliography view

- Action: open `View Bibliography`
- Expected:
  - list opens and handles empty/non-empty states correctly

14. Clear conversation

- Action: click `Clear Conversation`
- Expected:
  - conversation resets
  - app remains responsive

### F. Update Surface (manual-only behavior)

15. Update status/check

- Actions:
  - click `Check for Updates`
- Expected:
  - status field updates
  - release notes link behavior is correct

16. Confirm manual mode behavior

- Expected:
  - no automatic update application occurs

### G. Stop/Restart Resilience

17. Stop app

- Command:
  - `./scripts/librarian-stop-macos.sh`
- Expected:
  - process stops cleanly

18. Restart app and quick recheck

- Commands:
  - `./scripts/librarian-start-macos.sh`
  - `./scripts/librarian-status-macos.sh`
- Expected:
  - startup successful
  - model load and PDF status still work after restart

## 5) Windows Test Sequence

Run the same functional flow as macOS, substituting script commands:

- Start: `./scripts/librarian-start-windows.ps1`
- Stop: `./scripts/librarian-stop-windows.ps1`
- Status: `./scripts/librarian-status-windows.ps1`
- Open UI: `./scripts/librarian-open-ui-windows.ps1`

Windows-specific checks:

- Path handling in status/update output is valid on Windows.
- PowerShell scripts handle reruns cleanly (no orphan processes).

## 6) Linux Test Sequence

Run the same functional flow as macOS, substituting script commands:

- Start: `./scripts/librarian-start-linux.sh`
- Stop: `./scripts/librarian-stop-linux.sh`
- Status: `./scripts/librarian-status-linux.sh`
- Open UI: `./scripts/librarian-open-ui-linux.sh`

Linux-specific checks:

- XDG/home path defaults behave as expected.
- Script permissions and shebang execution are clean.

## 7) Failure Isolation Playbook

If models/PDF status fail in UI:

1. Check backend endpoints directly:

- `curl -sS -i http://127.0.0.1:8088/api/tags`
- `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

2. Check upstream Ollama:

- `curl -sS -i http://127.0.0.1:11434/api/tags`

3. If backend is healthy but UI is broken:

- reload page and check browser console/runtime errors
- suspect stale asset cache or frontend exception

4. If backend endpoints fail:

- capture exact status code and response body
- check service status scripts

## 8) Evidence Template (per platform)

Record this block after each platform run:

```text
Platform:
Date/Time:
Agent:
Branch/Commit:

Startup/Status:
API smoke:
UI smoke:
Chat:
PDF-grounded:
Upload/Sync:
Stash/Bibliography:
Update surface:
Restart resilience:

Failures:
- ID:
- Repro steps:
- Expected:
- Actual:
- Evidence:
- Severity:

Final verdict: PASS | FAIL | BLOCKED
```

## 9) Agent Handoff Template

Use this exact handoff payload between agents:

```text
Current platform: <macOS|Windows|Linux>
Completed test IDs:
Remaining test IDs:
Open failures:
Environment caveats:
Last known good commit:
Next immediate action:
```

## 10) Exit Criteria

Testing cycle is complete when:

- macOS, Windows, Linux each have a full evidence block
- no untriaged FAIL items remain
- any accepted residual issues are explicitly documented with severity and follow-up owner

## 11) Exact Reproduction Flow (Match Prior Agent Run)

Use this section when handing off to a new agent on a different machine and you want a near-identical execution path.

### A. Fixed Inputs

- App URL: `http://127.0.0.1:8088`
- Ollama URL: `http://127.0.0.1:11434`
- Preferred model in UI: `qwen2.5:14b`
- Quick chat prompt: `Reply with exactly OK.`
- Temporary upload file path:
  - macOS/Linux: `/tmp/ollama-librarian-smoke-upload.txt`
  - Windows: `$env:TEMP\\ollama-librarian-smoke-upload.txt`

### B. Exact macOS Command Sequence

Run in repo root:

1. `./scripts/librarian-start-macos.sh`
2. `./scripts/librarian-status-macos.sh`
3. `curl -sS -i http://127.0.0.1:8088/api/tags`
4. `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

Expected minimum signals:

- status script includes `Ollama: running` and `Web UI: running`
- both API calls return `HTTP/1.0 200 OK` or `HTTP/1.1 200 OK`
- `/api/tags` JSON contains `models`
- `/api/pdf/status` JSON contains `ok`

### C. Exact UI Action Sequence

1. Open `http://127.0.0.1:8088/`.
2. Verify sidebar shows online model state (for example `Online (N models)`).
3. Click `Refresh` next to model selector.
4. Ensure `Use PDF-grounded answers` is unchecked.
5. Send prompt `Reply with exactly OK.`.
6. If confirmation appears (`Send this query without PDF grounding?`), click confirm/OK.
7. Verify assistant returns `OK`.
8. Click `Upload Documents`.
9. Upload one disposable text file from the temp path.
10. Verify footer/status indicates upload success (for example `Uploaded 1 file; indexing started`).
11. Click `Sync New PDFs`.
12. Verify PDF status line transitions to running (contains `PDF index: running`).
13. Click `View Stash`, verify modal opens, then close it.
14. Click `View Bibliography`, verify modal opens (empty state acceptable), then close it.
15. Click `Check for Updates`.
16. Verify update area reports up-to-date state and release notes link appears.
17. Click `Clear Conversation` and verify chat resets (`Shared history cleared`).

### D. Exact Restart Verification

1. `./scripts/librarian-stop-macos.sh`
2. `./scripts/librarian-start-macos.sh`
3. `./scripts/librarian-status-macos.sh`
4. `curl -sS -i http://127.0.0.1:8088/api/tags`
5. `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

Expected minimum signals:

- stop/start scripts succeed without manual cleanup
- status script reports both services running
- both API calls still return 200

### E. Disposable Upload File Commands

macOS/Linux:

1. `cat > /tmp/ollama-librarian-smoke-upload.txt <<'EOF'`
2. `Ollama Librarian smoke upload file.`
3. `This is a disposable test document for manual QA.`
4. `EOF`
5. cleanup: `rm -f /tmp/ollama-librarian-smoke-upload.txt`

Windows PowerShell:

1. `@"`
2. `Ollama Librarian smoke upload file.`
3. `This is a disposable test document for manual QA.`
4. `"@ | Set-Content -Path "$env:TEMP\\ollama-librarian-smoke-upload.txt"`
5. cleanup: `Remove-Item "$env:TEMP\\ollama-librarian-smoke-upload.txt" -ErrorAction SilentlyContinue`

### F. Cross-Machine Handoff Payload (Required)

When handing to the next agent, include this exact payload:

```text
Platform: <macOS|Windows|Linux>
App URL used: http://127.0.0.1:8088
Ollama URL used: http://127.0.0.1:11434
Commands executed (in order):
1) ...
2) ...
3) ...
UI actions executed (in order):
1) ...
2) ...
3) ...
Observed confirmations:
- Startup/status:
- API 200 checks:
- Chat response text:
- Upload/sync status text:
- Update status text:
- Clear conversation text:
Deviations from expected flow:
-
Blocking issues:
-
Next immediate action for receiving agent:
-
```

### G. Known Non-Blocking Variability

- Model selector keyboard navigation may be inconsistent in some automation harnesses; mouse selection is acceptable.
- Index progress metrics can jump or look non-linear depending on existing library/index state.
- Ungrounded confirm dialog can appear for send actions when PDF grounding is off; accepting it is part of the expected flow.
- Chat responses can take a few seconds while model/runtime state warms up; avoid early cancellation.
- Browser `net::ERR_ABORTED` observed immediately after pressing `Cancel` indicates client-side abort, not a confirmed backend failure.
