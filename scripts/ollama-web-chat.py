#!/usr/bin/env python3

import json
import logging
import mimetypes
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
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
MAX_UPLOAD_BYTES = max(1024, int(os.environ.get(
    "OLLAMA_WEB_MAX_UPLOAD_BYTES", "536870912")))
SUPPORTED_DOC_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".epub"}
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
APP_VERSION_FILE = REPO_ROOT / "scripts" / "VERSION"
UPDATE_STATE_PATH = Path(os.path.dirname(HISTORY_PATH)
                         or str(REPO_ROOT)) / "update-state.json"
UPDATE_REPO_OWNER = os.environ.get(
    "OLLAMA_WEB_UPDATE_REPO_OWNER", "reprahkcin")
UPDATE_REPO_NAME = os.environ.get(
    "OLLAMA_WEB_UPDATE_REPO_NAME", "ollama-librarian")
UPDATE_GITHUB_TOKEN = os.environ.get("OLLAMA_WEB_UPDATE_GITHUB_TOKEN", "")
UPDATE_GIT_BRANCH = os.environ.get("OLLAMA_WEB_UPDATE_BRANCH", "main")
UPDATE_APPLY_MODE = os.environ.get(
    "OLLAMA_WEB_UPDATE_APPLY_MODE", "git").strip().lower()
UPDATE_APPLY_MODE_RESOLVED = (
    UPDATE_APPLY_MODE if UPDATE_APPLY_MODE in {"git", "script"} else "git"
)
UPDATE_SCRIPT_MACOS = REPO_ROOT / "scripts" / "librarian-update-macos.sh"
UPDATE_SCRIPT_WINDOWS = REPO_ROOT / "scripts" / "librarian-update-windows.ps1"
LOGGER = logging.getLogger("ollama_web_chat")

PDF_INDEX_STATE = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
}
UPDATE_LOCK = threading.Lock()
UPDATE_STATE = {
    "job_id": None,
    "running": False,
    "state": "idle",
    "step": "none",
    "progress_pct": 0,
    "message": "Not checked",
    "started_at": None,
    "finished_at": None,
    "last_checked_at": None,
    "current_version": None,
    "latest_version": None,
    "source": None,
    "apply_mode": UPDATE_APPLY_MODE_RESOLVED,
    "branch": UPDATE_GIT_BRANCH,
    "apply_target": UPDATE_GIT_BRANCH,
    "local_sha": None,
    "remote_sha": None,
    "update_available": False,
    "target_version": None,
    "last_error": None,
}


def _persist_update_state_unlocked():
    try:
        UPDATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = UPDATE_STATE_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(UPDATE_STATE, f, ensure_ascii=True)
        os.replace(tmp_path, UPDATE_STATE_PATH)
    except Exception as exc:
        LOGGER.exception("Failed to persist update state")


def _set_update_state(**changes):
    with UPDATE_LOCK:
        UPDATE_STATE.update(changes)
        _persist_update_state_unlocked()


def _load_update_state():
    try:
        if not UPDATE_STATE_PATH.is_file():
            return
        data = json.loads(UPDATE_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        with UPDATE_LOCK:
            for key in list(UPDATE_STATE.keys()):
                if key in data:
                    UPDATE_STATE[key] = data[key]
            # Recover from stale in-progress state left behind by crash/restart.
            if UPDATE_STATE.get("running"):
                now = int(time.time())
                UPDATE_STATE["running"] = False
                UPDATE_STATE["state"] = "failed"
                UPDATE_STATE["step"] = "recovered_after_restart"
                UPDATE_STATE["finished_at"] = now
                UPDATE_STATE["message"] = "Recovered stale update job after restart"
                if not UPDATE_STATE.get("last_error"):
                    UPDATE_STATE["last_error"] = (
                        "Previous update job did not complete before restart"
                    )
                _persist_update_state_unlocked()
    except Exception as exc:
        LOGGER.exception("Failed to load persisted update state")
        with UPDATE_LOCK:
            UPDATE_STATE["last_error"] = f"Failed to load persisted update state: {exc}"


_load_update_state()


def read_current_version() -> str:
    try:
        text = APP_VERSION_FILE.read_text(encoding="utf-8").strip()
        return text or "v0.0.0"
    except Exception:
        return "v0.0.0"


def _resolved_update_apply_mode() -> str:
    return UPDATE_APPLY_MODE_RESOLVED


def _parse_semver(v: str) -> tuple[int, int, int] | None:
    raw = str(v or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:]
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return None


def is_newer_version(latest: str, current: str) -> bool:
    latest_tuple = _parse_semver(latest)
    current_tuple = _parse_semver(current)
    if latest_tuple is None or current_tuple is None:
        return False
    return latest_tuple > current_tuple


def fetch_latest_release() -> dict:
    api_url = (
        f"https://api.github.com/repos/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/releases/latest"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ollama-librarian-update-check",
    }
    if UPDATE_GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {UPDATE_GITHUB_TOKEN}"
    req = Request(api_url, headers=headers)
    with urlopen(req, timeout=15) as resp:
        payload = resp.read().decode("utf-8")
    data = json.loads(payload) if payload else {}
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected release payload")
    if data.get("draft"):
        raise RuntimeError("Latest release is draft")

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("Latest release missing tag_name")

    return {
        "tag": tag,
        "published_at": data.get("published_at"),
        "notes_url": data.get("html_url"),
    }


def get_update_status() -> dict:
    current = read_current_version()
    with UPDATE_LOCK:
        state = dict(UPDATE_STATE)

    origin_url = ""
    origin_matches = None
    try:
        origin_url = _get_origin_remote_url()
        origin_matches = _origin_matches_configured_repo(origin_url)
    except Exception:
        origin_url = ""
        origin_matches = None

    state["current_version"] = current
    state["origin_remote"] = origin_url
    state["origin_matches_repo"] = origin_matches

    return {
        "ok": True,
        "repo": f"{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}",
        **state,
    }


def _run_git(args: list[str], timeout: int = 60) -> tuple[str, str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT)] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(
            err or out or f"git command failed: {' '.join(args)}")
    return out, err


def _get_origin_remote_url() -> str:
    out, _ = _run_git(["remote", "get-url", "origin"], timeout=20)
    return out.splitlines()[0].strip() if out else ""


def _origin_matches_configured_repo(origin_url: str) -> bool:
    normalized = str(origin_url or "").strip().lower()
    if not normalized:
        return False
    owner = UPDATE_REPO_OWNER.strip().lower()
    name = UPDATE_REPO_NAME.strip().lower()
    slash_form = f"github.com/{owner}/{name}"
    scp_form = f"github.com:{owner}/{name}"
    return slash_form in normalized or scp_form in normalized


def _ensure_origin_matches_configured_repo() -> None:
    origin_url = _get_origin_remote_url()
    if not _origin_matches_configured_repo(origin_url):
        raise RuntimeError(
            "git remote 'origin' does not match configured update repo "
            f"{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}"
        )


def _run_update_script(target_version: str, timeout: int = 300) -> tuple[str, str]:
    branch = str(target_version or UPDATE_GIT_BRANCH).strip(
    ) or UPDATE_GIT_BRANCH
    if os.name == "nt":
        if not UPDATE_SCRIPT_WINDOWS.is_file():
            raise RuntimeError(
                f"Updater script not found: {UPDATE_SCRIPT_WINDOWS}")
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATE_SCRIPT_WINDOWS),
            "-Branch",
            branch,
        ]
    else:
        if not UPDATE_SCRIPT_MACOS.is_file():
            raise RuntimeError(
                f"Updater script not found: {UPDATE_SCRIPT_MACOS}")
        cmd = [str(UPDATE_SCRIPT_MACOS), "--branch", branch]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or "Update script failed")
    return out, err


def check_for_git_updates() -> dict:
    mode = _resolved_update_apply_mode()
    _ensure_origin_matches_configured_repo()
    local_out, _ = _run_git(["rev-parse", "HEAD"], timeout=20)
    remote_out, _ = _run_git(
        ["ls-remote", "origin", f"refs/heads/{UPDATE_GIT_BRANCH}"],
        timeout=20,
    )
    local_sha = local_out.splitlines()[0].strip() if local_out else ""
    remote_sha = ""
    if remote_out:
        remote_sha = remote_out.split()[0].strip()

    if not local_sha or not remote_sha:
        raise RuntimeError("Unable to resolve local/remote git revision")

    available = local_sha != remote_sha
    now = int(time.time())
    _set_update_state(
        state="available" if available else "idle",
        step="checked",
        progress_pct=100,
        message=(
            f"Repository update available ({remote_sha[:8]})"
            if available
            else "Repository is up to date"
        ),
        latest_version=remote_sha[:8],
        source="git",
        apply_mode=mode,
        branch=UPDATE_GIT_BRANCH,
        apply_target=UPDATE_GIT_BRANCH,
        local_sha=local_sha,
        remote_sha=remote_sha,
        update_available=available,
        last_checked_at=now,
        last_error=None,
    )
    out = get_update_status()
    return out


def check_for_updates() -> dict:
    mode = _resolved_update_apply_mode()
    current = read_current_version()
    _set_update_state(
        state="checking",
        step="fetch_latest_release",
        message="Checking latest release",
        last_error=None,
        current_version=current,
    )
    try:
        release = fetch_latest_release()
        latest = str(release.get("tag") or "").strip()
        available = is_newer_version(latest, current)
        now = int(time.time())
        _set_update_state(
            state="available" if available else "idle",
            step="checked",
            progress_pct=100,
            message=(
                f"Update available: {latest}" if available else "You are up to date"
            ),
            latest_version=latest,
            source="release",
            apply_mode=mode,
            branch=UPDATE_GIT_BRANCH,
            apply_target=UPDATE_GIT_BRANCH,
            local_sha=None,
            remote_sha=None,
            update_available=available,
            last_checked_at=now,
            last_error=None,
        )
        out = get_update_status()
        out["release"] = release
        return out
    except HTTPError as exc:
        if int(getattr(exc, "code", 0) or 0) == 404:
            return check_for_git_updates()

        now = int(time.time())
        _set_update_state(
            state="failed",
            step="check_failed",
            progress_pct=0,
            message="Update check failed",
            last_checked_at=now,
            source=None,
            last_error=str(exc),
        )
        out = get_update_status()
        out["ok"] = False
        out["error"] = str(exc)
        return out
    except Exception as exc:
        now = int(time.time())
        _set_update_state(
            state="failed",
            step="check_failed",
            progress_pct=0,
            message="Update check failed",
            last_checked_at=now,
            source=None,
            last_error=str(exc),
        )
        out = get_update_status()
        out["ok"] = False
        out["error"] = str(exc)
        return out


def _apply_update_worker(job_id: str, target_version: str):
    started_at = int(time.time())
    mode = _resolved_update_apply_mode()
    _set_update_state(
        running=True,
        job_id=job_id,
        target_version=target_version or UPDATE_GIT_BRANCH,
        state="applying",
        step="starting",
        progress_pct=10,
        message="Starting update apply",
        started_at=started_at,
        finished_at=None,
        last_error=None,
    )
    try:
        changed = False
        if mode == "script":
            _set_update_state(
                state="applying",
                step="script_apply",
                progress_pct=55,
                message="Applying update with platform script",
            )
            script_out, _ = _run_update_script(target_version, timeout=600)
            changed = "already up to date" not in script_out.lower()
        else:
            _set_update_state(
                state="applying",
                step="git_fetch",
                progress_pct=30,
                message="Fetching repository updates",
            )
            _run_git(["fetch", "origin", target_version], timeout=90)
            _set_update_state(
                state="applying",
                step="git_pull",
                progress_pct=55,
                message="Applying fast-forward update",
            )
            pull_out, _ = _run_git(
                ["pull", "--ff-only", "origin", target_version], timeout=120
            )
            changed = "Already up to date" not in pull_out

        finished_at = int(time.time())
        _set_update_state(
            running=False,
            state="done",
            step="completed",
            progress_pct=100,
            message=(
                "Update applied. Restart app services to pick up all changes."
                if changed
                else "Already up to date"
            ),
            update_available=False,
            target_version=target_version,
            finished_at=finished_at,
            last_error=None,
        )
    except Exception as exc:
        finished_at = int(time.time())
        _set_update_state(
            running=False,
            state="failed",
            step="apply_failed",
            progress_pct=0,
            message="Update apply failed",
            finished_at=finished_at,
            last_error=str(exc),
        )


def _git_worktree_is_clean() -> tuple[bool, str]:
    out, _ = _run_git(["status", "--porcelain"], timeout=20)
    if not out.strip():
        return True, ""
    lines = out.splitlines()
    sample = " | ".join(lines[:3])
    return False, sample


def _git_current_branch() -> str:
    out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=20)
    return out.splitlines()[0].strip() if out else ""


def _is_valid_branch_target(target: str) -> bool:
    value = str(target or "").strip()
    # Keep a conservative branch charset to prevent option/path injection.
    return bool(re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", value))


def start_update_apply(target_version: str) -> dict:
    now = int(time.time())
    mode = _resolved_update_apply_mode()
    requested_target = str(target_version or "").strip()
    resolved_target = UPDATE_GIT_BRANCH

    if requested_target and not _is_valid_branch_target(requested_target):
        return {
            "ok": False,
            "started": False,
            "error": "Invalid target_version",
            "error_code": "invalid_target",
            "state": get_update_status(),
        }

    if requested_target and requested_target != UPDATE_GIT_BRANCH:
        return {
            "ok": False,
            "started": False,
        "error": f"update apply only supports target '{UPDATE_GIT_BRANCH}'",
            "error_code": "invalid_target",
            "state": get_update_status(),
        }

    job_id = f"update-{now}-{uuid.uuid4().hex[:8]}"

    with UPDATE_LOCK:
        if UPDATE_STATE.get("running"):
            return {
                "ok": False,
                "started": False,
                "error": "Update job already running",
                "error_code": "already_running",
                "state": dict(UPDATE_STATE),
            }
        UPDATE_STATE.update({
            "running": True,
            "job_id": job_id,
            "target_version": resolved_target,
            "state": "applying",
            "step": "preflight",
            "progress_pct": 2,
            "message": f"Running update preflight for {resolved_target} ({mode} mode)",
            "started_at": now,
            "finished_at": None,
            "last_error": None,
            "apply_mode": mode,
        })
        _persist_update_state_unlocked()

    try:
        if mode == "script":
            if os.name == "nt":
                if not UPDATE_SCRIPT_WINDOWS.is_file():
                    raise RuntimeError(
                        f"Updater script not found: {UPDATE_SCRIPT_WINDOWS}"
                    )
            else:
                if not UPDATE_SCRIPT_MACOS.is_file():
                    raise RuntimeError(
                        f"Updater script not found: {UPDATE_SCRIPT_MACOS}"
                    )

        current_branch = _git_current_branch()
        if current_branch != UPDATE_GIT_BRANCH:
            raise RuntimeError(
                f"Cannot apply update while on branch '{current_branch}'"
            )

        clean, dirty_sample = _git_worktree_is_clean()
        if not clean:
            raise RuntimeError(
                f"Working tree is dirty. Commit/stash changes first ({dirty_sample})"
            )

        _ensure_origin_matches_configured_repo()
        _run_git(["ls-remote", "origin",
           f"refs/heads/{resolved_target}"], timeout=20)
    except Exception as exc:
        finished_at = int(time.time())
        _set_update_state(
            running=False,
            state="failed",
            step="preflight_failed",
            progress_pct=0,
            message="Update preflight failed",
            finished_at=finished_at,
            last_error=str(exc),
            apply_mode=mode,
        )
        return {
            "ok": False,
            "started": False,
            "error": f"Update preflight failed: {exc}",
            "error_code": "preflight_failed",
            "state": get_update_status(),
        }

    _set_update_state(
        running=True,
        job_id=job_id,
        target_version=resolved_target,
        state="applying",
        step="queued",
        progress_pct=5,
        message=f"Update queued for {resolved_target} ({mode} mode)",
        started_at=now,
        finished_at=None,
        last_error=None,
        apply_mode=mode,
    )
    try:
        t = threading.Thread(
            target=_apply_update_worker,
            args=(job_id, resolved_target),
            daemon=True,
        )
        t.start()
    except Exception as exc:
        finished_at = int(time.time())
        _set_update_state(
            running=False,
            state="failed",
            step="apply_start_failed",
            progress_pct=0,
            message="Failed to launch update worker",
            finished_at=finished_at,
            last_error=str(exc),
            apply_mode=mode,
        )
        return {
            "ok": False,
            "started": False,
            "error": f"Failed to launch update worker: {exc}",
            "error_code": "apply_start_failed",
            "state": get_update_status(),
        }
    status = get_update_status()
    return {
        "ok": True,
        "started": True,
        "job_id": job_id,
        "message": "Update job started",
        "state": status,
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


def _normalize_entry_type(value) -> str:
    if not isinstance(value, str):
        return "response"
    cleaned = value.strip().lower()
    return cleaned if cleaned else "response"


def list_stash_entries(limit: int = 200, entry_type: str | None = None) -> dict:
    with STASH_LOCK:
        entries = _read_stash_entries_unlocked()

    indexed = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        item["entry_type"] = _normalize_entry_type(item.get("entry_type"))
        item["stash_id"] = idx
        if entry_type and item["entry_type"] != entry_type:
            continue
        indexed.append(item)

    indexed.reverse()
    if limit > 0:
        indexed = indexed[:limit]

    return {
        "ok": True,
        "count": len(indexed),
        "total_count": len(entries),
        "entry_type": entry_type or "all",
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


def clear_stash_entries(entry_type: str | None = None) -> dict:
    with STASH_LOCK:
        entries = _read_stash_entries_unlocked()
        if not entry_type:
            _write_stash_entries_unlocked([])
            return {"ok": True, "count": 0, "stash_path": STASH_PATH, "entry_type": "all"}

        kept = []
        removed = 0
        for entry in entries:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            e_type = _normalize_entry_type(entry.get("entry_type"))
            if e_type == entry_type:
                removed += 1
                continue
            kept.append(entry)
        _write_stash_entries_unlocked(kept)
        return {
            "ok": True,
            "count": len(kept),
            "removed": removed,
            "stash_path": STASH_PATH,
            "entry_type": entry_type,
        }


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
    real_paths = [
        os.path.realpath(os.path.expanduser(str(path)))
        for path, _, _ in rows
        if path
    ]

    fallback_root = ""
    if real_paths:
        try:
            common = os.path.commonpath(real_paths)
        except ValueError:
            common = ""
        if common:
            fallback_root = common if os.path.isdir(
                common) else os.path.dirname(common)

    def _rel_for(real_path: str, raw_path: str) -> str:
        if source_root and real_path.startswith(source_root + os.sep):
            return os.path.relpath(real_path, source_root)
        if fallback_root and real_path.startswith(fallback_root + os.sep):
            return os.path.relpath(real_path, fallback_root)
        return os.path.basename(raw_path)

    docs = []
    groups: dict[str, int] = {}
    for path, pages, chunks in rows:
        path_str = str(path)
        real_path = os.path.realpath(os.path.expanduser(path_str))

        rel = _rel_for(real_path, path_str)

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


def build_inline_content_disposition(filename: str) -> str:
    raw = str(filename or "").strip()
    if not raw:
        raw = "document"

    fallback = "".join(
        ch if 32 <= ord(ch) <= 126 and ch not in {'"', "\\", ";"} else "_"
        for ch in raw
    ).strip()
    if not fallback:
        fallback = "document"

    encoded = quote(raw, safe="")
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


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
  <title>Ollama Librarian</title>
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
      display: flex;
      align-items: center;
      gap: 0.45rem;
      width: 100%;
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
    .md .source-line {
      margin: 0.08rem 0 0.32rem;
      display: flex;
      flex-wrap: wrap;
      gap: 0.3rem;
    }
    .md .source-link,
    .md .source-link-static,
    .md .source-inline {
      display: inline;
      color: #94a3b8;
      font-size: 0.68rem;
      font-weight: 600;
      letter-spacing: 0.01em;
      text-transform: lowercase;
      text-decoration: none;
      cursor: help;
    }
    .md .source-link {
      cursor: pointer;
    }
    .md .source-link:hover,
    .md .source-link-static:hover,
    .md .source-inline:hover {
      color: #cbd5e1;
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
    .citation-list {
      margin-top: 0.5rem;
      display: grid;
      gap: 0.35rem;
    }
    .citation-row {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: start;
      gap: 0.45rem;
      border: 1px solid #334155;
      border-radius: 10px;
      background: #0f172a;
      padding: 0.35rem 0.45rem;
    }
    .citation-text {
      font-size: 0.82rem;
      line-height: 1.35;
      color: var(--ink);
      word-break: break-word;
    }
    .citation-row .stash-btn {
      margin-right: 0;
      min-width: 58px;
      padding: 0.18rem 0.48rem;
      font-size: 0.69rem;
      align-self: center;
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
    .model-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.4rem;
      align-items: center;
      margin-bottom: 0.25rem;
    }
    .btn-mini {
      min-width: 70px;
      padding: 0.28rem 0.45rem;
      font-size: 0.72rem;
    }
    .model-row #refresh {
      align-self: stretch;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding-top: 0;
      padding-bottom: 0;
    }
    .pdf-progress {
      height: 0.42rem;
      border-radius: 999px;
      border: 1px solid #334155;
      background: #0b1220;
      overflow: hidden;
      margin-top: 0.35rem;
    }
    .pdf-progress.hidden {
      display: none;
    }
    .pdf-progress-bar {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #0d9488, #22d3ee);
      transition: width 220ms ease;
    }
    .prompt-history-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto auto;
      gap: 0.4rem;
      align-items: center;
    }
    .prompt-history-row select {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.38rem 0.48rem;
      background: #111827;
      color: var(--ink);
      font-size: 0.76rem;
    }
    .prompt-history-row button {
      min-width: 70px;
      padding: 0.28rem 0.45rem;
      font-size: 0.72rem;
    }
    textarea {
      min-height: 92px;
      resize: vertical;
    }
    .composer-row {
      display: flex;
      gap: 0.5rem;
      align-items: stretch;
    }
    .composer-row button {
      width: auto;
      min-width: 110px;
      min-height: 46px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      line-height: 1.2;
      padding-top: 0.42rem;
      padding-bottom: 0.42rem;
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
    #pdfStatus {
      white-space: pre-line;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
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
      max-height: 92vh;
      overflow: hidden;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: #0b1220;
      display: flex;
      flex-direction: column;
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
      max-height: clamp(8rem, 22vh, 14rem);
      overflow: auto;
      background: #0a1325;
      flex: 0 0 auto;
    }
    .docs-group-row {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 0.45rem;
      font-size: 0.75rem;
      color: var(--muted);
    }
    .docs-group-root {
      color: #cbd5e1;
      font-weight: 600;
    }
    .docs-group-child .docs-group-label {
      padding-left: 1rem;
      color: #9ca3af;
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
      flex: 1 1 auto;
      min-height: 14rem;
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
    @media (max-height: 760px) {
      .docs-modal {
        padding: 0.55rem;
      }
      .docs-card {
        max-height: 96vh;
      }
      .docs-groups {
        max-height: clamp(6.5rem, 18vh, 9rem);
      }
      .docs-actions button {
        min-width: 68px;
        padding: 0.34rem 0.46rem;
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
      <h1 class="title">Ollama Librarian</h1>
      <div class="meta">Endpoint: %OLLAMA_BASE%</div>
      <div id="status" class="status">
        <span id="statusDot" class="dot"></span>
        <span id="statusText">Checking service...</span>
      </div>

      <label for="model">Model</label>
      <div class="model-row">
        <select id="model"></select>
        <button id="refresh" class="btn-soft btn-mini" type="button">Refresh</button>
      </div>

      <label for="instructions">Running Instructions</label>
      <textarea id="instructions" placeholder="Example: Be concise. Use bullet points. Ask clarifying questions if uncertain."></textarea>
      <button id="saveInstructions" class="btn-soft" type="button">Save Instructions</button>

      <label>PDF Library</label>
      <label class="checkrow" for="usePdfLibrary" title="Use retrieval from your indexed PDF library instead of plain model-only responses.">
        <input id="usePdfLibrary" type="checkbox" checked title="Use retrieval from your indexed PDF library instead of plain model-only responses." />
        Use PDF-grounded answers
      </label>
      <label class="checkrow" for="deepStudy" title="Expands retrieval depth and context for more thorough, citation-heavy answers. Slower but usually more complete.">
        <input id="deepStudy" type="checkbox" title="Expands retrieval depth and context for more thorough, citation-heavy answers. Slower but usually more complete." />
        Deep Study Mode
      </label>
      <button id="syncPdfLibrary" class="btn-soft" type="button" title="Indexes new or changed PDFs. OCR fallback is used for scanned/text-only images when available.">Sync New PDFs</button>
      <button id="uploadLibraryDocs" class="btn-soft" type="button" title="Upload supported documents into the configured library (.pdf, .txt, .md, .html, .htm, .epub).">Upload Documents</button>
      <input id="libraryUploadInput" type="file" accept=".pdf,.txt,.md,.html,.htm,.epub" multiple style="display:none" />
      <div id="pdfStatus" class="tiny">PDF index: checking...</div>
      <div id="pdfProgress" class="pdf-progress hidden"><div id="pdfProgressBar" class="pdf-progress-bar"></div></div>

      <label>App Updates</label>
      <div id="appVersion" class="tiny">Version: %CURRENT_VERSION%</div>
      <div id="updateStatus" class="tiny">Updates: not checked</div>
      <button id="checkUpdates" class="btn-soft" type="button">Check for Updates</button>
      <button id="applyUpdate" class="btn-soft" type="button" disabled>Update to Latest</button>

      <button id="openLibraryDocs" class="btn-soft" type="button">Library Docs</button>
      <button id="openStash" class="btn-soft" type="button">View Stash</button>
      <button id="openBibliography" class="btn-soft" type="button">View Bibliography</button>
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
        <div class="prompt-history-row">
          <select id="promptHistorySelect" title="Select a previous prompt">
            <option value="">Previous prompts...</option>
          </select>
          <button id="promptUseSelected" class="btn-soft" type="button" title="Ask using the selected prompt">Ask</button>
          <button id="promptPinSelected" class="btn-soft" type="button" title="Pin or unpin the selected prompt">Pin</button>
          <button id="promptClearHistory" class="btn-soft" type="button" title="Clear unpinned prompt history">Clear</button>
        </div>
        <div class="composer-row">
          <button id="send" class="btn-primary" type="button">Send</button>
          <button id="cancel" class="btn-soft" type="button" disabled>Cancel</button>
          <button id="studyBrief" class="btn-soft" type="button" title="Creates a structured brief from your PDF library with citations and suggested reading order.">Study Brief</button>
          <button id="makeBibliography" class="btn-soft" type="button" title="Generates an APA bibliography from the latest PDF-grounded answer and opens bibliography stash.">Generate Bibliography</button>
          <div id="meta" class="subtle">Ready</div>
        </div>
      </div>
    </section>
  </main>

  <div id="stashModal" class="stash-modal stash-hidden">
    <div class="stash-card">
      <div class="stash-head">
        <h3 id="stashTitle">Stashed Snippets</h3>
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
    const openBibliographyEl = document.getElementById('openBibliography');
    const instructionsEl = document.getElementById('instructions');
    const saveInstructionsEl = document.getElementById('saveInstructions');
    const usePdfLibraryEl = document.getElementById('usePdfLibrary');
    const deepStudyEl = document.getElementById('deepStudy');
    const syncPdfLibraryEl = document.getElementById('syncPdfLibrary');
    const uploadLibraryDocsEl = document.getElementById('uploadLibraryDocs');
    const libraryUploadInputEl = document.getElementById('libraryUploadInput');
    const pdfProgressEl = document.getElementById('pdfProgress');
    const pdfProgressBarEl = document.getElementById('pdfProgressBar');
    const appVersionEl = document.getElementById('appVersion');
    const updateStatusEl = document.getElementById('updateStatus');
    const checkUpdatesEl = document.getElementById('checkUpdates');
    const applyUpdateEl = document.getElementById('applyUpdate');
    const studyBriefEl = document.getElementById('studyBrief');
    const makeBibliographyEl = document.getElementById('makeBibliography');
    const promptHistorySelectEl = document.getElementById('promptHistorySelect');
    const promptUseSelectedEl = document.getElementById('promptUseSelected');
    const promptPinSelectedEl = document.getElementById('promptPinSelected');
    const promptClearHistoryEl = document.getElementById('promptClearHistory');
    const pdfStatusEl = document.getElementById('pdfStatus');
    const messagesEl = document.getElementById('messages');
    const statusDotEl = document.getElementById('statusDot');
    const statusTextEl = document.getElementById('statusText');
    const metaEl = document.getElementById('meta');
    const stashModalEl = document.getElementById('stashModal');
    const stashListEl = document.getElementById('stashList');
    const stashMetaEl = document.getElementById('stashMeta');
    const stashTitleEl = document.getElementById('stashTitle');
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
    let lastUserPrompt = '';
    let libraryDocs = [];
    let libraryGroups = [];
    let excludedDocPaths = new Set();
    let activeRequestController = null;
    let pendingPromptText = '';
    let stashViewMode = 'stash';
    let lastPdfSources = [];
    let lastCitationQuery = '';
    let promptHistory = [];
    let promptHistoryIndex = -1;
    let pinnedPrompts = [];
    let syncSnapshot = null;

    const DOC_FILTER_STORAGE_KEY = 'ollama_web_excluded_docs_v1';
    const PROMPT_HISTORY_STORAGE_KEY = 'ollama_web_prompt_history_v1';
    const PINNED_PROMPTS_STORAGE_KEY = 'ollama_web_pinned_prompts_v1';
    const MAX_PROMPT_HISTORY = 150;
    const MAX_UPLOAD_BYTES = Number('%MAX_UPLOAD_BYTES%');
    const SUPPORTED_UPLOAD_EXTENSIONS = new Set(['.pdf', '.txt', '.md', '.html', '.htm', '.epub']);
    let latestUpdateVersion = '';

    function extensionOfName(name) {
      const raw = String(name || '').trim().toLowerCase();
      const idx = raw.lastIndexOf('.');
      if (idx < 0) return '';
      return raw.slice(idx);
    }

    async function uploadLibraryFiles(fileList) {
      const allFiles = Array.from(fileList || []);
      if (!allFiles.length) return;

      const files = allFiles.filter((f) => SUPPORTED_UPLOAD_EXTENSIONS.has(extensionOfName(f && f.name)));
      if (!files.length) {
        metaEl.textContent = 'No supported files selected (.pdf, .txt, .md, .html, .htm, .epub)';
        return;
      }

      const tooLarge = files.filter((f) => Number(f && f.size) > MAX_UPLOAD_BYTES);
      if (tooLarge.length) {
        const limitMb = Math.round(MAX_UPLOAD_BYTES / (1024 * 1024));
        const sample = tooLarge.slice(0, 2).map((f) => String(f.name || '')).join(' | ');
        metaEl.textContent = `Upload blocked: ${tooLarge.length} file(s) exceed ${limitMb} MB. ${sample}`;
        return;
      }

      uploadLibraryDocsEl.disabled = true;
      const originalText = uploadLibraryDocsEl.textContent;
      uploadLibraryDocsEl.textContent = 'Uploading...';

      let uploaded = 0;
      let failed = 0;
      const failures = [];

      try {
        for (let i = 0; i < files.length; i += 1) {
          const file = files[i];
          metaEl.textContent = `Uploading ${i + 1}/${files.length}: ${file.name}`;
          const url = `/api/library/upload?name=${encodeURIComponent(file.name)}`;
          const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: file,
          });
          let data = {};
          try {
            data = await res.json();
          } catch (_) {
            data = {};
          }
          if (!res.ok || data.ok === false) {
            failed += 1;
            failures.push(`${file.name}: ${data.error || `HTTP ${res.status}`}`);
            continue;
          }
          uploaded += 1;
        }

        if (uploaded > 0) {
          try {
            await fetch('/api/pdf/index', { method: 'POST' });
          } catch (_) {
            // Upload succeeded even if index trigger fails.
          }
          refreshPdfStatus();
          if (!docsModalEl.classList.contains('docs-hidden')) {
            try {
              await loadLibraryDocs();
            } catch (_) {
              // Keep upload success message if docs refresh fails.
            }
          }
        }

        if (failed > 0) {
          const sample = failures.slice(0, 2).join(' | ');
          metaEl.textContent = `Uploaded ${uploaded}, failed ${failed}. ${sample}`;
        } else {
          metaEl.textContent = `Uploaded ${uploaded} file${uploaded === 1 ? '' : 's'}; indexing started`;
        }
      } finally {
        uploadLibraryDocsEl.disabled = false;
        uploadLibraryDocsEl.textContent = originalText;
      }
    }

    function loadPromptHistory() {
      try {
        const raw = localStorage.getItem(PROMPT_HISTORY_STORAGE_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return [];
        return arr
          .filter((x) => typeof x === 'string')
          .map((x) => x.trim())
          .filter(Boolean)
          .slice(-MAX_PROMPT_HISTORY);
      } catch (_) {
        return [];
      }
    }

    function loadPinnedPrompts() {
      try {
        const raw = localStorage.getItem(PINNED_PROMPTS_STORAGE_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return [];
        return arr
          .filter((x) => typeof x === 'string')
          .map((x) => x.trim())
          .filter(Boolean)
          .slice(-MAX_PROMPT_HISTORY);
      } catch (_) {
        return [];
      }
    }

    function persistPromptHistory() {
      try {
        localStorage.setItem(PROMPT_HISTORY_STORAGE_KEY, JSON.stringify(
            promptHistory.slice(-MAX_PROMPT_HISTORY)));
      } catch (_) {
        // Ignore storage errors.
      }
    }

    function persistPinnedPrompts() {
      try {
        localStorage.setItem(PINNED_PROMPTS_STORAGE_KEY, JSON.stringify(
            pinnedPrompts.slice(-MAX_PROMPT_HISTORY)));
      } catch (_) {
        // Ignore storage errors.
      }
    }

    function collectPromptRows() {
      const out = [];
      const seen = new Set();

      for (let i = pinnedPrompts.length - 1; i >= 0; i -= 1) {
        const text = pinnedPrompts[i];
        if (!text || seen.has(text)) continue;
        seen.add(text);
        out.push({ text, pinned: true });
      }

      for (let i = promptHistory.length - 1; i >= 0; i -= 1) {
        const text = promptHistory[i];
        if (!text || seen.has(text)) continue;
        seen.add(text);
        out.push({ text, pinned: false });
      }
      return out;
    }

    function renderPromptHistoryDropdown(selectText = '') {
      if (!promptHistorySelectEl) return;
      const selected = String(selectText || promptHistorySelectEl.value || '');
      const rows = collectPromptRows();

      promptHistorySelectEl.innerHTML = '';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = rows.length ? 'Previous prompts...' : 'No previous prompts';
      promptHistorySelectEl.appendChild(placeholder);

      for (const row of rows) {
        const opt = document.createElement('option');
        opt.value = row.text;
        const shortText = row.text.length > 170 ? `${row.text.slice(0, 170)}...` : row.text;
        opt.textContent = row.pinned ? `[PIN] ${shortText}` : shortText;
        promptHistorySelectEl.appendChild(opt);
      }

      if (selected) {
        promptHistorySelectEl.value = selected;
      }
    }

    function rememberPrompt(text, persist = true) {
      const value = String(text || '').trim();
      if (!value) return;
      const existingIdx = promptHistory.lastIndexOf(value);
      if (existingIdx >= 0) {
        promptHistory.splice(existingIdx, 1);
      }
      promptHistory.push(value);
      if (promptHistory.length > MAX_PROMPT_HISTORY) {
        promptHistory = promptHistory.slice(-MAX_PROMPT_HISTORY);
      }
      promptHistoryIndex = promptHistory.length;
      if (persist) {
        persistPromptHistory();
      }
      renderPromptHistoryDropdown(value);
    }

    function recallPromptHistory(direction) {
      if (!promptHistory.length) {
        metaEl.textContent = 'No saved prompts yet';
        return;
      }

      if (direction < 0) {
        promptHistoryIndex = Math.max(0, promptHistoryIndex - 1);
      } else {
        promptHistoryIndex = Math.min(
            promptHistory.length, promptHistoryIndex + 1);
      }

      if (promptHistoryIndex >= promptHistory.length) {
        promptEl.value = '';
        metaEl.textContent = 'Prompt history: newest';
        return;
      }

      promptEl.value = promptHistory[promptHistoryIndex] || '';
      promptEl.focus();
      promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
      metaEl.textContent = `Prompt history ${promptHistoryIndex + 1}/${promptHistory.length}`;
      renderPromptHistoryDropdown(promptEl.value);
    }

    function usePromptFromDropdown() {
      const selected = String(promptHistorySelectEl.value || '').trim();
      if (!selected) {
        metaEl.textContent = 'Select a prompt from the list first';
        return '';
      }
      promptEl.value = selected;
      promptEl.focus();
      promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
      return selected;
    }

    function togglePinSelectedPrompt() {
      const selected = String(promptHistorySelectEl.value || '').trim();
      if (!selected) {
        metaEl.textContent = 'Select a prompt to pin or unpin';
        return;
      }
      const idx = pinnedPrompts.lastIndexOf(selected);
      if (idx >= 0) {
        pinnedPrompts.splice(idx, 1);
        persistPinnedPrompts();
        renderPromptHistoryDropdown(selected);
        metaEl.textContent = 'Prompt unpinned';
        return;
      }
      pinnedPrompts.push(selected);
      if (pinnedPrompts.length > MAX_PROMPT_HISTORY) {
        pinnedPrompts = pinnedPrompts.slice(-MAX_PROMPT_HISTORY);
      }
      persistPinnedPrompts();
      renderPromptHistoryDropdown(selected);
      metaEl.textContent = 'Prompt pinned';
    }

    function clearPromptHistory() {
      const keepPinned = new Set(pinnedPrompts);
      const before = promptHistory.length;
      promptHistory = promptHistory.filter((p) => keepPinned.has(p));
      promptHistoryIndex = promptHistory.length;
      persistPromptHistory();
      renderPromptHistoryDropdown();
      metaEl.textContent = `Cleared ${Math.max(0, before - promptHistory.length)} unpinned prompts`;
    }

    async function askSelectedPrompt() {
      if (activeRequestController) return;
      const selected = usePromptFromDropdown();
      if (!selected) return;
      await sendPrompt();
    }

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

    function sourceLinkFromDescriptor(rawDescriptor) {
      const raw = String(rawDescriptor || '').trim();
      if (!raw) return null;

      const buildDocHref = (path, loc) => {
        const cleanPath = String(path || '').trim();
        if (!cleanPath) return null;
        const sectionOrPage = Math.max(1, Number(loc || 1));
        if (/\\.epub$/i.test(cleanPath)) {
          return `/epub-reader?path=${strictEncodeURIComponent(cleanPath)}&section=${sectionOrPage}`;
        }
        if (/\\.pdf$/i.test(cleanPath)) {
          return `/api/pdf/file?path=${strictEncodeURIComponent(cleanPath)}#page=${sectionOrPage}`;
        }
        return null;
      };

      const urlMatch = raw.match(/(?:https?:\\/\\/|\\/api\\/pdf\\/file\\?|\\/epub-reader\\?)[^\\s;,)\\]]+/i);
      if (urlMatch) {
        return { href: urlMatch[0], title: raw, label: 'source' };
      }

      const indexed = raw.match(/source\\s+path\\s*(\\d+)(?:\\s*,?\\s*(?:location|page)\\s*(\\d+))?/i);
      if (indexed) {
        const idx = Math.max(1, Number(indexed[1] || 1)) - 1;
        const loc = Number(indexed[2] || 1);
        const src = Array.isArray(lastPdfSources) ? lastPdfSources[idx] : null;
        const path = src && src.path ? String(src.path) : '';
        if (path) {
          const page = Number.isFinite(loc) && loc > 0 ? loc : Number(src.page || src.location || 1);
          const href = buildDocHref(path, Math.max(1, Number(page || 1)));
          if (!href) return null;
          return { href, title: raw, label: 'source' };
        }
      }

      const explicitSource = raw.match(/source\\s*=\\s*(.+?\\.(?:pdf|epub))\\b/i);
      if (explicitSource) {
        const path = String(explicitSource[1] || '').trim();
        const locMatch = raw.match(/(?:location|page)\\s*=\\s*(\\d+)/i);
        const loc = Number(locMatch && locMatch[1] ? locMatch[1] : 1);
        if (path) {
          const href = buildDocHref(path, Math.max(1, loc));
          if (!href) return null;
          return { href, title: raw, label: 'source' };
        }
      }

      const pathMatch = raw.match(/(?:\\/[\\w .\\-()&%+]+)+\\.(?:pdf|epub)\\b/i);
      if (pathMatch) {
        const path = pathMatch[0];
        const pageMatch = raw.match(/(?:page|location|p\\.)\\s*(\\d+)/i);
        const page = Number(pageMatch && pageMatch[1] ? pageMatch[1] : 1);
        const href = buildDocHref(path, Math.max(1, page));
        if (!href) return null;
        return { href, title: raw, label: 'source' };
      }

      return null;
    }

    function protectMathSegments(text) {
      const segments = [];
      let out = String(text || '');
      out = out.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\\n]+\$/g, (m) => {
        const token = `@@MATHSEG_${segments.length}@@`;
        segments.push(m);
        return token;
      });
      return { out, segments };
    }

    function renderInlineMarkdown(text) {
      const protectedMath = protectMathSegments(text);
      let out = protectedMath.out;
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
      out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      out = out.replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/api\/pdf\/file\?|\/epub-reader\?)[^\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      out = out.replace(/\[([^\]]*(?:source\s+path|source\s*=)[^\]]*)\]/gi, (_, inner) => {
        const raw = String(inner || '').trim();
        if (!raw) return '';
        const descriptorMatches = Array.from(raw.matchAll(/source\s+path\s*\d+(?:\s*,?\s*(?:location|page)\s*\d+)?|source\s*=\s*.+?\.(?:pdf|epub)(?:\s+(?:location|page)\s*=\s*\d+)?/gi));
        const descriptors = descriptorMatches.length
          ? descriptorMatches.map((m) => String(m[0] || '').trim()).filter(Boolean)
          : raw.split(/\s*;\s*/).map((x) => String(x || '').trim()).filter(Boolean);

        const links = [];
        for (const descriptor of descriptors) {
          const title = descriptor.replace(/"/g, '&quot;');
          const link = sourceLinkFromDescriptor(descriptor);
          if (link && link.href) {
            links.push(`<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`);
          } else {
            links.push(`<span class="source-inline" title="${title}">source</span>`);
          }
        }
        return links.length ? ` ${links.join(' ')}` : '';
      });
      out = out.replace(/\bsource\s+path\s*\d+(?:\s*,\s*(?:location|page)\s*\d+)?\b/gi, (match) => {
        const link = sourceLinkFromDescriptor(match);
        const title = String(match).replace(/"/g, '&quot;');
        if (link && link.href) {
          return `<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`;
        }
        return `<span class="source-inline" title="${title}">source</span>`;
      });
      out = out.replace(/\bsource\s*=\s*.+?\.(?:pdf|epub)(?:\s+(?:location|page)\s*=\s*\d+)?/gi, (match) => {
        const link = sourceLinkFromDescriptor(match);
        const title = String(match).replace(/"/g, '&quot;');
        if (link && link.href) {
          return `<a class="source-inline" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">source</a>`;
        }
        return `<span class="source-inline" title="${title}">source</span>`;
      });
      out = out.replace(/@@MATHSEG_(\d+)@@/g, (_, idx) => protectedMath.segments[Number(idx)] || '');
      return out;
    }

    function renderBracketSourceLinks(text) {
      const matches = Array.from(String(text || '').matchAll(/\[([^\]]+)\]/g));
      if (!matches.length) {
        return '';
      }

      const links = [];
      for (const match of matches) {
        const raw = String(match[1] || '').trim();
        if (!raw) {
          continue;
        }
        const title = raw.replace(/"/g, '&quot;');
        const link = sourceLinkFromDescriptor(raw);
        if (link && link.href) {
          links.push(`<a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a>`);
        } else {
          links.push(`<span class="source-link-static" title="${title}">Source</span>`);
        }
      }
      return links.join(' ');
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

      for (let i = 0; i < lines.length; i += 1) {
        const raw = lines[i];
        const line = raw.trimEnd();
        const t = line.trim();

        if (!t) {
          let nextNonEmpty = '';
          for (let j = i + 1; j < lines.length; j += 1) {
            const candidate = lines[j].trim();
            if (candidate) {
              nextNonEmpty = candidate;
              break;
            }
          }
          const nextKeepsUl = inUl && /^[-*]\s+/.test(nextNonEmpty);
          const nextKeepsOl = inOl && /^\d+\.\s+/.test(nextNonEmpty);
          if (!nextKeepsUl && !nextKeepsOl) {
            closeLists();
          }
          continue;
        }

        if (/^\[[^\]]+\](?:\s*[,;]?\s*\[[^\]]+\])*$/.test(t)) {
          closeLists();
          const links = renderBracketSourceLinks(t);
          if (links) {
            html.push(`<p class="source-line">${links}</p>`);
            continue;
          }
        }

        const sourcesLine = t.match(/^sources?:\s*(.+)$/i);
        if (sourcesLine) {
          closeLists();
          const parts = sourcesLine[1].split(/\s*;\s*/).filter(Boolean);
          const links = [];
          for (const part of parts) {
            const link = sourceLinkFromDescriptor(part);
            const title = String(part || '').trim().replace(/"/g, '&quot;');
            if (link && link.href) {
              links.push(`<a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a>`);
            } else if (title) {
              links.push(`<span class="source-link-static" title="${title}">Source</span>`);
            }
          }
          if (links.length) {
            html.push(`<p class="source-line">${links.join(' ')}</p>`);
            continue;
          }
        }

        if (/\.(?:pdf|epub)\b/i.test(t) && !/\[[^\]]+\]\([^\)]+\)/.test(t)) {
          closeLists();
          const link = sourceLinkFromDescriptor(t);
          if (link && link.href) {
            const title = t.replace(/"/g, '&quot;');
            html.push(`<p class="source-line"><a class="source-link" href="${link.href}" target="_blank" rel="noopener noreferrer" title="${title}">Source</a></p>`);
            continue;
          }
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

      const citationOnly = role === 'assistant' && opts.citationOnly === true;
      if (!citationOnly) {
        const textEl = document.createElement('div');
        textEl.className = role === 'assistant' ? 'msg-text md' : 'msg-text';
        if (role === 'assistant') {
          textEl.innerHTML = renderMarkdown(text);
          renderMathIn(textEl);
        } else {
          textEl.textContent = text;
        }
        el.appendChild(textEl);
      }

      if (role === 'assistant' && Array.isArray(opts.citationEntries) && opts.citationEntries.length) {
        const citationWrap = renderCitationActions(opts.citationEntries, opts.citationQuery || '');
        if (citationWrap) {
          el.appendChild(citationWrap);
        }
      }

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
      const opts = arguments.length > 2 ? arguments[2] : {};
      addMessage(role, text, opts);
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

    function getIncludedDocPaths() {
      return libraryDocs
        .filter((doc) => !excludedDocPaths.has(doc.path))
        .map((doc) => doc.path);
    }

    function hasIndexedChunks(doc) {
      return Number(doc && doc.chunks ? doc.chunks : 0) > 0;
    }

    function buildDocSelectionError(filters) {
      if (filters.includedCount <= 0) {
        return 'All documents are excluded. Open Library Docs and include at least one document.';
      }
      if (filters.includedChunkCount <= 0) {
        const sample = filters.zeroChunkIncluded.slice(0, 3).join(', ');
        const suffix = filters.zeroChunkIncluded.length > 3 ? ', ...' : '';
        return `Selected document filter has no indexed text chunks (${sample}${suffix}). Include at least one document with chunks > 0 or OCR/re-index that PDF.`;
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
      return {
        includePaths: included,
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

    function pathParts(relPath) {
      const raw = String(relPath || '').replace(/\\\\/g, '/').replace(/^\/+/, '');
      if (!raw) return [];
      return raw.split('/').filter(Boolean);
    }

    function folderKeysForDoc(doc) {
      const parts = pathParts(doc.rel_path || doc.path || '');
      const dirs = parts.slice(0, Math.max(0, parts.length - 1));
      if (!dirs.length) {
        return { root: '(root)', child: '' };
      }
      const root = dirs[0];
      const child = dirs.length >= 2 ? `${dirs[0]}/${dirs[1]}` : '';
      return { root, child };
    }

    function setFolderIncluded(folderKey, depth, shouldInclude) {
      for (const doc of libraryDocs) {
        const { root, child } = folderKeysForDoc(doc);
        const matches = depth === 1 ? root === folderKey : child === folderKey;
        if (!matches) continue;
        if (shouldInclude) {
          excludedDocPaths.delete(doc.path);
        } else {
          excludedDocPaths.add(doc.path);
        }
      }
      persistDocFilterState();
      renderLibraryDocs();
    }

    function buildFolderHierarchy(docs) {
      const roots = new Map();
      for (const doc of docs) {
        const { root, child } = folderKeysForDoc(doc);
        if (!roots.has(root)) {
          roots.set(root, { key: root, docs: [], children: new Map() });
        }
        const rootNode = roots.get(root);
        rootNode.docs.push(doc);

        if (!child) continue;
        if (!rootNode.children.has(child)) {
          const childLabel = child.split('/').slice(-1)[0] || child;
          rootNode.children.set(
              child, { key: child, label: childLabel, docs: [] });
        }
        rootNode.children.get(child).docs.push(doc);
      }

      const rootList = Array.from(roots.values()).sort((a, b) => a.key.localeCompare(b.key));
      for (const node of rootList) {
        node.children = Array.from(node.children.values()).sort((a, b) => a.label.localeCompare(b.label));
      }
      return rootList;
    }

    function renderLibraryDocs() {
      const q = (docsSearchEl.value || '').trim().toLowerCase();
      const filtered = q
        ? libraryDocs.filter((doc) => (doc.rel_path || doc.path || '').toLowerCase().includes(q))
        : libraryDocs;

      const includedCount = Math.max(0, libraryDocs.length - excludedDocPaths.size);
      const hierarchy = buildFolderHierarchy(filtered);
      docsMetaEl.textContent =
        `Docs: ${libraryDocs.length} | Included: ${includedCount} | Excluded: ${excludedDocPaths.size}` +
        (hierarchy.length ? `\nFolders shown: ${hierarchy.length}` : '');

      docsGroupsEl.innerHTML = '';
      for (const rootNode of hierarchy) {
        const rootIncluded = rootNode.docs.filter((d) => !excludedDocPaths.has(d.path)).length;

        const row = document.createElement('div');
        row.className = 'docs-group-row docs-group-root';

        const label = document.createElement('div');
        label.className = 'docs-group-label';
        label.textContent = `${rootNode.key}: ${rootIncluded}/${rootNode.docs.length} included`;

        const actions = document.createElement('div');
        actions.className = 'docs-group-actions';
        const inBtn = document.createElement('button');
        inBtn.type = 'button';
        inBtn.className = 'btn-soft';
        inBtn.textContent = 'In';
        inBtn.addEventListener('click', () => setFolderIncluded(rootNode.key, 1, true));

        const outBtn = document.createElement('button');
        outBtn.type = 'button';
        outBtn.className = 'btn-soft';
        outBtn.textContent = 'Out';
        outBtn.addEventListener('click', () => setFolderIncluded(rootNode.key, 1, false));

        actions.appendChild(inBtn);
        actions.appendChild(outBtn);
        row.appendChild(label);
        row.appendChild(actions);
        docsGroupsEl.appendChild(row);

        for (const childNode of rootNode.children) {
          const childIncluded = childNode.docs.filter((d) => !excludedDocPaths.has(d.path)).length;

          const childRow = document.createElement('div');
          childRow.className = 'docs-group-row docs-group-child';

          const childLabel = document.createElement('div');
          childLabel.className = 'docs-group-label';
          childLabel.textContent = `${childNode.label}: ${childIncluded}/${childNode.docs.length} included`;

          const childActions = document.createElement('div');
          childActions.className = 'docs-group-actions';

          const childInBtn = document.createElement('button');
          childInBtn.type = 'button';
          childInBtn.className = 'btn-soft';
          childInBtn.textContent = 'In';
          childInBtn.addEventListener('click', () => setFolderIncluded(childNode.key, 2, true));

          const childOutBtn = document.createElement('button');
          childOutBtn.type = 'button';
          childOutBtn.className = 'btn-soft';
          childOutBtn.textContent = 'Out';
          childOutBtn.addEventListener('click', () => setFolderIncluded(childNode.key, 2, false));

          childActions.appendChild(childInBtn);
          childActions.appendChild(childOutBtn);
          childRow.appendChild(childLabel);
          childRow.appendChild(childActions);
          docsGroupsEl.appendChild(childRow);
        }
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
      persistDocFilterState();

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

      const shownType = payload.entry_type || 'all';
      stashMetaEl.textContent = `Count: ${payload.count || 0}\nType: ${shownType}\nPath: ${payload.stash_path || ''}`;

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
      const endpoint = stashViewMode === 'bibliography' ? '/api/bibliography?limit=200' : '/api/stash?limit=200';
      const res = await fetch(endpoint);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      renderStashEntries(data);
    }

    async function openStashModal(mode = 'stash') {
      stashViewMode = mode === 'bibliography' ? 'bibliography' : 'stash';
      stashTitleEl.textContent = stashViewMode === 'bibliography' ? 'Bibliography Stash' : 'Stashed Snippets';
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
      return /\\.pdf$/i.test(String(p || '').trim());
    }

    function isEpubSourcePath(p) {
      return /\\.epub$/i.test(String(p || '').trim());
    }

    function buildSourceOpenUrl(path, loc) {
      const cleanPath = String(path || '').trim();
      const location = Math.max(1, Number(loc || 1));
      if (!cleanPath) return '';
      if (isPdfSourcePath(cleanPath)) {
        return `/api/pdf/file?path=${strictEncodeURIComponent(cleanPath)}#page=${location}`;
      }
      if (isEpubSourcePath(cleanPath)) {
        return `/epub-reader?path=${strictEncodeURIComponent(cleanPath)}&section=${location}`;
      }
      return '';
    }

    function sourceTitleFromPath(p) {
      const base = pathBase(p || 'document');
      const noExt = base.replace(/\.[^/.]+$/, '');
      const normalized = noExt.replace(/[._-]+/g, ' ').replace(/\s+/g, ' ').trim();
      return normalized || 'Untitled document';
    }

    function formatApaAuthorList(authors) {
      if (!Array.isArray(authors)) {
        return '';
      }
      const clean = authors
        .map((a) => String(a || '').trim())
        .filter((a) => a.length > 0)
        .slice(0, 6);
      if (!clean.length) {
        return '';
      }
      if (clean.length === 1) {
        return clean[0];
      }
      if (clean.length === 2) {
        return `${clean[0]} & ${clean[1]}`;
      }
      return `${clean.slice(0, clean.length - 1).join(', ')}, & ${clean[clean.length - 1]}`;
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

    function buildApaCitationEntries(sources) {
      const seen = new Set();
      const entries = [];
      for (const s of (Array.isArray(sources) ? sources : []).slice(0, 24)) {
        const path = String(s.path || '').trim();
        const loc = Number(s.page || s.location || 1);
        const key = `${path}#${loc}`;
        if (!path || seen.has(key)) continue;
        seen.add(key);

        const title = String(s.title || '').trim() || sourceTitleFromPath(path);
        const author = formatApaAuthorList(s.authors);
        const year = String(s.year || '').trim() || 'n.d.';
        let titlePart = `*${title}*`;
        let locator = `loc. ${loc}`;
        const openUrl = buildSourceOpenUrl(path, loc);
        if (openUrl) {
          titlePart = `*[${title}](${openUrl})*`;
        }
        if (isPdfSourcePath(path)) {
          locator = `p. ${loc}`;
        } else if (isEpubSourcePath(path)) {
          locator = `section ${loc}`;
        }
        const citation = author
          ? `${author}. (${year}). ${titlePart}. (${locator}).`
          : `${titlePart}. (${year}). (${locator}).`;
        entries.push({
          citation,
          source: {
            path,
            page: loc,
            location: loc,
            title,
            authors: Array.isArray(s.authors) ? s.authors : [],
            year,
          }
        });
      }
      return entries;
    }

    function formatApaSources(sources) {
      return buildApaCitationEntries(sources).map((entry) => `- ${entry.citation}`);
    }

    function renderCitationActions(citationEntries, queryText = '') {
      const entries = Array.isArray(citationEntries) ? citationEntries : [];
      if (!entries.length) {
        return null;
      }

      const wrap = document.createElement('div');
      wrap.className = 'citation-list';

      for (const entry of entries) {
        const row = document.createElement('div');
        row.className = 'citation-row';

        const text = document.createElement('div');
        text.className = 'citation-text md';
        text.innerHTML = renderInlineMarkdown(String(entry.citation || ''));

        const stashBtn = document.createElement('button');
        stashBtn.className = 'stash-btn';
        stashBtn.type = 'button';
        stashBtn.textContent = 'Add to Bibliography';
        stashBtn.addEventListener('click', async () => {
          stashBtn.disabled = true;
          stashBtn.textContent = 'Adding...';
          try {
            const payloadSources = entry.source ? [entry.source] : [];
            const result = await stashResponse(String(entry.citation || ''), {
              entry_type: 'bibliography',
              query: queryText || lastCitationQuery || '',
              sources: payloadSources,
            });
            metaEl.textContent = `Added citation to bibliography (${result.count || '?'})`;
            stashBtn.textContent = 'Added';
            setTimeout(() => {
              stashBtn.textContent = 'Add to Bibliography';
              stashBtn.disabled = false;
            }, 1200);
          } catch (err) {
            metaEl.textContent = `Citation stash failed: ${err.message}`;
            stashBtn.textContent = 'Add to Bibliography';
            stashBtn.disabled = false;
          }
        });

        row.appendChild(text);
        row.appendChild(stashBtn);
        wrap.appendChild(row);
      }

      return wrap;
    }

    function buildBibliographyText(sources, queryText = '') {
      const apaLines = formatApaSources(sources);
      if (!apaLines.length) {
        return '';
      }
      const heading = 'References (APA 7):';
      const topic = queryText ? `\\nQuery: ${queryText}` : '';
      return `${heading}${topic}\\n\\n${apaLines.join('\\n')}`;
    }

    async function generateBibliographyFromLatestSources() {
      if (!Array.isArray(lastPdfSources) || !lastPdfSources.length) {
        addMessage(
            'system', 'No recent PDF-grounded sources found. Ask with PDF-grounded mode first.');
        return;
      }

      const citationEntries = buildApaCitationEntries(lastPdfSources);
      const bibliographyText = buildBibliographyText(lastPdfSources, lastCitationQuery);
      if (!bibliographyText) {
        addMessage(
            'system', 'Could not generate bibliography from current sources.');
        return;
      }

      try {
        await addMessageAndStore('assistant', '', {
          citationOnly: true,
          citationEntries,
          citationQuery: lastCitationQuery,
        });
        await stashResponse(bibliographyText, {
          entry_type: 'bibliography',
          query: lastCitationQuery,
          sources: Array.isArray(lastPdfSources) ? lastPdfSources : []
        });
        metaEl.textContent = 'Bibliography generated and opened';
        openStashModal('bibliography');
      } catch (err) {
        addMessage('system', `Bibliography generation failed: ${err.message}`);
      }
    }

    async function createStudyBrief() {
      const query = promptEl.value.trim() || lastUserPrompt;
      if (!query) {
        addMessage(
            'system', 'Enter a topic first (or ask a question) to create a study brief.');
        return;
      }
      if (!usePdfLibraryEl.checked) {
        addMessage(
            'system', 'Enable PDF-grounded answers to create a study brief.');
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

        const sourceRows = Array.isArray(data.sources) ? data.sources : [];
        const citationEntries = buildApaCitationEntries(sourceRows);
        let answer = data.answer || '[no brief field]';

        lastPdfSources = sourceRows;
        lastCitationQuery = query;

        await addMessageAndStore('assistant', answer, {
          citationEntries,
          citationQuery: query,
        });
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

    function summarizeIndexError(rawError) {
      if (!rawError) return '';
      const text = String(rawError).replace(/\\r/g, '');
      const lines = text.split('\\n').map((line) => line.trim()).filter(Boolean);
      let best = lines.length ? lines[lines.length - 1] : text.trim();
      if (!best || /^traceback/i.test(best)) {
        const fallback = lines.find((line) => !/^traceback/i.test(line));
        best = fallback || 'Indexing failed (see logs)';
      }
      if (best.length > 180) best = `${best.slice(0, 177)}...`;
      return best;
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

        if (job.running) {
          if (!syncSnapshot) {
            syncSnapshot = {
              startedAt: Number(job.last_started_at || Math.floor(Date.now() / 1000)),
              startDocs: Number(docs || 0),
              startChunks: Number(chunks || 0),
            };
          }
          const elapsedSec = Math.max(1, Math.floor(Date.now() / 1000) - Number(syncSnapshot.startedAt || Math.floor(Date.now() / 1000)));
          const chunkDelta = Math.max(0, Number(chunks || 0) - Number(syncSnapshot.startChunks || 0));
          const chunksPerMin = Math.round((chunkDelta / elapsedSec) * 60);

          const result = job.last_result && typeof job.last_result === 'object' ? job.last_result : {};
          const processed = Number(result.processed || result.updated || result.indexed || 0);
          const total = Number(result.total || result.discovered || result.candidates || 0);
          let progressPct = 0;
          let etaText = 'ETA: estimating';

          if (Number.isFinite(total) && total > 0 && Number.isFinite(processed) && processed >= 0) {
            progressPct = Math.max(0, Math.min(
                100, Math.round((processed / total) * 100)));
            const remaining = Math.max(0, total - processed);
            const perSec = processed > 0 ? processed / elapsedSec : 0;
            if (perSec > 0) {
              const etaSec = Math.round(remaining / perSec);
              etaText = `ETA: ~${Math.max(0, Math.ceil(etaSec / 60))} min`;
            }
          } else {
            progressPct = Math.max(8, Math.min(
                92, 12 + Math.round(Math.min(80, elapsedSec / 3))));
          }

          pdfProgressEl.classList.remove('hidden');
          pdfProgressBarEl.style.width = `${progressPct}%`;
          pdfStatusEl.textContent = `PDF index: running (${progressPct}%)\nDocs: ${docs} | Chunks: ${chunks} | +${chunkDelta} this run\nElapsed: ${Math.ceil(elapsedSec / 60)} min | ${etaText} | ${chunksPerMin}/min`;
        } else {
          syncSnapshot = null;
          pdfProgressEl.classList.add('hidden');
          pdfProgressBarEl.style.width = '0%';
          const compactError = summarizeIndexError(job.last_error);
          const statusTail = compactError ? `\nLast error: ${compactError}` : '';
          pdfStatusEl.textContent = `PDF index: ${running}\nDocs: ${docs} | Chunks: ${chunks}\nLast indexed: ${idx}${statusTail}`;
        }
      } catch (err) {
        pdfProgressEl.classList.add('hidden');
        pdfProgressBarEl.style.width = '0%';
        pdfStatusEl.textContent = `PDF index status error: ${err.message}`;
      }
    }

    function renderUpdateUi(data) {
      const currentVersion = String((data && data.current_version) || 'unknown');
      const latestVersion = String((data && data.latest_version) || '').trim();
      const updateAvailable = Boolean(data && data.update_available);
      const source = String((data && data.source) || 'none');
      const branch = String((data && data.branch) || 'main');
      const applyTarget = String((data && data.apply_target) || '').trim();
      const state = String((data && data.state) || 'idle');
      const message = String((data && data.message) || 'Not checked');
      const err = data && data.last_error ? ` | ${data.last_error}` : '';

      appVersionEl.textContent = `Version: ${currentVersion}`;
      updateStatusEl.textContent = `Updates: ${state} (${source}) - ${message}${err}`;

      if (source === 'git') {
        latestUpdateVersion = updateAvailable ? branch : '';
      } else {
        latestUpdateVersion = updateAvailable ? (applyTarget || latestVersion) : '';
      }
      applyUpdateEl.disabled = !latestUpdateVersion;
      if (source === 'git') {
        applyUpdateEl.textContent = latestUpdateVersion
          ? `Sync from ${latestUpdateVersion}`
          : `Sync from ${branch}`;
      } else {
        applyUpdateEl.textContent = latestUpdateVersion
          ? `Update to ${latestUpdateVersion}`
          : 'Update to Latest';
      }
    }

    async function refreshUpdateStatus() {
      try {
        const res = await fetch('/api/update/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderUpdateUi(data || {});
      } catch (err) {
        updateStatusEl.textContent = `Updates: status error - ${err.message}`;
      }
    }

    async function checkForUpdates() {
      checkUpdatesEl.disabled = true;
      const original = checkUpdatesEl.textContent;
      checkUpdatesEl.textContent = 'Checking...';
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          const detail = (data && (data.error || data.last_error)) || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        renderUpdateUi(data || {});
        metaEl.textContent = data.update_available
          ? `Update available: ${data.latest_version}`
          : 'Already on latest version';
      } catch (err) {
        updateStatusEl.textContent = `Updates: check failed - ${err.message}`;
        metaEl.textContent = 'Update check failed';
      } finally {
        checkUpdatesEl.disabled = false;
        checkUpdatesEl.textContent = original;
      }
    }

    async function applyUpdate() {
      if (!latestUpdateVersion) return;
      applyUpdateEl.disabled = true;
      try {
        const res = await fetch('/api/update/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_version: latestUpdateVersion }),
        });
        const data = await res.json();
        if (!res.ok || data.ok === false) {
          const detail = (data && (data.error || data.message)) || `HTTP ${res.status}`;
          throw new Error(detail);
        }
        renderUpdateUi((data && data.state) || data || {});
        metaEl.textContent = data.message || 'Update job started';
      } catch (err) {
        updateStatusEl.textContent = `Updates: apply failed - ${err.message}`;
        metaEl.textContent = 'Update apply failed';
      } finally {
        applyUpdateEl.disabled = !latestUpdateVersion;
      }
    }

    async function syncPdfLibrary() {
      syncPdfLibraryEl.disabled = true;
      syncPdfLibraryEl.textContent = 'Syncing...';
      try {
        const res = await fetch('/api/pdf/index', { method: 'POST' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        syncSnapshot = {
          startedAt: Math.floor(Date.now() / 1000),
          startDocs: 0,
          startChunks: 0,
        };
        pdfProgressEl.classList.remove('hidden');
        pdfProgressBarEl.style.width = '8%';
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
      promptUseSelectedEl.disabled = isBusy;
      promptPinSelectedEl.disabled = isBusy;
      promptClearHistoryEl.disabled = isBusy;
      promptHistorySelectEl.disabled = isBusy;
      cancelEl.disabled = !isBusy;
      refreshEl.disabled = isBusy;
      modelEl.disabled = isBusy;
      instructionsEl.disabled = isBusy;
      saveInstructionsEl.disabled = isBusy;
      usePdfLibraryEl.disabled = isBusy;
      deepStudyEl.disabled = isBusy;
      syncPdfLibraryEl.disabled = isBusy;
      uploadLibraryDocsEl.disabled = isBusy;
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
          addMessage('assistant', 'Shared history is empty. Start the conversation.', {
                     showAssistantTools: false });
          return;
        }
        for (const item of items) {
          const role = ['user', 'assistant', 'system'].includes(item.role) ? item.role : 'system';
          const text = typeof item.text === 'string' ? item.text : '';
          if (!text) continue;
          if (role === 'user') {
            rememberPrompt(text, false);
            lastUserPrompt = text;
          }
          addMessage(role, text);
        }
        persistPromptHistory();
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
        addMessage(
            'system', 'No model is available. Install a model and refresh.');
        return;
      }

      rememberPrompt(prompt);

      if (!usePdfLibrary) {
        const proceedUngrounded = confirm(
          'Send this query without PDF grounding?\\n\\nThis app is optimized for PDF-grounded answers, and ungrounded queries are usually better handled by general chat tools.'
        );
        if (!proceedUngrounded) {
          usePdfLibraryEl.checked = true;
          metaEl.textContent = 'PDF-grounded mode re-enabled';
          return;
        }
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
          const sourceRows = Array.isArray(data.sources) ? data.sources : [];
          const citationEntries = buildApaCitationEntries(sourceRows);
          answer = data.answer || '[no answer field]';
          lastPdfSources = sourceRows;
          lastCitationQuery = prompt;
          await addMessageAndStore('assistant', answer, {
            citationEntries,
            citationQuery: prompt,
          });
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
          await addMessageAndStore('assistant', answer);
        }

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
    openBibliographyEl.addEventListener('click', () => openStashModal('bibliography'));
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
      persistDocFilterState();
      renderLibraryDocs();
    });
    docsSelectNoneEl.addEventListener('click', () => {
      excludedDocPaths = new Set(libraryDocs.map((d) => d.path));
      persistDocFilterState();
      renderLibraryDocs();
    });
    docsSearchEl.addEventListener('input', renderLibraryDocs);
    docsModalEl.addEventListener('click', (e) => {
      if (e.target === docsModalEl) closeLibraryDocsModal();
    });
    openStashEl.addEventListener('click', () => openStashModal('stash'));
    stashCloseEl.addEventListener('click', closeStashModal);
    stashReloadEl.addEventListener('click', async () => {
      try {
        await loadStashEntries();
      } catch (err) {
        stashMetaEl.textContent = `Failed to load stash: ${err.message}`;
      }
    });
    stashClearAllEl.addEventListener('click', async () => {
      const clearLabel = stashViewMode === 'bibliography' ? 'all bibliography entries' : 'all stashed snippets';
      if (!confirm(`Delete ${clearLabel}?`)) return;
      try {
        const clearEndpoint = stashViewMode === 'bibliography' ? '/api/bibliography?all=1' : '/api/stash?all=1';
        const res = await fetch(clearEndpoint, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        await loadStashEntries();
        metaEl.textContent = stashViewMode === 'bibliography' ? 'Cleared bibliography stash' : 'Cleared stash';
      } catch (err) {
        stashMetaEl.textContent = `Failed to clear stash: ${err.message}`;
      }
    });
    stashModalEl.addEventListener('click', (e) => {
      if (e.target === stashModalEl) closeStashModal();
    });
    saveInstructionsEl.addEventListener('click', saveInstructions);
    syncPdfLibraryEl.addEventListener('click', syncPdfLibrary);
    checkUpdatesEl.addEventListener('click', checkForUpdates);
    applyUpdateEl.addEventListener('click', applyUpdate);
    uploadLibraryDocsEl.addEventListener('click', () => {
      libraryUploadInputEl.click();
    });
    libraryUploadInputEl.addEventListener('change', async () => {
      try {
        await uploadLibraryFiles(libraryUploadInputEl.files);
      } finally {
        libraryUploadInputEl.value = '';
      }
    });
    usePdfLibraryEl.addEventListener('change', () => {
      if (usePdfLibraryEl.checked) {
        metaEl.textContent = 'PDF-grounded mode enabled';
        return;
      }
      const proceedUngrounded = confirm(
        'Turn off PDF grounding?\\n\\nOllama Librarian is intended primarily for PDF-grounded research. Continue with ungrounded mode?'
      );
      if (!proceedUngrounded) {
        usePdfLibraryEl.checked = true;
        metaEl.textContent = 'PDF-grounded mode kept on';
        return;
      }
      metaEl.textContent = 'Ungrounded mode enabled';
    });
    studyBriefEl.addEventListener('click', createStudyBrief);
    makeBibliographyEl.addEventListener(
        'click', generateBibliographyFromLatestSources);
    cancelEl.addEventListener('click', cancelPromptRequest);
    clearEl.addEventListener('click', async () => {
      try {
        await fetch('/api/history', { method: 'DELETE' });
      } catch (_) {
        // If delete fails, still clear local view for usability.
      }
      messagesEl.innerHTML = '';
      addMessage('assistant', 'Shared history cleared.',
                 { showAssistantTools: false });
      metaEl.textContent = 'Ready';
      promptEl.focus();
    });
    sendEl.addEventListener('click', sendPrompt);
    promptUseSelectedEl.addEventListener('click', askSelectedPrompt);
    promptPinSelectedEl.addEventListener('click', togglePinSelectedPrompt);
    promptClearHistoryEl.addEventListener('click', () => {
      if (!confirm('Clear unpinned prompt history?')) return;
      clearPromptHistory();
    });
    promptHistorySelectEl.addEventListener('change', () => {
      const selected = String(promptHistorySelectEl.value || '').trim();
      if (!selected) return;
      promptEl.value = selected;
      promptEl.focus();
      promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
    });
    promptEl.addEventListener('keydown', (e) => {
      if (e.ctrlKey && !e.shiftKey && e.key === 'ArrowUp') {
        e.preventDefault();
        recallPromptHistory(-1);
        return;
      }
      if (e.ctrlKey && !e.shiftKey && e.key === 'ArrowDown') {
        e.preventDefault();
        recallPromptHistory(1);
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendPrompt();
      }
    });

    promptHistory = loadPromptHistory();
    pinnedPrompts = loadPinnedPrompts();
    promptHistoryIndex = promptHistory.length;
    renderPromptHistoryDropdown();
    loadHistory();
    loadInstructions();
    loadModels();
    refreshPdfStatus();
    refreshUpdateStatus();
    setInterval(refreshPdfStatus, 15000);
    setInterval(refreshUpdateStatus, 30000);
  </script>
</body>
</html>
"""

EPUB_READER_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EPUB Reader</title>
  <style>
    :root { color-scheme: light; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      background: #f7f7f4;
      color: #1d232f;
      height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .bar {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.65rem 0.85rem;
      background: #ffffff;
      border-bottom: 1px solid #d8dee8;
    }
    .bar button {
      border: 1px solid #c8cfdb;
      border-radius: 8px;
      background: #eef3fb;
      color: #1f2a44;
      padding: 0.38rem 0.62rem;
      cursor: pointer;
    }
    .meta {
      margin-left: auto;
      font-size: 0.86rem;
      color: #4d5b75;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 65vw;
    }
    #viewer {
      width: 100%;
      height: calc(100vh - 52px);
      background: #ffffff;
    }
  </style>
  <script src="/assets/jszip/jszip.min.js"></script>
  <script src="/assets/epubjs/epub.min.js"></script>
</head>
<body>
  <div class="bar">
    <button id="prev" type="button">Prev</button>
    <button id="next" type="button">Next</button>
    <div id="meta" class="meta">Loading EPUB...</div>
  </div>
  <div id="viewer"></div>
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

    function strictEncodeURIComponent(value) {
      return encodeURIComponent(String(value)).replace(/[!'()*]/g, (ch) => `%${ch.charCodeAt(0).toString(16).toUpperCase()}`);
    }

    function getQuery() {
      const params = new URLSearchParams(window.location.search);
      return {
        path: (params.get('path') || '').trim(),
        section: Math.max(1, Number(params.get('section') || '1') || 1),
        cfi: (params.get('cfi') || '').trim(),
      };
    }

    async function loadEpub() {
      const metaEl = document.getElementById('meta');
      let openTimer = null;
      try {
        const q = getQuery();
        if (!q.path) {
          metaEl.textContent = 'Missing EPUB path';
          return;
        }

        if (typeof window.JSZip === 'undefined') {
          metaEl.textContent = 'EPUB dependency error: JSZip not loaded';
          return;
        }
        if (typeof window.ePub !== 'function') {
          metaEl.textContent = 'EPUB dependency error: epub.js not loaded';
          return;
        }

        const headers = apiKey ? { 'X-API-Key': apiKey } : {};
        const url = `/api/epub/file?path=${strictEncodeURIComponent(q.path)}`;
        metaEl.textContent = 'Downloading EPUB...';
        const res = await fetch(url, { headers });
        if (!res.ok) {
          metaEl.textContent = `Failed to load EPUB: HTTP ${res.status}`;
          return;
        }

        metaEl.textContent = 'Parsing EPUB (large files can take a while)...';
        const bytes = await res.arrayBuffer();
        const openedAtMs = Date.now();
        openTimer = window.setInterval(() => {
          const elapsed = Math.max(0, Math.floor((Date.now() - openedAtMs) / 1000));
          metaEl.textContent = `Opening EPUB... ${elapsed}s`;
        }, 1000);
        const book = ePub(bytes);
        const rendition = book.renderTo('viewer', {
          width: '100%',
          height: '100%',
        });

        rendition.on('relocated', (loc) => {
          if (openTimer) {
            window.clearInterval(openTimer);
            openTimer = null;
          }
          const start = loc && loc.start ? loc.start : null;
          const href = start && start.href ? start.href : '';
          const disp = start && start.displayed ? start.displayed : null;
          const shown = disp && disp.page ? `p.${disp.page}` : href;
          metaEl.textContent = `${q.path}${shown ? ` | ${shown}` : ''}`;
        });

        const prevBtn = document.getElementById('prev');
        const nextBtn = document.getElementById('next');
        prevBtn.addEventListener('click', () => rendition.prev());
        nextBtn.addEventListener('click', () => rendition.next());

        try {
          if (q.cfi) {
            await rendition.display(q.cfi);
            return;
          }
          const spine = book.spine && typeof book.spine.get === 'function'
            ? book.spine.get(Math.max(0, q.section - 1))
            : null;
          if (spine && spine.href) {
            await rendition.display(spine.href);
          } else {
            await rendition.display();
          }
        } catch (err) {
          metaEl.textContent = `Failed to open location: ${err && err.message ? err.message : err}`;
          await rendition.display();
        }
      } catch (err) {
        if (openTimer) {
          window.clearInterval(openTimer);
          openTimer = null;
        }
        metaEl.textContent = `Failed to load EPUB: ${err && err.message ? err.message : err}`;
        console.error(err);
      }
    }

    loadEpub();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_security_headers(self):
        if self.path.startswith("/epub-reader"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline' blob:; script-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; font-src 'self' data: blob:; connect-src 'self' blob:; frame-src 'self' blob:; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        else:
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

    def _expected_origin(self):
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return None
        return f"http://{host}"

    def _require_same_origin_for_state_change(self, route_path):
        if not route_path.startswith("/api/"):
            return True

        sec_fetch_site = (self.headers.get(
            "Sec-Fetch-Site") or "").strip().lower()
        if sec_fetch_site in {"cross-site", "none"}:
            self._send(
                403,
                json.dumps(
                    {"error": "Cross-site requests are not allowed"}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return False

        expected_origin = self._expected_origin()
        origin = (self.headers.get("Origin") or "").strip()
        if origin and expected_origin and origin != expected_origin:
            self._send(
                403,
                json.dumps({"error": "Origin not allowed"}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return False

        referer = (self.headers.get("Referer") or "").strip()
        if referer and expected_origin and not referer.startswith(expected_origin + "/"):
            self._send(
                403,
                json.dumps({"error": "Referer not allowed"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
            return False

        return True

    def _send_file(self, file_path, content_type, extra_headers=None):
        size = os.path.getsize(file_path)
        self.send_response(200)
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _resolve_library_file_path(self, requested_path):
        if not isinstance(requested_path, str) or not requested_path.strip():
            return None, "path is required", 400

        resolved_root = os.path.realpath(os.path.expanduser(PDF_SOURCE))
        resolved_path = os.path.realpath(os.path.expanduser(requested_path))

        if not resolved_path.startswith(resolved_root + os.sep):
            return None, "path is outside configured PDF library", 403

        if not os.path.isfile(resolved_path):
            return None, "File not found", 404

        return resolved_path, None, 200

    def _resolve_upload_target_path(self, requested_name):
        if not isinstance(requested_name, str) or not requested_name.strip():
            return None, None, "name is required", 400

        normalized_name = str(requested_name).replace(
            "\\", "/").split("/")[-1].strip()
        if not normalized_name or normalized_name in {".", ".."}:
            return None, None, "invalid file name", 400

        # Keep Unicode, but normalize characters invalid on Windows filesystems.
        invalid_windows_chars = set('<>:"/\\|?*')
        cleaned = "".join(
            "_" if (ch in invalid_windows_chars or ord(
                ch) < 32 or ord(ch) == 127) else ch
            for ch in normalized_name
        ).strip().strip(". ")
        if not cleaned or cleaned in {".", ".."}:
            return None, None, "invalid file name", 400

        suffix = Path(cleaned).suffix.lower()
        if suffix not in SUPPORTED_DOC_EXTENSIONS:
            return None, None, (
                "unsupported file extension (allowed: .pdf, .txt, .md, .html, .htm, .epub)"
            ), 400

        root = Path(os.path.expanduser(PDF_SOURCE)).resolve()
        root.mkdir(parents=True, exist_ok=True)

        base_name = Path(cleaned).stem.strip().strip(". ") or "document"
        windows_reserved_names = {
            "con", "prn", "aux", "nul",
            "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
            "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
        }
        if base_name.lower() in windows_reserved_names:
            base_name = f"{base_name}_"

        target = root / f"{base_name}{suffix}"
        collision = 1
        while target.exists():
            target = root / f"{base_name} ({collision}){suffix}"
            collision += 1

        resolved_target = target.resolve()
        root_prefix = str(root) + os.sep
        if not str(resolved_target).startswith(root_prefix):
            return None, None, "invalid target path", 400

        return root, resolved_target, None, 200

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
            html = html.replace("%MAX_UPLOAD_BYTES%", str(MAX_UPLOAD_BYTES))
            html = html.replace("%CURRENT_VERSION%", read_current_version())
            return self._send(200, html, "text/html; charset=utf-8")

        if route_path == "/epub-reader":
            html = EPUB_READER_HTML.replace(
                "%API_KEY_REQUIRED%", "true" if bool(API_KEY) else "false"
            )
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
            raw_entry_type = params.get("entry_type", [""])[0]
            entry_type = _normalize_entry_type(raw_entry_type) if str(
                raw_entry_type).strip() else None
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 200
            try:
                payload = list_stash_entries(
                    limit=max(0, limit), entry_type=entry_type)
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

        if route_path == "/api/bibliography":
            params = parse_qs(parsed_url.query)
            limit_raw = params.get("limit", ["200"])[0]
            try:
                limit = int(limit_raw)
            except Exception:
                limit = 200
            try:
                payload = list_stash_entries(
                    limit=max(0, limit), entry_type="bibliography")
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

        if route_path == "/api/update/status":
            return self._send(
                200,
                json.dumps(get_update_status(), ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/update/check":
            return self._send(
            200,
            json.dumps(get_update_status(), ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/pdf/file":
            params = parse_qs(parsed_url.query)
            pdf_path = params.get("path", [""])[0]
            resolved_path, error, code = self._resolve_library_file_path(
                pdf_path)
            if error:
                return self._send(
                    code,
                    json.dumps({"error": error}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            if not resolved_path.lower().endswith(".pdf"):
                return self._send(
                    404,
                    json.dumps({"error": "PDF not found"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            filename = os.path.basename(resolved_path)
            return self._send_file(
                resolved_path,
                "application/pdf",
                {
                    "Content-Disposition": build_inline_content_disposition(filename),
                    "Cache-Control": "no-cache",
                },
            )

        if route_path == "/api/epub/file":
            params = parse_qs(parsed_url.query)
            epub_path = params.get("path", [""])[0]
            resolved_path, error, code = self._resolve_library_file_path(
                epub_path)
            if error:
                return self._send(
                    code,
                    json.dumps({"error": error}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            if not resolved_path.lower().endswith(".epub"):
                return self._send(
                    404,
                    json.dumps({"error": "EPUB not found"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            filename = os.path.basename(resolved_path)
            return self._send_file(
                resolved_path,
                "application/epub+zip",
                {
                    "Content-Disposition": build_inline_content_disposition(filename),
                    "Cache-Control": "no-cache",
                },
            )

        return self._send(404, "Not found")

    def do_POST(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path

        if not self._require_api_auth_for_route(route_path):
            return

        if not self._require_same_origin_for_state_change(route_path):
            return

        if route_path == "/api/generate":
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

        if route_path == "/api/history":
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

        if route_path == "/api/instructions":
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

        if route_path == "/api/pdf/index":
            started = start_pdf_index_job()
            return self._send(
                200,
                json.dumps({"ok": True, "started": started},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/update/apply":
            payload = self._read_json_body()
            if payload is None:
                return

            requested_target = payload.get("target_version", "")
            target_version = str(requested_target or "").strip()
            result = start_update_apply(target_version)
            code = 202
            if not result.get("ok"):
                error_code = str(result.get("error_code") or "")
                if error_code == "already_running":
                    code = 409
                elif error_code == "invalid_target":
                    code = 400
                elif error_code == "preflight_failed":
                    code = 412
                elif error_code == "apply_start_failed":
                    code = 500
                else:
                    code = 400
            return self._send(
                code,
                json.dumps(result, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/update/check":
            payload = check_for_updates()
            code = 200 if payload.get("ok") else 502
            return self._send(
                code,
                json.dumps(payload, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/pdf/ask":
            payload = self._read_json_body()
            if payload is None:
                return

            query = payload.get("query", "")
            model = payload.get("model", "qwen2.5:14b")
            try:
                top_k = int(payload.get("top_k", PDF_TOP_K))
            except Exception:
                top_k = PDF_TOP_K
            top_k = max(1, min(100, top_k))
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

        if route_path == "/api/pdf/brief":
            payload = self._read_json_body()
            if payload is None:
                return

            query = payload.get("query", "")
            model = payload.get("model", "qwen2.5:14b")
            try:
                top_k = int(payload.get("top_k", 14))
            except Exception:
                top_k = 14
            top_k = max(1, min(100, top_k))
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

        if route_path == "/api/library/upload":
            params = parse_qs(parsed_url.query)
            raw_name = params.get("name", [""])[0]
            root, target_path, error, code = self._resolve_upload_target_path(
                raw_name)
            if error:
                return self._send(
                    code,
                    json.dumps({"error": error}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

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

            if length <= 0:
                return self._send(
                    400,
                    json.dumps({"error": "Request body is required"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            if length > MAX_UPLOAD_BYTES:
                return self._send(
                    413,
                    json.dumps(
                        {"error": "Upload exceeds maximum size"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            tmp_path = root / \
                f".upload-{int(time.time() * 1000)}-{os.getpid()}-{uuid.uuid4().hex}.part"
            written = 0
            try:
                with open(tmp_path, "wb") as out_f:
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(64 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Unexpected end of upload stream")
                        out_f.write(chunk)
                        written += len(chunk)
                        remaining -= len(chunk)

                if written != length:
                    raise ValueError("Upload size mismatch")

                os.replace(tmp_path, target_path)
            except ValueError as exc:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
                return self._send(
                    400,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
                return self._send(
                    500,
                    json.dumps(
                        {"error": f"Failed to save upload: {exc}"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            rel_path = os.path.relpath(str(target_path), str(root))
            return self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "rel_path": rel_path,
                        "bytes": written,
                    },
                    ensure_ascii=True,
                ),
                "application/json; charset=utf-8",
            )

        if route_path == "/api/stash":
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

        if not self._require_same_origin_for_state_change(route_path):
            return

        if route_path == "/api/history":
            save_history([])
            return self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")

        if route_path == "/api/stash":
            params = parse_qs(parsed_url.query)
            raw_entry_type = params.get("entry_type", [""])[0]
            entry_type = _normalize_entry_type(raw_entry_type) if str(
                raw_entry_type).strip() else None
            if params.get("all", [""])[0] == "1":
                try:
                    result = clear_stash_entries(entry_type=entry_type)
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

        if route_path == "/api/bibliography":
            params = parse_qs(parsed_url.query)
            if params.get("all", [""])[0] == "1":
                try:
                    result = clear_stash_entries(entry_type="bibliography")
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

            return self._send(
                400,
                json.dumps(
                    {"error": "set all=1 to clear bibliography stash"}, ensure_ascii=True),
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
