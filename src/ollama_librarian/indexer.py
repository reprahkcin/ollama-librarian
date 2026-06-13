#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import json
import math
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ollama_librarian.hardware import (
    classify_resource_pressure,
    detect_hardware_profile,
    recommend_model,
    safety_policy_for_pressure,
)

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from ebooklib import ITEM_DOCUMENT, epub
except Exception:
    ITEM_DOCUMENT = None
    epub = None


SUPPORTED_DOC_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".epub"}
NOISY_AUTHOR_TOKENS = {
    "unknown",
    "author",
    "pdfdrive",
    "pdfdrive.com",
    "www.pdfdrive.com",
    "z-lib",
    "z-lib.org",
    "zlibrary",
    "z-library",
}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_title_candidate(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""

    text = text.replace("_", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"(?i)\b(?:www\.)?pdfdrive(?:\.com)?\b", " ", text)
    text = re.sub(
        r"(?i)\b(?:z[- ]?library|z-lib\.org|libgen(?:\.[a-z]+)?)\b", " ", text)
    text = re.sub(r"\s*\(\s*pdf\s*\)\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*[_\-]+", "", text)
    text = re.sub(r"^\s*\d+(?:\.\d+)*(?:\)|\.|:|-)?\s+", "", text)
    text = re.sub(r"\s+-\s+pdf\s*(?:drive(?:\.com)?)?\s*$",
                  "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -_.")


def looks_like_author_name(value: str) -> bool:
    text = normalize_text(value)
    if not text:
        return False
    if re.search(r"\d", text):
        return False
    words = text.replace(",", " ").split()
    if len(words) < 1 or len(words) > 6:
        return False
    return True


def infer_author_and_title_from_path(doc_path: Path) -> tuple[str, str]:
    stem = clean_title_candidate(doc_path.stem)
    if not stem:
        return "", "Untitled document"

    by_match = re.match(r"^(.+?)\s+by\s+(.+)$", stem, flags=re.IGNORECASE)
    if by_match:
        title_guess = clean_title_candidate(by_match.group(1))
        author_guess = normalize_text(
            by_match.group(2)).removeprefix("by ").strip()
        if title_guess and looks_like_author_name(author_guess):
            return author_guess, title_guess

    parts = re.split(r"\s+-\s+", stem, maxsplit=1)
    if len(parts) == 2:
        left, right = clean_title_candidate(
            parts[0]), clean_title_candidate(parts[1])
        if left and right and looks_like_author_name(left):
            return left, right

    return "", stem


def title_from_path(doc_path: Path) -> str:
    _, inferred_title = infer_author_and_title_from_path(doc_path)
    return inferred_title or "Untitled document"


def split_authors(raw: str) -> list[str]:
    text = normalize_text(raw)
    if not text:
        return []
    parts = [
        normalize_text(p) for p in re.split(
            r"\s*;\s*|\s+\band\b\s+|\s*&\s*|\s*/\s*",
            text,
            flags=re.IGNORECASE,
        )
    ]
    out: list[str] = []
    seen = set()
    for part in parts:
        if not part:
            continue
        cleaned = normalize_text(re.sub(r"(?i)^by\s+", "", part)).strip(" ,;")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in NOISY_AUTHOR_TOKENS:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
    return out


def extract_year(raw: object) -> str:
    text = normalize_text(raw)
    if not text:
        return ""
    m = re.search(r"(19|20)\d{2}", text)
    return m.group(0) if m else ""


def extract_pdf_document_metadata(doc_path: Path) -> dict:
    inferred_author, inferred_title = infer_author_and_title_from_path(
        doc_path)
    out = {
        "title": inferred_title or title_from_path(doc_path),
        "authors": [inferred_author] if inferred_author else [],
        "year": "",
    }
    if PdfReader is None:
        return out
    try:
        reader = PdfReader(str(doc_path))
        meta = reader.metadata
    except Exception:
        return out

    if not meta:
        return out

    def _safe_meta_attr(name: str) -> object:
        try:
            return getattr(meta, name, None)
        except Exception:
            return None

    title = clean_title_candidate(
        _safe_meta_attr("title") or meta.get("/Title"))
    author_raw = normalize_text(
        _safe_meta_attr("author") or meta.get("/Author"))
    created = normalize_text(
        meta.get("/CreationDate") or _safe_meta_attr("creation_date"))
    modified = normalize_text(
        meta.get("/ModDate") or _safe_meta_attr("modification_date"))

    if title and len(title) >= 3 and title.lower() not in {"untitled", "document"}:
        out["title"] = title
    authors = split_authors(author_raw)
    if authors:
        out["authors"] = authors
    out["year"] = extract_year(created) or extract_year(
        modified) or extract_year(doc_path.stem)
    return out


def extract_epub_document_metadata(doc_path: Path) -> dict:
    inferred_author, inferred_title = infer_author_and_title_from_path(
        doc_path)
    out = {
        "title": inferred_title or title_from_path(doc_path),
        "authors": [inferred_author] if inferred_author else [],
        "year": "",
    }
    if epub is None:
        return out
    try:
        book = epub.read_epub(str(doc_path))
    except Exception:
        return out

    try:
        titles = book.get_metadata("DC", "title")
        if titles and titles[0] and titles[0][0]:
            out["title"] = clean_title_candidate(titles[0][0]) or out["title"]
    except Exception:
        pass

    try:
        creators = book.get_metadata("DC", "creator")
        authors = []
        for item in creators:
            if not item:
                continue
            authors.extend(split_authors(item[0]))
        if authors:
            out["authors"] = authors
    except Exception:
        pass

    try:
        dates = book.get_metadata("DC", "date")
        if dates and dates[0] and dates[0][0]:
            out["year"] = extract_year(dates[0][0])
    except Exception:
        pass

    if not out.get("year"):
        out["year"] = extract_year(doc_path.stem)

    return out


def extract_document_metadata(doc_path: Path) -> dict:
    suffix = doc_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_document_metadata(doc_path)
    if suffix == ".epub":
        return extract_epub_document_metadata(doc_path)
    inferred_author, _ = infer_author_and_title_from_path(doc_path)
    return {
        "title": title_from_path(doc_path),
        "authors": [inferred_author] if inferred_author else [],
        "year": extract_year(doc_path.stem),
    }


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return unescape("".join(self.parts))


def resolve_default_state_dir() -> Path:
    system = platform.system().lower()
    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "ollama-librarian"
    if system == "windows":
        appdata = str(os.environ.get("APPDATA", "")).strip()
        if appdata:
            return Path(os.path.expanduser(appdata)) / "ollama-librarian"
        return Path.home() / "AppData" / "Roaming" / "ollama-librarian"

    xdg_data_home = str(os.environ.get("XDG_DATA_HOME", "")).strip()
    if xdg_data_home:
        return Path(os.path.expanduser(xdg_data_home)) / "ollama-librarian"
    return Path.home() / ".local" / "share" / "ollama-librarian"


def resolve_default_index_db_path() -> str:
    return str(resolve_default_state_dir() / "pdf-rag.sqlite")


def resolve_default_pdf_source() -> str:
    default_candidate = str(Path.home() / "Documents" / "LLM Library")
    candidates = [
        default_candidate,
        str(Path.home() / "pdf_library"),
    ]

    if platform.system().lower() == "darwin":
        candidates.append("/Volumes/shared/LLM Library")

    for candidate in candidates:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return os.path.expanduser(default_candidate)


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = str(env.get(key, str(default))).strip()
    try:
        return int(raw)
    except Exception:
        return default


def _env_bool_true_unless_false(env: Mapping[str, str], key: str, default: str = "1") -> bool:
    return str(env.get(key, default)).strip().lower() not in {
        "0", "false", "no", "off"
    }


@dataclass(frozen=True)
class RagCliConfig:
    ollama_base: str
    embed_model: str
    index_db: str
    source_dir: str
    search_top_k: int
    ask_top_k: int
    ocr_lang: str
    ocr_jobs: int
    ocr_timeout: int
    embed_num_thread: int = 2
    embed_delay_ms: int = 200
    doc_cooldown_seconds: int = 10
    dynamic_throttle: bool = True
    dynamic_target_embed_ms: int = 1400
    dynamic_max_delay_ms: int = 2000
    dynamic_delay_step_ms: int = 50
    dynamic_min_threads: int = 1
    dynamic_max_threads: int = 3
    web_host: str = "127.0.0.1"
    web_port: int = 8088
    ask_answer_timeout: int = 600
    answer_num_thread: int = 0
    answer_keep_alive: str = "60s"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RagCliConfig":
        return cls(
            ollama_base=str(env.get("OLLAMA_BASE_URL",
                            "http://127.0.0.1:11434")),
            embed_model=str(
                env.get("OLLAMA_WEB_PDF_EMBED_MODEL", "nomic-embed-text")),
            index_db=os.path.expanduser(
                str(env.get("OLLAMA_WEB_PDF_INDEX_DB",
                    resolve_default_index_db_path()))
            ),
            source_dir=os.path.expanduser(
                str(env.get("OLLAMA_WEB_PDF_SOURCE", resolve_default_pdf_source()))
            ),
            search_top_k=max(1, _env_int(env, "OLLAMA_WEB_PDF_TOP_K", 6)),
            ask_top_k=max(1, _env_int(env, "OLLAMA_WEB_PDF_TOP_K", 6)),
            ask_answer_timeout=max(30, _env_int(
                env, "OLLAMA_WEB_PDF_ANSWER_TIMEOUT", 600)),
            ocr_lang=str(env.get("OLLAMA_WEB_PDF_OCR_LANG", "eng")),
            ocr_jobs=max(1, _env_int(env, "OLLAMA_WEB_PDF_OCR_JOBS", 2)),
            ocr_timeout=max(60, _env_int(
                env, "OLLAMA_WEB_PDF_OCR_TIMEOUT", 1800)),
            embed_num_thread=max(1, _env_int(
                env, "OLLAMA_WEB_PDF_EMBED_NUM_THREAD", 2)),
            embed_delay_ms=max(0, _env_int(
                env, "OLLAMA_WEB_PDF_EMBED_DELAY_MS", 200)),
            doc_cooldown_seconds=max(0, _env_int(
                env, "OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS", 10)),
            dynamic_throttle=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_PDF_DYNAMIC_THROTTLE", "1"),
            dynamic_target_embed_ms=max(200, _env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS", 1400)),
            dynamic_max_delay_ms=max(0, _env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS", 2000)),
            dynamic_delay_step_ms=max(1, _env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS", 50)),
            dynamic_min_threads=max(1, _env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS", 1)),
            dynamic_max_threads=max(1, _env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS", 3)),
            web_host=str(env.get("OLLAMA_WEB_HOST", "127.0.0.1")).strip(),
            web_port=max(1, _env_int(env, "OLLAMA_WEB_PORT", 8088)),
            answer_num_thread=max(0, _env_int(
                env, "OLLAMA_WEB_ANSWER_NUM_THREAD", 0)),
            answer_keep_alive=str(
                env.get("OLLAMA_WEB_ANSWER_KEEP_ALIVE", "60s")),
        )


RAG_CONFIG = RagCliConfig.from_env(os.environ)


def open_index_db(index_db: Path, writable: bool = False) -> sqlite3.Connection:
    # Give SQLite enough time to wait for transient lock contention.
    conn = sqlite3.connect(str(index_db), timeout=60 if writable else 15)
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA foreign_keys = ON")
    if writable:
        # WAL allows concurrent readers during long-running writes.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def is_pdf_path(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def discover_source_documents(source_root: Path) -> list[Path]:
    docs = []
    for candidate in source_root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in SUPPORTED_DOC_EXTENSIONS:
            docs.append(candidate)
    docs.sort()
    return docs


def strip_html_to_text(html: str) -> str:
    parser = HTMLTextExtractor()
    parser.feed(html)
    return parser.text()


def extract_text_document_pages(doc_path: Path) -> list[tuple[int, str]]:
    raw = doc_path.read_text(encoding="utf-8", errors="replace")
    text = raw.strip()
    if not text:
        return []
    return [(1, text)]


def extract_html_document_pages(doc_path: Path) -> list[tuple[int, str]]:
    raw = doc_path.read_text(encoding="utf-8", errors="replace")
    text = strip_html_to_text(raw).strip()
    if not text:
        return []
    return [(1, text)]


def extract_epub_document_pages(doc_path: Path) -> list[tuple[int, str]]:
    if epub is None or ITEM_DOCUMENT is None:
        raise RuntimeError(
            "EPUB parsing dependency is missing. Install 'ebooklib'.")
    book = epub.read_epub(str(doc_path))
    pages: list[tuple[int, str]] = []
    section_num = 1
    for item in book.get_items():
        if item.get_type() != ITEM_DOCUMENT:
            continue
        content = item.get_content() or b""
        if isinstance(content, bytes):
            html = content.decode("utf-8", errors="replace")
        else:
            html = str(content)
        text = strip_html_to_text(html).strip()
        if not text:
            continue
        pages.append((section_num, text))
        section_num += 1
    return pages


def extract_document_pages(doc_path: Path) -> list[tuple[int, str]]:
    suffix = doc_path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_pages(doc_path)
    if suffix in {".txt", ".md"}:
        return extract_text_document_pages(doc_path)
    if suffix in {".html", ".htm"}:
        return extract_html_document_pages(doc_path)
    if suffix == ".epub":
        return extract_epub_document_pages(doc_path)
    return []


def now_ts() -> int:
    return int(time.time())


def http_post_json(base_url: str, endpoint: str, payload: dict, timeout: int = 180) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{base_url.rstrip('/')}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=max(1, int(timeout))) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}: {exc}") from exc


def embed_text(base_url: str, model: str, text: str, num_thread: int = 3) -> list[float]:
    embed_options = {"num_thread": max(1, int(num_thread))}
    # Newer Ollama endpoint.
    try:
        data = http_post_json(base_url, "/api/embed",
                              {"model": model, "input": text, "options": embed_options})
        if isinstance(data.get("embeddings"), list) and data["embeddings"]:
            first = data["embeddings"][0]
            if isinstance(first, list):
                return [float(v) for v in first]
        if isinstance(data.get("embedding"), list):
            return [float(v) for v in data["embedding"]]
    except RuntimeError:
        pass

    # Backward-compatible endpoint.
    data = http_post_json(base_url, "/api/embeddings",
                          {"model": model, "prompt": text, "options": embed_options})
    if isinstance(data.get("embedding"), list):
        return [float(v) for v in data["embedding"]]
    raise RuntimeError("Unexpected embedding response format from Ollama")


def generate_answer(
    base_url: str,
    model: str,
    prompt: str,
    timeout: int = 180,
    num_thread: int = 0,
    keep_alive: str = "60s",
    format: str | None = None,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": str(keep_alive or "60s"),
    }
    if int(num_thread or 0) > 0:
        payload["options"] = {"num_thread": max(1, int(num_thread))}
    if format:
        payload["format"] = format
    data = http_post_json(
        base_url,
        "/api/generate",
        payload,
        timeout=timeout,
    )
    return str(data.get("response", "")).strip()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]
    step = max(1, chunk_size - overlap)
    chunks = []
    idx = 0
    while idx < len(cleaned):
        piece = cleaned[idx: idx + chunk_size]
        if piece:
            chunks.append(piece)
        if idx + chunk_size >= len(cleaned):
            break
        idx += step
    return chunks


def extract_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    if PdfReader is None:
        raise RuntimeError(
            "PDF parsing dependency is missing. Install 'pypdf'.")
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i, text))
    return pages


def extract_pdf_pages_with_ocr(
    pdf_path: Path,
    ocr_lang: str,
    ocr_jobs: int,
    ocr_timeout: int,
) -> list[tuple[int, str]]:
    with tempfile.TemporaryDirectory(prefix="pdf-rag-ocr-") as tmp_dir:
        out_pdf = Path(tmp_dir) / "ocr-output.pdf"
        cmd = [
            "ocrmypdf",
            "--skip-text",
            "--optimize",
            "0",
            "--jobs",
            str(max(1, int(ocr_jobs))),
        ]
        if isinstance(ocr_lang, str) and ocr_lang.strip():
            cmd.extend(["-l", ocr_lang.strip()])
        cmd.extend([str(pdf_path), str(out_pdf)])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60, int(ocr_timeout)),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                detail or f"ocrmypdf failed with code {proc.returncode}")

        return extract_pdf_pages(out_pdf)


class AdaptiveEmbedThrottle:
    def __init__(
        self,
        enabled: bool,
        base_threads: int,
        base_delay_ms: int,
        min_threads: int,
        max_threads: int,
        target_embed_ms: int,
        max_delay_ms: int,
        delay_step_ms: int,
    ):
        self.enabled = bool(enabled)
        self.base_threads = max(1, int(base_threads))
        self.base_delay_ms = max(0, int(base_delay_ms))
        self.min_threads = max(1, int(min_threads))
        self.max_threads = max(self.min_threads, int(max_threads))
        self.target_embed_ms = max(200, int(target_embed_ms))
        self.max_delay_ms = max(self.base_delay_ms, int(max_delay_ms))
        self.delay_step_ms = max(1, int(delay_step_ms))

        self.current_threads = min(
            self.max_threads,
            max(self.min_threads, self.base_threads),
        )
        self.current_delay_ms = self.base_delay_ms

        self.samples = 0
        self.adjustments = 0
        self.ema_embed_ms: float | None = None

    def _step_down(self) -> str | None:
        if self.current_threads > self.min_threads:
            self.current_threads -= 1
            self.adjustments += 1
            return "threads_down"
        if self.current_delay_ms < self.max_delay_ms:
            self.current_delay_ms = min(
                self.max_delay_ms,
                self.current_delay_ms + self.delay_step_ms,
            )
            self.adjustments += 1
            return "delay_up"
        return None

    def _step_up(self) -> str | None:
        if self.current_delay_ms > self.base_delay_ms:
            self.current_delay_ms = max(
                self.base_delay_ms,
                self.current_delay_ms - self.delay_step_ms,
            )
            self.adjustments += 1
            return "delay_down"
        if self.current_threads < self.max_threads:
            self.current_threads += 1
            self.adjustments += 1
            return "threads_up"
        return None

    def observe_embed_ms(self, elapsed_ms: float) -> str | None:
        if not self.enabled:
            return None

        elapsed = max(1.0, float(elapsed_ms))
        self.samples += 1
        if self.ema_embed_ms is None:
            self.ema_embed_ms = elapsed
        else:
            self.ema_embed_ms = (0.2 * elapsed) + (0.8 * self.ema_embed_ms)

        # Adjust at a fixed cadence to avoid oscillation.
        if self.samples % 6 != 0:
            return None

        high_ms = self.target_embed_ms * 1.2
        low_ms = self.target_embed_ms * 0.75
        if self.ema_embed_ms > high_ms:
            return self._step_down()
        if self.ema_embed_ms < low_ms:
            return self._step_up()
        return None


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL,
            mtime INTEGER NOT NULL,
            indexed_at INTEGER NOT NULL,
            pages_indexed INTEGER NOT NULL,
            chunks_indexed INTEGER NOT NULL,
            title TEXT,
            authors_json TEXT,
            year TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            doc_id INTEGER NOT NULL,
            page_num INTEGER NOT NULL,
            chunk_idx INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_path ON documents(path)")

    cols = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        if len(row) > 1
    }
    if "title" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN title TEXT")
    if "authors_json" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN authors_json TEXT")
    if "year" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN year TEXT")

    conn.commit()


def upsert_document(
    conn: sqlite3.Connection,
    path: str,
    size: int,
    mtime: int,
    pages_indexed: int,
    chunks_indexed: int,
    title: str,
    authors_json: str,
    year: str,
) -> int:
    conn.execute(
        """
        INSERT INTO documents(path, size, mtime, indexed_at, pages_indexed, chunks_indexed, title, authors_json, year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size=excluded.size,
            mtime=excluded.mtime,
            indexed_at=excluded.indexed_at,
            pages_indexed=excluded.pages_indexed,
            chunks_indexed=excluded.chunks_indexed,
            title=excluded.title,
            authors_json=excluded.authors_json,
            year=excluded.year
        """,
        (path, size, mtime, now_ts(), pages_indexed,
         chunks_indexed, title, authors_json, year),
    )
    row = conn.execute(
        "SELECT id FROM documents WHERE path = ?", (path,)).fetchone()
    assert row is not None
    return int(row[0])


def get_doc_row(conn: sqlite3.Connection, path: str):
    return conn.execute(
        "SELECT id, size, mtime FROM documents WHERE path = ?",
        (path,),
    ).fetchone()


def delete_doc_chunks(conn: sqlite3.Connection, doc_id: int) -> None:
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))


def load_document_metadata_map(conn: sqlite3.Connection, paths: list[str]) -> dict[str, dict]:
    if not paths:
        return {}
    unique_paths = sorted(
        {str(p) for p in paths if isinstance(p, str) and str(p).strip()})
    if not unique_paths:
        return {}

    placeholders = ",".join(["?"] * len(unique_paths))
    rows = conn.execute(
        f"SELECT path, title, authors_json, year FROM documents WHERE path IN ({placeholders})",
        unique_paths,
    ).fetchall()

    out: dict[str, dict] = {}
    for path, title, authors_json, year in rows:
        authors: list[str] = []
        try:
            parsed = json.loads(str(authors_json or "[]"))
            if isinstance(parsed, list):
                authors = [normalize_text(a)
                           for a in parsed if normalize_text(a)]
        except Exception:
            authors = []
        out[str(path)] = {
            "title": normalize_text(title),
            "authors": authors,
            "year": extract_year(year),
        }
    return out


def metadata_sync_command(args) -> int:
    source = Path(args.source).expanduser()
    if not source.exists():
        print(f"Source path does not exist: {source}", file=sys.stderr)
        return 1

    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        print(f"Index DB not found: {index_db}", file=sys.stderr)
        return 1

    conn = open_index_db(index_db, writable=True)
    init_db(conn)

    docs = discover_source_documents(source)
    updated = 0
    skipped_unindexed = 0
    failed = 0

    for doc_path in docs:
        rel_or_abs = str(doc_path)
        existing = get_doc_row(conn, rel_or_abs)
        if not existing:
            skipped_unindexed += 1
            continue
        try:
            st = doc_path.stat()
            metadata = extract_document_metadata(doc_path)
            conn.execute(
                """
                UPDATE documents
                SET size = ?, mtime = ?, title = ?, authors_json = ?, year = ?
                WHERE path = ?
                """,
                (
                    int(st.st_size),
                    int(st.st_mtime),
                    normalize_text(metadata.get("title")
                                   ) or title_from_path(doc_path),
                    json.dumps(metadata.get("authors") or [],
                               ensure_ascii=True, separators=(",", ":")),
                    extract_year(metadata.get("year")),
                    rel_or_abs,
                ),
            )
            updated += 1
        except Exception as exc:
            failed += 1
            print(
                f"[warn] metadata sync failed for {doc_path}: {exc}", file=sys.stderr)

    conn.commit()
    payload = {
        "ok": True,
        "updated": updated,
        "skipped_unindexed": skipped_unindexed,
        "failed": failed,
        "total_documents": len(docs),
    }
    if getattr(args, "json_output", False):
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(
            f"Metadata sync complete. updated={updated}, skipped_unindexed={skipped_unindexed}, "
            f"failed={failed}, total_documents={len(docs)}"
        )
    return 0


def index_command(args) -> int:
    source = Path(args.source).expanduser()
    if not source.exists():
        print(f"Source path does not exist: {source}", file=sys.stderr)
        return 1

    index_db = Path(args.index_db).expanduser()
    index_db.parent.mkdir(parents=True, exist_ok=True)

    conn = open_index_db(index_db, writable=True)
    init_db(conn)

    docs = discover_source_documents(source)
    if not docs:
        if getattr(args, "json_summary", False):
            print(json.dumps({"ok": True, "indexed": 0, "skipped": 0,
                  "total_documents": 0, "total_pdfs": 0, "pruned": 0}, ensure_ascii=True))
        else:
            print(f"No supported documents found under {source}")
        return 0

    seen_paths = set()
    indexed = 0
    skipped = 0
    ocr_attempted = 0
    ocr_succeeded = 0
    ocr_failed = 0

    ocr_requested = bool(getattr(args, "ocr_missing", False))
    ocr_available = bool(shutil.which("ocrmypdf")) if ocr_requested else False
    if ocr_requested and not ocr_available:
        print(
            "[warn] --ocr-missing is enabled but 'ocrmypdf' is not installed; textless PDFs will remain unindexed.",
            file=sys.stderr,
        )

    total_pdfs = sum(1 for doc_path in docs if is_pdf_path(doc_path))
    embed_delay_sec = max(0, int(getattr(args, "embed_delay_ms", 0))) / 1000.0
    doc_cooldown_sec = max(0, int(getattr(args, "doc_cooldown_seconds", 0)))
    throttle = AdaptiveEmbedThrottle(
        enabled=bool(getattr(args, "dynamic_throttle", False)),
        base_threads=max(1, int(getattr(args, "embed_num_thread", 1))),
        base_delay_ms=max(0, int(getattr(args, "embed_delay_ms", 0))),
        min_threads=max(1, int(getattr(args, "dynamic_min_threads", 1))),
        max_threads=max(1, int(getattr(args, "dynamic_max_threads", 1))),
        target_embed_ms=max(
            200, int(getattr(args, "dynamic_target_embed_ms", 1400))),
        max_delay_ms=max(0, int(getattr(args, "dynamic_max_delay_ms", 2000))),
        delay_step_ms=max(1, int(getattr(args, "dynamic_delay_step_ms", 50))),
    )

    for doc_path in docs:
        rel_or_abs = str(doc_path)
        seen_paths.add(rel_or_abs)
        st = doc_path.stat()
        size = int(st.st_size)
        mtime = int(st.st_mtime)

        existing = get_doc_row(conn, rel_or_abs)
        metadata = extract_document_metadata(doc_path)
        if existing and (not args.force) and int(existing[1]) == size and int(existing[2]) == mtime:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, authors_json = ?, year = ?
                WHERE id = ?
                """,
                (
                    normalize_text(metadata.get("title")
                                   ) or title_from_path(doc_path),
                    json.dumps(metadata.get("authors") or [],
                               ensure_ascii=True, separators=(",", ":")),
                    extract_year(metadata.get("year")),
                    int(existing[0]),
                ),
            )
            skipped += 1
            continue

        doc_id = int(existing[0]) if existing else None
        if doc_id is not None:
            delete_doc_chunks(conn, doc_id)

        try:
            pages = extract_document_pages(doc_path)
        except Exception as exc:
            print(f"[warn] failed to parse {doc_path}: {exc}", file=sys.stderr)
            continue

        if is_pdf_path(doc_path) and ocr_requested and ocr_available and not pages:
            ocr_attempted += 1
            try:
                pages = extract_pdf_pages_with_ocr(
                    doc_path,
                    args.ocr_lang,
                    args.ocr_jobs,
                    args.ocr_timeout,
                )
                if pages:
                    ocr_succeeded += 1
                else:
                    ocr_failed += 1
                    print(
                        f"[warn] OCR completed but no text was extracted: {doc_path}",
                        file=sys.stderr,
                    )
            except Exception as exc:
                ocr_failed += 1
                print(
                    f"[warn] OCR failed for {doc_path}: {exc}", file=sys.stderr)

        chunk_rows = []
        chunk_count = 0
        for page_num, page_text in pages:
            chunks = chunk_text(page_text, args.chunk_size, args.chunk_overlap)
            for i, chunk in enumerate(chunks):
                try:
                    embed_started = time.perf_counter()
                    emb = embed_text(
                        args.ollama_base,
                        args.embed_model,
                        chunk,
                        num_thread=throttle.current_threads if throttle.enabled else args.embed_num_thread,
                    )
                    embed_elapsed_ms = (
                        time.perf_counter() - embed_started) * 1000.0
                    change = throttle.observe_embed_ms(embed_elapsed_ms)
                    if change and not getattr(args, "json_summary", False):
                        avg_ms = round(
                            float(throttle.ema_embed_ms or embed_elapsed_ms), 1)
                        print(
                            f"[throttle] {change}: threads={throttle.current_threads}, "
                            f"delay_ms={throttle.current_delay_ms}, avg_embed_ms={avg_ms}",
                            file=sys.stderr,
                        )
                except Exception as exc:
                    print(
                        f"[warn] embedding failed for {doc_path} unit {page_num}: {exc}", file=sys.stderr)
                    continue
                chunk_rows.append(
                    (page_num, i, chunk, json.dumps(emb, separators=(",", ":"))))
                chunk_count += 1
                current_embed_delay_sec = (
                    throttle.current_delay_ms / 1000.0
                    if throttle.enabled
                    else embed_delay_sec
                )
                if current_embed_delay_sec > 0:
                    time.sleep(current_embed_delay_sec)

        doc_id = upsert_document(
            conn,
            rel_or_abs,
            size,
            mtime,
            len(pages),
            chunk_count,
            normalize_text(metadata.get("title")) or title_from_path(doc_path),
            json.dumps(metadata.get("authors") or [],
                       ensure_ascii=True, separators=(",", ":")),
            extract_year(metadata.get("year")),
        )
        if chunk_rows:
            conn.executemany(
                "INSERT INTO chunks(doc_id, page_num, chunk_idx, text, embedding_json) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, p, idx, text, emb)
                 for (p, idx, text, emb) in chunk_rows],
            )
        conn.commit()
        indexed += 1
        if not getattr(args, "json_summary", False):
            print(
                f"[indexed] {doc_path} (units={len(pages)}, chunks={chunk_count})")
        if doc_cooldown_sec > 0:
            time.sleep(doc_cooldown_sec)

    removed = 0
    conn.commit()
    if args.prune:
        # Safety check: verify all indexed documents are under current source directory
        source_realpath = os.path.realpath(os.path.expanduser(args.source))
        all_indexed_docs = conn.execute(
            "SELECT id, path FROM documents").fetchall()

        mismatched_paths = []
        for doc_id, doc_path in all_indexed_docs:
            doc_realpath = os.path.realpath(os.path.expanduser(doc_path))
            try:
                doc_is_under_source = (
                    os.path.commonpath([doc_realpath, source_realpath])
                    == source_realpath
                )
            except ValueError:
                # Raised on Windows when paths are on different drives
                doc_is_under_source = False
            if not doc_is_under_source:
                mismatched_paths.append(doc_path)

        if mismatched_paths:
            # Path mismatch detected - refuse to prune to prevent accidental deletions
            error_msg = (
                f"SAFETY CHECK FAILED: {len(mismatched_paths)} indexed documents "
                f"are outside current source directory '{args.source}'. "
                f"Refusing to prune to prevent data loss. "
                f"First mismatched path: {mismatched_paths[0]}"
            )
            print(f"[ERROR] {error_msg}", file=sys.stderr)
            raise RuntimeError(error_msg)

        # Safe to prune - all indexed docs are under current source
        rows = conn.execute("SELECT id, path FROM documents").fetchall()
        for doc_id, path in rows:
            if path not in seen_paths:
                conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
                conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
                removed += 1
        conn.commit()
        if removed and not getattr(args, "json_summary", False):
            print(f"[pruned] removed {removed} missing documents from index")

    summary = {
        "ok": True,
        "indexed": indexed,
        "skipped": skipped,
        "total_documents": len(docs),
        "total_pdfs": total_pdfs,
        "pruned": removed,
        "ocr_requested": ocr_requested,
        "ocr_available": ocr_available,
        "ocr_attempted": ocr_attempted,
        "ocr_succeeded": ocr_succeeded,
        "ocr_failed": ocr_failed,
        "dynamic_throttle": bool(throttle.enabled),
        "dynamic_adjustments": int(throttle.adjustments),
        "dynamic_final_embed_num_thread": int(throttle.current_threads),
        "dynamic_final_embed_delay_ms": int(throttle.current_delay_ms),
        "dynamic_avg_embed_ms": round(float(throttle.ema_embed_ms or 0.0), 1),
    }
    if getattr(args, "json_summary", False):
        print(json.dumps(summary, ensure_ascii=True))
    else:
        print(
            f"Done. indexed={indexed}, skipped={skipped}, total_documents={len(docs)}")
    return 0


def load_all_chunks(conn: sqlite3.Connection):
    return conn.execute(
        """
        SELECT d.path, d.title, c.page_num, c.text, c.embedding_json
        FROM chunks c
        JOIN documents d ON c.doc_id = d.id
        """
    ).fetchall()


def _normalize_for_match(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize_for_match(value: object) -> set[str]:
    normalized = _normalize_for_match(value)
    if not normalized:
        return set()
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "what",
        "who",
        "when",
        "where",
        "which",
        "why",
        "how",
        "tell",
        "about",
        "explain",
        "describe",
        "summarize",
        "your",
        "you",
        "me",
        "was",
        "were",
        "are",
        "is",
        "did",
        "does",
        "can",
        "could",
        "would",
        "should",
        "into",
        "one",
        "sentence",
    }
    return {t for t in normalized.split(" ") if len(t) >= 3 and t not in stop}


def _lexical_path_title_boost(query_text: str, path: str, title: str) -> float:
    q_norm = _normalize_for_match(query_text)
    if not q_norm:
        return 0.0

    descriptor = _normalize_for_match(f"{title} {path}")
    if not descriptor:
        return 0.0

    boost = 0.0
    if q_norm in descriptor:
        boost += 0.28

    q_tokens = _tokenize_for_match(query_text)
    if not q_tokens:
        return boost

    d_tokens = _tokenize_for_match(descriptor)
    if not d_tokens:
        return boost

    overlap = len(q_tokens & d_tokens)
    ratio = overlap / float(len(q_tokens))
    boost += min(0.22, ratio * 0.22)

    if overlap >= 3 and ratio >= 0.75:
        boost += 0.12

    return boost


def _lexical_chunk_text_boost(query_text: str, chunk_text: str) -> float:
    q_tokens = _tokenize_for_match(query_text)
    if not q_tokens:
        return 0.0

    chunk_norm = _normalize_for_match(chunk_text)
    if not chunk_norm:
        return 0.0

    boost = 0.0
    q_norm = _normalize_for_match(query_text)
    if q_norm and q_norm in chunk_norm:
        boost += 1.40

    c_tokens = _tokenize_for_match(chunk_norm)
    if not c_tokens:
        return boost

    overlap = len(q_tokens & c_tokens)
    if overlap <= 0:
        return boost

    # Strongly reward chunks that contain every meaningful query token.
    if len(q_tokens) >= 2 and q_tokens.issubset(c_tokens):
        boost += 1.00

    ratio = overlap / float(len(q_tokens))
    boost += min(0.55, ratio * 0.55)
    if overlap >= 2 and ratio >= 0.8:
        boost += 0.40

    return boost


def _extract_entity_phrases(query_text: str) -> list[str]:
    text = str(query_text or "")
    if not text:
        return []

    candidates: list[str] = []
    # Capture multi-token capitalized spans such as "Reconstruction Finance Corporation".
    for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9.-]*\s+){1,}[A-Z][A-Za-z0-9.-]*\b", text):
        phrase = normalize_text(match.group(0)).strip(" .,:;()[]{}\"'")
        if not phrase:
            continue
        if len(phrase.split()) < 2:
            continue
        candidates.append(phrase)

    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in candidates:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(phrase)
    return deduped


def _entity_alignment_boost(query_text: str, path: str, title: str, chunk_text: str) -> float:
    phrases = _extract_entity_phrases(query_text)
    if not phrases:
        return 0.0

    descriptor_norm = _normalize_for_match(f"{path} {title}")
    chunk_norm = _normalize_for_match(chunk_text)
    descriptor_tokens = _tokenize_for_match(descriptor_norm)
    chunk_tokens = _tokenize_for_match(chunk_norm)

    boost = 0.0
    for phrase in phrases:
        phrase_norm = _normalize_for_match(phrase)
        if not phrase_norm:
            continue
        phrase_tokens = _tokenize_for_match(phrase_norm)
        if not phrase_tokens:
            continue

        if phrase_norm in chunk_norm:
            boost += 0.65
            continue
        if phrase_norm in descriptor_norm:
            boost += 0.50
            continue

        if phrase_tokens.issubset(chunk_tokens):
            boost += 0.30
            continue
        if phrase_tokens.issubset(descriptor_tokens):
            boost += 0.20

    return min(0.95, boost)


def _semantic_drift_penalty(query_text: str, chunk_text: str, vector_score: float) -> float:
    q_tokens = _tokenize_for_match(query_text)
    if len(q_tokens) < 3:
        return 0.0

    c_tokens = _tokenize_for_match(chunk_text)
    overlap = len(q_tokens & c_tokens)
    ratio = overlap / float(len(q_tokens)) if q_tokens else 0.0

    if vector_score >= 0.90 and overlap <= 1 and ratio < 0.30:
        return -0.28
    return 0.0


def _score_chunk_for_query(
    query_text: str,
    path: str,
    title: str,
    chunk_text: str,
    vector_score: float,
) -> tuple[float, float, float, float, float]:
    path_title_boost = _lexical_path_title_boost(query_text, path, title)
    chunk_text_boost = _lexical_chunk_text_boost(query_text, str(chunk_text))
    entity_boost = _entity_alignment_boost(
        query_text, path, title, str(chunk_text))
    drift_penalty = _semantic_drift_penalty(
        query_text, str(chunk_text), vector_score)
    final_score = (
        vector_score
        + path_title_boost
        + chunk_text_boost
        + entity_boost
        + drift_penalty
    )
    return final_score, path_title_boost, chunk_text_boost, entity_boost, drift_penalty


def retrieve_top_chunks(conn: sqlite3.Connection, query_embedding: list[float], top_k: int):
    return retrieve_top_chunks_filtered(conn, query_embedding, top_k, "", None, None)


def retrieve_top_chunks_filtered(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int,
    query_text: str,
    include_paths: set[str] | None,
    exclude_paths: set[str] | None,
    trace_out: list[dict] | None = None,
):
    rows = load_all_chunks(conn)
    scored = []
    for path, title, page_num, text, emb_json in rows:
        path = str(path)
        title = normalize_text(title)
        if include_paths and path not in include_paths:
            continue
        if exclude_paths and path in exclude_paths:
            continue
        try:
            emb = json.loads(emb_json)
            vector_score = cosine_similarity(query_embedding, emb)
        except Exception:
            continue
        final_score, path_title_boost, chunk_text_boost, entity_boost, drift_penalty = _score_chunk_for_query(
            query_text,
            path,
            title,
            str(text),
            vector_score,
        )
        scored.append(
            (
                final_score,
                path,
                int(page_num),
                str(text),
                vector_score,
                path_title_boost,
                chunk_text_boost,
                entity_boost,
                drift_penalty,
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    top_scored = scored[:top_k]
    if trace_out is not None:
        trace_out.clear()
        for rank, item in enumerate(top_scored, start=1):
            (
                final_score,
                path,
                page,
                _,
                vector_score,
                path_title_boost,
                chunk_text_boost,
                entity_boost,
                drift_penalty,
            ) = item
            trace_out.append(
                {
                    "rank": rank,
                    "path": path,
                    "location": page,
                    "vector_score": vector_score,
                    "lexical_path_title_score": path_title_boost,
                    "lexical_chunk_score": chunk_text_boost,
                    "entity_alignment_score": entity_boost,
                    "semantic_drift_penalty": drift_penalty,
                    "final_score": final_score,
                }
            )
    return [(score, path, page, text) for score, path, page, text, *_ in top_scored]


def format_context(chunks) -> str:
    out = []
    for i, (score, path, page, text) in enumerate(chunks, start=1):
        out.append(
            f"[{i}] source={path} location={page} score={score:.4f}\n{text}")
    return "\n\n".join(out)


def search_command(args) -> int:
    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        print(f"Index DB not found: {index_db}", file=sys.stderr)
        return 1

    conn = open_index_db(index_db)
    q_emb = embed_text(
        args.ollama_base,
        args.embed_model,
        args.query,
        num_thread=args.embed_num_thread,
    )
    top = retrieve_top_chunks(conn, q_emb, args.top_k)

    if not top:
        print("No indexed chunks found.")
        return 0

    for score, path, page, text in top:
        snippet = text[:280].replace("\n", " ")
        print(f"score={score:.4f} | {path} | loc {page}\n  {snippet}\n")
    return 0


def ask_command(args) -> int:
    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        if getattr(args, "json_output", False):
            print(json.dumps({
                "ok": False,
                "answer": "",
                "sources": [],
                "error": f"Index DB not found: {index_db}",
            }, ensure_ascii=True))
            return 0
        print(f"Index DB not found: {index_db}", file=sys.stderr)
        return 1

    conn = open_index_db(index_db)
    q_emb = embed_text(
        args.ollama_base,
        args.embed_model,
        args.query,
        num_thread=args.embed_num_thread,
    )
    include_paths = {
        str(path).strip()
        for path in getattr(args, "include_path", [])
        if isinstance(path, str) and str(path).strip()
    }
    exclude_paths = {
        str(path).strip()
        for path in getattr(args, "exclude_path", [])
        if isinstance(path, str) and str(path).strip()
    }
    retrieval_trace_rows: list[dict] | None = [] if getattr(
        args, "debug_trace", False) else None
    top = retrieve_top_chunks_filtered(
        conn,
        q_emb,
        args.top_k,
        args.query,
        include_paths if include_paths else None,
        exclude_paths if exclude_paths else None,
        trace_out=retrieval_trace_rows,
    )

    if args.deepen and top:
        seed_paths = {path for _, path, _,
                      _ in top[: max(1, args.deep_seed_docs)]}
        seen = {(path, page, text) for _, path, page, text in top}
        expanded = []
        for path, title, page_num, text, emb_json in load_all_chunks(conn):
            path = str(path)
            title = normalize_text(title)
            page_num = int(page_num)
            text = str(text)
            key = (path, page_num, text)
            if include_paths and path not in include_paths:
                continue
            if exclude_paths and path in exclude_paths:
                continue
            if path not in seed_paths or key in seen:
                continue
            try:
                emb = json.loads(emb_json)
                score = cosine_similarity(q_emb, emb)
            except Exception:
                continue
            score, _, _, _, _ = _score_chunk_for_query(
                args.query,
                path,
                title,
                text,
                score,
            )
            expanded.append((score, path, page_num, text))

        expanded.sort(key=lambda x: x[0], reverse=True)
        top.extend(expanded[: max(0, args.deep_extra_k)])
    if not top:
        if getattr(args, "json_output", False):
            print(json.dumps({
                "ok": False,
                "answer": "",
                "sources": [],
                "error": "No indexed chunks found.",
            }, ensure_ascii=True))
            return 0
        print("No indexed chunks found.")
        return 0

    context = format_context(top)
    prompt = (
        "You are answering questions using retrieved excerpts from a local document library. "
        "Use only the provided context. If the context is insufficient, say so clearly. "
        "Always include citations in the form [source path, location].\n\n"
        f"Question:\n{args.query}\n\n"
        f"Context:\n{context}\n\n"
        "Answer:"
    )
    answer = generate_answer(
        args.ollama_base,
        args.answer_model,
        prompt,
        timeout=max(1, int(getattr(args, "answer_timeout", 180))),
        num_thread=max(0, int(getattr(args, "answer_num_thread", 0) or 0)),
        keep_alive=str(getattr(args, "answer_keep_alive", "60s") or "60s"),
    )
    metadata_map = load_document_metadata_map(
        conn, [path for _, path, _, _ in top])
    sources = [
        {
            "path": path,
            "doc_type": Path(path).suffix.lower().lstrip("."),
            "location_type": "page" if Path(path).suffix.lower() == ".pdf" else "section",
            "page": page,
            "section": page,
            "location": page,
            "score": score,
            "title": (metadata_map.get(path) or {}).get("title", ""),
            "authors": (metadata_map.get(path) or {}).get("authors", []),
            "year": (metadata_map.get(path) or {}).get("year", ""),
        }
        for score, path, page, _ in top
    ]

    if getattr(args, "json_output", False):
        payload = {
            "ok": True,
            "answer": answer,
            "sources": sources,
        }
        if retrieval_trace_rows is not None:
            payload["debug_trace"] = {
                "enabled": True,
                "top_k": int(args.top_k),
                "retrieval": retrieval_trace_rows,
            }
        print(json.dumps(payload, ensure_ascii=True))
        return 0

    print(answer)
    print("\nSources:")
    for score, path, page, _ in top:
        print(f"- {path} (page {page}, score={score:.4f})")
    return 0


def build_synthesize_prompt(query: str, sources: list[dict]) -> str:
    lines = [
        "You are a research assistant. For each source document below, write exactly ONE sentence "
        "explaining how it is relevant to the query.\n",
        f"Query: {query}\n",
        "Source documents:",
    ]
    for src in sources:
        excerpt = str(src.get("excerpt", "")).strip().replace("\n", " ")
        if len(excerpt) > 350:
            excerpt = excerpt[:350] + "…"
        lines.append(
            f"\n[{src['citation_id']}] {src['path']} (loc {src['location']}, score {src['score']:.3f})\n"
            f"Excerpt: {excerpt}"
        )
    cid_list = ", ".join(src["citation_id"] for src in sources)
    lines.append(
        f'\n\nRespond with one line per source in exactly this format — the citation ID, a colon, then one sentence:\n'
        f'{sources[0]["citation_id"]}: This source is relevant because...\n'
        f'Output lines for: {cid_list}\nNo other text.'
    )
    return "\n".join(lines)


def synthesize_command(args) -> int:
    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        if getattr(args, "json_output", False):
            print(json.dumps({
                "ok": False,
                "sources": [],
                "error": f"Index DB not found: {index_db}",
            }, ensure_ascii=True))
            return 0
        print(f"Index DB not found: {index_db}", file=sys.stderr)
        return 1

    conn = open_index_db(index_db)
    q_emb = embed_text(
        args.ollama_base,
        args.embed_model,
        args.query,
        num_thread=args.embed_num_thread,
    )
    include_paths = {
        str(p).strip()
        for p in getattr(args, "include_path", [])
        if isinstance(p, str) and str(p).strip()
    }
    exclude_paths = {
        str(p).strip()
        for p in getattr(args, "exclude_path", [])
        if isinstance(p, str) and str(p).strip()
    }
    top = retrieve_top_chunks_filtered(
        conn,
        q_emb,
        args.top_k,
        args.query,
        include_paths if include_paths else None,
        exclude_paths if exclude_paths else None,
    )

    if not top:
        payload = {"ok": False, "sources": [], "error": "No indexed chunks found."}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, ensure_ascii=True))
            return 0
        print("No indexed chunks found.")
        return 0

    # One best chunk per unique document path
    seen_paths: set[str] = set()
    unique_sources: list[dict] = []
    for score, path, page, text in top:
        if path not in seen_paths:
            seen_paths.add(path)
            unique_sources.append({
                "citation_id": f"c{len(unique_sources) + 1}",
                "path": path,
                "location": page,
                "score": score,
                "excerpt": text,
            })

    prompt = build_synthesize_prompt(args.query, unique_sources)
    raw_answer = generate_answer(
        args.ollama_base,
        args.answer_model,
        prompt,
        timeout=max(1, int(getattr(args, "answer_timeout", 90))),
        num_thread=max(0, int(getattr(args, "answer_num_thread", 0) or 0)),
        keep_alive=str(getattr(args, "answer_keep_alive", "15s") or "15s"),
    )
    print(f"[synthesize] raw_answer: {raw_answer!r}", file=sys.stderr)

    # Parse "cX: sentence" lines — robust against any model output style.
    relevancy_map: dict[str, str] = {}
    for line in raw_answer.splitlines():
        line = line.strip().lstrip("-•*# ")
        m = re.match(r'^\[?(c\d+)\]?\s*[:\-]\s*(.+)$', line, re.IGNORECASE)
        if m:
            cid = m.group(1).lower()
            rel = m.group(2).strip().rstrip(".")
            if cid and rel:
                relevancy_map[cid] = rel + "."

    metadata_map = load_document_metadata_map(conn, list(seen_paths))
    sources = []
    for src in unique_sources:
        path = src["path"]
        meta = metadata_map.get(path) or {}
        suffix = Path(path).suffix.lower()
        sources.append({
            "citation_id": src["citation_id"],
            "path": path,
            "doc_type": suffix.lstrip("."),
            "title": meta.get("title", ""),
            "authors": meta.get("authors", []),
            "year": meta.get("year", ""),
            "location": src["location"],
            "location_type": "page" if suffix == ".pdf" else "section",
            "score": src["score"],
            "relevancy": relevancy_map.get(src["citation_id"], ""),
        })

    if getattr(args, "json_output", False):
        print(json.dumps({"ok": True, "sources": sources}, ensure_ascii=True))
        return 0

    print(f'Source map for: "{args.query}"\n')
    for src in sources:
        label = src.get("title") or Path(src["path"]).name
        print(f"• {label} (loc {src['location']}, score={src['score']:.3f})")
        if src.get("relevancy"):
            print(f"  → {src['relevancy']}")
        print()
    return 0


def status_command(args) -> int:
    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        print(json.dumps({
            "ok": True,
            "index_exists": False,
            "documents": 0,
            "chunks": 0,
            "last_indexed_at": None,
        }, ensure_ascii=True))
        return 0

    conn = open_index_db(index_db)
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(chunks_indexed),0), MAX(indexed_at) FROM documents"
    ).fetchone()
    print(json.dumps({
        "ok": True,
        "index_exists": True,
        "documents": int(row[0]) if row else 0,
        "chunks": int(row[1]) if row else 0,
        "last_indexed_at": int(row[2]) if row and row[2] is not None else None,
    }, ensure_ascii=True))
    return 0


def verify_command(args) -> int:
    index_db = Path(args.index_db).expanduser()
    if not index_db.exists():
        payload = {
            "ok": False,
            "index_exists": False,
            "error": f"Index DB not found: {index_db}",
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, ensure_ascii=True))
            return 0
        print(payload["error"], file=sys.stderr)
        return 1

    conn = open_index_db(index_db)
    rows = conn.execute(
        "SELECT path, pages_indexed, chunks_indexed, indexed_at FROM documents ORDER BY path"
    ).fetchall()

    docs = []
    for path, pages, chunks, indexed_at in rows:
        pages_i = int(pages or 0)
        chunks_i = int(chunks or 0)
        density = 0.0
        if pages_i > 0:
            density = float(chunks_i) / float(pages_i)
        docs.append({
            "path": str(path),
            "pages": pages_i,
            "chunks": chunks_i,
            "indexed_at": int(indexed_at or 0),
            "chunks_per_page": density,
        })

    zero_chunk_docs = [d for d in docs if d["pages"] > 0 and d["chunks"] == 0]
    empty_page_docs = [d for d in docs if d["pages"] == 0]
    low_density_docs = [
        d for d in docs
        if d["pages"] > 0 and d["chunks"] > 0 and d["chunks_per_page"] < float(args.min_chunks_per_page)
    ]

    max_rows = max(1, int(args.list_limit))
    zero_chunk_docs.sort(key=lambda d: (d["pages"], d["path"]), reverse=True)
    low_density_docs.sort(key=lambda d: (
        d["chunks_per_page"], d["pages"], d["path"]))

    payload = {
        "ok": True,
        "index_exists": True,
        "documents": len(docs),
        "chunks": int(sum(d["chunks"] for d in docs)),
        "avg_chunks_per_page": (
            round(
                sum(d["chunks_per_page"] for d in docs if d["pages"] > 0)
                / max(1, sum(1 for d in docs if d["pages"] > 0)),
                3,
            )
            if docs
            else 0.0
        ),
        "thresholds": {
            "min_chunks_per_page": float(args.min_chunks_per_page),
        },
        "issues": {
            "zero_chunk_docs": len(zero_chunk_docs),
            "empty_page_docs": len(empty_page_docs),
            "low_density_docs": len(low_density_docs),
        },
        "samples": {
            "zero_chunk_docs": zero_chunk_docs[:max_rows],
            "empty_page_docs": empty_page_docs[:max_rows],
            "low_density_docs": low_density_docs[:max_rows],
        },
    }

    if getattr(args, "json_output", False):
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(f"Documents: {payload['documents']}")
        print(f"Chunks: {payload['chunks']}")
        print(f"Avg chunks/page: {payload['avg_chunks_per_page']}")
        print(
            "Issues: "
            f"zero_chunk={payload['issues']['zero_chunk_docs']} | "
            f"empty_pages={payload['issues']['empty_page_docs']} | "
            f"low_density(<{float(args.min_chunks_per_page):.3f})={payload['issues']['low_density_docs']}"
        )

        if payload["samples"]["zero_chunk_docs"]:
            print("\nTop zero-chunk docs:")
            for d in payload["samples"]["zero_chunk_docs"]:
                print(
                    f"- pages={d['pages']} chunks={d['chunks']} path={d['path']}")

        if payload["samples"]["low_density_docs"]:
            print("\nLow-density docs:")
            for d in payload["samples"]["low_density_docs"]:
                print(
                    f"- cpp={d['chunks_per_page']:.3f} pages={d['pages']} chunks={d['chunks']} path={d['path']}"
                )

        if payload["samples"]["empty_page_docs"]:
            print("\nDocs with no extractable pages:")
            for d in payload["samples"]["empty_page_docs"]:
                print(f"- path={d['path']}")

    has_issues = (
        payload["issues"]["zero_chunk_docs"] > 0
        or payload["issues"]["empty_page_docs"] > 0
        or payload["issues"]["low_density_docs"] > 0
    )
    if getattr(args, "fail_on_issues", False) and has_issues:
        return 2
    return 0


def _doctor_result(check: str, ok: bool, message: str) -> dict:
    return {
        "check": check,
        "ok": bool(ok),
        "message": str(message),
    }


def _doctor_check_python_version(min_major: int = 3, min_minor: int = 10) -> dict:
    current = (sys.version_info.major, sys.version_info.minor)
    required = (min_major, min_minor)
    ok = current >= required
    if ok:
        return _doctor_result(
            "python_version",
            True,
            f"Python {current[0]}.{current[1]} meets >= {required[0]}.{required[1]}",
        )
    return _doctor_result(
        "python_version",
        False,
        f"Python {current[0]}.{current[1]} is below required {required[0]}.{required[1]}",
    )


def _doctor_check_dependency_imports() -> list[dict]:
    checks = []
    pypdf_ok = PdfReader is not None
    checks.append(
        _doctor_result(
            "import_pypdf",
            pypdf_ok,
            "pypdf import ok" if pypdf_ok else "pypdf import failed",
        )
    )
    ebook_ok = epub is not None and ITEM_DOCUMENT is not None
    checks.append(
        _doctor_result(
            "import_ebooklib",
            ebook_ok,
            "ebooklib import ok" if ebook_ok else "ebooklib import failed",
        )
    )
    return checks


def _fetch_ollama_model_names(base_url: str, timeout: int = 10) -> list[str]:
    req = Request(
        f"{base_url.rstrip('/')}/api/tags",
        method="GET",
    )
    try:
        with urlopen(req, timeout=max(1, int(timeout))) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}: {exc}") from exc

    data = json.loads(payload) if payload else {}
    models = data.get("models", []) if isinstance(data, dict) else []
    out: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or item.get("model") or "").strip()
        if raw_name:
            out.append(raw_name)
    return sorted(set(out))


def _model_available(required_model: str, available_models: list[str]) -> bool:
    required = normalize_text(required_model)
    if not required:
        return False
    avail_set = {normalize_text(x)
                 for x in available_models if normalize_text(x)}
    if required in avail_set:
        return True

    required_base = required.split(":", 1)[0]
    for model in avail_set:
        base = model.split(":", 1)[0]
        if base == required_base:
            return True
    return False


def _doctor_check_ollama_and_models(base_url: str, required_models: list[str], timeout: int = 10) -> list[dict]:
    try:
        models = _fetch_ollama_model_names(base_url, timeout=timeout)
    except Exception as exc:
        return [
            _doctor_result("ollama_reachable", False, str(exc)),
            _doctor_result("required_models", False,
                           "Model checks skipped because Ollama is unreachable"),
        ]

    checks = [
        _doctor_result(
            "ollama_reachable",
            True,
            f"Ollama reachable; discovered {len(models)} model(s)",
        )
    ]

    missing = [m for m in required_models if not _model_available(m, models)]
    if missing:
        checks.append(
            _doctor_result(
                "required_models",
                False,
                f"Missing required models: {', '.join(missing)}",
            )
        )
    else:
        checks.append(
            _doctor_result(
                "required_models",
                True,
                "All required models are available",
            )
        )
    return checks


def _doctor_check_hardware_profile() -> dict:
    try:
        hardware = detect_hardware_profile()
        pressure = classify_resource_pressure(hardware)
        policy = safety_policy_for_pressure(pressure)
    except Exception as exc:
        return _doctor_result(
            "hardware_profile",
            False,
            f"Hardware profile detection failed: {exc}",
        )

    total_gb = hardware.to_dict().get("total_memory_gb")
    available_gb = hardware.to_dict().get("available_memory_gb")
    return _doctor_result(
        "hardware_profile",
        True,
        (
            f"Detected {hardware.os_name}/{hardware.machine}; "
            f"cpu={hardware.cpu_count}; memory={total_gb}GB total, "
            f"{available_gb}GB available; pressure={pressure}; "
            f"safe action={policy.get('message', '')}"
        ),
    )


def _doctor_check_model_recommendation(available_models: list[str]) -> dict:
    if not available_models:
        return _doctor_result(
            "model_fit_recommendation",
            True,
            "Model fit recommendation skipped because no Ollama models were discovered",
        )
    try:
        hardware = detect_hardware_profile()
        recommendation = recommend_model(available_models, hardware)
    except Exception as exc:
        return _doctor_result(
            "model_fit_recommendation",
            False,
            f"Model fit recommendation failed: {exc}",
        )

    recommended = str(recommendation.get("recommended_model") or "").strip()
    if not recommended:
        return _doctor_result(
            "model_fit_recommendation",
            False,
            "No chat model recommendation is available; install a non-embedding model",
        )

    unsafe = [
        str(item.get("name"))
        for item in recommendation.get("models", [])
        if isinstance(item, dict) and str(item.get("safety")) == "unsafe"
    ]
    caution = [
        str(item.get("name"))
        for item in recommendation.get("models", [])
        if isinstance(item, dict) and str(item.get("safety")) == "caution"
    ]
    details = [
        f"Recommended model: {recommended}",
        f"reason={recommendation.get('reason', '')}",
        f"safe_budget={recommendation.get('safe_budget_gb')}GB",
    ]
    if caution:
        details.append(f"caution={', '.join(caution)}")
    if unsafe:
        details.append(f"unsafe={', '.join(unsafe)}")
    return _doctor_result(
        "model_fit_recommendation",
        True,
        "; ".join(details),
    )


def _doctor_check_index_db_writable(index_db: str) -> dict:
    path = Path(index_db).expanduser()
    parent = path.parent
    if not parent.exists():
        return _doctor_result(
            "index_db_writable",
            False,
            f"Index DB parent directory does not exist: {parent}",
        )
    if not parent.is_dir():
        return _doctor_result(
            "index_db_writable",
            False,
            f"Index DB parent is not a directory: {parent}",
        )
    try:
        with tempfile.NamedTemporaryFile(dir=str(parent), prefix="doctor-write-", delete=True):
            pass
    except Exception as exc:
        return _doctor_result(
            "index_db_writable",
            False,
            f"Index DB parent is not writable: {exc}",
        )
    return _doctor_result(
        "index_db_writable",
        True,
        f"Index DB parent writable: {parent}",
    )


def _doctor_check_source_dir(source: str) -> dict:
    path = Path(source).expanduser()
    if not path.exists():
        return _doctor_result(
            "source_dir_access",
            False,
            f"Source directory does not exist: {path}",
        )
    if not path.is_dir():
        return _doctor_result(
            "source_dir_access",
            False,
            f"Source path is not a directory: {path}",
        )
    if not os.access(path, os.R_OK | os.X_OK):
        return _doctor_result(
            "source_dir_access",
            False,
            f"Source directory is not readable: {path}",
        )
    return _doctor_result(
        "source_dir_access",
        True,
        f"Source directory accessible: {path}",
    )


def _doctor_check_port_available(host: str, port: int) -> dict:
    candidate_host = normalize_text(host) or "127.0.0.1"
    family = socket.AF_INET6 if ":" in candidate_host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((candidate_host, int(port)))
    except Exception as exc:
        return _doctor_result(
            "web_port_available",
            False,
            f"Port {port} on {candidate_host} is not available: {exc}",
        )
    finally:
        sock.close()
    return _doctor_result(
        "web_port_available",
        True,
        f"Port {port} on {candidate_host} is available",
    )


def doctor_command(args) -> int:
    required_models: list[str] = []
    for model in [args.embed_model, args.answer_model] + list(getattr(args, "required_model", []) or []):
        normalized = normalize_text(model)
        if normalized and normalized not in required_models:
            required_models.append(normalized)

    checks: list[dict] = []
    checks.append(_doctor_check_python_version())
    checks.extend(_doctor_check_dependency_imports())
    checks.extend(_doctor_check_ollama_and_models(
        args.ollama_base, required_models, timeout=args.timeout))
    checks.append(_doctor_check_hardware_profile())
    try:
        discovered_models = _fetch_ollama_model_names(
            args.ollama_base, timeout=args.timeout)
    except Exception:
        discovered_models = []
    checks.append(_doctor_check_model_recommendation(discovered_models))
    checks.append(_doctor_check_index_db_writable(args.index_db))
    checks.append(_doctor_check_source_dir(args.source))
    checks.append(_doctor_check_port_available(args.web_host, args.web_port))

    failed_checks = [item for item in checks if not item.get("ok")]
    payload = {
        "ok": len(failed_checks) == 0,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed_checks),
            "failed": len(failed_checks),
        },
    }

    if getattr(args, "json_output", False):
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print("Doctor checks:")
        for item in checks:
            marker = "PASS" if item.get("ok") else "FAIL"
            print(f"[{marker}] {item.get('check')}: {item.get('message')}")
        summary = payload["summary"]
        print(
            f"Summary: passed={summary['passed']} failed={summary['failed']} total={summary['total']}"
        )

    return 0 if payload["ok"] else 2


def build_parser(config: RagCliConfig | None = None):
    resolved = config or RAG_CONFIG
    parser = argparse.ArgumentParser(
        description="Index documents from NAS/local storage into a retrieval DB and query with Ollama.",
    )
    parser.add_argument(
        "--ollama-base",
        default=resolved.ollama_base,
        help="Ollama base URL",
    )
    parser.add_argument(
        "--embed-model",
        default=resolved.embed_model,
        help="Embedding model name available in Ollama",
    )
    parser.add_argument(
        "--embed-num-thread",
        type=int,
        default=resolved.embed_num_thread,
        help=(
            "Per-request thread cap for embedding calls "
            f"(lower is cooler, default: {resolved.embed_num_thread})"
        ),
    )
    parser.add_argument(
        "--embed-delay-ms",
        type=int,
        default=resolved.embed_delay_ms,
        help="Delay in milliseconds between embedding calls to reduce sustained heat (default: 200)",
    )
    parser.add_argument(
        "--doc-cooldown-seconds",
        type=int,
        default=resolved.doc_cooldown_seconds,
        help=(
            "Cooldown in seconds after each indexed document to reduce thermal spikes "
            f"(default: {resolved.doc_cooldown_seconds})"
        ),
    )
    parser.add_argument(
        "--dynamic-throttle",
        dest="dynamic_throttle",
        action="store_true",
        default=bool(resolved.dynamic_throttle),
        help="Enable adaptive embed throttling based on observed embed latency",
    )
    parser.add_argument(
        "--no-dynamic-throttle",
        dest="dynamic_throttle",
        action="store_false",
        help="Disable adaptive embed throttling",
    )
    parser.add_argument(
        "--dynamic-target-embed-ms",
        type=int,
        default=resolved.dynamic_target_embed_ms,
        help="Target average embedding latency in milliseconds for adaptive throttling",
    )
    parser.add_argument(
        "--dynamic-max-delay-ms",
        type=int,
        default=resolved.dynamic_max_delay_ms,
        help="Maximum adaptive delay between embedding calls in milliseconds",
    )
    parser.add_argument(
        "--dynamic-delay-step-ms",
        type=int,
        default=resolved.dynamic_delay_step_ms,
        help="Adaptive delay adjustment step in milliseconds",
    )
    parser.add_argument(
        "--dynamic-min-threads",
        type=int,
        default=resolved.dynamic_min_threads,
        help="Minimum embed threads allowed during adaptive throttling",
    )
    parser.add_argument(
        "--dynamic-max-threads",
        type=int,
        default=resolved.dynamic_max_threads,
        help="Maximum embed threads allowed during adaptive throttling",
    )
    parser.add_argument(
        "--index-db",
        default=resolved.index_db,
        help="Local sqlite index path",
    )
    parser.add_argument(
        "--answer-num-thread",
        type=int,
        default=resolved.answer_num_thread,
        help="Optional thread cap for answer generation calls; 0 lets Ollama choose",
    )
    parser.add_argument(
        "--answer-keep-alive",
        default=resolved.answer_keep_alive,
        help="Ollama keep_alive value for answer generation calls",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser(
        "index", help="Index supported documents under a source directory")
    p_index.add_argument(
        "--source",
        default=resolved.source_dir,
        help="Directory containing document library (.pdf, .txt, .md, .html, .htm, .epub)",
    )
    p_index.add_argument("--chunk-size", type=int, default=1200)
    p_index.add_argument("--chunk-overlap", type=int, default=180)
    p_index.add_argument("--force", action="store_true",
                         help="Re-index even if file unchanged")
    p_index.add_argument("--prune", action="store_true",
                         help="Remove docs that no longer exist")
    p_index.add_argument(
        "--ocr-missing",
        action="store_true",
        help="Use OCR for PDFs that have no extractable text",
    )
    p_index.add_argument(
        "--ocr-lang",
        default=resolved.ocr_lang,
        help="OCR language for ocrmypdf (e.g. eng, eng+spa)",
    )
    p_index.add_argument(
        "--ocr-jobs",
        type=int,
        default=resolved.ocr_jobs,
        help="Parallel OCR worker count",
    )
    p_index.add_argument(
        "--ocr-timeout",
        type=int,
        default=resolved.ocr_timeout,
        help="Max seconds per OCR invocation",
    )
    p_index.add_argument("--json-summary", action="store_true",
                         help="Print JSON summary instead of progress logs")

    p_search = sub.add_parser("search", help="Retrieve top matching chunks")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=resolved.search_top_k)

    p_ask = sub.add_parser(
        "ask", help="Answer question with retrieved document context")
    p_ask.add_argument("--query", required=True)
    p_ask.add_argument("--top-k", type=int, default=resolved.ask_top_k)
    p_ask.add_argument("--answer-model", default="qwen2.5:14b")
    p_ask.add_argument(
        "--answer-timeout",
        type=int,
        default=resolved.ask_answer_timeout,
        help="Network timeout in seconds for /api/generate while producing grounded answers",
    )
    p_ask.add_argument(
        "--include-path",
        action="append",
        default=[],
        help="Only include chunks from this exact document path (repeatable)",
    )
    p_ask.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Exclude chunks from this exact document path (repeatable)",
    )
    p_ask.add_argument("--deepen", action="store_true",
                       help="Expand context from top matching source documents")
    p_ask.add_argument("--deep-seed-docs", type=int, default=2,
                       help="Number of top documents to deepen from")
    p_ask.add_argument("--deep-extra-k", type=int, default=12,
                       help="Additional chunks to add during deepen mode")
    p_ask.add_argument("--json-output", action="store_true",
                       help="Print JSON answer payload")
    p_ask.add_argument(
        "--debug-trace",
        action="store_true",
        help="Include retrieval score-component trace in JSON output",
    )

    p_synthesize = sub.add_parser(
        "synthesize", help="Map relevant source documents with one-sentence relevancy summaries")
    p_synthesize.add_argument("--query", required=True)
    p_synthesize.add_argument("--top-k", type=int, default=resolved.ask_top_k)
    p_synthesize.add_argument("--answer-model", default="qwen2.5:14b")
    p_synthesize.add_argument(
        "--answer-timeout",
        type=int,
        default=90,
        help="Network timeout in seconds for the synthesis LLM call",
    )
    p_synthesize.add_argument(
        "--include-path",
        action="append",
        default=[],
        help="Only include chunks from this exact document path (repeatable)",
    )
    p_synthesize.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Exclude chunks from this exact document path (repeatable)",
    )
    p_synthesize.add_argument("--json-output", action="store_true",
                              help="Print JSON source map payload")

    sub.add_parser("status", help="Print JSON index status")

    p_verify = sub.add_parser(
        "verify", help="Audit indexed document quality and coverage")
    p_verify.add_argument(
        "--min-chunks-per-page",
        type=float,
        default=0.2,
        help="Flag docs with non-zero chunks but very low chunk density",
    )
    p_verify.add_argument(
        "--list-limit",
        type=int,
        default=25,
        help="Max sample rows to print per issue category",
    )
    p_verify.add_argument("--json-output", action="store_true",
                          help="Print JSON verification payload")
    p_verify.add_argument("--fail-on-issues", action="store_true",
                          help="Return exit code 2 when verification finds issues")

    p_meta = sub.add_parser(
        "metadata-sync",
        help="Extract and update title/author/year metadata for existing indexed documents",
    )
    p_meta.add_argument(
        "--source",
        default=resolved.source_dir,
        help="Directory containing document library (.pdf, .txt, .md, .html, .htm, .epub)",
    )
    p_meta.add_argument("--json-output", action="store_true",
                        help="Print JSON metadata sync payload")

    p_doctor = sub.add_parser(
        "doctor",
        help="Run non-interactive environment and dependency diagnostics",
    )
    p_doctor.add_argument(
        "--source",
        default=resolved.source_dir,
        help="Directory containing document library (.pdf, .txt, .md, .html, .htm, .epub)",
    )
    p_doctor.add_argument(
        "--answer-model",
        default="qwen2.5:14b",
        help="Answer model that should be available in Ollama",
    )
    p_doctor.add_argument(
        "--required-model",
        action="append",
        default=[],
        help="Additional required model name (repeatable)",
    )
    p_doctor.add_argument(
        "--web-host",
        default=resolved.web_host,
        help="Configured web bind host to validate",
    )
    p_doctor.add_argument(
        "--web-port",
        type=int,
        default=resolved.web_port,
        help="Configured web bind port to validate",
    )
    p_doctor.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Network timeout in seconds for Ollama checks",
    )
    p_doctor.add_argument("--json-output", action="store_true",
                          help="Print JSON doctor payload")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "index":
        return index_command(args)
    if args.cmd == "search":
        return search_command(args)
    if args.cmd == "ask":
        return ask_command(args)
    if args.cmd == "synthesize":
        return synthesize_command(args)
    if args.cmd == "status":
        return status_command(args)
    if args.cmd == "verify":
        return verify_command(args)
    if args.cmd == "metadata-sync":
        return metadata_sync_command(args)
    if args.cmd == "doctor":
        return doctor_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
