#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WEB_MODULE_PATH = SRC / "ollama_librarian" / "web.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_original_name = __name__
_original_file = __file__
globals()["__name__"] = "ollama_librarian.web"
globals()["__file__"] = str(WEB_MODULE_PATH)
exec(compile(WEB_MODULE_PATH.read_text(encoding="utf-8"),
     str(WEB_MODULE_PATH), "exec"), globals(), globals())
globals()["__name__"] = _original_name
globals()["__file__"] = _original_file


if __name__ == "__main__":
    raise SystemExit(main())
