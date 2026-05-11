#!/usr/bin/env python3

import argparse
from html import unescape
from html.parser import HTMLParser
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pypdf import PdfReader

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


def http_post_json(base_url: str, endpoint: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{base_url.rstrip('/')}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {base_url}: {exc}") from exc


def embed_text(base_url: str, model: str, text: str) -> list[float]:
    # Newer Ollama endpoint.
    try:
        data = http_post_json(base_url, "/api/embed",
                              {"model": model, "input": text})
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
                          {"model": model, "prompt": text})
    if isinstance(data.get("embedding"), list):
        return [float(v) for v in data["embedding"]]
    raise RuntimeError("Unexpected embedding response format from Ollama")


def generate_answer(base_url: str, model: str, prompt: str) -> str:
    data = http_post_json(
        base_url,
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "60s",
        },
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

    conn = sqlite3.connect(str(index_db))
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

    conn = sqlite3.connect(str(index_db))
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
                    emb = embed_text(args.ollama_base, args.embed_model, chunk)
                except Exception as exc:
                    print(
                        f"[warn] embedding failed for {doc_path} unit {page_num}: {exc}", file=sys.stderr)
                    continue
                chunk_rows.append(
                    (page_num, i, chunk, json.dumps(emb, separators=(",", ":"))))
                chunk_count += 1

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

    removed = 0
    conn.commit()
    if args.prune:
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
        SELECT d.path, c.page_num, c.text, c.embedding_json
        FROM chunks c
        JOIN documents d ON c.doc_id = d.id
        """
    ).fetchall()


def retrieve_top_chunks(conn: sqlite3.Connection, query_embedding: list[float], top_k: int):
    return retrieve_top_chunks_filtered(conn, query_embedding, top_k, None, None)


def retrieve_top_chunks_filtered(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int,
    include_paths: set[str] | None,
    exclude_paths: set[str] | None,
):
    rows = load_all_chunks(conn)
    scored = []
    for path, page_num, text, emb_json in rows:
        path = str(path)
        if include_paths and path not in include_paths:
            continue
        if exclude_paths and path in exclude_paths:
            continue
        try:
            emb = json.loads(emb_json)
            score = cosine_similarity(query_embedding, emb)
        except Exception:
            continue
        scored.append((score, path, int(page_num), str(text)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


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

    conn = sqlite3.connect(str(index_db))
    q_emb = embed_text(args.ollama_base, args.embed_model, args.query)
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

    conn = sqlite3.connect(str(index_db))
    q_emb = embed_text(args.ollama_base, args.embed_model, args.query)
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
    top = retrieve_top_chunks_filtered(
        conn,
        q_emb,
        args.top_k,
        include_paths if include_paths else None,
        exclude_paths if exclude_paths else None,
    )

    if args.deepen and top:
        seed_paths = {path for _, path, _,
                      _ in top[: max(1, args.deep_seed_docs)]}
        seen = {(path, page, text) for _, path, page, text in top}
        expanded = []
        for path, page_num, text, emb_json in load_all_chunks(conn):
            path = str(path)
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
    answer = generate_answer(args.ollama_base, args.answer_model, prompt)
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
        print(json.dumps({"ok": True, "answer": answer,
              "sources": sources}, ensure_ascii=True))
        return 0

    print(answer)
    print("\nSources:")
    for score, path, page, _ in top:
        print(f"- {path} (page {page}, score={score:.4f})")
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

    conn = sqlite3.connect(str(index_db))
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

    conn = sqlite3.connect(str(index_db))
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


def build_parser():
    parser = argparse.ArgumentParser(
        description="Index documents from NAS/local storage into a retrieval DB and query with Ollama.",
    )
    parser.add_argument(
        "--ollama-base",
        default="http://127.0.0.1:11434",
        help="Ollama base URL",
    )
    parser.add_argument(
        "--embed-model",
        default="nomic-embed-text",
        help="Embedding model name available in Ollama",
    )
    parser.add_argument(
        "--index-db",
        default="~/Library/Application Support/home-network-setup/pdf-rag.sqlite",
        help="Local sqlite index path",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser(
        "index", help="Index supported documents under a source directory")
    p_index.add_argument(
        "--source",
        default=resolve_default_pdf_source(),
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
        default="eng",
        help="OCR language for ocrmypdf (e.g. eng, eng+spa)",
    )
    p_index.add_argument(
        "--ocr-jobs",
        type=int,
        default=2,
        help="Parallel OCR worker count",
    )
    p_index.add_argument(
        "--ocr-timeout",
        type=int,
        default=1800,
        help="Max seconds per OCR invocation",
    )
    p_index.add_argument("--json-summary", action="store_true",
                         help="Print JSON summary instead of progress logs")

    p_search = sub.add_parser("search", help="Retrieve top matching chunks")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=6)

    p_ask = sub.add_parser(
        "ask", help="Answer question with retrieved document context")
    p_ask.add_argument("--query", required=True)
    p_ask.add_argument("--top-k", type=int, default=6)
    p_ask.add_argument("--answer-model", default="qwen2.5:14b")
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
        default=resolve_default_pdf_source(),
        help="Directory containing document library (.pdf, .txt, .md, .html, .htm, .epub)",
    )
    p_meta.add_argument("--json-output", action="store_true",
                        help="Print JSON metadata sync payload")

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
    if args.cmd == "status":
        return status_command(args)
    if args.cmd == "verify":
        return verify_command(args)
    if args.cmd == "metadata-sync":
        return metadata_sync_command(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
