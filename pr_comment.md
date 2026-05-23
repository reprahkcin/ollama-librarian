# Code Review Notes — PR #9

Branch: fixes -> main
URL: https://github.com/reprahkcin/ollama-librarian/pull/9

This document is a running review log. Earlier findings below were addressed during follow-up commits, unless explicitly marked open.

## Status Snapshot

- Packaging path issue for templates/assets in non-editable installs: addressed.
- Dead web config fields (pdf_rag_script/pdf_rag_python): addressed.
- Dependency minimum bounds in pyproject: addressed.
- Version mismatch between project metadata and app VERSION files: addressed.
- CSP inline-style issue for update notes link: addressed.
- Compatibility shim uses exec: acknowledged as a known tradeoff to preserve current dynamic test-loading behavior.

## Current Guidance

- Focus additional changes on correctness, security, and test reliability.
- Defer stylistic refactors unless they reduce concrete maintenance risk.
- Treat shim modernization as a separate tracked task, because loader changes affect many tests.
