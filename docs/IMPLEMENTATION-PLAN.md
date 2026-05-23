# Ollama Librarian Implementation Plan

This file is the single source of truth for the suggested fixes in docs/Fixes Needed.md.

Purpose:

- Keep scope stable while we implement.
- Break work into small, reviewable units.
- Commit after each unit with a descriptive message.
- Preserve easy rollback points.

## Working Agreement

- We implement one phase at a time.
- We run targeted tests before each commit.
- We commit each completed phase with the suggested commit message (or a refined equivalent).
- We do not start the next phase until the current phase is green.

## Commit Cadence

One commit per phase by default. If a phase is still too large, split into Phase X.a and X.b.

Commit message format:

```
<type>: <short summary>

- What changed
- Why it changed
- Test coverage added/updated
```

Suggested types:

- refactor
- test
- feat
- chore
- docs

## Phase Roadmap (Granular)

### Phase 0 - Baseline and guardrails

Status: DONE

Scope:

- Add a lightweight endpoint test harness.
- Capture current API response shape assumptions for critical routes.
- Document a pre-refactor smoke test command list.

Deliverables:

- tests/helpers/server_harness.py (or equivalent)
- tests/test_routes.py skeleton with first route checks
- docs note for local smoke test sequence (if needed)

Acceptance checks:

- New harness can start server on random port.
- At least one GET and one POST route check passes.
- Existing tests still pass.

Suggested commit message:

- test: add route harness and baseline endpoint contract checks

### Phase 1 - High-value tests first

Status: DONE

Scope:

- Add route coverage for:
  - /api/tags
  - /api/history (GET/POST/DELETE)
  - /api/instructions (GET/POST)
  - /api/library/docs
  - /api/stash (GET/POST/DELETE)
  - /api/bibliography
  - /api/pdf/status
  - /api/update/status
  - /api/abstract/evaluate
- Add deterministic unit tests in pdf_library_rag.py for:
  - chunk_text
  - cosine_similarity
  - extract_year
  - split_authors
  - infer_author_and_title_from_path
  - clean_title_candidate
  - looks_like_author_name
  - strip_html_to_text
- Expand abstract helper tests in ollama-web-chat.py for:
  - \_extract_json_object
  - \_clamp_confidence
  - \_confidence_bucket
  - \_normalize_recommendation
  - \_recommendation_label
  - \_extract_reason_list

Deliverables:

- tests/test_routes.py
- tests/test_rag_units.py
- tests/test_abstract_helpers.py (or extend existing security test file)

Acceptance checks:

- New tests pass locally.
- Existing security and update tests pass.

Suggested commit messages:

- test: add HTTP route contract tests for key API endpoints
- test: add deterministic RAG helper unit tests
- test: harden abstract output normalization coverage

### Phase 2 - Cross-platform default paths

Status: DONE

Scope:

- Replace hard-coded macOS-only defaults in:
  - scripts/ollama-web-chat.py
  - scripts/pdf_library_rag.py
- Add shared platform-aware helpers for default app data directory.
- Update defaults for:
  - HISTORY_PATH
  - PDF_INDEX_DB
  - STASH_PATH
  - UPDATE_STATE_PATH
  - pdf_library_rag --index-db default
- Update resolve_default_pdf_source fallback behavior.

Target defaults:

- macOS: ~/Library/Application Support/ollama-librarian/
- Windows: %APPDATA%/ollama-librarian/
- Linux: $XDG_DATA_HOME/ollama-librarian/ or ~/.local/share/ollama-librarian/

Acceptance checks:

- Defaults are platform-derived with env override support.
- Existing explicit env overrides still win.
- Tests cover helper behavior.

Suggested commit message:

- refactor: make state and library defaults cross-platform

### Phase 3 - Extract HTML templates from server script

Status: DONE

Scope:

- Move embedded HTML and EPUB HTML into template files:
  - scripts/templates/index.html
  - scripts/templates/epub-reader.html
- Load templates at startup.
- Keep placeholder replacement behavior:
  - %OLLAMA_BASE%
  - %API_KEY_REQUIRED%
  - %MAX_UPLOAD_BYTES%
  - %CURRENT_VERSION%
  - %CSP_NONCE_ATTR%
- Restrict do_GET changes to root and epub-reader rendering.

Acceptance checks:

- Root page loads.
- EPUB reader page loads.
- Placeholder replacement still works.
- CSP nonce flow still works at this phase.

Suggested commit message:

- refactor: externalize web templates from server script

### Phase 4 - Extract inline CSS and JS, tighten CSP

Status: TODO

Scope:

- Move inline style/script blocks into:
  - scripts/assets/app.css
  - scripts/assets/app.js
  - scripts/assets/epub-reader.css
  - scripts/assets/epub-reader.js
- Update templates to reference external assets only.
- Remove inline script nonce requirement from templates once inline scripts are gone.
- Tighten CSP script-src policy to disallow unsafe-inline.

Acceptance checks:

- No inline script blocks remain in templates.
- Main UI and EPUB UI function correctly.
- Security tests updated and passing.

Suggested commit message:

- refactor: serve app CSS and JS as static assets and tighten CSP

### Phase 5 - Route-table refactor

Status: TODO

Scope:

- Replace long if/elif route chains in Handler methods with route dispatch table.
- Keep auth and same-origin checks at dispatcher boundary.
- Group handler methods by domain:
  - chat
  - RAG
  - library
  - stash
  - abstract screener
  - update
  - history/instructions

Acceptance checks:

- Route tests remain green with no response-shape regressions.
- 404 behavior unchanged for unknown routes.

Suggested commit message:

- refactor: replace route chains with method-path dispatch table

### Phase 6 - Centralize configuration

Status: TODO

Scope:

- Introduce Config dataclass for server and indexer settings.
- Load env vars once at startup.
- Replace scattered module-level reads with config object usage.
- Keep environment variable names backward compatible.

Acceptance checks:

- Existing startup scripts still work.
- Tests can instantiate config with controlled values.

Suggested commit message:

- refactor: centralize environment settings into config dataclasses

### Phase 7 - Package into installable project

Status: TODO

Scope:

- Add pyproject.toml.
- Add src/ollama_librarian package.
- Move scripts into package modules.
- Add entry points:
  - ollama-librarian
  - ollama-librarian-index
- Replace direct script subprocess call with:
  - sys.executable -m ollama_librarian.indexer
- Preserve compatibility for existing shell scripts during migration.

Acceptance checks:

- Package installs in local venv.
- Entry points run.
- Existing launcher scripts continue to work (or are updated in same phase).

Suggested commit message:

- feat: package project with entry points and module-based indexer launch

### Phase 8 - Doctor/diagnose command

Status: TODO

Scope:

- Add doctor command to validate runtime prerequisites:
  - Python version >= 3.10
  - pypdf and ebooklib import checks
  - Ollama reachability
  - required models availability
  - index DB path writable
  - source directory exists/readable
  - configured port availability
- Return clear pass/fail per check.

Acceptance checks:

- Command runs non-interactively.
- Output is readable and actionable.
- Exit code reflects overall status.

Suggested commit message:

- feat: add doctor command for environment and dependency diagnostics

## Execution Log

Update this table as we complete each phase.

| Phase | Branch | Commit SHA | Summary                                                                                                                   | Tests run                                                                                                                                                                                                           | Result  |
| ----- | ------ | ---------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 0     | main   |            | Added route harness and baseline GET/POST route contract tests                                                            | python -m unittest tests/test_routes.py tests/test_security_regressions.py tests/test_update_flow.py                                                                                                                | pass    |
| 1     | main   |            | Added route contract coverage plus deterministic RAG and abstract helper unit tests                                       | python -m unittest tests/test_abstract_helpers.py tests/test_rag_units.py tests/test_routes.py tests/test_security_regressions.py tests/test_update_flow.py                                                         | pass    |
| 2     | main   |            | Added cross-platform default state/source paths in web+indexer scripts with path-default tests                            | python -m unittest tests/test_path_defaults.py tests/test_abstract_helpers.py tests/test_rag_units.py tests/test_routes.py tests/test_security_regressions.py tests/test_update_flow.py                             | pass    |
| 3     | main   |            | Extracted embedded HTML/EPUB templates to scripts/templates and loaded at startup with placeholder substitution preserved | python -m unittest -q tests/test_path_defaults.py tests/test_abstract_helpers.py tests/test_rag_units.py && python -m unittest -q tests/test_routes.py tests/test_security_regressions.py tests/test_update_flow.py | pass    |
| 4     |        |            |                                                                                                                           |                                                                                                                                                                                                                     | pending |
| 5     |        |            |                                                                                                                           |                                                                                                                                                                                                                     | pending |
| 6     |        |            |                                                                                                                           |                                                                                                                                                                                                                     | pending |
| 7     |        |            |                                                                                                                           |                                                                                                                                                                                                                     | pending |
| 8     |        |            |                                                                                                                           |                                                                                                                                                                                                                     | pending |

## Regroup Rules

Stop and regroup if any of these occur:

- Security headers or auth behavior changes unexpectedly.
- More than 10 endpoint assertions fail in a single phase.
- Launch scripts fail on a supported platform after packaging changes.
- Any phase expands beyond 2 focused commits.

When regrouping:

- Update this file first.
- Record decision in Execution Log summary.
- Re-scope next phase before writing code.
