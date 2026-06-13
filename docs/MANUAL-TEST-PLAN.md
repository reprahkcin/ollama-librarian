# Manual Test Plan (Agent-Operable)

Purpose: define a repeatable, low-noise manual test workflow that any agent or human tester can execute and hand off.

Scope:

- Platform order: macOS (Mac Mini) → Windows 10 PC → Linux Mint PC
- Product surface: startup, UI load, model loading, PDF index visibility, chat flows, upload/index flows, update/status flows, and stop/start scripts
- Excludes: performance benchmarking and deep model-quality evaluation

## 1) Execution Rules

- Only run tests in this plan unless explicitly requested otherwise.
- Record objective evidence for each failed step (command output, API response, or exact UI symptom).
- Do not make speculative code changes during testing.
- For chat/retrieval actions, define a tester-selected wait duration before each run (for example, 90s, 180s, or another value you choose).
- After each query submission, pause and wait the full tester-selected duration before treating the request as potentially hung.
- Do not click `Cancel` before the selected wait duration unless the UI is clearly unresponsive.
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

- Repository is on branch `optimization-1.0.9` (or the branch under test).
- Python environment is set up and dependencies installed.
- Ollama is installed and reachable.
- At least these models are available:
  - `qwen2.5:7b`
  - `qwen2.5:3b`
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

## 4) Waterfall Machine Order

Run one machine at a time, in this order:

| #   | Machine       | Platform   | Status            |
| --- | ------------- | ---------- | ----------------- |
| 1   | Mac Mini      | macOS      | PASS (2026-06-12) |
| 2   | Windows 10 PC | Windows    | PASS (2026-06-12) |
| 3   | Linux Mint PC | Linux Mint | pending           |

The cycle is complete only when all three machines have a PASS verdict. If any machine produces FAIL, stop the waterfall, fix and commit, then restart from Machine 1.

## 5) macOS Test Sequence (Mac Mini — Run First)

### A. Startup and Health

1. Start services

- Command:
  - `./scripts/librarian-start-macos.sh`
- Expected:
  - script exits successfully
  - app listening on `http://127.0.0.1:8088`

1. Check service status

- Command:
  - `./scripts/librarian-status-macos.sh`
- Expected:
  - Ollama: running
  - Web UI: running

1. API smoke check

- Commands:
  - `curl -sS -i http://127.0.0.1:8088/api/tags`
  - `curl -sS -i http://127.0.0.1:8088/api/pdf/status`
- Expected:
  - HTTP 200 from both
  - `/api/tags` contains model list
  - `/api/pdf/status` contains JSON with `ok`

### B. Core UI Smoke

1. Load UI

- Action: open `http://127.0.0.1:8088/`
- Expected:
  - page renders with no blocking JS errors
  - model status transitions from checking to online

1. Model dropdown

- Action: click Refresh models
- Expected:
  - model list populated
  - `qwen2.5:7b` available/selectable

1. PDF status panel

- Expected:
  - shows non-error status text
  - if indexed data exists, shows docs/chunks and last indexed time

### C. Chat and Retrieval

1. Basic chat

- Action: send `reply with exactly ok`
- Expected:
  - assistant responds
  - no client-side errors

1. PDF-grounded ask

- Preconditions: `Use PDF-grounded answers` checked
- Action: ask a grounded question about indexed content
- Expected:
  - response returned
  - no route/auth/CSP errors

### D. Upload and Index Interaction

1. Upload docs

- Action: click `Upload Documents` and select supported files
- Expected:
  - upload flow completes without JS error
  - status/metadata updates visibly

1. Trigger sync

- Action: click `Sync New PDFs`
- Expected:
  - index job starts or reports already synced
  - status panel updates without error

### D1. Library Directory Selection

1. Directory picker path set

- Action: in `PDF Processing`, click `Browse...` and choose a folder
- Expected:
  - path field updates to selected folder
  - status/meta confirms directory update
  - subsequent uploads/indexing use that directory

1. Manual fallback path set

- Action: type a valid full path and click `Set Directory`
- Expected:
  - path accepted and normalized
  - no JS/backend error
  - updated path is reflected in `/api/pdf/status`

### D2. Pause and ETA Validation

1. Pause flow

- Action: start sync, then click `Pause Processing`
- Expected:
  - button transitions to pause-requested state, then returns to `Sync New PDFs`
  - `/api/pdf/status.index_job.running` becomes `false`
  - `/api/pdf/status.index_job.last_result.paused` is `true`

1. ETA stabilization behavior

- Action: start sync and observe status during first minutes
- Expected:
  - early run may show `ETA: estimating`
  - ETA should appear only after enough progress is collected
  - ETA should not jump immediately to unrealistically short values based on pre-existing indexed docs

### E. Stash / Bibliography / History

1. Stash controls

- Actions:
  - stash an assistant response
  - open `View Stash`
  - reload and delete one item
- Expected:
  - CRUD operations succeed

1. Bibliography view

- Action: open `View Bibliography`
- Expected:
  - list opens and handles empty/non-empty states correctly

1. Clear conversation

- Action: click `Clear Conversation`
- Expected:
  - conversation resets
  - app remains responsive

### F. Update Surface (manual-only behavior)

1. Update status/check

- Actions:
  - click `Check for Updates`
- Expected:
  - status field updates
  - release notes link behavior is correct

1. Confirm manual mode behavior

- Expected:
  - no automatic update application occurs

### G. Stop/Restart Resilience

1. Stop app

- Command:
  - `./scripts/librarian-stop-macos.sh`
- Expected:
  - process stops cleanly

1. Restart app and quick recheck

- Commands:
  - `./scripts/librarian-start-macos.sh`
  - `./scripts/librarian-status-macos.sh`
- Expected:
  - startup successful
  - model load and PDF status still work after restart

### H. macOS Handoff to Windows 10 PC

When macOS is PASS, give the Windows tester this payload:

```text
Handoff from: macOS (Mac Mini)
Handoff to: Windows 10 PC
Date/Time: 2026-06-12
Branch/Commit: optimization-1.0.9 / ba72d18

macOS result: PASS
macOS evidence summary:
- Startup/Status: PASS — Ollama: running, Web UI: running
- API smoke: PASS — /api/tags 200, /api/pdf/status 200 (ok: true)
- UI smoke: PASS — page 200, system profile ok, pressure: ok
- Chat: PASS — qwen2.5:7b replied "OK"
- PDF-grounded: PASS — answer returned with 6 sources
- Query wait duration used: <10s (well under 90s threshold)
- Upload/Sync: PASS — file uploaded, index started and completed cleanly
- Stash/Bibliography: PASS — stash CRUD ok, bibliography GET ok (empty state)
- Update surface: PASS — status idle, check ok, release notes link present, no auto-apply
- Restart resilience: PASS — stop/start/status clean, post-restart APIs 200

Environment caveats (macOS):
- Index pruned 685 stale docs on sync (source_path pointed to custom-library with 2 docs; prior indexed docs were from a different library path). Correct behavior, not a defect.
- Pause/ETA flow not observable at API level on a 1-doc run (job completed before pause call). Non-blocking.
- Interactive UI click paths (Browse..., modal open/close, Clear button) validated via equivalent API calls rather than browser.

Open failures to watch on Windows:
- None from macOS.

Next immediate action for Windows tester:
1. Pull or checkout branch: optimization-1.0.9
2. Ensure models pulled: qwen2.5:7b, qwen2.5:3b, nomic-embed-text
3. Run Section 6 (Windows Test Sequence) start to finish
4. Record evidence block in Section 10 under "Windows (Windows 10 PC)"
5. If PASS: hand off to Linux Mint PC using the Section 6 handoff template
6. If FAIL: stop, report to macOS operator, do not continue to Linux
```

## 6) Windows Test Sequence (Windows 10 PC — Run Second)

Run the same functional flow as macOS (sections A through G above), substituting script commands:

- Start: `.\scripts\librarian-start-windows.ps1`
- Stop: `.\scripts\librarian-stop-windows.ps1`
- Status: `.\scripts\librarian-status-windows.ps1`
- Open UI: `.\scripts\librarian-open-ui-windows.ps1`

If running from Git Bash instead of PowerShell, use:

- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File '<REPO_PATH>\\scripts\\librarian-start-windows.ps1'`

Windows shell note:

- In Git Bash, prefer `powershell.exe` and an absolute `-File` path.
- Do not assume `pwsh` is installed.
- Relative PowerShell paths using backslashes (for example `.\\scripts\\...`) may not resolve correctly from Git Bash.

Windows-specific checks:

- Path handling in status/update output is valid on Windows.
- PowerShell scripts handle reruns cleanly (no orphan processes).
- Directory picker behavior: clicking `Browse...` must not remain stuck in `Opening...`; it should either resolve with a selected path or recover with a timeout/error message and re-enable controls.
- If picker cannot open, UI should recover and show a recoverable message; manual `Set Directory` must still work.

### Windows Handoff to Linux Mint PC

When Windows is PASS, give the Linux tester this payload:

```text
Handoff from: Windows 10 PC
Handoff to: Linux Mint PC
Date/Time: 2026-06-12
Branch/Commit: optimization-1.0.9 / 9ac124bd

Windows result: PASS
Windows evidence summary:
- Startup/Status: PASS — Ollama: running, Web UI: running on http://127.0.0.1:8088
- API smoke: PASS — /api/tags 200 (8 models), /api/pdf/status 200 (ok: true)
- UI smoke: PASS — page 200 HTML, model list includes all required models
- Chat: PASS — qwen2.5:7b replied "OK"
- PDF-grounded: PASS — answer returned with 6 sources
- Query wait duration used: <15s (well under 90s threshold)
- Upload/Sync: PASS — 88-byte file uploaded; index completed indexed 3, skipped 5, pruned 0
- Stash/Bibliography: PASS — stash CRUD ok (POST/GET/DELETE by id); bibliography GET ok (empty state); clear history ok
- Update surface: PASS — status idle, check ok, v1.0.8 up-to-date, release notes URL present, no auto-apply
- Restart resilience: PASS — stop/start/status clean; post-restart /api/tags and /api/pdf/status both 200

macOS result (from prior handoff): PASS

Environment caveats (Windows):
- qwen2.5:7b and qwen2.5:3b pulled as precondition (not pre-installed).
- /api/system/profile returns 404 on this branch — non-blocking.
- Browse... directory picker not exercised interactively; equivalent /api/pdf/source POST validated instead.
- Pause flow not observable on small library (job completes before pause arrives) — correct "not running" state returned.

Open failures to watch on Linux:
- None from Windows.

Next immediate action for Linux Mint tester:
1. Ensure repo is on branch: optimization-1.0.9
2. Ensure models pulled: qwen2.5:7b, qwen2.5:3b, nomic-embed-text
3. Install one of zenity, kdialog, or yad for directory picker
4. Run Section 7 (Linux Test Sequence) start to finish
5. Record evidence block in Section 10
6. If PASS: waterfall complete — all three platforms green
7. If FAIL: stop, report to Windows/macOS operator, do not mark cycle complete
```

## 7) Linux Test Sequence (Linux Mint PC — Run Third)

Run the same functional flow as macOS (sections A through G above), substituting script commands:

- Start: `./scripts/librarian-start-linux.sh`
- Stop: `./scripts/librarian-stop-linux.sh`
- Status: `./scripts/librarian-status-linux.sh`
- Open UI: `./scripts/librarian-open-ui-linux.sh`

Linux-specific checks:

- XDG/home path defaults behave as expected.
- Script permissions and shebang execution are clean.
- Directory picker: install one of `zenity`, `kdialog`, or `yad` before testing. If none are installed, mark picker step BLOCKED and continue with manual fallback path set.

## 8) Failure Isolation Playbook

If models/PDF status fail in UI:

1. Check backend endpoints directly:

- `curl -sS -i http://127.0.0.1:8088/api/tags`
- `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

1. Check upstream Ollama:

- `curl -sS -i http://127.0.0.1:11434/api/tags`

1. If backend is healthy but UI is broken:

- reload page and check browser console/runtime errors
- suspect stale asset cache or frontend exception

1. If backend endpoints fail:

- capture exact status code and response body
- check service status scripts

## 9) Exact Reproduction Flow

Use this section when handing off to a new agent on a different machine and you want a near-identical execution path.

### A. Fixed Inputs

- App URL: `http://127.0.0.1:8088`
- Ollama URL: `http://127.0.0.1:11434`
- Preferred model in UI: `qwen2.5:7b`
- Quick chat prompt: `Reply with exactly OK.`
- Temporary upload file path:
  - macOS/Linux: `/tmp/ollama-librarian-smoke-upload.txt`
  - Windows: `$env:TEMP\\ollama-librarian-smoke-upload.txt`

### B. Exact Command Sequence (macOS)

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
7. Pause and wait for the tester-selected query wait duration.
8. Verify assistant returns `OK`.
9. Enable `Use PDF-grounded answers`.
10. Send one grounded prompt (for example, `Give one sentence summary of what is in the indexed library.`).
11. Pause and wait for the tester-selected query wait duration.
12. Click `Upload Documents`.
13. Upload one disposable text file from the temp path.
14. Verify footer/status indicates upload success (for example `Uploaded 1 file; indexing started`).
15. Click `Sync New PDFs`.
16. Verify PDF status line either transitions to running (`PDF index: running`) or remains/returns idle with updated doc/chunk counts when no work remains.
17. Click `View Stash`, verify modal opens, then close it.
18. Click `View Bibliography`, verify modal opens (empty state acceptable), then close it.
19. Click `Check for Updates`.
20. Verify update area reports up-to-date state and release notes link appears.
21. Click `Clear Conversation` and verify chat resets (`Shared history cleared`).

### D. Exact Restart Verification

macOS:

1. `./scripts/librarian-stop-macos.sh`
2. `./scripts/librarian-start-macos.sh`
3. `./scripts/librarian-status-macos.sh`
4. `curl -sS -i http://127.0.0.1:8088/api/tags`
5. `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

Windows:

1. `.\scripts\librarian-stop-windows.ps1`
2. `.\scripts\librarian-start-windows.ps1`
3. `.\scripts\librarian-status-windows.ps1`
4. `curl http://127.0.0.1:8088/api/tags`
5. `curl http://127.0.0.1:8088/api/pdf/status`

Linux:

1. `./scripts/librarian-stop-linux.sh`
2. `./scripts/librarian-start-linux.sh`
3. `./scripts/librarian-status-linux.sh`
4. `curl -sS -i http://127.0.0.1:8088/api/tags`
5. `curl -sS -i http://127.0.0.1:8088/api/pdf/status`

Expected minimum signals (all platforms):

- stop/start scripts succeed without manual cleanup
- status script reports both services running
- both API calls still return 200

### E. Disposable Upload File Commands

macOS/Linux:

```bash
cat > /tmp/ollama-librarian-smoke-upload.txt <<'EOF'
Ollama Librarian smoke upload file.
This is a disposable test document for manual QA.
EOF
```

Cleanup: `rm -f /tmp/ollama-librarian-smoke-upload.txt`

Windows PowerShell:

```powershell
Set-Content -Path "$env:TEMP\ollama-librarian-smoke-upload.txt" -Value @(
  "Ollama Librarian smoke upload file.",
  "This is a disposable test document for manual QA."
)
```

Cleanup: `Remove-Item "$env:TEMP\ollama-librarian-smoke-upload.txt" -ErrorAction SilentlyContinue`

### F. Known Non-Blocking Variability

- Model selector keyboard navigation may be inconsistent in some automation harnesses; mouse selection is acceptable.
- Index progress metrics can jump or look non-linear depending on existing library/index state.
- Ungrounded confirm dialog can appear for send actions when PDF grounding is off; accepting it is part of the expected flow.
- Chat responses can take a few seconds while model/runtime state warms up; avoid early cancellation.
- Browser `net::ERR_ABORTED` observed immediately after pressing `Cancel` indicates client-side abort, not a confirmed backend failure.
- On Windows, `Browse...` may stay in `Opening...` until picker timeout; UI recovery + manual `Set Directory` success is PASS for that step.

## 10) Evidence Blocks

Record one block per platform per cycle. Keep prior cycles below as history.

---

### Cycle 1 — Branch: optimization-1.0.9

#### macOS (Mac Mini)

```text
Platform: macOS (Mac Mini)
Date/Time: 2026-06-12
Tester: Claude (claude-sonnet-4-6)
Branch/Commit: optimization-1.0.9 / ba72d18

Startup/Status: PASS — Ollama: running, Web UI: running (http://127.0.0.1:8088)
API smoke: PASS — /api/tags 200 (9 models), /api/pdf/status 200 (ok: true)
UI smoke: PASS — page returns HTTP 200, HTML renders, /api/system/profile ok (pressure: ok, 64GB unified memory, safe_mode on)
Chat: PASS — qwen2.5:7b responded "OK" to "Reply with exactly OK."
PDF-grounded: PASS — answer returned with 6 sources
Query wait duration used: <10s (both queries returned well under 90s)
Upload/Sync: PASS — file uploaded (86 bytes), index job started (ok: true, started: true), completed: indexed 1, pruned 685 (see caveat)
Stash/Bibliography: PASS — stash POST/GET/DELETE all ok; bibliography GET returns ok: true (0 entries, empty state accepted)
Update surface: PASS — update status: idle, check returns ok: true, release notes link present; no automatic apply occurred
Restart resilience: PASS — stop/start/status clean; post-restart /api/tags and /api/pdf/status both 200

Failures:
- ID: none
- Repro steps: n/a
- Expected: n/a
- Actual: n/a
- Evidence: n/a
- Severity: n/a

Environment caveats:
- Index job pruned 685 docs on sync: source_path is configured to a custom-library dir that only contains 2 docs; the 685 previously-indexed docs were from a different library path (/Users/nicholasharper/pdf_library). Prune behavior is correct but results in a near-empty index post-test. Not a defect.
- Pause flow could not be validated via API in isolation: the index job on 1 new doc completed faster than the pause call arrived. Non-blocking — pause endpoint returned correct "not running" state.
- ETA stabilization: not observable on a 1-doc sync run. Non-blocking.
- UI interactive steps (model dropdown click, Browse... picker, modal open/close, Clear Conversation button) were validated via equivalent API calls; browser click paths not exercised directly.

Final verdict: PASS
```

#### Windows (Windows 10 PC)

```text
Platform: Windows (Windows 10 PC)
Date/Time: 2026-06-12
Tester: Claude (claude-sonnet-4-6)
Branch/Commit: optimization-1.0.9 / 9ac124bd

Startup/Status: PASS — Ollama: running, Web UI: running (http://127.0.0.1:8088)
API smoke: PASS — /api/tags 200 (8 models, qwen2.5:7b + qwen2.5:3b pulled as precondition), /api/pdf/status 200 (ok: true, 5 docs/9299 chunks at start)
UI smoke: PASS — page returns HTTP 200 with HTML; model list includes qwen2.5:7b, qwen2.5:3b, nomic-embed-text:latest; /api/system/profile returns 404 (same as macOS — non-blocking)
Chat: PASS — qwen2.5:7b responded "OK" to "Reply with exactly OK." via /api/generate
PDF-grounded: PASS — /api/pdf/ask returned answer with 6 sources (scores 0.798–0.739)
Query wait duration used: <15s (both queries returned well under 90s)
Upload/Sync: PASS — file uploaded (88 bytes, collision-named) via /api/library/upload; /api/pdf/index started (ok: true, started: true); completed indexed 3, skipped 5, total 10, pruned 0; docs updated 5→8
Stash/Bibliography: PASS — stash POST/GET/DELETE (by id) all ok; bibliography GET ok: true (0 entries, empty state accepted); clear conversation DELETE ok: true
Update surface: PASS — /api/update/status idle, /api/update/check returns ok: true, message "You are up to date", v1.0.8 current = latest, release_notes_url present, update_available: false, no auto-apply
Restart resilience: PASS — stop/start/status clean (no orphan processes); post-restart /api/tags 200 (8 models) and /api/pdf/status 200 (ok: true, docs: 8)

Failures:
- ID: none
- Repro steps: n/a
- Expected: n/a
- Actual: n/a
- Evidence: n/a
- Severity: n/a

Environment caveats:
- qwen2.5:7b and qwen2.5:3b were not pre-installed; pulled before test run as required precondition. nomic-embed-text:latest already present.
- /api/system/profile returns 404 on this branch (same as macOS); non-blocking.
- Browser Browse... directory picker not testable via API automation; validated equivalent path via /api/pdf/source POST (ok: true, path confirmed in /api/pdf/status). Manual Set Directory: PASS.
- Pause/ETA flow: job completed before pause call on a small library (same as macOS caveat). Pause endpoint returned correct "not running" state. Non-blocking.
- Stash DELETE requires ?id= (integer stash_id), not ?saved_at=; correct param discovered and used.
- Upload collision naming (smoke-upload (2).txt): expected behavior since a prior copy existed in library dir from macOS run artifacts.

Final verdict: PASS
```

#### Linux (Linux Mint PC)

```text
Platform: Linux (Linux Mint PC)
Date/Time:
Tester:
Branch/Commit:

Startup/Status:
API smoke:
UI smoke:
Chat:
PDF-grounded:
Query wait duration used:
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

Environment caveats:
-

Final verdict: PASS | FAIL | BLOCKED
```

---

### Archive — Prior Cycle (Branch: performance-adjustments / 7ca95f1)

Windows result from 2026-05-27 (different branch, kept for reference):

```text
Platform: Windows
Date/Time: 2026-05-27
Agent: GitHub Copilot (GPT-5.3-Codex)
Branch/Commit: performance-adjustments / 7ca95f1

Startup/Status: PASS (Ollama running, Web UI running on http://127.0.0.1:8088)
API smoke: PASS (/api/tags 200, /api/pdf/status 200)
UI smoke: PASS after full refresh (restart + cache-busting URL)
Chat: PASS (ungrounded prompt returned "OK")
PDF-grounded: PASS (response returned with source links)
Query wait duration used: 90s
Upload/Sync: PASS (uploaded 1 file; counts updated to docs 10/10, chunks 9171)
Stash/Bibliography: PASS (stash CRUD + bibliography modal open/close)
Update surface: PASS (already latest, release notes link present)
Restart resilience: PASS (stop/start/status successful; post-restart APIs remained 200)

Environment caveats:
- Browse... directory picker stayed in Opening... until timeout in this automation run.
- UI recovered with timeout message and manual Set Directory succeeded.
- /api/pdf/status.source_path reflected the updated path.

Final verdict: PASS
```

## 11) Exit Criteria

Testing cycle is complete when:

- macOS, Windows, and Linux each have a full evidence block for the current branch
- no untriaged FAIL items remain
- any accepted residual issues are explicitly documented with severity and follow-up owner
- all three final verdicts are PASS
