# Fixes Needed

## Resolved Issue

Linux deep search (Deep Study Mode) instability.

- Status: Resolved in v1.0.3 by product-surface removal.
- Severity: Previously high for Linux users who relied on deep retrieval flows.

### Summary

- On Linux systems, larger prompt payloads could fail or time out when Deep Study Mode was enabled.
- The instability was reproducible through direct Ollama generate calls (outside web route), indicating runtime-level instability rather than app-only logic.

### User-Facing Resolution

- Deep Study functionality was removed from the UI and web route layer.
- Study Brief action was removed from the chat controls.
- The `/api/pdf/brief` route was removed.
- Web-layer usage of `deepen` for `/api/pdf/ask` was removed.

### Historical Evidence Snapshot

- Short prompts succeeded consistently.
- Larger prompts could return 500 after extended runtimes (for example around 1m14s to 1m30s).
- Reproduced on Linux after Ollama reinstall and NVIDIA open/proprietary 595 driver validation.

### Current Follow-Up

- Keep this file as historical context for why Deep Study was removed.
- Re-evaluate reintroduction only after upstream runtime stability is demonstrated cross-platform.

## Resolved Issue

Directory picker could leave the UI stuck on `Opening...`.

- Status: Resolved on 2026-05-27 with recoverable timeout handling in native picker calls.
- Severity: Medium (primary UX path impaired, but manual path fallback remained available).

### Summary

- Native folder picker calls could block long enough that the web route never returned promptly.
- The frontend would remain in `Opening...` until service restart in bad cases.

### User-Facing Resolution

- Native picker subprocess calls now enforce bounded timeout windows.
- Timeout/errors return recoverable responses so UI restores from `Opening...`.
- Manual path entry (`Set Directory`) continues to work as explicit fallback.

### Current Follow-Up

- Validate interactive native picker behavior on Windows and Linux desktop sessions.
- Keep treating headless picker timeout as non-blocking when UI recovery + manual fallback pass.

## Fixes for the Coding Agent

The items below are discrete and actionable, with enough context that an agent can pick any one up without re-deriving the situation.

1. **Extract embedded frontend HTML from `scripts/ollama-web-chat.py` into separate files.**
   The `HTML` and `EPUB_READER_HTML` string literals inside `scripts/ollama-web-chat.py` account for most of the file's ~5,800 lines. Move them to `scripts/templates/index.html` and `scripts/templates/epub-reader.html` (or similar), and load them at server startup.

   Keep the existing `%OLLAMA_BASE%`, `%API_KEY_REQUIRED%`, `%MAX_UPLOAD_BYTES%`, `%CURRENT_VERSION%`, and `%CSP_NONCE_ATTR%` placeholder substitution mechanism. Do not introduce a templating dependency; keep simple `.replace()` calls.

   The `do_GET` handler for `/` and `/epub-reader` should be the only places that change. Make sure the CSP nonce flow still works.

2. **Split inline CSS and JS out of the templates.**
   Once HTML is in separate files, move inline `<style>` and `<script>` blocks into `scripts/assets/app.css` and `scripts/assets/app.js` (and equivalents for the EPUB reader).

   Serve them through the existing `/assets/` route, which already has path-traversal guards and immutable cache headers. The CSP nonce currently gates inline scripts; once JS is external, remove nonce usage from script tags and tighten CSP to disallow inline scripts entirely.

3. **Fix macOS-only default paths so Linux and Windows work without env var overrides.**
   In `scripts/ollama-web-chat.py` and `scripts/pdf_library_rag.py`, these defaults are hard-coded to `~/Library/Application Support/home-network-setup/...`:

   - `HISTORY_PATH`
   - `PDF_INDEX_DB`
   - `STASH_PATH` (via `resolve_default_stash_path`)
   - `UPDATE_STATE_PATH` (derived from `HISTORY_PATH`)
   - The `--index-db` argparse default in `pdf_library_rag.py`

   Replace with a platform-dispatched helper:

   - macOS: `~/Library/Application Support/ollama-librarian/`
   - Windows: `%APPDATA%\ollama-librarian\` (via `os.environ["APPDATA"]`)
   - Linux: `$XDG_DATA_HOME/ollama-librarian/` or `~/.local/share/ollama-librarian/`

   Also, `resolve_default_pdf_source()` currently hard-codes `/Volumes/shared/LLM Library` (a macOS NAS mount). Replace with a platform-appropriate default such as `~/Documents/LLM Library` and fall back gracefully if it does not exist.

   The `home-network-setup` folder name appears to be a personal leftover and should not be used in defaults.

4. **Add `pyproject.toml` and turn scripts into an installable package.**
   The two Python files are currently loose scripts and communicate by subprocess (`ollama-web-chat.py` shells out to `pdf_library_rag.py` via `run_pdf_rag`).

   Add a `pyproject.toml` with dependencies (`pypdf>=4.2.0`, `ebooklib>=0.18`) and entry points (`ollama-librarian = ...`, `ollama-librarian-index = ...`). Move files under `src/ollama_librarian/`.

   Keeping subprocess isolation is fine, but invoke with `sys.executable -m ollama_librarian.indexer` instead of resolving `.venv/bin/python`. This removes the brittle `PDF_RAG_PYTHON = REPO_ROOT / ".venv/bin/python"` assumption.

5. **Break up the large `Handler` class.**
   `Handler.do_GET` and `Handler.do_POST` are long `if/elif` chains routing by string.

   Extract a route table (for example, a dict mapping `(method, path)` to handler function), then have `do_GET`, `do_POST`, and `do_DELETE` dispatch via that table.

   Group handlers by domain: chat, RAG, library, stash, abstract screener, update, and history/instructions. This should be a pure refactor with no behavior change.

6. **Add tests for the HTTP routing table.**
   `tests/` currently has only `test_security_regressions.py` and `test_update_flow.py`.

   Add `tests/test_routes.py` that starts the server on a random port and asserts response shape for documented endpoints:

   - `/api/tags`
   - `/api/history` (GET/POST/DELETE)
   - `/api/instructions` (GET/POST)
   - `/api/library/docs`
   - `/api/stash` (GET/POST/DELETE)
   - `/api/bibliography`
   - `/api/pdf/status`
   - `/api/update/status`
   - `/api/abstract/evaluate`

   Stub Ollama proxy calls (for example, point `OLLAMA_BASE_URL` at a local fake responder fixture). Goal: catch route regressions, auth-enforcement regressions, and JSON-shape regressions, not model quality.

7. **Add tests for deterministic RAG helpers.**
   In `pdf_library_rag.py`, add unit tests for pure functions:

   - `chunk_text`
   - `cosine_similarity`
   - `extract_year`
   - `split_authors`
   - `infer_author_and_title_from_path`
   - `clean_title_candidate`
   - `looks_like_author_name`
   - `strip_html_to_text`

   None of these require Ollama or filesystem access. Add coverage in `tests/test_rag_units.py`.

8. **Add tests for abstract screener normalization helpers.**
   In `ollama-web-chat.py`, test these pure contract-normalization helpers:

   - `_extract_json_object`
   - `_clamp_confidence`
   - `_confidence_bucket`
   - `_normalize_recommendation`
   - `_recommendation_label`
   - `_extract_reason_list`

   Feed malformed and well-formed LLM-style outputs and assert normalization and bucket behavior. This is high-value coverage because it controls what the UI shows from unreliable model output.

9. **Centralize configuration.**
   Environment reads are currently scattered through module-level code in `ollama-web-chat.py` (around lines 21-130), and similarly in `pdf_library_rag.py`.

   Move configuration into a `Config` dataclass loaded at startup so overrides are testable and the full config surface is centralized. The Runtime Environment Variables section in README is currently hand-maintained and could drift; consider generating it from dataclass field docs.

10. **Add a doctor/diagnose subcommand.**
   Common user failure mode: "I followed setup but it doesn't work."

   Add `scripts/librarian-doctor` (or a `--doctor` flag, or an `ollama-librarian doctor` entry point) that checks:

- Python version >= 3.10
- `pypdf` and `ebooklib` importability
- Ollama reachability at `OLLAMA_BASE_URL`
- Required models pulled (`nomic-embed-text`, `qwen2.5:14b`)
- Index DB writability
- Source directory existence/readability
- `OLLAMA_WEB_PORT` availability

   Print pass/fail per check to reduce support load.
