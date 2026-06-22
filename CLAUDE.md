# CLAUDE.md

Local-first document Q&A app: a stdlib-only Python web UI + RAG indexer that proxies a local Ollama for chat/embeddings and answers questions over a personal PDF/EPUB/text library with citations. Single-machine, localhost-only by design.

## Commands

Tests need `src` on the path (CI sets `PYTHONPATH=src`):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Without `PYTHONPATH=src`, `test_hardware_profile.py` fails to import `ollama_librarian`. The other ~99 tests still run because they load modules via the `scripts/*.py` shims.

Run the web app (serves on `127.0.0.1:8088`):

```bash
PYTHONPATH=src python3 -m ollama_librarian.web      # or: python3 scripts/ollama-web-chat.py
```

Indexer / CLI (subcommands: `index search ask synthesize status verify metadata-sync doctor`):

```bash
PYTHONPATH=src python3 -m ollama_librarian.indexer doctor --json-output
python3 scripts/pdf_library_rag.py index --help
```

`doctor` is the preflight: checks deps, Ollama reachability, required models, hardware, port, DB writability. Run it before long syncs.

No linter/formatter or build step is configured. Packaging is setuptools (`pyproject.toml`); console entry points are `ollama-librarian` and `ollama-librarian-index`. CI (`.github/workflows/security-regressions.yml`) only `py_compile`s the shims and runs the unittest suite.

Start/stop/status helper scripts exist per-OS in `scripts/librarian-*-{macos,windows,linux}.{sh,ps1}`.

## Architecture

Three real source modules live in `src/ollama_librarian/`; everything else orbits them.

- **`web.py`** (~4150 lines) — the entire app: a stdlib `ThreadingHTTPServer` + one `Handler` class. Routing is plain dicts keyed by path inside `do_GET`/`do_POST`/`do_DELETE` (no framework). All app endpoints are under `/api/*`; it proxies chat/model calls straight to Ollama (`/api/generate`, `/api/tags`, `/api/show`) and serves the SPA from `templates/index.html` + `assets/`.
- **`indexer.py`** (~2580 lines) — `argparse` CLI and the RAG core. Extracts text (pypdf, ebooklib, HTML parser, OCR fallback), chunks, embeds via Ollama `/api/embed`, and stores everything in a single **SQLite** file (`documents` + `chunks` tables, embeddings as JSON in `embedding_json`). Retrieval is brute-force cosine similarity in Python — no vector DB. `web.py` reuses indexer logic for the in-UI ask/index flows.
- **`hardware.py`** (~590 lines) — detects CPU/RAM/VRAM, classifies "resource pressure", and produces model recommendations + a safety policy. This drives "safe mode": admission control (one heavy generation at a time), adaptive embed throttling, and the ability to pause indexing under sustained pressure. Surfaced at `/api/system/profile` and `/api/system/health`.

Configuration is entirely via `OLLAMA_WEB_*` environment variables (no config file) — the full list with defaults is in `README.md`. State (history, stash, model cache, index DB) lives under an app state directory, all overridable by env vars.

## Conventions / gotchas

- **Template/asset parity:** `templates/` and `assets/` are duplicated in BOTH `scripts/` and `src/ollama_librarian/`. A test enforces they stay byte-identical — edit both copies (or sync after editing one) or the suite fails.
- **The `scripts/*.py` entry points are thin shims**, not the implementation. `ollama-web-chat.py` and `pdf_library_rag.py` just `exec` the matching `src/ollama_librarian/*.py` under the package module name. Make real changes in `src/`.
- **Stdlib only for the app runtime.** `web.py`/`hardware.py` use no third-party packages; only the indexer needs `pypdf` and `ebooklib` (declared in `pyproject.toml` / `scripts/pdf-rag-requirements.txt`), and it imports them defensively (`try/except` → `None`) so it loads without them.
- **Security posture is load-bearing and tested.** Localhost-only bind is enforced (non-loopback hosts rejected), state-changing routes get same-origin checks, citations are HTML-injection-hardened, request bodies are size-capped, and path access uses `os.path.commonpath` guards. `tests/test_security_regressions.py` will catch regressions — don't loosen these casually.
- **Updates are manual by design.** The app checks GitHub for releases but never auto-applies; `/api/update/apply` in default `git` mode only accepts the configured branch.
- `VERSION` exists in both `scripts/` and `src/ollama_librarian/` and should match `pyproject.toml`'s version.
- `docs/` holds extensive manual-test plans and quality-benchmark reports; `docs/MANUAL-TEST-PLAN.md` is the agent-to-agent QA handoff.
