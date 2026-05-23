#!/usr/bin/env python3

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
INDEXER_MODULE_PATH = SRC / "ollama_librarian" / "indexer.py"

_original_name = __name__
_original_file = __file__
globals()["__name__"] = "ollama_librarian.indexer"
globals()["__file__"] = str(INDEXER_MODULE_PATH)
exec(compile(INDEXER_MODULE_PATH.read_text(encoding="utf-8"),
     str(INDEXER_MODULE_PATH), "exec"), globals(), globals())
globals()["__name__"] = _original_name
globals()["__file__"] = _original_file


if __name__ == "__main__":
    raise SystemExit(main())
