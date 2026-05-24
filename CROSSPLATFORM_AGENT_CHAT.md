# Cross-Platform Agent Handoff

Platform: Windows
App URL used: http://127.0.0.1:8088
Ollama URL used: http://127.0.0.1:11434
Commands executed (in order):

1. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-start-windows.ps1
2. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-status-windows.ps1
3. curl -sS -i http://127.0.0.1:8088/api/tags
4. curl -sS -i http://127.0.0.1:8088/api/pdf/status
5. curl -sS -i http://127.0.0.1:11434/api/tags
6. powershell.exe -NoProfile -Command @"... "@ | Set-Content -Path "$env:TEMP\\ollama-librarian-smoke-upload.txt"
7. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-stop-windows.ps1
8. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-start-windows.ps1
9. powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/librarian-status-windows.ps1
10. curl -sS -i http://127.0.0.1:8088/api/tags
11. curl -sS -i http://127.0.0.1:8088/api/pdf/status
12. powershell.exe -NoProfile -Command Remove-Item "$env:TEMP\\ollama-librarian-smoke-upload.txt" -ErrorAction SilentlyContinue
    UI actions executed (in order):
13. Opened app at http://127.0.0.1:8088
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
