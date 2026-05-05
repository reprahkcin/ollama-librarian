#!/usr/bin/env python3

import json
import mimetypes
import os
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HOST = os.environ.get("OLLAMA_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("OLLAMA_WEB_PORT", "8088"))
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
API_KEY = os.environ.get("OLLAMA_WEB_API_KEY", "")
ALLOW_INSECURE_BIND = os.environ.get("OLLAMA_WEB_ALLOW_INSECURE_BIND", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MAX_BODY_BYTES = max(1024, int(os.environ.get(
    "OLLAMA_WEB_MAX_BODY_BYTES", "1048576")))
HISTORY_PATH = os.path.expanduser(
    os.environ.get(
        "OLLAMA_WEB_HISTORY_PATH",
        "~/Library/Application Support/home-network-setup/ollama-web-chat-history.json",
    )
)
HISTORY_LOCK = threading.Lock()
PDF_LOCK = threading.Lock()
STASH_LOCK = threading.Lock()

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ASSET_ROOT = SCRIPT_DIR / "assets"


def resolve_default_pdf_source() -> str:
    candidates = [
        "/Volumes/shared/LLM Library",
        "/Volumes/shared/Doomsday School",
    ]
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(candidates[0])


def resolve_default_stash_path() -> str:
    local_default = "~/Library/Application Support/home-network-setup/ollama-response-stash.json"
    candidates = [
        local_default,
        "/Volumes/shared/LLM Library/ollama-response-stash.json",
        "/Volumes/shared/Doomsday School/ollama-response-stash.json",
        "/Volumes/shared/ollama-response-stash.json",
    ]

    # Prefer an already-existing stash file to preserve continuity.
    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded):
            return expanded

    # Otherwise default to local-first to avoid NAS mount dependency.
    return os.path.expanduser(local_default)


PDF_RAG_SCRIPT = os.path.expanduser(
    os.environ.get("OLLAMA_WEB_PDF_RAG_SCRIPT", str(
        SCRIPT_DIR / "pdf_library_rag.py"))
)
PDF_RAG_PYTHON = os.path.expanduser(
    os.environ.get("OLLAMA_WEB_PDF_RAG_PYTHON",
                   str(REPO_ROOT / ".venv/bin/python"))
)
PDF_SOURCE = os.path.expanduser(
    os.environ.get("OLLAMA_WEB_PDF_SOURCE", resolve_default_pdf_source())
)
PDF_INDEX_DB = os.path.expanduser(
    os.environ.get(
        "OLLAMA_WEB_PDF_INDEX_DB",
        "~/Library/Application Support/home-network-setup/pdf-rag.sqlite",
    )
)
PDF_EMBED_MODEL = os.environ.get(
    "OLLAMA_WEB_PDF_EMBED_MODEL", "nomic-embed-text")
PDF_TOP_K = int(os.environ.get("OLLAMA_WEB_PDF_TOP_K", "6"))
PDF_OCR_ON_SYNC = os.environ.get("OLLAMA_WEB_PDF_OCR_ON_SYNC", "1").strip().lower() not in {
    "0", "false", "no", "off"
}
PDF_OCR_LANG = os.environ.get("OLLAMA_WEB_PDF_OCR_LANG", "eng")
PDF_OCR_JOBS = max(1, int(os.environ.get("OLLAMA_WEB_PDF_OCR_JOBS", "2")))
PDF_OCR_TIMEOUT = max(
    60, int(os.environ.get("OLLAMA_WEB_PDF_OCR_TIMEOUT", "1800"))
)
STASH_PATH = os.path.expanduser(
    os.environ.get(
        "OLLAMA_WEB_STASH_PATH",
        resolve_default_stash_path(),
    )
)

PDF_INDEX_STATE = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
}


def run_pdf_rag(extra_args, timeout=600):
    cmd = [
        PDF_RAG_PYTHON,
        PDF_RAG_SCRIPT,
        "--ollama-base",
        OLLAMA_BASE,
        "--embed-model",
        PDF_EMBED_MODEL,
        "--index-db",
        PDF_INDEX_DB,
    ] + list(extra_args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"Command failed: {' '.join(cmd)}")
    return out


def get_pdf_status():
    status = {
        "ok": True,
        "index_exists": False,
        "documents": 0,
        "chunks": 0,
        "last_indexed_at": None,
    }
    try:
        raw = run_pdf_rag(["status"], timeout=45)
        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            status.update(parsed)
    except Exception as exc:
        status = {"ok": False, "error": str(exc)}

    with PDF_LOCK:
        state = dict(PDF_INDEX_STATE)
    status["index_job"] = state
    status["source_path"] = PDF_SOURCE
    return status


def _index_worker():
    with PDF_LOCK:
        PDF_INDEX_STATE["running"] = True
        PDF_INDEX_STATE["last_started_at"] = int(time.time())
        PDF_INDEX_STATE["last_error"] = None
    try:
        index_args = ["index", "--source",
                      PDF_SOURCE, "--prune", "--json-summary"]
        if PDF_OCR_ON_SYNC:
            index_args.extend([
                "--ocr-missing",
                "--ocr-lang",
                PDF_OCR_LANG,
                "--ocr-jobs",
                str(PDF_OCR_JOBS),
                "--ocr-timeout",
                str(PDF_OCR_TIMEOUT),
            ])
            raw = run_pdf_rag(
                index_args,
                timeout=7200,
            )
            parsed = json.loads(raw) if raw else {"ok": True}
            with PDF_LOCK:
                PDF_INDEX_STATE["last_result"] = parsed
    except Exception as exc:
        with PDF_LOCK:
            PDF_INDEX_STATE["last_error"] = str(exc)
    finally:
        with PDF_LOCK:
            PDF_INDEX_STATE["running"] = False
            PDF_INDEX_STATE["last_finished_at"] = int(time.time())


def start_pdf_index_job():
    with PDF_LOCK:
        if PDF_INDEX_STATE["running"]:
            return False
    t = threading.Thread(target=_index_worker, daemon=True)
    t.start()
    return True


def ask_pdf_library(
    query: str,
    model: str,
    top_k: int,
    deepen: bool = False,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
):
    args = [
        "ask",
        "--query",
        query,
        "--top-k",
        str(top_k),
        "--answer-model",
        model,
        "--json-output",
    ]
    if deepen:
        args.append("--deepen")
    for path in include_paths or []:
        if isinstance(path, str) and path.strip():
            args.extend(["--include-path", path.strip()])
    for path in exclude_paths or []:
        if isinstance(path, str) and path.strip():
            args.extend(["--exclude-path", path.strip()])

    raw = run_pdf_rag(args, timeout=600)
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise RuntimeError("Unexpected PDF ask response")
    return parsed


def append_stash_entry(entry: dict):
    with STASH_LOCK:
        entries = _read_stash_entries_unlocked()
        entries.append(entry)
        _write_stash_entries_unlocked(entries)
        return {"ok": True, "count": len(entries), "stash_path": STASH_PATH}


def _ensure_stash_parent_dir() -> None:
    parent = os.path.dirname(STASH_PATH)
    if not parent:
        raise RuntimeError("Invalid stash path configuration")
    if not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def _read_stash_entries_unlocked() -> list:
    _ensure_stash_parent_dir()
    if not os.path.exists(STASH_PATH):
        return []

    with open(STASH_PATH, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []

    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
        return parsed["entries"]
    raise RuntimeError(
        f"Unexpected stash file format at {STASH_PATH}; expected list or dict with entries"
    )


def _write_stash_entries_unlocked(entries: list) -> None:
    _ensure_stash_parent_dir()
    tmp_path = f"{STASH_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=True, indent=2)
    os.replace(tmp_path, STASH_PATH)


def list_stash_entries(limit: int = 200) -> dict:
    with STASH_LOCK:
        entries = _read_stash_entries_unlocked()

    indexed = []
    for idx, entry in enumerate(entries):
        if isinstance(entry, dict):
            item = dict(entry)
            item["stash_id"] = idx
            indexed.append(item)

    indexed.reverse()
    if limit > 0:
        indexed = indexed[:limit]

    return {
        "ok": True,
        "count": len(entries),
        "stash_path": STASH_PATH,
        "entries": indexed,
    }


def delete_stash_entry(stash_id: int) -> dict:
    with STASH_LOCK:
        entries = _read_stash_entries_unlocked()
        if stash_id < 0 or stash_id >= len(entries):
            raise RuntimeError("stash entry not found")
        del entries[stash_id]
        _write_stash_entries_unlocked(entries)
        return {"ok": True, "count": len(entries), "stash_path": STASH_PATH}


def clear_stash_entries() -> dict:
    with STASH_LOCK:
        _write_stash_entries_unlocked([])
    return {"ok": True, "count": 0, "stash_path": STASH_PATH}


def list_library_docs() -> dict:
    index_db = os.path.expanduser(PDF_INDEX_DB)
    if not os.path.exists(index_db):
        return {"ok": True, "documents": [], "groups": [], "count": 0}

    conn = sqlite3.connect(index_db)
    try:
        rows = conn.execute(
            "SELECT path, pages_indexed, chunks_indexed FROM documents ORDER BY path"
        ).fetchall()
    finally:
        conn.close()

    source_root = os.path.realpath(os.path.expanduser(PDF_SOURCE))
    docs = []
    groups: dict[str, int] = {}
    for path, pages, chunks in rows:
        path_str = str(path)
        real_path = os.path.realpath(os.path.expanduser(path_str))

        if real_path.startswith(source_root + os.sep):
            rel = os.path.relpath(real_path, source_root)
        else:
            rel = os.path.basename(path_str)

        top = rel.split(os.sep)[0] if rel else "(unknown)"
        groups[top] = groups.get(top, 0) + 1

        docs.append({
            "path": path_str,
            "rel_path": rel,
            "top_group": top,
            "pages": int(pages or 0),
            "chunks": int(chunks or 0),
        })

    group_list = [{"name": name, "count": count}
                  for name, count in sorted(groups.items())]
    return {
        "ok": True,
        "count": len(docs),
        "source_path": PDF_SOURCE,
        "documents": docs,
        "groups": group_list,
    }


def _ensure_history_file():
    parent = os.path.dirname(HISTORY_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"messages": [], "instructions": ""}, f)


def load_state():
    with HISTORY_LOCK:
        _ensure_history_file()
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        instructions = data.get("instructions", "")
        if not isinstance(instructions, str):
            instructions = ""
        return {"messages": messages, "instructions": instructions}


def save_state(state):
    with HISTORY_LOCK:
        _ensure_history_file()
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=True)


def load_history():
    state = load_state()
    return {"messages": state.get("messages", [])}


def save_history(messages):
    state = load_state()
    state["messages"] = messages
    save_state(state)


def append_history(message):
    state = load_state()
    messages = state.get("messages", [])
    messages.append(message)
    state["messages"] = messages
    save_state(state)


def load_instructions():
    state = load_state()
    return {"instructions": state.get("instructions", "")}


def save_instructions(instructions):
    state = load_state()
    state["instructions"] = instructions
    save_state(state)


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Home LLM Chat</title>
  <link rel="stylesheet" href="/assets/katex/katex.min.css" />
  <script defer src="/assets/katex/katex.min.js"></script>
  <script defer src="/assets/katex/contrib/auto-render.min.js"></script>
  <style>
    :root {
      --bg-a: #111827;
      --bg-b: #0f172a;
      --surface: #111827;
      --surface-soft: #1f2937;
      --ink: #e5e7eb;
      --muted: #94a3b8;
      --primary: #0d9488;
      --primary-2: #0284c7;
      --accent: #f59e0b;
      --border: #334155;
      --user-msg: #134e4a;
      --assistant-msg: #1e293b;
      --danger: #ef4444;
      --ok: #22c55e;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif;
      background: radial-gradient(circle at 15% 15%, #1e293b, transparent 42%),
                  radial-gradient(circle at 85% 80%, #0b1120, transparent 48%),
                  linear-gradient(160deg, var(--bg-b), #020617);
    }
    .shell {
      width: min(1080px, 100% - 1.25rem);
      margin: 1rem auto;
      display: grid;
      grid-template-columns: 280px 1fr;
      gap: 0.9rem;
      align-items: stretch;
      animation: fade-in 320ms ease-out;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 14px 36px rgba(2, 6, 23, 0.45);
    }
    .sidebar {
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    .title {
      margin: 0;
      font-size: 1.1rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }
    .meta {
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.35;
      word-break: break-word;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      width: fit-content;
      padding: 0.35rem 0.55rem;
      border: 1px solid var(--border);
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
      background: var(--surface-soft);
    }
    .dot {
      width: 0.6rem;
      height: 0.6rem;
      border-radius: 50%;
      background: #94a3b8;
    }
    .dot.ok {
      background: var(--ok);
    }
    .dot.err {
      background: var(--danger);
    }
    label {
      font-size: 0.8rem;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.07em;
    }
    select, textarea, button {
      width: 100%;
      font: inherit;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.65rem 0.75rem;
      background: #0b1220;
      color: var(--ink);
    }
    button {
      cursor: pointer;
      font-weight: 700;
      border: none;
      transition: transform 120ms ease, filter 120ms ease;
    }
    button:hover {
      transform: translateY(-1px);
      filter: brightness(0.98);
    }
    button:disabled {
      opacity: 0.65;
      transform: none;
      cursor: not-allowed;
    }
    .btn-primary {
      background: linear-gradient(120deg, var(--primary), var(--primary-2));
      color: #fff;
    }
    .btn-soft {
      border: 1px solid var(--border);
      background: var(--surface-soft);
      color: var(--ink);
    }
    .chat {
      padding: 0.8rem;
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 78vh;
    }
    .chat-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      margin: 0.2rem 0.35rem 0.7rem;
    }
    .chat-head h2 {
      margin: 0;
      font-size: 1rem;
      font-weight: 700;
    }
    .chat-head .hint {
      font-size: 0.78rem;
      color: var(--muted);
      text-align: right;
    }
    .messages {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 0.9rem;
      background: linear-gradient(180deg, #0b1220, #111827);
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .msg {
      max-width: 85%;
      padding: 0.65rem 0.75rem;
      border-radius: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-wrap: break-word;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
      animation: rise 140ms ease-out;
    }
    .msg-text {
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .md {
      white-space: normal;
    }
    .md p {
      margin: 0.45rem 0;
    }
    .md h1, .md h2, .md h3 {
      margin: 0.55rem 0 0.35rem;
      line-height: 1.25;
    }
    .md h1 { font-size: 1.05rem; }
    .md h2 { font-size: 1rem; }
    .md h3 { font-size: 0.95rem; }
    .md ul, .md ol {
      margin: 0.35rem 0 0.5rem 1.2rem;
      padding: 0;
    }
    .md li {
      margin: 0.15rem 0;
    }
    .md pre {
      margin: 0.5rem 0;
      padding: 0.55rem 0.7rem;
      border: 1px solid #334155;
      border-radius: 10px;
      background: #020617;
      color: #dbeafe;
      overflow-x: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.83rem;
      white-space: pre;
    }
    .md code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.84em;
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 6px;
      padding: 0.08rem 0.3rem;
    }
    .md pre code {
      background: transparent;
      border: none;
      padding: 0;
    }
    .md a {
      color: #7dd3fc;
      text-decoration: underline;
    }
    .md .math-block {
      margin: 0.45rem 0;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 0.1rem;
    }
    .md .katex-display {
      margin: 0.5rem 0;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 0.1rem;
    }
    .msg.user {
      align-self: flex-end;
      background: var(--user-msg);
      border: 1px solid #0f766e;
    }
    .msg.assistant {
      align-self: flex-start;
      background: var(--assistant-msg);
      border: 1px solid #334155;
    }
    .msg-tools {
      margin-top: 0.45rem;
      display: flex;
      justify-content: flex-end;
    }
    .copy-btn {
      width: auto;
      min-width: 64px;
      border: 1px solid #475569;
      border-radius: 999px;
      padding: 0.2rem 0.55rem;
      font-size: 0.72rem;
      font-weight: 700;
      background: #1e293b;
      color: #e2e8f0;
    }
    .stash-btn {
      width: auto;
      min-width: 64px;
      border: 1px solid #0f766e;
      border-radius: 999px;
      padding: 0.2rem 0.55rem;
      font-size: 0.72rem;
      font-weight: 700;
      background: #134e4a;
      color: #ccfbf1;
      margin-right: 0.35rem;
    }
    .copy-btn:hover {
      filter: brightness(0.95);
    }
    .stash-btn:hover {
      filter: brightness(0.95);
    }
    .msg.system {
      align-self: center;
      background: #fff7ed;
      border: 1px solid #fed7aa;
      color: #7c2d12;
      font-size: 0.9rem;
    }
    .composer {
      margin-top: 0.7rem;
      display: grid;
      gap: 0.55rem;
    }
    textarea {
      min-height: 92px;
      resize: vertical;
    }
    .composer-row {
      display: flex;
      gap: 0.5rem;
      align-items: center;
    }
    .composer-row button {
      width: auto;
      min-width: 110px;
    }
    .subtle {
      font-size: 0.78rem;
      color: var(--muted);
      margin-left: auto;
    }
    .checkrow {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.86rem;
      color: var(--ink);
    }
    .checkrow input[type="checkbox"] {
      width: 1rem;
      height: 1rem;
      margin: 0;
      accent-color: var(--primary);
    }
    .tiny {
      font-size: 0.76rem;
      color: var(--muted);
      line-height: 1.3;
      white-space: pre-wrap;
    }
    .stash-modal {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 23, 0.72);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
      z-index: 50;
    }
    .stash-hidden {
      display: none;
    }
    .stash-card {
      width: min(920px, 100%);
      max-height: 88vh;
      overflow: hidden;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: #0b1220;
      display: grid;
      grid-template-rows: auto auto 1fr;
    }
    .stash-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      padding: 0.8rem 0.9rem;
      border-bottom: 1px solid var(--border);
    }
    .stash-head h3 {
      margin: 0;
      font-size: 0.96rem;
    }
    .stash-actions {
      display: flex;
      gap: 0.45rem;
    }
    .stash-actions button {
      width: auto;
      min-width: 84px;
      padding: 0.45rem 0.6rem;
    }
    .stash-meta {
      color: var(--muted);
      font-size: 0.76rem;
      padding: 0.55rem 0.9rem;
      border-bottom: 1px solid var(--border);
      white-space: pre-wrap;
    }
    .stash-list {
      overflow: auto;
      padding: 0.75rem;
      display: grid;
      gap: 0.55rem;
    }
    .stash-item {
      border: 1px solid #334155;
      background: #0f172a;
      border-radius: 10px;
      padding: 0.6rem;
      display: grid;
      gap: 0.45rem;
    }
    .stash-item-meta {
      color: #94a3b8;
      font-size: 0.75rem;
    }
    .stash-item-text {
      font-size: 0.86rem;
      line-height: 1.4;
      white-space: pre-wrap;
      max-height: 13rem;
      overflow: auto;
    }
    .stash-item-actions {
      display: flex;
      justify-content: flex-end;
      gap: 0.4rem;
    }
    .stash-item-actions button {
      width: auto;
      min-width: 70px;
      padding: 0.3rem 0.55rem;
      font-size: 0.74rem;
    }
    .docs-modal {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 23, 0.72);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
      z-index: 51;
    }
    .docs-hidden {
      display: none;
    }
    .docs-card {
      width: min(980px, 100%);
      max-height: 88vh;
      overflow: hidden;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: #0b1220;
      display: grid;
      grid-template-rows: auto auto auto 1fr;
    }
    .docs-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      padding: 0.8rem 0.9rem;
      border-bottom: 1px solid var(--border);
    }
    .docs-head h3 {
      margin: 0;
      font-size: 0.96rem;
    }
    .docs-actions {
      display: flex;
      gap: 0.45rem;
    }
    .docs-actions button {
      width: auto;
      min-width: 76px;
      padding: 0.4rem 0.58rem;
    }
    .docs-filter {
      padding: 0.6rem 0.9rem;
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 0.5rem;
    }
    .docs-filter-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.6rem;
      flex-wrap: wrap;
    }
    .docs-filter input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.5rem 0.65rem;
      background: #111827;
      color: var(--ink);
    }
    .docs-checkrow {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      font-size: 0.75rem;
      color: var(--muted);
    }
    .docs-checkrow input[type="checkbox"] {
      margin: 0;
      accent-color: var(--primary);
    }
    .docs-meta {
      color: var(--muted);
      font-size: 0.76rem;
      padding: 0.55rem 0.9rem;
      border-bottom: 1px solid var(--border);
      white-space: pre-wrap;
    }
    .docs-groups {
      padding: 0.5rem 0.9rem;
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 0.35rem;
      max-height: 9.5rem;
      overflow: auto;
      background: #0a1325;
    }
    .docs-group-row {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 0.45rem;
      font-size: 0.75rem;
      color: var(--muted);
    }
    .docs-group-label {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .docs-group-actions {
      display: inline-flex;
      gap: 0.3rem;
    }
    .docs-group-actions button {
      width: auto;
      min-width: 34px;
      padding: 0.2rem 0.38rem;
      font-size: 0.7rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #0f172a;
      color: var(--ink);
    }
    .docs-list {
      overflow: auto;
      padding: 0.7rem;
      display: grid;
      gap: 0.35rem;
    }
    .docs-item {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 0.55rem;
      align-items: start;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 0.45rem 0.55rem;
      background: #0f172a;
    }
    .docs-item input[type="checkbox"] {
      margin-top: 0.2rem;
      accent-color: var(--primary);
    }
    .docs-item-path {
      font-size: 0.83rem;
      line-height: 1.35;
      word-break: break-word;
    }
    .docs-item-meta {
      color: var(--muted);
      font-size: 0.74rem;
      margin-top: 0.15rem;
    }
    @media (max-width: 860px) {
      .shell {
        grid-template-columns: 1fr;
      }
      .chat {
        min-height: 68vh;
      }
      .msg {
        max-width: 92%;
      }
      .chat-head {
        flex-direction: column;
        align-items: flex-start;
      }
      .chat-head .hint {
        text-align: left;
      }
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes fade-in {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <main class="shell">
    <aside class="panel sidebar">
      <h1 class="title">Home LLM Console</h1>
      <div class="meta">Endpoint: %OLLAMA_BASE%</div>
      <div id="status" class="status">
        <span id="statusDot" class="dot"></span>
        <span id="statusText">Checking service...</span>
      </div>

      <label for="model">Model</label>
      <select id="model"></select>

      <label for="instructions">Running Instructions</label>
      <textarea id="instructions" placeholder="Example: Be concise. Use bullet points. Ask clarifying questions if uncertain."></textarea>
      <button id="saveInstructions" class="btn-soft" type="button">Save Instructions</button>

      <label>PDF Library</label>
      <label class="checkrow" for="usePdfLibrary" title="Use retrieval from your indexed PDF library instead of plain model-only responses.">
        <input id="usePdfLibrary" type="checkbox" title="Use retrieval from your indexed PDF library instead of plain model-only responses." />
        Use PDF-grounded answers
      </label>
      <label class="checkrow" for="deepStudy" title="Expands retrieval depth and context for more thorough, citation-heavy answers. Slower but usually more complete.">
        <input id="deepStudy" type="checkbox" title="Expands retrieval depth and context for more thorough, citation-heavy answers. Slower but usually more complete." />
        Deep Study Mode
      </label>
      <button id="syncPdfLibrary" class="btn-soft" type="button" title="Indexes new or changed PDFs. OCR fallback is used for scanned/text-only images when available.">Sync New PDFs</button>
      <div id="pdfStatus" class="tiny">PDF index: checking...</div>

      <button id="refresh" class="btn-soft" type="button">Refresh Models</button>
      <button id="openLibraryDocs" class="btn-soft" type="button">Library Docs</button>
      <button id="openStash" class="btn-soft" type="button">View Stash</button>
      <button id="clear" class="btn-soft" type="button">Clear Conversation</button>
    </aside>

    <section class="panel chat">
      <header class="chat-head">
        <h2>Chat</h2>
        <div class="hint">Press Enter to send, Shift+Enter for newline</div>
      </header>

      <div id="messages" class="messages"></div>

      <div class="composer">
        <textarea id="prompt" placeholder="Ask the model something useful..."></textarea>
        <div class="composer-row">
          <button id="send" class="btn-primary" type="button">Send</button>
          <button id="cancel" class="btn-soft" type="button" disabled>Cancel</button>
          <button id="studyBrief" class="btn-soft" type="button" title="Creates a structured brief from your PDF library with citations and suggested reading order.">Study Brief</button>
          <div id="meta" class="subtle">Ready</div>
        </div>
      </div>
    </section>
  </main>

  <div id="stashModal" class="stash-modal stash-hidden">
    <div class="stash-card">
      <div class="stash-head">
        <h3>Stashed Snippets</h3>
        <div class="stash-actions">
          <button id="stashReload" class="btn-soft" type="button">Reload</button>
          <button id="stashClearAll" class="btn-soft" type="button">Clear All</button>
          <button id="stashClose" class="btn-soft" type="button">Close</button>
        </div>
      </div>
      <div id="stashMeta" class="stash-meta">Loading...</div>
      <div id="stashList" class="stash-list"></div>
    </div>
  </div>

  <div id="docsModal" class="docs-modal docs-hidden">
    <div class="docs-card">
      <div class="docs-head">
        <h3>Library Documents</h3>
        <div class="docs-actions">
          <button id="docsReload" class="btn-soft" type="button">Reload</button>
          <button id="docsSelectAll" class="btn-soft" type="button">All</button>
          <button id="docsSelectNone" class="btn-soft" type="button">None</button>
          <button id="docsClose" class="btn-soft" type="button">Close</button>
        </div>
      </div>
      <div class="docs-filter">
        <input id="docsSearch" type="text" placeholder="Filter by filename or folder..." />
        <div class="docs-filter-row">
          <label class="docs-checkrow" for="docsIncludeOnly" title="When enabled, only checked documents are searched. Unchecked docs are ignored.">
            <input id="docsIncludeOnly" type="checkbox" title="When enabled, only checked documents are searched. Unchecked docs are ignored." />
            Include-only mode (send only checked docs)
          </label>
        </div>
      </div>
      <div id="docsMeta" class="docs-meta">Loading...</div>
      <div id="docsGroups" class="docs-groups"></div>
      <div id="docsList" class="docs-list"></div>
    </div>
  </div>

  <script>
    const API_KEY_REQUIRED = %API_KEY_REQUIRED%;
    const API_KEY_STORAGE_KEY = 'ollama_web_api_key_v1';
    let apiKey = localStorage.getItem(API_KEY_STORAGE_KEY) || '';

    if (API_KEY_REQUIRED && !apiKey) {
      const entered = window.prompt('Enter API key for Ollama Librarian');
      if (typeof entered === 'string' && entered.trim()) {
        apiKey = entered.trim();
        localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
      }
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      const reqInit = Object.assign({}, init);
      const headers = new Headers(init.headers || {});
      if (apiKey) {
        headers.set('X-API-Key', apiKey);
      }
      reqInit.headers = headers;
      return nativeFetch(input, reqInit);
    };

    const modelEl = document.getElementById('model');
    const promptEl = document.getElementById('prompt');
    const sendEl = document.getElementById('send');
    const cancelEl = document.getElementById('cancel');
    const refreshEl = document.getElementById('refresh');
    const clearEl = document.getElementById('clear');
    const openLibraryDocsEl = document.getElementById('openLibraryDocs');
    const openStashEl = document.getElementById('openStash');
    const instructionsEl = document.getElementById('instructions');
    const saveInstructionsEl = document.getElementById('saveInstructions');
    const usePdfLibraryEl = document.getElementById('usePdfLibrary');
    const deepStudyEl = document.getElementById('deepStudy');
    const syncPdfLibraryEl = document.getElementById('syncPdfLibrary');
    const studyBriefEl = document.getElementById('studyBrief');
    const pdfStatusEl = document.getElementById('pdfStatus');
    const messagesEl = document.getElementById('messages');
    const statusDotEl = document.getElementById('statusDot');
    const statusTextEl = document.getElementById('statusText');
    const metaEl = document.getElementById('meta');
    const stashModalEl = document.getElementById('stashModal');
    const stashListEl = document.getElementById('stashList');
    const stashMetaEl = document.getElementById('stashMeta');
    const stashReloadEl = document.getElementById('stashReload');
    const stashClearAllEl = document.getElementById('stashClearAll');
    const stashCloseEl = document.getElementById('stashClose');
    const docsModalEl = document.getElementById('docsModal');
    const docsListEl = document.getElementById('docsList');
    const docsMetaEl = document.getElementById('docsMeta');
    const docsGroupsEl = document.getElementById('docsGroups');
    const docsReloadEl = document.getElementById('docsReload');
    const docsSelectAllEl = document.getElementById('docsSelectAll');
    const docsSelectNoneEl = document.getElementById('docsSelectNone');
    const docsCloseEl = document.getElementById('docsClose');
    const docsSearchEl = document.getElementById('docsSearch');
    const docsIncludeOnlyEl = document.getElementById('docsIncludeOnly');
    let lastUserPrompt = '';
    let libraryDocs = [];
    let libraryGroups = [];
    let excludedDocPaths = new Set();
    let includeOnlyMode = false;
    let activeRequestController = null;
    let pendingPromptText = '';

    const DOC_FILTER_STORAGE_KEY = 'ollama_web_excluded_docs_v1';
    const DOC_FILTER_MODE_STORAGE_KEY = 'ollama_web_doc_filter_mode_v1';

    function setStatus(state, text) {
      statusDotEl.classList.remove('ok', 'err');
      if (state === 'ok') statusDotEl.classList.add('ok');
      if (state === 'err') statusDotEl.classList.add('err');
      statusTextEl.textContent = text;
    }

    function isoNow() {
      return new Date().toISOString();
    }

    async function persistMessage(role, text, ts) {
      await fetch('/api/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role, text, ts })
      });
    }

    function escapeHtml(text) {
      return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function renderInlineMarkdown(text) {
      let out = text;
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
      out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      out = out.replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/api\/pdf\/file\?)[^\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return out;
    }

    function normalizeMathDelimiters(text) {
      // LLM output often mixes single and double-escaped delimiters (e.g. \\( ... \\)).
      // Normalize them so KaTeX can consistently detect inline/display math boundaries.
      const bs = String.fromCharCode(92);
      let out = text
        .split(bs + bs + '(').join(bs + '(')
        .split(bs + bs + ')').join(bs + ')')
        .split(bs + bs + '[').join(bs + '[')
        .split(bs + bs + ']').join(bs + ']');

      // Downgrade obvious prose accidentally wrapped as \( ... \) back to plain parentheses.
      // Example: \(the perpendicular distance between these sides\) should not be math.
      const open = bs + '(';
      const close = bs + ')';
      const rebuilt = [];
      let i = 0;

      while (i < out.length) {
        const start = out.indexOf(open, i);
        if (start === -1) {
          rebuilt.push(out.slice(i));
          break;
        }

        const end = out.indexOf(close, start + open.length);
        if (end === -1) {
          rebuilt.push(out.slice(i));
          break;
        }

        rebuilt.push(out.slice(i, start));
        const inner = out.slice(start + open.length, end);
        const content = inner.trim();
        if (!content) {
          rebuilt.push(open + inner + close);
          i = end + close.length;
          continue;
        }

        const hasLetters = /[A-Za-z]/.test(content);
        const hasSpaces = /\s/.test(content);
        const hasMathSignal = /[0-9=+\-*/^_<>]|\\[A-Za-z]+|[{}\[\]]/.test(content);
        const isLikelyProse = hasLetters && hasSpaces && !hasMathSignal;
        rebuilt.push(isLikelyProse ? '(' + inner + ')' : open + inner + close);
        i = end + close.length;
      }

      out = rebuilt.join('');

      return out;
    }

    function renderMathIn(element) {
      if (!element || typeof window.renderMathInElement !== 'function') {
        return;
      }
      try {
        const bs = String.fromCharCode(92);
        window.renderMathInElement(element, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: bs + '[', right: bs + ']', display: true },
            { left: '$', right: '$', display: false },
            { left: bs + '(', right: bs + ')', display: false }
          ],
          throwOnError: false
        });
      } catch (_) {
        // Leave original text untouched if math rendering fails.
      }
    }

    function renderMarkdown(text) {
      const normalized = normalizeMathDelimiters(text);
      const escaped = escapeHtml(normalized);

      // Preserve fenced code blocks before other transformations.
      const codeBlocks = [];
      let withPlaceholders = escaped.replace(/```([\s\S]*?)```/g, (_, code) => {
        const token = `@@CODEBLOCK_${codeBlocks.length}@@`;
        codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
        return token;
      });

      // Preserve multi-line block math so markdown line splitting does not break delimiters.
      const mathBlocks = [];
      withPlaceholders = withPlaceholders.replace(/\$\$([\s\S]*?)\$\$/g, (_, expr) => {
        const token = `@@MATHBLOCK_${mathBlocks.length}@@`;
        mathBlocks.push(`<div class="math-block">$$${expr.trim()}$$</div>`);
        return token;
      });

      const lines = withPlaceholders.split('\\n');
      const html = [];
      let inUl = false;
      let inOl = false;

      const closeLists = () => {
        if (inUl) {
          html.push('</ul>');
          inUl = false;
        }
        if (inOl) {
          html.push('</ol>');
          inOl = false;
        }
      };

      for (const raw of lines) {
        const line = raw.trimEnd();
        const t = line.trim();

        if (!t) {
          closeLists();
          continue;
        }

        const headingMatch = t.match(/^(#{1,6})\s+(.*)$/);
        if (headingMatch) {
          closeLists();
          const level = headingMatch[1].length;
          const content = headingMatch[2];
          html.push(`<h${level}>${renderInlineMarkdown(content)}</h${level}>`);
          continue;
        }

        if (/^[-*]\s+/.test(t)) {
          if (!inUl) {
            closeLists();
            html.push('<ul>');
            inUl = true;
          }
          html.push(`<li>${renderInlineMarkdown(t.replace(/^[-*]\s+/, ''))}</li>`);
          continue;
        }

        if (/^\d+\.\s+/.test(t)) {
          if (!inOl) {
            closeLists();
            html.push('<ol>');
            inOl = true;
          }
          html.push(`<li>${renderInlineMarkdown(t.replace(/^\d+\.\s+/, ''))}</li>`);
          continue;
        }

        closeLists();
        html.push(`<p>${renderInlineMarkdown(t)}</p>`);
      }

      closeLists();
      let joined = html.join('');
      joined = joined.replace(/@@CODEBLOCK_(\d+)@@/g, (_, idx) => codeBlocks[Number(idx)] || '');
      joined = joined.replace(/@@MATHBLOCK_(\d+)@@/g, (_, idx) => mathBlocks[Number(idx)] || '');
      return joined;
    }

    async function loadInstructions() {
      try {
        const res = await fetch('/api/instructions');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        instructionsEl.value = typeof data.instructions === 'string' ? data.instructions : '';
      } catch (err) {
        addMessage('system', `Failed to load instructions: ${err.message}`);
      }
    }

    async function saveInstructions() {
      const instructions = instructionsEl.value.trim();
      try {
        const res = await fetch('/api/instructions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instructions })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        metaEl.textContent = instructions ? 'Instructions saved' : 'Instructions cleared';
      } catch (err) {
        addMessage('system', `Failed to save instructions: ${err.message}`);
      }
    }

    function addMessage(role, text, opts = {}) {
      const showAssistantTools = opts.showAssistantTools !== false;
      const el = document.createElement('div');
      el.className = `msg ${role}`;

      const textEl = document.createElement('div');
      textEl.className = role === 'assistant' ? 'msg-text md' : 'msg-text';
      if (role === 'assistant') {
        textEl.innerHTML = renderMarkdown(text);
        renderMathIn(textEl);
      } else {
        textEl.textContent = text;
      }
      el.appendChild(textEl);

      if (role === 'assistant' && showAssistantTools) {
        const tools = document.createElement('div');
        tools.className = 'msg-tools';

        const stashBtn = document.createElement('button');
        stashBtn.className = 'stash-btn';
        stashBtn.type = 'button';
        stashBtn.textContent = 'Stash';
        stashBtn.addEventListener('click', async () => {
          stashBtn.disabled = true;
          stashBtn.textContent = 'Saving...';
          try {
            const result = await stashResponse(text);
            metaEl.textContent = `Stashed response (${result.count || '?'})`;
            stashBtn.textContent = 'Stashed';
            setTimeout(() => {
              stashBtn.textContent = 'Stash';
              stashBtn.disabled = false;
            }, 1200);
          } catch (err) {
            metaEl.textContent = `Stash failed: ${err.message}`;
            stashBtn.textContent = 'Stash';
            stashBtn.disabled = false;
          }
        });

        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.type = 'button';
        copyBtn.textContent = 'Copy';
        copyBtn.addEventListener('click', async () => {
          const ok = await copyText(text);
          if (ok) {
            metaEl.textContent = 'Copied response';
            copyBtn.textContent = 'Copied';
            setTimeout(() => {
              copyBtn.textContent = 'Copy';
            }, 1100);
          } else {
            metaEl.textContent = 'Copy failed';
          }
        });

        tools.appendChild(stashBtn);
        tools.appendChild(copyBtn);
        el.appendChild(tools);
      }

      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function copyText(text) {
      if (navigator.clipboard && window.isSecureContext) {
        try {
          await navigator.clipboard.writeText(text);
          return true;
        } catch (_) {
          // Fall through to legacy copy path.
        }
      }

      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.left = '-1000px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
      } catch (_) {
        return false;
      }
    }

    async function addMessageAndStore(role, text) {
      const ts = isoNow();
      addMessage(role, text);
      try {
        await persistMessage(role, text, ts);
      } catch (_) {
        // Keep UI responsive if history persistence fails.
      }
    }

    async function stashResponse(text, extra = {}) {
      const payload = {
        text,
        model: modelEl.value || '',
        use_pdf_library: !!usePdfLibraryEl.checked,
        ts: isoNow(),
        ...extra
      };

      const res = await fetch('/api/stash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      let data = {};
      try {
        data = await res.json();
      } catch (_) {
        data = {};
      }

      if (!res.ok) {
        const detail = data.error || `HTTP ${res.status}`;
        throw new Error(detail);
      }

      return data;
    }

    function persistDocFilterState() {
      try {
        localStorage.setItem(DOC_FILTER_STORAGE_KEY, JSON.stringify(Array.from(excludedDocPaths)));
      } catch (_) {
        // Ignore storage errors.
      }
    }

    function loadDocFilterState() {
      try {
        const raw = localStorage.getItem(DOC_FILTER_STORAGE_KEY);
        if (!raw) return new Set();
        const arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return new Set();
        return new Set(arr.filter((x) => typeof x === 'string'));
      } catch (_) {
        return new Set();
      }
    }

    function persistDocFilterModeState() {
      try {
        localStorage.setItem(DOC_FILTER_MODE_STORAGE_KEY, includeOnlyMode ? 'include-only' : 'exclude-only');
      } catch (_) {
        // Ignore storage errors.
      }
    }

    function loadDocFilterModeState() {
      try {
        const raw = localStorage.getItem(DOC_FILTER_MODE_STORAGE_KEY);
        return raw === 'include-only';
      } catch (_) {
        return false;
      }
    }

    function getIncludedDocPaths() {
      return libraryDocs
        .filter((doc) => !excludedDocPaths.has(doc.path))
        .map((doc) => doc.path);
    }

    function hasIndexedChunks(doc) {
      return Number(doc && doc.chunks ? doc.chunks : 0) > 0;
    }

    function sanitizeIncludeOnlySelection() {
      if (!includeOnlyMode) return;
      for (const doc of libraryDocs) {
        if (!hasIndexedChunks(doc)) {
          excludedDocPaths.add(doc.path);
        }
      }
    }

    function buildDocSelectionError(filters) {
      if (filters.includedCount <= 0) {
        return 'All documents are excluded. Open Library Docs and include at least one document.';
      }
      if (filters.includedChunkCount <= 0) {
        const sample = filters.zeroChunkIncluded.slice(0, 3).join(', ');
        const suffix = filters.zeroChunkIncluded.length > 3 ? ', ...' : '';
        return `Selected document filter has no indexed text chunks (${sample}${suffix}). Include at least one document with chunks > 0, disable Include-only mode, or OCR/re-index that PDF.`;
      }
      return '';
    }

    function buildDocFiltersForRequest() {
      const includedDocs = libraryDocs.filter((doc) => !excludedDocPaths.has(doc.path));
      const included = includedDocs.map((doc) => doc.path);
      const includedChunkCount = includedDocs.filter((doc) => hasIndexedChunks(doc)).length;
      const zeroChunkIncluded = includedDocs
        .filter((doc) => !hasIndexedChunks(doc))
        .map((doc) => doc.rel_path || pathBase(doc.path));
      if (includeOnlyMode) {
        return {
          includePaths: included,
          excludePaths: [],
          includedCount: included.length,
          includedChunkCount,
          zeroChunkIncluded,
        };
      }
      return {
        includePaths: [],
        excludePaths: Array.from(excludedDocPaths),
        includedCount: included.length,
        includedChunkCount,
        zeroChunkIncluded,
      };
    }

    function setGroupIncluded(groupName, shouldInclude) {
      for (const doc of libraryDocs) {
        if ((doc.top_group || '(unknown)') !== groupName) continue;
        if (shouldInclude) {
          excludedDocPaths.delete(doc.path);
        } else {
          excludedDocPaths.add(doc.path);
        }
      }
      persistDocFilterState();
      renderLibraryDocs();
    }

    function renderLibraryDocs() {
      const q = (docsSearchEl.value || '').trim().toLowerCase();
      const filtered = q
        ? libraryDocs.filter((doc) => (doc.rel_path || doc.path || '').toLowerCase().includes(q))
        : libraryDocs;

      const includedCount = Math.max(0, libraryDocs.length - excludedDocPaths.size);
      const groupSummary = libraryGroups.slice(0, 8).map((g) => `${g.name}: ${g.count}`).join(', ');
      docsMetaEl.textContent =
        `Docs: ${libraryDocs.length} | Included: ${includedCount} | Excluded: ${excludedDocPaths.size}` +
        (groupSummary ? `\nTop groups: ${groupSummary}` : '');

      docsGroupsEl.innerHTML = '';
      const groupsForUi = libraryGroups.length
        ? libraryGroups
        : [{ name: '(all)', count: libraryDocs.length }];
      for (const group of groupsForUi) {
        const groupName = group.name || '(unknown)';
        const docsInGroup = libraryDocs.filter((d) => (d.top_group || '(unknown)') === groupName);
        const groupIncluded = docsInGroup.filter((d) => !excludedDocPaths.has(d.path)).length;

        const row = document.createElement('div');
        row.className = 'docs-group-row';

        const label = document.createElement('div');
        label.className = 'docs-group-label';
        label.textContent = `${groupName}: ${groupIncluded}/${docsInGroup.length} included`;

        const actions = document.createElement('div');
        actions.className = 'docs-group-actions';
        const inBtn = document.createElement('button');
        inBtn.type = 'button';
        inBtn.className = 'btn-soft';
        inBtn.textContent = 'In';
        inBtn.addEventListener('click', () => setGroupIncluded(groupName, true));

        const outBtn = document.createElement('button');
        outBtn.type = 'button';
        outBtn.className = 'btn-soft';
        outBtn.textContent = 'Out';
        outBtn.addEventListener('click', () => setGroupIncluded(groupName, false));

        actions.appendChild(inBtn);
        actions.appendChild(outBtn);
        row.appendChild(label);
        row.appendChild(actions);
        docsGroupsEl.appendChild(row);
      }

      docsListEl.innerHTML = '';
      if (!filtered.length) {
        const empty = document.createElement('div');
        empty.className = 'docs-item-meta';
        empty.textContent = 'No matching documents.';
        docsListEl.appendChild(empty);
        return;
      }

      for (const doc of filtered) {
        const item = document.createElement('label');
        item.className = 'docs-item';

        const box = document.createElement('input');
        const chunkCount = Number(doc.chunks || 0);
        const noChunks = chunkCount <= 0;
        box.type = 'checkbox';
        box.checked = !excludedDocPaths.has(doc.path);
        if (includeOnlyMode && noChunks) {
          box.checked = false;
          box.disabled = true;
          box.title = 'No indexed text chunks. Re-index with OCR text extraction, or disable Include-only mode.';
        }
        box.addEventListener('change', () => {
          if (box.checked) {
            excludedDocPaths.delete(doc.path);
          } else {
            excludedDocPaths.add(doc.path);
          }
          persistDocFilterState();
          renderLibraryDocs();
        });

        const body = document.createElement('div');
        const pathLine = document.createElement('div');
        pathLine.className = 'docs-item-path';
        pathLine.textContent = doc.rel_path || doc.path || '[unknown]';
        const metaLine = document.createElement('div');
        metaLine.className = 'docs-item-meta';
        metaLine.textContent = `${doc.top_group || '(unknown)'} | pages=${doc.pages || 0} | chunks=${doc.chunks || 0}` + (noChunks ? ' | no indexed text' : '');

        body.appendChild(pathLine);
        body.appendChild(metaLine);

        item.appendChild(box);
        item.appendChild(body);
        docsListEl.appendChild(item);
      }
    }

    async function loadLibraryDocs() {
      docsMetaEl.textContent = 'Loading...';
      docsListEl.innerHTML = '';
      const res = await fetch('/api/library/docs');
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

      libraryDocs = Array.isArray(data.documents) ? data.documents : [];
      libraryGroups = Array.isArray(data.groups) ? data.groups : [];

      const saved = loadDocFilterState();
      const validPaths = new Set(libraryDocs.map((d) => d.path));
      excludedDocPaths = new Set(Array.from(saved).filter((p) => validPaths.has(p)));
      includeOnlyMode = loadDocFilterModeState();
      sanitizeIncludeOnlySelection();
      docsIncludeOnlyEl.checked = includeOnlyMode;
      persistDocFilterState();
      persistDocFilterModeState();

      renderLibraryDocs();
    }

    async function openLibraryDocsModal() {
      docsModalEl.classList.remove('docs-hidden');
      try {
        await loadLibraryDocs();
      } catch (err) {
        docsMetaEl.textContent = `Failed to load library docs: ${err.message}`;
      }
    }

    function closeLibraryDocsModal() {
      docsModalEl.classList.add('docs-hidden');
    }

    function formatStashTime(entry) {
      if (entry.saved_at_iso) return entry.saved_at_iso;
      if (entry.saved_at) {
        const d = new Date(Number(entry.saved_at) * 1000);
        return d.toISOString();
      }
      return '[unknown time]';
    }

    function renderStashEntries(payload) {
      const entries = Array.isArray(payload.entries) ? payload.entries : [];
      stashListEl.innerHTML = '';

      stashMetaEl.textContent = `Count: ${payload.count || 0}\nPath: ${payload.stash_path || ''}`;

      if (!entries.length) {
        const empty = document.createElement('div');
        empty.className = 'stash-item-meta';
        empty.textContent = 'No stashed snippets yet.';
        stashListEl.appendChild(empty);
        return;
      }

      for (const entry of entries) {
        const wrap = document.createElement('div');
        wrap.className = 'stash-item';

        const top = document.createElement('div');
        top.className = 'stash-item-meta';
        const entryType = entry.entry_type || 'response';
        const model = entry.model || 'unknown-model';
        top.textContent = `${formatStashTime(entry)} | ${entryType} | ${model}`;

        const rawText = typeof entry.text === 'string' ? entry.text : '';
        const text = document.createElement('div');
        text.className = 'stash-item-text md';
        text.innerHTML = renderMarkdown(rawText);
        renderMathIn(text);

        const actions = document.createElement('div');
        actions.className = 'stash-item-actions';

        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn-soft';
        copyBtn.type = 'button';
        copyBtn.textContent = 'Copy';
        copyBtn.addEventListener('click', async () => {
          const ok = await copyText(rawText);
          metaEl.textContent = ok ? 'Copied stashed snippet' : 'Copy failed';
        });

        const delBtn = document.createElement('button');
        delBtn.className = 'btn-soft';
        delBtn.type = 'button';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', async () => {
          if (!Number.isInteger(entry.stash_id)) return;
          delBtn.disabled = true;
          try {
            const res = await fetch(`/api/stash?id=${entry.stash_id}`, { method: 'DELETE' });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            await loadStashEntries();
            metaEl.textContent = 'Deleted stash entry';
          } catch (err) {
            metaEl.textContent = `Delete failed: ${err.message}`;
            delBtn.disabled = false;
          }
        });

        actions.appendChild(copyBtn);
        actions.appendChild(delBtn);

        wrap.appendChild(top);
        wrap.appendChild(text);
        wrap.appendChild(actions);
        stashListEl.appendChild(wrap);
      }
    }

    async function loadStashEntries() {
      stashMetaEl.textContent = 'Loading...';
      stashListEl.innerHTML = '';
      const res = await fetch('/api/stash?limit=200');
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      renderStashEntries(data);
    }

    async function openStashModal() {
      stashModalEl.classList.remove('stash-hidden');
      try {
        await loadStashEntries();
      } catch (err) {
        stashMetaEl.textContent = `Failed to load stash: ${err.message}`;
      }
    }

    function closeStashModal() {
      stashModalEl.classList.add('stash-hidden');
    }

    function pathBase(p) {
      if (!p) return 'document';
      const parts = String(p).split('/');
      return parts[parts.length - 1] || 'document';
    }

    function isPdfSourcePath(p) {
      return /\.pdf$/i.test(String(p || '').trim());
    }

    function strictEncodeURIComponent(value) {
      return encodeURIComponent(String(value)).replace(/[!'()*]/g, (ch) => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`);
    }

    function compactSourceLabel(p) {
      const base = pathBase(p);
      const maxLen = 56;
      if (base.length <= maxLen) return base;
      return `${base.slice(0, maxLen - 1)}...`;
    }

    function formatPdfSources(sources) {
      return sources
        .slice(0, 8)
        .map((s) => {
          const loc = Number(s.page || s.location || 1);
          const label = `${compactSourceLabel(s.path)} loc.${loc}`;
          if (!isPdfSourcePath(s.path)) {
            return `- ${label} (score=${Number(s.score).toFixed(4)})`;
          }
          const encodedPath = strictEncodeURIComponent(s.path || '');
          const openUrl = `/api/pdf/file?path=${encodedPath}#page=${loc}`;
          return `- [${label}](${openUrl}) (score=${Number(s.score).toFixed(4)})`;
        })
        .join(String.fromCharCode(10));
    }

    async function createStudyBrief() {
      const query = promptEl.value.trim() || lastUserPrompt;
      if (!query) {
        addMessage('system', 'Enter a topic first (or ask a question) to create a study brief.');
        return;
      }
      if (!usePdfLibraryEl.checked) {
        addMessage('system', 'Enable PDF-grounded answers to create a study brief.');
        return;
      }

      setBusy(true);
      metaEl.textContent = 'Building study brief...';
      try {
        const model = modelEl.value;
        const filters = buildDocFiltersForRequest();
        if (libraryDocs.length) {
          const selectionError = buildDocSelectionError(filters);
          if (selectionError) {
            throw new Error(selectionError);
          }
        }
        const res = await fetch('/api/pdf/brief', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query,
            model,
            top_k: deepStudyEl.checked ? 20 : 14,
            include_paths: filters.includePaths,
            exclude_paths: filters.excludePaths,
          })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        let answer = data.answer || '[no brief field]';
        if (Array.isArray(data.sources) && data.sources.length) {
          answer += `

Sources:
${formatPdfSources(data.sources)}`;
        }

        await addMessageAndStore('assistant', answer);
        await stashResponse(answer, {
          entry_type: 'study_brief',
          query,
          sources: Array.isArray(data.sources) ? data.sources : []
        });
        metaEl.textContent = 'Study brief ready (and stashed)';
      } catch (err) {
        addMessage('system', `Study brief failed: ${err.message}`);
        metaEl.textContent = 'Study brief failed';
      } finally {
        setBusy(false);
      }
    }

    function formatEpoch(ts) {
      if (!ts) return 'never';
      const d = new Date(ts * 1000);
      return d.toLocaleString();
    }

    async function refreshPdfStatus() {
      try {
        const res = await fetch('/api/pdf/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const job = data.index_job || {};
        const docs = data.documents ?? 0;
        const chunks = data.chunks ?? 0;
        const idx = formatEpoch(data.last_indexed_at);
        const running = job.running ? 'running' : 'idle';
        pdfStatusEl.textContent = `PDF index: ${running}\nDocs: ${docs} | Chunks: ${chunks}\nLast indexed: ${idx}`;
      } catch (err) {
        pdfStatusEl.textContent = `PDF index status error: ${err.message}`;
      }
    }

    async function syncPdfLibrary() {
      syncPdfLibraryEl.disabled = true;
      syncPdfLibraryEl.textContent = 'Syncing...';
      try {
        const res = await fetch('/api/pdf/index', { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        metaEl.textContent = 'PDF index sync started';
      } catch (err) {
        addMessage('system', `Failed to start PDF sync: ${err.message}`);
      } finally {
        syncPdfLibraryEl.disabled = false;
        syncPdfLibraryEl.textContent = 'Sync New PDFs';
        refreshPdfStatus();
      }
    }

    function setBusy(isBusy) {
      sendEl.disabled = isBusy;
      cancelEl.disabled = !isBusy;
      refreshEl.disabled = isBusy;
      modelEl.disabled = isBusy;
      instructionsEl.disabled = isBusy;
      saveInstructionsEl.disabled = isBusy;
      usePdfLibraryEl.disabled = isBusy;
      deepStudyEl.disabled = isBusy;
      syncPdfLibraryEl.disabled = isBusy;
      openLibraryDocsEl.disabled = isBusy;
      openStashEl.disabled = isBusy;
      studyBriefEl.disabled = isBusy;
      clearEl.disabled = isBusy;
      sendEl.textContent = isBusy ? 'Thinking...' : 'Send';
    }

    function cancelPromptRequest() {
      if (!activeRequestController) return;
      cancelEl.disabled = true;
      metaEl.textContent = 'Cancelling...';
      activeRequestController.abort();
    }

    async function loadModels() {
      modelEl.innerHTML = '';
      setStatus('', 'Checking service...');
      try {
        const res = await fetch('/api/tags');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const models = (data.models || []).map((m) => m.name);

        if (!models.length) {
          const opt = document.createElement('option');
          opt.textContent = 'No models found';
          opt.value = '';
          modelEl.appendChild(opt);
          setStatus('err', 'No models installed');
          return;
        }

        for (const name of models) {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          modelEl.appendChild(opt);
        }
        const preferred = models.includes('qwen2.5:14b') ? 'qwen2.5:14b' : models[0];
        modelEl.value = preferred;
        setStatus('ok', `Online (${models.length} models)`);
      } catch (err) {
        setStatus('err', 'Service unreachable');
        addMessage('system', `Failed to load models: ${err.message}`);
      }
    }

    async function loadHistory() {
      messagesEl.innerHTML = '';
      try {
        const res = await fetch('/api/history');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const items = Array.isArray(data.messages) ? data.messages : [];
        if (!items.length) {
          addMessage('assistant', 'Shared history is empty. Start the conversation.');
          return;
        }
        for (const item of items) {
          const role = ['user', 'assistant', 'system'].includes(item.role) ? item.role : 'system';
          const text = typeof item.text === 'string' ? item.text : '';
          if (text) addMessage(role, text);
        }
      } catch (err) {
        addMessage('system', `Failed to load shared history: ${err.message}`);
      }
    }

    async function sendPrompt() {
      if (activeRequestController) return;

      const prompt = promptEl.value.trim();
      const model = modelEl.value;
      const instructions = instructionsEl.value.trim();
      const usePdfLibrary = usePdfLibraryEl.checked;
      const deepStudy = deepStudyEl.checked;
      if (!prompt) return;
      if (!model) {
        addMessage('system', 'No model is available. Install a model and refresh.');
        return;
      }

      lastUserPrompt = prompt;
      pendingPromptText = prompt;

      await addMessageAndStore('user', prompt);
      promptEl.value = '';
      setBusy(true);
      metaEl.textContent = `Model: ${model}`;

      const start = performance.now();
      const requestController = new AbortController();
      activeRequestController = requestController;
      try {
        let answer = '';
        if (usePdfLibrary) {
          const filters = buildDocFiltersForRequest();
          if (libraryDocs.length) {
            const selectionError = buildDocSelectionError(filters);
            if (selectionError) {
              throw new Error(selectionError);
            }
          }
          const res = await fetch('/api/pdf/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: requestController.signal,
            body: JSON.stringify({
              query: prompt,
              model,
              top_k: deepStudy ? 16 : 8,
              deepen: deepStudy,
              include_paths: filters.includePaths,
              exclude_paths: filters.excludePaths,
            })
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          if (data.ok === false && data.error) {
            throw new Error(data.error);
          }
          answer = data.answer || '[no answer field]';
          if (Array.isArray(data.sources) && data.sources.length) {
            answer += `

Sources:
${formatPdfSources(data.sources)}`;
          }
        } else {
          const res = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: requestController.signal,
            body: JSON.stringify({ model, prompt, stream: false, system: instructions || undefined, keep_alive: '60s' })
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          answer = data.response || '[no response field]';
        }

        await addMessageAndStore('assistant', answer);

        const elapsedMs = Math.round(performance.now() - start);
        metaEl.textContent = `Model: ${model}${usePdfLibrary ? ' + PDF' : ''} | ${elapsedMs} ms`;
      } catch (err) {
        if (err && err.name === 'AbortError') {
          // Keep the canceled query in the input so users can quickly adjust and resend.
          if (!promptEl.value.trim()) {
            promptEl.value = pendingPromptText;
          }
          promptEl.focus();
          addMessage('system', 'Request canceled.');
          metaEl.textContent = 'Request canceled';
        } else {
          addMessage('system', `Request failed: ${err.message}`);
          metaEl.textContent = 'Request failed';
        }
      } finally {
        if (activeRequestController === requestController) {
          activeRequestController = null;
        }
        pendingPromptText = '';
        setBusy(false);
      }
    }

    refreshEl.addEventListener('click', loadModels);
    openLibraryDocsEl.addEventListener('click', openLibraryDocsModal);
    docsCloseEl.addEventListener('click', closeLibraryDocsModal);
    docsReloadEl.addEventListener('click', async () => {
      try {
        await loadLibraryDocs();
      } catch (err) {
        docsMetaEl.textContent = `Failed to load library docs: ${err.message}`;
      }
    });
    docsSelectAllEl.addEventListener('click', () => {
      excludedDocPaths = new Set();
      sanitizeIncludeOnlySelection();
      persistDocFilterState();
      renderLibraryDocs();
    });
    docsSelectNoneEl.addEventListener('click', () => {
      excludedDocPaths = new Set(libraryDocs.map((d) => d.path));
      persistDocFilterState();
      renderLibraryDocs();
    });
    docsIncludeOnlyEl.addEventListener('change', () => {
      includeOnlyMode = !!docsIncludeOnlyEl.checked;
      sanitizeIncludeOnlySelection();
      persistDocFilterModeState();
      persistDocFilterState();
      renderLibraryDocs();
    });
    docsSearchEl.addEventListener('input', renderLibraryDocs);
    docsModalEl.addEventListener('click', (e) => {
      if (e.target === docsModalEl) closeLibraryDocsModal();
    });
    openStashEl.addEventListener('click', openStashModal);
    stashCloseEl.addEventListener('click', closeStashModal);
    stashReloadEl.addEventListener('click', async () => {
      try {
        await loadStashEntries();
      } catch (err) {
        stashMetaEl.textContent = `Failed to load stash: ${err.message}`;
      }
    });
    stashClearAllEl.addEventListener('click', async () => {
      if (!confirm('Delete all stashed snippets?')) return;
      try {
        const res = await fetch('/api/stash?all=1', { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        await loadStashEntries();
        metaEl.textContent = 'Cleared stash';
      } catch (err) {
        stashMetaEl.textContent = `Failed to clear stash: ${err.message}`;
      }
    });
    stashModalEl.addEventListener('click', (e) => {
      if (e.target === stashModalEl) closeStashModal();
    });
    saveInstructionsEl.addEventListener('click', saveInstructions);
    syncPdfLibraryEl.addEventListener('click', syncPdfLibrary);
    studyBriefEl.addEventListener('click', createStudyBrief);
    cancelEl.addEventListener('click', cancelPromptRequest);
    clearEl.addEventListener('click', async () => {
      try {
        await fetch('/api/history', { method: 'DELETE' });
      } catch (_) {
        // If delete fails, still clear local view for usability.
      }
      messagesEl.innerHTML = '';
      addMessage('assistant', 'Shared history cleared.', { showAssistantTools: false });
      metaEl.textContent = 'Ready';
      promptEl.focus();
    });
    sendEl.addEventListener('click', sendPrompt);
    promptEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendPrompt();
      }
    });

    loadHistory();
    loadInstructions();
    loadModels();
    refreshPdfStatus();
    setInterval(refreshPdfStatus, 15000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_security_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send(self, code, body, content_type="text/plain; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(code)
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, code, payload, content_type, extra_headers=None):
        self.send_response(code)
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _is_authorized(self):
        if not API_KEY:
            return True
        direct = self.headers.get("X-API-Key", "")
        if direct == API_KEY:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:].strip() == API_KEY:
            return True
        return False

    def _require_api_auth_for_route(self, route_path):
        if not route_path.startswith("/api/"):
            return True
        if self._is_authorized():
            return True
        self._send(
            401,
            json.dumps({"error": "Unauthorized"}, ensure_ascii=True),
            "application/json; charset=utf-8",
        )
        return False

    def _read_json_body(self):
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._send(
                400,
                json.dumps({"error": "Invalid Content-Length"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return None

        if length < 0:
            self._send(
                400,
                json.dumps({"error": "Invalid Content-Length"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return None

        if length > MAX_BODY_BYTES:
            self._send(
                413,
                json.dumps({"error": "Request body too large"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return None

        data = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            self._send(
                400,
                json.dumps({"error": "Invalid JSON"}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return None

    def do_GET(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path

        if not self._require_api_auth_for_route(route_path):
            return

        if self.path == "/":
            html = HTML.replace("%OLLAMA_BASE%", OLLAMA_BASE)
            html = html.replace("%API_KEY_REQUIRED%",
                                "true" if bool(API_KEY) else "false")
            return self._send(200, html, "text/html; charset=utf-8")

        if route_path.startswith("/assets/"):
            rel_asset = unquote(route_path[len("/assets/"):]).lstrip("/")
            candidate = (ASSET_ROOT / rel_asset).resolve()
            asset_root_resolved = ASSET_ROOT.resolve()
            if (
                not str(candidate).startswith(
                    str(asset_root_resolved) + os.sep)
                or not candidate.is_file()
            ):
                return self._send(404, "Not found")

            content_type, _ = mimetypes.guess_type(str(candidate))
            if not content_type:
                content_type = "application/octet-stream"
            with open(candidate, "rb") as f:
                payload = f.read()
            return self._send_bytes(
                200,
                payload,
                content_type,
                {"Cache-Control": "public, max-age=31536000, immutable"},
            )

        if route_path == "/api/tags":
            return self._proxy("GET", "/api/tags", None)

        if route_path == "/api/history":
            return self._send(
                200,
                json.dumps(load_history(), ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/instructions":
            return self._send(
                200,
                json.dumps(load_instructions(), ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/library/docs":
            try:
                payload = list_library_docs()
                return self._send(
                    200,
                    json.dumps(payload, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    500,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        if route_path == "/api/stash":
            params = parse_qs(parsed_url.query)
            limit_raw = params.get("limit", ["200"])[0]
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 200
            try:
                payload = list_stash_entries(limit=max(0, limit))
                return self._send(
                    200,
                    json.dumps(payload, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    500,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        if route_path == "/api/pdf/status":
            return self._send(
                200,
                json.dumps(get_pdf_status(), ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/pdf/file":
            params = parse_qs(parsed_url.query)
            pdf_path = params.get("path", [""])[0]
            if not isinstance(pdf_path, str) or not pdf_path.strip():
                return self._send(
                    400,
                    json.dumps({"error": "path is required"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            resolved_root = os.path.realpath(os.path.expanduser(PDF_SOURCE))
            resolved_path = os.path.realpath(os.path.expanduser(pdf_path))

            if not resolved_path.startswith(resolved_root + os.sep):
                return self._send(
                    403,
                    json.dumps(
                        {"error": "path is outside configured PDF library"}, ensure_ascii=True
                    ),
                    "application/json; charset=utf-8",
                )

            if not os.path.isfile(resolved_path) or not resolved_path.lower().endswith(".pdf"):
                return self._send(
                    404,
                    json.dumps({"error": "PDF not found"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            with open(resolved_path, "rb") as f:
                payload = f.read()

            filename = os.path.basename(resolved_path)
            return self._send_bytes(
                200,
                payload,
                "application/pdf",
                {
                    "Content-Disposition": f'inline; filename="{filename}"',
                    "Cache-Control": "no-cache",
                },
            )

        return self._send(404, "Not found")

    def do_POST(self):
        if not self._require_api_auth_for_route(self.path):
            return

        if self.path == "/api/generate":
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                return self._send(
                    400,
                    json.dumps({"error": "Invalid Content-Length"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            if length < 0:
                return self._send(
                    400,
                    json.dumps({"error": "Invalid Content-Length"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            if length > MAX_BODY_BYTES:
                return self._send(
                    413,
                    json.dumps({"error": "Request body too large"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            data = self.rfile.read(length) if length > 0 else b"{}"
            return self._proxy("POST", "/api/generate", data)

        if self.path == "/api/history":
            payload = self._read_json_body()
            if payload is None:
                return

            role = payload.get("role")
            text = payload.get("text")
            ts = payload.get("ts")
            if role not in {"user", "assistant", "system"} or not isinstance(text, str):
                return self._send(
                    400,
                    json.dumps({"error": "role and text are required"}),
                    "application/json; charset=utf-8",
                )

            append_history({"role": role, "text": text, "ts": ts})
            return self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")

        if self.path == "/api/instructions":
            payload = self._read_json_body()
            if payload is None:
                return

            instructions = payload.get("instructions", "")
            if not isinstance(instructions, str):
                return self._send(
                    400,
                    json.dumps({"error": "instructions must be a string"}),
                    "application/json; charset=utf-8",
                )

            save_instructions(instructions)
            return self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")

        if self.path == "/api/pdf/index":
            started = start_pdf_index_job()
            return self._send(
                200,
                json.dumps({"ok": True, "started": started},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if self.path == "/api/pdf/ask":
            payload = self._read_json_body()
            if payload is None:
                return

            query = payload.get("query", "")
            model = payload.get("model", "qwen2.5:14b")
            top_k = int(payload.get("top_k", PDF_TOP_K))
            deepen = bool(payload.get("deepen", False))
            include_paths = payload.get("include_paths", [])
            exclude_paths = payload.get("exclude_paths", [])
            if not isinstance(include_paths, list):
                include_paths = []
            if not isinstance(exclude_paths, list):
                exclude_paths = []

            if not isinstance(query, str) or not query.strip():
                return self._send(
                    400,
                    json.dumps({"error": "query is required"}),
                    "application/json; charset=utf-8",
                )

            try:
                result = ask_pdf_library(
                    query.strip(),
                    str(model),
                    top_k,
                    deepen=deepen,
                    include_paths=[str(x)
                                   for x in include_paths if isinstance(x, str)],
                    exclude_paths=[str(x)
                                   for x in exclude_paths if isinstance(x, str)],
                )
                return self._send(
                    200,
                    json.dumps(result, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    502,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        if self.path == "/api/pdf/brief":
            payload = self._read_json_body()
            if payload is None:
                return

            query = payload.get("query", "")
            model = payload.get("model", "qwen2.5:14b")
            top_k = int(payload.get("top_k", 14))
            include_paths = payload.get("include_paths", [])
            exclude_paths = payload.get("exclude_paths", [])
            if not isinstance(include_paths, list):
                include_paths = []
            if not isinstance(exclude_paths, list):
                exclude_paths = []
            if not isinstance(query, str) or not query.strip():
                return self._send(
                    400,
                    json.dumps({"error": "query is required"}),
                    "application/json; charset=utf-8",
                )

            brief_prompt = (
                "Create a concise study brief for the topic below using the library context. "
                "Include sections: Overview, Key Concepts, Formulas/Definitions (if relevant), "
                "and Suggested Reading Order with citations.\\n\\n"
                f"Topic: {query.strip()}"
            )

            try:
                result = ask_pdf_library(
                    brief_prompt,
                    str(model),
                    top_k,
                    deepen=True,
                    include_paths=[str(x)
                                   for x in include_paths if isinstance(x, str)],
                    exclude_paths=[str(x)
                                   for x in exclude_paths if isinstance(x, str)],
                )
                result["brief_for"] = query.strip()
                return self._send(
                    200,
                    json.dumps(result, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    502,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        if self.path == "/api/stash":
            payload = self._read_json_body()
            if payload is None:
                return

            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return self._send(
                    400,
                    json.dumps({"error": "text is required"}),
                    "application/json; charset=utf-8",
                )

            entry = {
                "saved_at": int(time.time()),
                "saved_at_iso": payload.get("ts") if isinstance(payload.get("ts"), str) else None,
                "model": payload.get("model") if isinstance(payload.get("model"), str) else "",
                "use_pdf_library": bool(payload.get("use_pdf_library", False)),
                "entry_type": payload.get("entry_type") if isinstance(payload.get("entry_type"), str) else "response",
                "query": payload.get("query") if isinstance(payload.get("query"), str) else "",
                "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
                "text": text.strip(),
            }

            try:
                result = append_stash_entry(entry)
                return self._send(
                    200,
                    json.dumps(result, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    502,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        return self._send(404, "Not found")

    def do_DELETE(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path

        if not self._require_api_auth_for_route(route_path):
            return

        if route_path == "/api/history":
            save_history([])
            return self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")

        if route_path == "/api/stash":
            params = parse_qs(parsed_url.query)
            if params.get("all", [""])[0] == "1":
                try:
                    result = clear_stash_entries()
                    return self._send(
                        200,
                        json.dumps(result, ensure_ascii=True),
                        "application/json; charset=utf-8",
                    )
                except Exception as exc:
                    return self._send(
                        500,
                        json.dumps({"error": str(exc)}, ensure_ascii=True),
                        "application/json; charset=utf-8",
                    )

            stash_id_raw = params.get("id", [None])[0]
            if stash_id_raw is None:
                return self._send(
                    400,
                    json.dumps(
                        {"error": "id is required (or set all=1)"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            try:
                stash_id = int(stash_id_raw)
                result = delete_stash_entry(stash_id)
                return self._send(
                    200,
                    json.dumps(result, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    404,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

        return self._send(404, "Not found")

    def _proxy(self, method, path, data):
        req = Request(
            f"{OLLAMA_BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(req, timeout=90) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return self._send(resp.status, body, "application/json; charset=utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return self._send(exc.code, detail, "application/json; charset=utf-8")
        except URLError as exc:
            return self._send(502, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")


def main():
    is_loopback = HOST in {"127.0.0.1", "localhost", "::1"}
    if not is_loopback and not ALLOW_INSECURE_BIND and not API_KEY:
        raise SystemExit(
            "Refusing non-loopback bind without auth. Set OLLAMA_WEB_API_KEY or "
            "OLLAMA_WEB_ALLOW_INSECURE_BIND=1 to override."
        )

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving UI at http://{HOST}:{PORT} (proxying {OLLAMA_BASE})")
    server.serve_forever()


if __name__ == "__main__":
    main()
