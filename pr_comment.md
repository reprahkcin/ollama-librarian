# Code Review — PR #9: Implement phased hardening, packaging, and diagnostics (Phases 0-8)

**Branch:** `fixes` → `main`
**URL:** https://github.com/reprahkcin/ollama-librarian/pull/9

---

## Overall Assessment

This is a well-structured, thorough PR that successfully delivers all 9 phases from the implementation plan. The scope is large but the execution is disciplined: tests were written first, phases were committed independently, and backward compatibility was preserved via shims. No blocking issues, but there are a few worth addressing before merge.

---

## Issues

### 1. Packaging bug — assets and templates won't be found on non-editable installs (Medium)

In `src/ollama_librarian/web.py`:

```python
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent       # works only in-place
SCRIPT_DIR = REPO_ROOT / "scripts"
ASSET_ROOT = SCRIPT_DIR / "assets"          # not in the wheel
```

`_load_template("index.html")` also reads from `SCRIPT_DIR / "templates"`. Since `pyproject.toml` only packages `src/`, a regular `pip install ollama-librarian` (not `-e`) would place `web.py` in site-packages with no `scripts/` sibling, crashing at startup. Either:

- Move `templates/` and `assets/` into `src/ollama_librarian/` and use `importlib.resources`, or
- Add `[tool.setuptools.package-data]` and update the paths accordingly.

The current setup effectively only supports editable installs, which should be documented explicitly if a non-editable wheel is ever published.

---

### 2. Dead config fields in `WebConfig` (Minor)

`pdf_rag_script` and `pdf_rag_python` are populated in `WebConfig.from_env()` and exported as `PDF_RAG_SCRIPT` / `PDF_RAG_PYTHON` module constants, but `run_pdf_rag()` uses `sys.executable -m ollama_librarian.indexer` directly — neither constant is consumed anywhere. They should either be removed from the dataclass or used. As-is they signal to readers that path-based subprocess dispatch is still active, which is misleading.

---

### 3. Missing version lower bounds in `pyproject.toml` (Minor)

`pyproject.toml` declares bare `pypdf` and `ebooklib` with no lower bounds. The original fix spec called for `pypdf>=4.2.0` and `ebooklib>=0.18`. Without lower bounds, a fresh install could resolve older incompatible versions — especially on systems with pre-existing constraints.

---

### 4. Compatibility shim uses `exec` with modified globals (Minor)

`scripts/ollama-web-chat.py` works, but the approach of `exec(compile(WEB_MODULE_PATH.read_text(...)))` with `globals()["__name__"]` surgery is fragile. If `web.py` ever gains a `if __name__ == "ollama_librarian.web":` guard or uses `__file__` at runtime in a path-sensitive way, the shim behavior could diverge silently. A safer alternative would be `importlib.import_module` after injecting `src/` into `sys.path`.

---

## Positives

- **Security posture is solid.** CSP correctly tightened to `script-src 'self'` (no nonces needed post-asset extraction). Path traversal is properly guarded in both `_resolve_library_file_path` and `_handle_get_assets` using `os.path.realpath()` + `os.sep` suffix check. Same-origin enforcement is in place. `escapeHtml()` is called before `renderInlineMarkdown()` on user-controlled citation strings.
- **`run_pdf_rag` correctly uses `sys.executable`** — the `.venv/bin/python` brittleness is resolved.
- **`subprocess.run` is called with a list throughout**, so the `target_version` branch name passed to the update script poses no shell-injection risk.
- **Doctor command tests are well-isolated** — all network/port/import checks are properly stubbed for CI determinism.
- **Route dispatch table** is clean and makes the handler auditable at a glance.
- **Cross-platform paths** correctly handle macOS, Windows, and XDG Linux conventions.
