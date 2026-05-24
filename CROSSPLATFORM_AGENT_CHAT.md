# Cross-Platform Agent Handoff

Note: The first Windows section below is historical pre-v1.0.3 context and includes steps/features that were later removed.

Platform: Windows
App URL used: <http://127.0.0.1:8088>
Ollama URL used: <http://127.0.0.1:11434>
Commands executed (in order):

1. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-start-windows.ps1
2. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-status-windows.ps1
3. curl -sS -i <http://127.0.0.1:8088/api/tags>
4. curl -sS -i <http://127.0.0.1:8088/api/pdf/status>
5. curl -sS -i <http://127.0.0.1:11434/api/tags>
6. powershell.exe -NoProfile -Command @"... "@ | Set-Content -Path "$env:TEMP\\ollama-librarian-smoke-upload.txt"
7. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-stop-windows.ps1
8. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-start-windows.ps1
9. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-status-windows.ps1
10. curl -sS -i <http://127.0.0.1:8088/api/tags>
11. curl -sS -i <http://127.0.0.1:8088/api/pdf/status>
12. powershell.exe -NoProfile -Command Remove-Item "$env:TEMP\\ollama-librarian-smoke-upload.txt" -ErrorAction SilentlyContinue
    UI actions executed (in order):
13. Opened app at <http://127.0.0.1:8088>
14. Verified Online model state in sidebar
15. Clicked Refresh by model selector
16. Unchecked Use PDF-grounded answers and accepted confirmation
17. Sent prompt Reply with exactly OK. and waited for completion
18. Re-enabled Use PDF-grounded answers
19. Sent grounded prompt Give one sentence summary of what is in the indexed library. and waited for completion
20. Enabled Deep Study Mode
21. Sent deep-study prompt In one sentence, what topics dominate these sources? and waited for completion
22. Clicked Stash on assistant response
23. Clicked Upload Documents and uploaded F:/Temp/ollama-librarian-smoke-upload.txt
24. Clicked Sync New PDFs
25. Opened View Stash, clicked Reload, deleted one item, closed modal
26. Opened View Bibliography, verified empty state, closed modal
27. Clicked Check for Updates
28. Clicked Clear Conversation
    Observed confirmations:

- Startup/status: start script succeeded; status reported Ollama running and Web UI running
- API 200 checks: /api/tags 200, /api/pdf/status 200 with ok true, Ollama /api/tags 200
- Chat response text: ungrounded returned OK; grounded returned summary with citations; deep-study returned long grounded answer (also confirmed by direct /api/pdf/ask deepen=true returning 200 in ~12s)
- Upload/sync status text: Uploaded 1 file; indexing started, then PDF index sync started; status showed running then idle with docs/chunks updated
- Update status text: idle (release) - You are up to date, and release notes link present
- Clear conversation text: Shared history cleared.
  Deviations from expected flow:
- App Updates briefly showed DNS/update-check failure state before manual check; after Check for Updates it resolved to up-to-date
  Blocking issues:
- None
  Next immediate action for receiving agent:
- Run Linux sequence from top using scripts/librarian-start-linux.sh, scripts/librarian-status-linux.sh, scripts/librarian-stop-linux.sh and mirror the same UI flow with the 30s chat/retrieval wait rule before any cancel.

---

## Linux -> Mac Handoff (Post-Timeout + Deep-Study Removal Changes)

Platform: Linux
App URL used: <http://127.0.0.1:8088>
Ollama URL used: <http://127.0.0.1:11434>
Branch/commit tested: fixes / 6069ee1

### What Changed In Code (Needs Mac Validation)

1. Increased/propagated PDF answer timeout path so long grounded queries can complete.
2. Removed Deep Study product surface from web UI/API path for now.

- Removed Deep Study checkbox and Linux Deep Study notice from main UI templates.
- Removed Study Brief button and related frontend flow.
- Removed `/api/pdf/brief` route in web backend.
- Removed web-layer usage of `deepen` for `/api/pdf/ask`.

3. Updated manual test plan guidance for tester-controlled wait duration before cancel decisions.

### Linux Run Summary

Commands executed (in order):

1. ./scripts/librarian-start-linux.sh
2. ./scripts/librarian-status-linux.sh
3. curl -sS -i <http://127.0.0.1:8088/api/tags>
4. curl -sS -i <http://127.0.0.1:8088/api/pdf/status>
5. curl -sS -i <http://127.0.0.1:11434/api/tags>
6. Created /tmp/ollama-librarian-smoke-upload.txt
7. ./scripts/librarian-stop-linux.sh
8. ./scripts/librarian-start-linux.sh
9. ./scripts/librarian-status-linux.sh
10. curl -sS -i <http://127.0.0.1:8088/api/tags>
11. curl -sS -i <http://127.0.0.1:8088/api/pdf/status>

UI actions executed (in order):

1. Opened app at <http://127.0.0.1:8088>
2. Refreshed model list
3. Ungrounded ask: Reply with exactly OK.
4. Grounded ask: Give one sentence summary of what is in the indexed library.
5. Uploaded disposable document and triggered sync
6. Opened stash/bibliography views and validated behavior
7. Checked updates
8. Cleared conversation

Observed confirmations:

- Startup/status: PASS
- API 200 checks: PASS
- Chat response text: ungrounded OK + grounded response with citations
- Query wait duration used: 90s minimum pause before any cancel decision
- Upload/sync status text: upload success and index status progressed to idle
- Update status text: up-to-date with release notes link
- Clear conversation text: Shared history cleared.

Deviations from expected flow:

- None blocking. Grounded calls can be slow on warmed/cold runs.

Blocking issues:

- None in Linux run.

Next immediate action for Mac receiving agent:

1. Run full macOS manual plan from top with same tester-controlled wait rule.
2. Verify no Deep Study / Study Brief controls are present in UI.
3. Verify normal ungrounded + grounded ask flows still succeed.
4. Verify upload/sync, stash/bibliography, update check, and stop/start resilience.

---

## Release Closure: v1.0.3

Platform summary:

- macOS: PASS
- Windows: PASS
- Linux: PASS

Release decisions captured in this round:

1. Deep Study and Study Brief remain removed.
2. Manual test plan was updated to remove Deep Study/Study Brief expectations.
3. Version bumped for release packaging and runtime markers to `v1.0.3`.

Ready state:

- The current app state has passed end-to-end manual testing across all three target platforms.
