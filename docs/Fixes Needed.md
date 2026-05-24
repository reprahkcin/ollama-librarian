Outstanding issue: Linux deep search (Deep Study Mode) instability

Status: Open
Severity: High for Linux users who rely on deep retrieval flows

Summary

- On Linux systems, larger prompt payloads can fail or time out when Deep Study Mode is enabled.
- Reproduced through direct Ollama generate calls (outside web route), indicating runtime-level instability rather than app-only logic.

User-facing mitigation

- UI now includes a Linux-only footnote near Deep Study Mode warning users about this limitation.
- Recommended fallback is to retry with Deep Study Mode disabled.

Evidence snapshot

- Short prompts succeed consistently.
- Larger prompts can return 500 after extended runtimes (for example around 1m14s to 1m30s).
- Reproduced on Linux after Ollama reinstall and NVIDIA open/proprietary 595 driver validation.

Next environment actions

- Reboot after driver stack changes before re-validation.
- If still failing, validate on alternate NVIDIA driver branch (for example 580 or 535).
- Keep code behavior aligned with main while environment root cause is isolated.

Fixes for the coding agent
I'll write these as discrete, actionable items with enough context that an agent can pick any one up without re-deriving the situation.

1. Extract the embedded frontend HTML out of scripts/ollama-web-chat.py into separate files.
The HTML and EPUB_READER_HTML string literals inside ollama-web-chat.py account for most of the file's ~5,800 lines. Move them to scripts/templates/index.html and scripts/templates/epub-reader.html (or similar). Load them at server startup. Keep the existing %OLLAMA_BASE%, %API_KEY_REQUIRED%, %MAX_UPLOAD_BYTES%, %CURRENT_VERSION%, %CSP_NONCE_ATTR% placeholder substitution mechanism — don't introduce a templating dependency, just .replace() calls. The do_GET handler for / and /epub-reader should be the only places that change. Make sure the CSP nonce flow still works.
2. Split inline CSS and JS out of the templates.
Once the HTML is in separate files, the inline <style> and <script> blocks should move into scripts/assets/app.css and scripts/assets/app.js (and equivalents for the epub reader). They can be served by the existing /assets/ route, which already has path-traversal guards and immutable cache headers. The CSP nonce currently gates inline scripts — once JS is external, the nonce can be removed from <script> tags and the CSP tightened to disallow unsafe-inline for scripts entirely.
3. Fix macOS-only default paths so Linux and Windows work without env-var overrides.
In scripts/ollama-web-chat.py and scripts/pdf_library_rag.py, the following defaults are hard-coded to ~/Library/Application Support/home-network-setup/...:

HISTORY_PATH
PDF_INDEX_DB
STASH_PATH (via resolve_default_stash_path)
UPDATE_STATE_PATH (derived from HISTORY_PATH)
The --index-db argparse default in pdf_library_rag.py

Replace with a platform-dispatched helper that returns:

macOS → ~/Library/Application Support/ollama-librarian/
Windows → %APPDATA%\ollama-librarian\ (via os.environ['APPDATA'])
Linux → $XDG_DATA_HOME/ollama-librarian/ or ~/.local/share/ollama-librarian/

Also: resolve_default_pdf_source() hard-codes /Volumes/shared/LLM Library (a macOS NAS mount). Replace with a platform-appropriate default like ~/Documents/LLM Library and fall back gracefully if it doesn't exist. The home-network-setup folder name in particular looks like a leftover from the author's personal setup and should not be in defaults.
4. Add a pyproject.toml and turn the scripts into an installable package.
Currently both Python files are loose scripts with no module structure; they communicate by subprocess (ollama-web-chat.py shells out to pdf_library_rag.py via run_pdf_rag). Add a pyproject.toml declaring the project, dependencies (pypdf>=4.2.0, ebooklib>=0.18), and entry points (ollama-librarian = ..., ollama-librarian-index = ...). Move the two files under a src/ollama_librarian/ package. Keep the subprocess boundary if you want process isolation for indexing, but use sys.executable -m ollama_librarian.indexer instead of resolving a .venv/bin/python path. This kills the brittle PDF_RAG_PYTHON = REPO_ROOT / ".venv/bin/python" assumption.
5. Break up the monster Handler class.
Handler.do_GET and Handler.do_POST are long if-elif chains routing by string. Extract a small route table — a dict mapping (method, path) → handler function — and have do_GET/do_POST/do_DELETE look up and dispatch. Group the handlers by domain: chat, RAG, library, stash, abstract screener, update, history/instructions. This is a pure refactor, no behavior change, but it makes the next two items much easier.
6. Add tests for the HTTP routing table.
tests/ currently has only test_security_regressions.py and test_update_flow.py. Add tests/test_routes.py that spins up the server on a random port and asserts the response shape for each documented endpoint: /api/tags, /api/history (GET/POST/DELETE), /api/instructions (GET/POST), /api/library/docs, /api/stash (GET/POST/DELETE), /api/bibliography, /api/pdf/status, /api/update/status, /api/abstract/evaluate. Stub the Ollama proxy calls (e.g., point OLLAMA_BASE_URL at a fake local responder fixture). The goal is to catch route regressions, auth-enforcement regressions, and JSON-shape regressions — not to test the model.
7. Add tests for the RAG pipeline's deterministic parts.
In pdf_library_rag.py, the following are pure functions that should have unit tests: chunk_text, cosine_similarity, extract_year, split_authors, infer_author_and_title_from_path, clean_title_candidate, looks_like_author_name, strip_html_to_text. None of these touch Ollama or the filesystem. Add tests/test_rag_units.py.
8. Add tests for the abstract screener's normalization helpers.
In ollama-web-chat.py, these are pure functions that wrap unreliable LLM output into a stable contract and should be tested:_extract_json_object, _clamp_confidence, _confidence_bucket, _normalize_recommendation, _recommendation_label, _extract_reason_list. Feed each malformed and well-formed LLM-style strings and assert the bucketing is correct. This is the highest-value test surface in the project — it's the boundary between "model said something" and "UI shows something" — and currently has zero coverage.
9. Centralize configuration.
Environment variable reads are scattered throughout module-level code in ollama-web-chat.py (lines ~21–130). Move them into a Config dataclass loaded once at startup. Same for pdf_library_rag.py. This makes overrides testable (you can instantiate a Config for a test) and surfaces the full config surface in one place for documentation. The current Runtime Environment Variables README section is hand-maintained and will drift; consider auto-generating it from the dataclass field docstrings.
10. Add a "doctor" / "diagnose" subcommand.
A common failure mode for users will be "I followed setup but it doesn't work." Add scripts/librarian-doctor (or a --doctor flag on the main server, or an ollama-librarian doctor entry point post-packaging) that checks: Python version ≥3.10, pypdf and ebooklib importable, Ollama reachable at OLLAMA_BASE_URL, required models pulled (nomic-embed-text, qwen2.5:14b), index DB writable, source directory exists and readable, port OLLAMA_WEB_PORT free. Print pass/fail per check. This will save significant support work.
