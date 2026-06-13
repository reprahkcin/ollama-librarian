#!/usr/bin/env python3

from dataclasses import dataclass
import json
import logging
import mimetypes
import os
import platform
import re
import resource
import signal
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOGGER = logging.getLogger("ollama_web_chat")


def _env_int(env: Mapping[str, str], key: str, default: int, min_value: int | None = None) -> int:
    raw = str(env.get(key, str(default))).strip()
    try:
        parsed = int(raw)
    except Exception:
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    return parsed


def _env_bool_true_unless_false(env: Mapping[str, str], key: str, default: str = "1") -> bool:
    return str(env.get(key, default)).strip().lower() not in {
        "0", "false", "no", "off"
    }


def _read_update_events_max(raw_value: object) -> int:
    raw_text = str(raw_value).strip()
    try:
        parsed = int(raw_text)
    except Exception:
        LOGGER.warning(
            "Invalid OLLAMA_WEB_UPDATE_EVENTS_MAX=%r; falling back to 200",
            raw_text,
        )
        parsed = 200
    return max(20, parsed)


@dataclass(frozen=True)
class WebConfig:
    host: str
    port: int
    ollama_base: str
    api_key: str
    max_body_bytes: int
    max_upload_bytes: int
    abstract_need_max_chars: int
    abstract_text_max_chars: int
    default_state_dir: Path
    history_path: str
    pdf_source: str
    pdf_index_db: str
    pdf_embed_model: str
    pdf_embed_delay_ms: int
    pdf_doc_cooldown_seconds: int
    pdf_dynamic_throttle: bool
    pdf_dynamic_target_embed_ms: int
    pdf_dynamic_max_delay_ms: int
    pdf_dynamic_delay_step_ms: int
    pdf_dynamic_min_threads: int
    pdf_dynamic_max_threads: int
    pdf_top_k: int
    pdf_answer_timeout: int
    pdf_embed_num_thread: int
    pdf_ocr_on_sync: bool
    pdf_ocr_lang: str
    pdf_ocr_jobs: int
    pdf_ocr_timeout: int
    stash_path: str
    update_state_path: Path
    update_repo_owner: str
    update_repo_name: str
    update_github_token: str
    update_git_branch: str
    update_apply_mode: str
    update_apply_mode_resolved: str
    update_events_max: int
    generate_timeout: int
    model_failure_threshold: int
    model_failure_cooldown_seconds: int
    monitor_enabled: bool
    monitor_max_events: int
    monitor_slow_ms: int
    monitor_log_jsonl: bool
    monitor_log_path: str
    safety_brake_enabled: bool
    safety_brake_cooldown_seconds: int
    safety_brake_cpu_pct: int
    safety_brake_gpu_util_pct: int
    safety_brake_gpu_mem_pct: int
    safety_brake_gpu_temp_c: int
    safety_brake_min_hold_seconds: int
    safety_brake_release_streak: int
    safety_brake_recover_margin_pct: int
    safety_brake_recover_temp_c: int
    soft_throttle_enabled: bool
    soft_throttle_start_ratio_pct: int
    soft_throttle_max_delay_ms: int
    soft_throttle_min_gap_ms: int
    heavy_serial_enabled: bool
    heavy_serial_queue_timeout_seconds: int
    safe_generate_profile_enabled: bool
    safe_generate_num_thread: int
    safe_generate_num_batch: int
    safe_generate_num_gpu: int
    safe_generate_num_predict_cap: int

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "WebConfig":
        default_state_dir = resolve_default_state_dir()
        history_path = os.path.expanduser(
            str(
                env.get(
                    "OLLAMA_WEB_HISTORY_PATH",
                    str(default_state_dir / "ollama-web-chat-history.json"),
                )
            )
        )
        stash_path = os.path.expanduser(
            str(
                env.get(
                    "OLLAMA_WEB_STASH_PATH",
                    str(default_state_dir / "ollama-response-stash.json"),
                )
            )
        )
        update_apply_mode = str(
            env.get("OLLAMA_WEB_UPDATE_APPLY_MODE", "git")).strip().lower()
        update_apply_mode_resolved = (
            update_apply_mode if update_apply_mode in {
                "git", "script"} else "git"
        )

        return cls(
            host=str(env.get("OLLAMA_WEB_HOST", "127.0.0.1")).strip(),
            port=_env_int(env, "OLLAMA_WEB_PORT", 8088),
            ollama_base=str(env.get("OLLAMA_BASE_URL",
                            "http://127.0.0.1:11434")),
            api_key=str(env.get("OLLAMA_WEB_API_KEY", "")),
            max_body_bytes=_env_int(
                env, "OLLAMA_WEB_MAX_BODY_BYTES", 1048576, min_value=1024),
            max_upload_bytes=_env_int(
                env, "OLLAMA_WEB_MAX_UPLOAD_BYTES", 536870912, min_value=1024),
            abstract_need_max_chars=_env_int(
                env, "OLLAMA_WEB_ABSTRACT_NEED_MAX_CHARS", 3000, min_value=64
            ),
            abstract_text_max_chars=_env_int(
                env, "OLLAMA_WEB_ABSTRACT_TEXT_MAX_CHARS", 12000, min_value=256
            ),
            default_state_dir=default_state_dir,
            history_path=history_path,
            pdf_source=os.path.expanduser(
                str(env.get("OLLAMA_WEB_PDF_SOURCE", resolve_default_pdf_source()))
            ),
            pdf_index_db=os.path.expanduser(
                str(env.get("OLLAMA_WEB_PDF_INDEX_DB", str(
                    default_state_dir / "pdf-rag.sqlite")))
            ),
            pdf_embed_model=str(
                env.get("OLLAMA_WEB_PDF_EMBED_MODEL", "nomic-embed-text")),
            pdf_embed_delay_ms=_env_int(
                env, "OLLAMA_WEB_PDF_EMBED_DELAY_MS", 200, min_value=0),
            pdf_doc_cooldown_seconds=_env_int(
                env, "OLLAMA_WEB_PDF_DOC_COOLDOWN_SECONDS", 10, min_value=0),
            pdf_dynamic_throttle=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_PDF_DYNAMIC_THROTTLE", "1"),
            pdf_dynamic_target_embed_ms=_env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_TARGET_EMBED_MS", 1400, min_value=200),
            pdf_dynamic_max_delay_ms=_env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MAX_DELAY_MS", 2000, min_value=0),
            pdf_dynamic_delay_step_ms=_env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_DELAY_STEP_MS", 50, min_value=1),
            pdf_dynamic_min_threads=_env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MIN_THREADS", 1, min_value=1),
            pdf_dynamic_max_threads=_env_int(
                env, "OLLAMA_WEB_PDF_DYNAMIC_MAX_THREADS", 3, min_value=1),
            pdf_embed_num_thread=_env_int(
                env, "OLLAMA_WEB_PDF_EMBED_NUM_THREAD", 2, min_value=1),
            pdf_top_k=_env_int(env, "OLLAMA_WEB_PDF_TOP_K", 6),
            pdf_answer_timeout=_env_int(
                env, "OLLAMA_WEB_PDF_ANSWER_TIMEOUT", 600, min_value=30),
            pdf_ocr_on_sync=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_PDF_OCR_ON_SYNC", "1"),
            pdf_ocr_lang=str(env.get("OLLAMA_WEB_PDF_OCR_LANG", "eng")),
            pdf_ocr_jobs=_env_int(
                env, "OLLAMA_WEB_PDF_OCR_JOBS", 2, min_value=1),
            pdf_ocr_timeout=_env_int(
                env, "OLLAMA_WEB_PDF_OCR_TIMEOUT", 1800, min_value=60),
            stash_path=stash_path,
            update_state_path=Path(os.path.dirname(
                history_path) or str(REPO_ROOT)) / "update-state.json",
            update_repo_owner=str(
                env.get("OLLAMA_WEB_UPDATE_REPO_OWNER", "reprahkcin")),
            update_repo_name=str(
                env.get("OLLAMA_WEB_UPDATE_REPO_NAME", "ollama-librarian")),
            update_github_token=str(
                env.get("OLLAMA_WEB_UPDATE_GITHUB_TOKEN", "")),
            update_git_branch=str(env.get("OLLAMA_WEB_UPDATE_BRANCH", "main")),
            update_apply_mode=update_apply_mode,
            update_apply_mode_resolved=update_apply_mode_resolved,
            update_events_max=_read_update_events_max(
                env.get("OLLAMA_WEB_UPDATE_EVENTS_MAX", "200")),
            generate_timeout=_env_int(
                env, "OLLAMA_WEB_GENERATE_TIMEOUT", 120, min_value=10),
            model_failure_threshold=_env_int(
                env, "OLLAMA_WEB_MODEL_FAILURE_THRESHOLD", 2, min_value=1),
            model_failure_cooldown_seconds=_env_int(
                env, "OLLAMA_WEB_MODEL_FAILURE_COOLDOWN_SECONDS", 180, min_value=5),
            monitor_enabled=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_MONITOR_ENABLED", "1"),
            monitor_max_events=_env_int(
                env, "OLLAMA_WEB_MONITOR_MAX_EVENTS", 1000, min_value=20),
            monitor_slow_ms=_env_int(
                env, "OLLAMA_WEB_MONITOR_SLOW_MS", 2500, min_value=100),
            monitor_log_jsonl=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_MONITOR_LOG_JSONL", "1"),
            monitor_log_path=os.path.expanduser(
                str(
                    env.get(
                        "OLLAMA_WEB_MONITOR_LOG_PATH",
                        str(default_state_dir / "perf-events.jsonl"),
                    )
                )
            ),
            safety_brake_enabled=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_SAFETY_BRAKE_ENABLED", "1"
            ),
            safety_brake_cooldown_seconds=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_COOLDOWN_SECONDS", 300, min_value=30
            ),
            safety_brake_cpu_pct=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_CPU_PCT", 95, min_value=60
            ),
            safety_brake_gpu_util_pct=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_GPU_UTIL_PCT", 92, min_value=50
            ),
            safety_brake_gpu_mem_pct=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_GPU_MEM_PCT", 92, min_value=50
            ),
            safety_brake_gpu_temp_c=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_GPU_TEMP_C", 82, min_value=50
            ),
            safety_brake_min_hold_seconds=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_MIN_HOLD_SECONDS", 45, min_value=0
            ),
            safety_brake_release_streak=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_RELEASE_STREAK", 3, min_value=1
            ),
            safety_brake_recover_margin_pct=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_RECOVER_MARGIN_PCT", 12, min_value=1
            ),
            safety_brake_recover_temp_c=_env_int(
                env, "OLLAMA_WEB_SAFETY_BRAKE_RECOVER_TEMP_C", 6, min_value=1
            ),
            soft_throttle_enabled=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_SOFT_THROTTLE_ENABLED", "1"
            ),
            soft_throttle_start_ratio_pct=_env_int(
                env, "OLLAMA_WEB_SOFT_THROTTLE_START_RATIO_PCT", 24, min_value=20
            ),
            soft_throttle_max_delay_ms=_env_int(
                env, "OLLAMA_WEB_SOFT_THROTTLE_MAX_DELAY_MS", 30000, min_value=0
            ),
            soft_throttle_min_gap_ms=_env_int(
                env, "OLLAMA_WEB_SOFT_THROTTLE_MIN_GAP_MS", 50000, min_value=0
            ),
            heavy_serial_enabled=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_HEAVY_SERIAL_ENABLED", "1"
            ),
            heavy_serial_queue_timeout_seconds=_env_int(
                env, "OLLAMA_WEB_HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS", 30, min_value=0
            ),
            safe_generate_profile_enabled=_env_bool_true_unless_false(
                env, "OLLAMA_WEB_SAFE_GENERATE_PROFILE_ENABLED", "1"
            ),
            safe_generate_num_thread=_env_int(
                env, "OLLAMA_WEB_SAFE_GENERATE_NUM_THREAD", 1, min_value=1
            ),
            safe_generate_num_batch=_env_int(
                env, "OLLAMA_WEB_SAFE_GENERATE_NUM_BATCH", 10, min_value=0
            ),
            safe_generate_num_gpu=_env_int(
                env, "OLLAMA_WEB_SAFE_GENERATE_NUM_GPU", 0, min_value=-1
            ),
            safe_generate_num_predict_cap=_env_int(
                env, "OLLAMA_WEB_SAFE_GENERATE_NUM_PREDICT_CAP", 640, min_value=0
            ),
        )


SUPPORTED_DOC_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".epub"}

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent
SCRIPT_DIR = REPO_ROOT / "scripts"
PACKAGE_ASSET_ROOT = PACKAGE_DIR / "assets"
DEV_ASSET_ROOT = SCRIPT_DIR / "assets"
ASSET_ROOT = DEV_ASSET_ROOT if DEV_ASSET_ROOT.is_dir() else PACKAGE_ASSET_ROOT
PACKAGE_TEMPLATE_ROOT = PACKAGE_DIR / "templates"
DEV_TEMPLATE_ROOT = SCRIPT_DIR / "templates"
TEMPLATE_ROOT = (
    DEV_TEMPLATE_ROOT if DEV_TEMPLATE_ROOT.is_dir() else PACKAGE_TEMPLATE_ROOT
)


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


def resolve_default_stash_path() -> str:
    return os.path.expanduser(str(resolve_default_state_dir() / "ollama-response-stash.json"))


CONFIG = WebConfig.from_env(os.environ)

HOST = CONFIG.host
PORT = CONFIG.port
OLLAMA_BASE = CONFIG.ollama_base
API_KEY = CONFIG.api_key
MAX_BODY_BYTES = CONFIG.max_body_bytes
MAX_UPLOAD_BYTES = CONFIG.max_upload_bytes
ABSTRACT_NEED_MAX_CHARS = CONFIG.abstract_need_max_chars
ABSTRACT_TEXT_MAX_CHARS = CONFIG.abstract_text_max_chars
DEFAULT_STATE_DIR = CONFIG.default_state_dir
HISTORY_PATH = CONFIG.history_path
HISTORY_LOCK = threading.Lock()
PDF_LOCK = threading.Lock()
STASH_LOCK = threading.Lock()
PDF_SOURCE_OVERRIDE_PATH = Path(
    os.path.dirname(HISTORY_PATH) or str(DEFAULT_STATE_DIR)
) / "ui-config.json"


PDF_SOURCE = CONFIG.pdf_source
PDF_INDEX_DB = CONFIG.pdf_index_db
PDF_EMBED_MODEL = CONFIG.pdf_embed_model
PDF_EMBED_DELAY_MS = CONFIG.pdf_embed_delay_ms
PDF_DOC_COOLDOWN_SECONDS = CONFIG.pdf_doc_cooldown_seconds
PDF_DYNAMIC_THROTTLE = CONFIG.pdf_dynamic_throttle
PDF_DYNAMIC_TARGET_EMBED_MS = CONFIG.pdf_dynamic_target_embed_ms
PDF_DYNAMIC_MAX_DELAY_MS = CONFIG.pdf_dynamic_max_delay_ms
PDF_DYNAMIC_DELAY_STEP_MS = CONFIG.pdf_dynamic_delay_step_ms
PDF_DYNAMIC_MIN_THREADS = CONFIG.pdf_dynamic_min_threads
PDF_DYNAMIC_MAX_THREADS = CONFIG.pdf_dynamic_max_threads
PDF_EMBED_NUM_THREAD = CONFIG.pdf_embed_num_thread
PDF_TOP_K = CONFIG.pdf_top_k
PDF_ANSWER_TIMEOUT = CONFIG.pdf_answer_timeout
PDF_OCR_ON_SYNC = CONFIG.pdf_ocr_on_sync
PDF_OCR_LANG = CONFIG.pdf_ocr_lang
PDF_OCR_JOBS = CONFIG.pdf_ocr_jobs
PDF_OCR_TIMEOUT = CONFIG.pdf_ocr_timeout
STASH_PATH = CONFIG.stash_path
APP_VERSION_FILE = REPO_ROOT / "scripts" / "VERSION"
if (PACKAGE_DIR / "VERSION").is_file():
    APP_VERSION_FILE = PACKAGE_DIR / "VERSION"
UPDATE_STATE_PATH = CONFIG.update_state_path
UPDATE_REPO_OWNER = CONFIG.update_repo_owner
UPDATE_REPO_NAME = CONFIG.update_repo_name
UPDATE_GITHUB_TOKEN = CONFIG.update_github_token
UPDATE_GIT_BRANCH = CONFIG.update_git_branch
UPDATE_APPLY_MODE = CONFIG.update_apply_mode
UPDATE_APPLY_MODE_RESOLVED = CONFIG.update_apply_mode_resolved
UPDATE_SCRIPT_MACOS = REPO_ROOT / "scripts" / "librarian-update-macos.sh"
UPDATE_SCRIPT_WINDOWS = REPO_ROOT / "scripts" / "librarian-update-windows.ps1"
UPDATE_EVENTS_MAX = CONFIG.update_events_max
GENERATE_TIMEOUT = CONFIG.generate_timeout
MODEL_FAILURE_THRESHOLD = CONFIG.model_failure_threshold
MODEL_FAILURE_COOLDOWN_SECONDS = CONFIG.model_failure_cooldown_seconds
MONITOR_ENABLED = CONFIG.monitor_enabled
MONITOR_MAX_EVENTS = CONFIG.monitor_max_events
MONITOR_SLOW_MS = CONFIG.monitor_slow_ms
MONITOR_LOG_JSONL = CONFIG.monitor_log_jsonl
MONITOR_LOG_PATH = CONFIG.monitor_log_path
SAFETY_BRAKE_ENABLED = CONFIG.safety_brake_enabled
SAFETY_BRAKE_COOLDOWN_SECONDS = CONFIG.safety_brake_cooldown_seconds
SAFETY_BRAKE_CPU_PCT = CONFIG.safety_brake_cpu_pct
SAFETY_BRAKE_GPU_UTIL_PCT = CONFIG.safety_brake_gpu_util_pct
SAFETY_BRAKE_GPU_MEM_PCT = CONFIG.safety_brake_gpu_mem_pct
SAFETY_BRAKE_GPU_TEMP_C = CONFIG.safety_brake_gpu_temp_c
SAFETY_BRAKE_MIN_HOLD_SECONDS = CONFIG.safety_brake_min_hold_seconds
SAFETY_BRAKE_RELEASE_STREAK = CONFIG.safety_brake_release_streak
SAFETY_BRAKE_RECOVER_MARGIN_PCT = CONFIG.safety_brake_recover_margin_pct
SAFETY_BRAKE_RECOVER_TEMP_C = CONFIG.safety_brake_recover_temp_c
SOFT_THROTTLE_ENABLED = CONFIG.soft_throttle_enabled
SOFT_THROTTLE_START_RATIO_PCT = CONFIG.soft_throttle_start_ratio_pct
SOFT_THROTTLE_MAX_DELAY_MS = CONFIG.soft_throttle_max_delay_ms
SOFT_THROTTLE_MIN_GAP_MS = CONFIG.soft_throttle_min_gap_ms
HEAVY_SERIAL_ENABLED = CONFIG.heavy_serial_enabled
HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS = CONFIG.heavy_serial_queue_timeout_seconds
SAFE_GENERATE_PROFILE_ENABLED = CONFIG.safe_generate_profile_enabled
SAFE_GENERATE_NUM_THREAD = CONFIG.safe_generate_num_thread
SAFE_GENERATE_NUM_BATCH = CONFIG.safe_generate_num_batch
SAFE_GENERATE_NUM_GPU = CONFIG.safe_generate_num_gpu
SAFE_GENERATE_NUM_PREDICT_CAP = CONFIG.safe_generate_num_predict_cap
ASSET_CACHE_BUSTER = str(int(time.time()))

PDF_INDEX_STATE = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
    "last_error": None,
    "pause_requested": False,
    "last_paused_at": None,
    "active_pid": None,
}
PDF_INDEX_PROCESS: subprocess.Popen | None = None
PDF_SOURCE_SCAN_CACHE = {
    "source_path": "",
    "total_documents": 0,
    "scanned_at": 0.0,
}
PDF_SOURCE_SCAN_CACHE_TTL_SECONDS = 30.0
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
    "release_notes_url": None,
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
UPDATE_EVENTS: list[dict] = []
MODEL_GUARD_LOCK = threading.Lock()
MODEL_GUARD_STATE: dict[str, dict[str, object]] = {}
MONITOR_LOCK = threading.Lock()
MONITOR_STATE: dict[str, object] = {
    "started_at": int(time.time()),
    "requests_total": 0,
    "requests_error": 0,
    "requests_slow": 0,
    "by_route": {},
    "recent": [],
    "last_resource": None,
}
CPU_SAMPLE_LOCK = threading.Lock()
CPU_SAMPLE_PREV: dict[str, float | None] = {
    "total": None,
    "idle": None,
}
GPU_SAMPLE_LOCK = threading.Lock()
GPU_SAMPLE_CACHE: dict[str, object] = {
    "ts": 0.0,
    "data": None,
}
SAFETY_BRAKE_LOCK = threading.Lock()
SAFETY_BRAKE_STATE: dict[str, object] = {
    "last_triggered_at": None,
    "last_reason": "",
    "trigger_count": 0,
    "last_resource": None,
    "safe_streak": 0,
}
SOFT_THROTTLE_LOCK = threading.Lock()
SOFT_THROTTLE_STATE: dict[str, object] = {
    "last_heavy_started_at": 0.0,
    "last_delay_ms": 0,
    "last_pressure_ratio": 0.0,
}
HEAVY_OP_LOCK = threading.Lock()
HEAVY_OP_STATE_LOCK = threading.Lock()
HEAVY_OP_STATE: dict[str, object] = {
    "active": False,
    "active_operation": "",
    "active_since_ts": None,
    "last_rejected_at": None,
    "last_rejected_operation": "",
}
COOLDOWN_LOCK = threading.Lock()
COOLDOWN_STATE: dict[str, object] = {
    "until_ts": 0,
    "last_set_at": None,
    "last_cleared_at": None,
    "reason": "",
}


def _cooldown_status_snapshot() -> dict:
    now = int(time.time())
    with COOLDOWN_LOCK:
        until_ts = int(COOLDOWN_STATE.get("until_ts", 0) or 0)
        last_set_at = COOLDOWN_STATE.get("last_set_at")
        last_cleared_at = COOLDOWN_STATE.get("last_cleared_at")
        reason = str(COOLDOWN_STATE.get("reason", "") or "")

    active = until_ts > now
    remaining_seconds = max(0, until_ts - now)
    return {
        "active": active,
        "remaining_seconds": int(remaining_seconds),
        "until_ts": int(until_ts),
        "last_set_at": last_set_at,
        "last_cleared_at": last_cleared_at,
        "reason": reason,
    }


def set_cooldown(seconds: int, reason: str = "") -> dict:
    duration = max(0, int(seconds))
    now = int(time.time())
    until_ts = now + duration

    with COOLDOWN_LOCK:
        COOLDOWN_STATE["until_ts"] = until_ts
        COOLDOWN_STATE["last_set_at"] = now
        COOLDOWN_STATE["reason"] = str(reason or "")[:200]

    # If indexing is currently running, request pause immediately.
    pause_result = pause_pdf_index_job()
    out = _cooldown_status_snapshot()
    out["ok"] = True
    out["pause_result"] = pause_result
    return out


def clear_cooldown() -> dict:
    now = int(time.time())
    with COOLDOWN_LOCK:
        COOLDOWN_STATE["until_ts"] = 0
        COOLDOWN_STATE["last_cleared_at"] = now
        COOLDOWN_STATE["reason"] = ""
    out = _cooldown_status_snapshot()
    out["ok"] = True
    return out


def _cooldown_block_payload(operation: str) -> dict:
    status = _cooldown_status_snapshot()
    reason = str(status.get("reason", "") or "")
    reason_tail = f" Reason: {reason}" if reason else ""
    return {
        "error": (
            f"{operation} paused while cooldown is active. "
            f"Use Resume to continue heavy operations.{reason_tail}"
        ),
        "cooldown": status,
    }


def _is_cooldown_active() -> bool:
    return bool(_cooldown_status_snapshot().get("active"))


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _safety_brake_status_snapshot() -> dict:
    with SAFETY_BRAKE_LOCK:
        return {
            "enabled": bool(SAFETY_BRAKE_ENABLED),
            "cooldown_seconds": int(SAFETY_BRAKE_COOLDOWN_SECONDS),
            "min_hold_seconds": int(SAFETY_BRAKE_MIN_HOLD_SECONDS),
            "release_streak": int(SAFETY_BRAKE_RELEASE_STREAK),
            "thresholds": {
                "cpu_pct": int(SAFETY_BRAKE_CPU_PCT),
                "gpu_util_pct": int(SAFETY_BRAKE_GPU_UTIL_PCT),
                "gpu_mem_pct": int(SAFETY_BRAKE_GPU_MEM_PCT),
                "gpu_temp_c": int(SAFETY_BRAKE_GPU_TEMP_C),
                "recover_margin_pct": int(SAFETY_BRAKE_RECOVER_MARGIN_PCT),
                "recover_temp_c": int(SAFETY_BRAKE_RECOVER_TEMP_C),
            },
            "last_triggered_at": SAFETY_BRAKE_STATE.get("last_triggered_at"),
            "last_reason": str(SAFETY_BRAKE_STATE.get("last_reason", "") or ""),
            "trigger_count": int(SAFETY_BRAKE_STATE.get("trigger_count", 0) or 0),
            "safe_streak": int(SAFETY_BRAKE_STATE.get("safe_streak", 0) or 0),
        }


def _safety_brake_reasons(resource: dict) -> list[str]:
    reasons: list[str] = []
    cpu_now = _safe_float(resource.get("cpu_usage_pct_now"))
    gpu_monitoring = str(resource.get("gpu_monitoring", "") or "")
    gpu_present = bool(resource.get("gpu_present"))
    gpu_util = _safe_float(resource.get("gpu_util_pct_max"))
    gpu_mem = _safe_float(resource.get("gpu_mem_util_pct_max"))
    gpu_temp = _safe_float(resource.get("gpu_temp_c_max"))

    if cpu_now is not None and cpu_now >= float(SAFETY_BRAKE_CPU_PCT):
        reasons.append(
            f"CPU now {round(cpu_now, 1)}% >= {int(SAFETY_BRAKE_CPU_PCT)}%"
        )

    if gpu_monitoring == "ok" and gpu_present:
        if gpu_util is not None and gpu_util >= float(SAFETY_BRAKE_GPU_UTIL_PCT):
            reasons.append(
                f"GPU util {round(gpu_util, 1)}% >= {int(SAFETY_BRAKE_GPU_UTIL_PCT)}%"
            )
        if gpu_mem is not None and gpu_mem >= float(SAFETY_BRAKE_GPU_MEM_PCT):
            reasons.append(
                f"VRAM {round(gpu_mem, 1)}% >= {int(SAFETY_BRAKE_GPU_MEM_PCT)}%"
            )
        if gpu_temp is not None and gpu_temp >= float(SAFETY_BRAKE_GPU_TEMP_C):
            reasons.append(
                f"GPU temp {round(gpu_temp, 1)}C >= {int(SAFETY_BRAKE_GPU_TEMP_C)}C"
            )

    return reasons


def _safety_brake_recovered(resource: dict) -> bool:
    cpu_now = _safe_float(resource.get("cpu_usage_pct_now"))
    gpu_monitoring = str(resource.get("gpu_monitoring", "") or "")
    gpu_present = bool(resource.get("gpu_present"))
    gpu_util = _safe_float(resource.get("gpu_util_pct_max"))
    gpu_mem = _safe_float(resource.get("gpu_mem_util_pct_max"))
    gpu_temp = _safe_float(resource.get("gpu_temp_c_max"))

    cpu_limit = max(0, int(SAFETY_BRAKE_CPU_PCT) -
                    int(SAFETY_BRAKE_RECOVER_MARGIN_PCT))
    gpu_util_limit = max(0, int(SAFETY_BRAKE_GPU_UTIL_PCT) -
                         int(SAFETY_BRAKE_RECOVER_MARGIN_PCT))
    gpu_mem_limit = max(0, int(SAFETY_BRAKE_GPU_MEM_PCT) -
                        int(SAFETY_BRAKE_RECOVER_MARGIN_PCT))
    gpu_temp_limit = max(0, int(SAFETY_BRAKE_GPU_TEMP_C) -
                         int(SAFETY_BRAKE_RECOVER_TEMP_C))

    if cpu_now is not None and cpu_now > float(cpu_limit):
        return False

    if gpu_monitoring == "ok" and gpu_present:
        if gpu_util is not None and gpu_util > float(gpu_util_limit):
            return False
        if gpu_mem is not None and gpu_mem > float(gpu_mem_limit):
            return False
        if gpu_temp is not None and gpu_temp > float(gpu_temp_limit):
            return False

    return True


def _maybe_release_safety_brake(resource: dict | None = None) -> bool:
    snapshot = resource if isinstance(resource, dict) else _resource_snapshot()
    now = int(time.time())

    with COOLDOWN_LOCK:
        reason = str(COOLDOWN_STATE.get("reason", "") or "")
        until_ts = int(COOLDOWN_STATE.get("until_ts", 0) or 0)

    if not reason.startswith("Auto safety brake"):
        with SAFETY_BRAKE_LOCK:
            SAFETY_BRAKE_STATE["safe_streak"] = 0
        return False

    if until_ts <= now:
        with SAFETY_BRAKE_LOCK:
            SAFETY_BRAKE_STATE["safe_streak"] = 0
        return False

    with SAFETY_BRAKE_LOCK:
        last_triggered = int(SAFETY_BRAKE_STATE.get(
            "last_triggered_at", 0) or 0)
        safe_streak = int(SAFETY_BRAKE_STATE.get("safe_streak", 0) or 0)

    if last_triggered > 0 and (now - last_triggered) < int(SAFETY_BRAKE_MIN_HOLD_SECONDS):
        with SAFETY_BRAKE_LOCK:
            SAFETY_BRAKE_STATE["safe_streak"] = 0
        return False

    if not _safety_brake_recovered(snapshot):
        with SAFETY_BRAKE_LOCK:
            SAFETY_BRAKE_STATE["safe_streak"] = 0
            SAFETY_BRAKE_STATE["last_resource"] = snapshot
        return False

    safe_streak += 1
    with SAFETY_BRAKE_LOCK:
        SAFETY_BRAKE_STATE["safe_streak"] = safe_streak
        SAFETY_BRAKE_STATE["last_resource"] = snapshot

    if safe_streak < int(SAFETY_BRAKE_RELEASE_STREAK):
        return False

    clear_cooldown()
    with SAFETY_BRAKE_LOCK:
        SAFETY_BRAKE_STATE["safe_streak"] = 0
    return True


def _maybe_apply_safety_brake(operation: str, resource: dict | None = None) -> dict | None:
    if not SAFETY_BRAKE_ENABLED:
        return None

    snapshot = resource if isinstance(resource, dict) else _resource_snapshot()
    reasons = _safety_brake_reasons(snapshot)
    if not reasons:
        return None

    reason_text = "; ".join(reasons)
    cooldown = set_cooldown(
        seconds=SAFETY_BRAKE_COOLDOWN_SECONDS,
        reason=f"Auto safety brake: {reason_text}",
    )

    with SAFETY_BRAKE_LOCK:
        SAFETY_BRAKE_STATE["last_triggered_at"] = int(time.time())
        SAFETY_BRAKE_STATE["last_reason"] = reason_text
        SAFETY_BRAKE_STATE["trigger_count"] = int(
            SAFETY_BRAKE_STATE.get("trigger_count", 0) or 0
        ) + 1
        SAFETY_BRAKE_STATE["last_resource"] = snapshot
        SAFETY_BRAKE_STATE["safe_streak"] = 0

    return {
        "error": (
            f"{operation} paused by automatic safety brake. "
            f"{reason_text}. Cooling down for at least "
            f"{max(1, int(SAFETY_BRAKE_COOLDOWN_SECONDS / 60))} min."
        ),
        "cooldown": cooldown,
        "safety_brake": {
            "triggered": True,
            "reason": reason_text,
        },
    }


def _preflight_heavy_operation_block(operation: str) -> dict | None:
    resource = _resource_snapshot()

    _maybe_release_safety_brake(resource=resource)

    auto_block = _maybe_apply_safety_brake(operation, resource=resource)
    if isinstance(auto_block, dict):
        return auto_block

    _apply_soft_throttle(operation, resource=resource)

    resource_after_delay = _resource_snapshot()
    _maybe_release_safety_brake(resource=resource_after_delay)
    auto_block = _maybe_apply_safety_brake(
        operation, resource=resource_after_delay)
    if isinstance(auto_block, dict):
        return auto_block

    if _is_cooldown_active():
        return _cooldown_block_payload(operation)

    return None


def _heavy_operation_status_snapshot() -> dict:
    with HEAVY_OP_STATE_LOCK:
        active = bool(HEAVY_OP_STATE.get("active", False))
        active_operation = str(HEAVY_OP_STATE.get(
            "active_operation", "") or "")
        active_since_ts = HEAVY_OP_STATE.get("active_since_ts")
        last_rejected_at = HEAVY_OP_STATE.get("last_rejected_at")
        last_rejected_operation = str(
            HEAVY_OP_STATE.get("last_rejected_operation", "") or ""
        )

    return {
        "enabled": bool(HEAVY_SERIAL_ENABLED),
        "queue_timeout_seconds": int(HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS),
        "active": active,
        "active_operation": active_operation,
        "active_since_ts": active_since_ts,
        "last_rejected_at": last_rejected_at,
        "last_rejected_operation": last_rejected_operation,
    }


def _acquire_heavy_operation_slot(operation: str) -> dict | None:
    if not HEAVY_SERIAL_ENABLED:
        return None

    timeout_seconds = max(0, int(HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS))
    if timeout_seconds <= 0:
        acquired = HEAVY_OP_LOCK.acquire(blocking=False)
    else:
        acquired = HEAVY_OP_LOCK.acquire(timeout=float(timeout_seconds))

    if not acquired:
        now = int(time.time())
        with HEAVY_OP_STATE_LOCK:
            HEAVY_OP_STATE["last_rejected_at"] = now
            HEAVY_OP_STATE["last_rejected_operation"] = operation
            active_operation = str(HEAVY_OP_STATE.get(
                "active_operation", "") or "")

        retry_after = max(1, int(min(30, max(1, timeout_seconds))))
        active_tail = (
            f" Current heavy operation: {active_operation}." if active_operation else ""
        )
        return {
            "error": (
                f"{operation} is waiting for another heavy operation and timed out."
                f" Please retry shortly.{active_tail}"
            ),
            "retry_after_seconds": retry_after,
            "heavy_operation_guard": {
                "enabled": bool(HEAVY_SERIAL_ENABLED),
                "queue_timeout_seconds": int(HEAVY_SERIAL_QUEUE_TIMEOUT_SECONDS),
                "active": True,
                "active_operation": active_operation,
                "active_since_ts": None,
                "last_rejected_at": now,
                "last_rejected_operation": operation,
            },
        }

    now = int(time.time())
    with HEAVY_OP_STATE_LOCK:
        HEAVY_OP_STATE["active"] = True
        HEAVY_OP_STATE["active_operation"] = operation
        HEAVY_OP_STATE["active_since_ts"] = now
    return None


def _release_heavy_operation_slot() -> None:
    if not HEAVY_SERIAL_ENABLED:
        return
    try:
        with HEAVY_OP_STATE_LOCK:
            HEAVY_OP_STATE["active"] = False
            HEAVY_OP_STATE["active_operation"] = ""
            HEAVY_OP_STATE["active_since_ts"] = None
    finally:
        HEAVY_OP_LOCK.release()


def _resource_pressure_ratio(resource: dict) -> float:
    ratios: list[float] = []
    cpu_now = _safe_float(resource.get("cpu_usage_pct_now"))
    gpu_monitoring = str(resource.get("gpu_monitoring", "") or "")
    gpu_present = bool(resource.get("gpu_present"))
    gpu_util = _safe_float(resource.get("gpu_util_pct_max"))
    gpu_mem = _safe_float(resource.get("gpu_mem_util_pct_max"))
    gpu_temp = _safe_float(resource.get("gpu_temp_c_max"))

    if cpu_now is not None and SAFETY_BRAKE_CPU_PCT > 0:
        ratios.append(max(0.0, cpu_now / float(SAFETY_BRAKE_CPU_PCT)))

    if gpu_monitoring == "ok" and gpu_present:
        if gpu_util is not None and SAFETY_BRAKE_GPU_UTIL_PCT > 0:
            ratios.append(
                max(0.0, gpu_util / float(SAFETY_BRAKE_GPU_UTIL_PCT)))
        if gpu_mem is not None and SAFETY_BRAKE_GPU_MEM_PCT > 0:
            ratios.append(max(0.0, gpu_mem / float(SAFETY_BRAKE_GPU_MEM_PCT)))
        if gpu_temp is not None and SAFETY_BRAKE_GPU_TEMP_C > 0:
            ratios.append(max(0.0, gpu_temp / float(SAFETY_BRAKE_GPU_TEMP_C)))

    if not ratios:
        return 0.0
    return max(ratios)


def _apply_soft_throttle(operation: str, resource: dict | None = None) -> dict:
    if not SOFT_THROTTLE_ENABLED:
        return {"applied": False, "delay_ms": 0}

    snapshot = resource if isinstance(resource, dict) else _resource_snapshot()
    pressure_ratio = _resource_pressure_ratio(snapshot)
    start_ratio = max(0.05, min(0.98, float(
        SOFT_THROTTLE_START_RATIO_PCT) / 100.0))

    pressure_delay_ms = 0
    if pressure_ratio > start_ratio and SOFT_THROTTLE_MAX_DELAY_MS > 0:
        scale = min(1.0, (pressure_ratio - start_ratio) /
                    max(0.01, 1.0 - start_ratio))
        pressure_delay_ms = int(
            round(float(SOFT_THROTTLE_MAX_DELAY_MS) * scale))

    # Reserve a start slot while holding the lock so concurrent heavy requests
    # cannot calculate the same delay and then launch together.
    with SOFT_THROTTLE_LOCK:
        now = time.time()
        last_heavy_started_at = float(
            SOFT_THROTTLE_STATE.get("last_heavy_started_at", 0.0) or 0.0
        )
        target_start_at = now
        if SOFT_THROTTLE_MIN_GAP_MS > 0 and last_heavy_started_at > 0:
            min_gap_s = float(SOFT_THROTTLE_MIN_GAP_MS) / 1000.0
            target_start_at = max(
                target_start_at, last_heavy_started_at + min_gap_s)
        if pressure_delay_ms > 0:
            pressure_delay_s = float(pressure_delay_ms) / 1000.0
            target_start_at = max(target_start_at, now + pressure_delay_s)

        SOFT_THROTTLE_STATE["last_heavy_started_at"] = target_start_at
        delay_ms = int(max(0.0, round((target_start_at - now) * 1000.0)))

    if delay_ms > 0:
        time.sleep(float(delay_ms) / 1000.0)

    with SOFT_THROTTLE_LOCK:
        SOFT_THROTTLE_STATE["last_delay_ms"] = int(delay_ms)
        SOFT_THROTTLE_STATE["last_pressure_ratio"] = float(
            round(pressure_ratio, 4))

    if delay_ms >= 500:
        LOGGER.info(
            "Soft throttle delayed %s by %sms (pressure_ratio=%.2f)",
            operation,
            delay_ms,
            pressure_ratio,
        )

    return {
        "applied": bool(delay_ms > 0),
        "delay_ms": int(delay_ms),
        "pressure_ratio": float(round(pressure_ratio, 4)),
    }


def _coerce_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _apply_safe_generate_profile(payload: dict) -> dict:
    if not SAFE_GENERATE_PROFILE_ENABLED or not isinstance(payload, dict):
        return payload

    options = payload.get("options")
    if not isinstance(options, dict):
        options = {}
        payload["options"] = options

    if SAFE_GENERATE_NUM_THREAD > 0:
        existing = options.get("num_thread")
        if existing in (None, ""):
            options["num_thread"] = int(SAFE_GENERATE_NUM_THREAD)
        else:
            options["num_thread"] = max(1, _coerce_int(
                existing, SAFE_GENERATE_NUM_THREAD))

    if SAFE_GENERATE_NUM_BATCH > 0:
        existing = options.get("num_batch")
        if existing in (None, ""):
            options["num_batch"] = int(SAFE_GENERATE_NUM_BATCH)
        else:
            options["num_batch"] = max(1, _coerce_int(
                existing, SAFE_GENERATE_NUM_BATCH))

    if SAFE_GENERATE_NUM_GPU >= 0:
        existing_num_gpu = options.get("num_gpu")
        if existing_num_gpu in (None, ""):
            options["num_gpu"] = int(SAFE_GENERATE_NUM_GPU)
        else:
            options["num_gpu"] = max(0, _coerce_int(
                existing_num_gpu, SAFE_GENERATE_NUM_GPU))

    if SAFE_GENERATE_NUM_PREDICT_CAP > 0:
        existing_predict = options.get("num_predict")
        if existing_predict in (None, ""):
            options["num_predict"] = int(SAFE_GENERATE_NUM_PREDICT_CAP)
        else:
            parsed = _coerce_int(
                existing_predict, SAFE_GENERATE_NUM_PREDICT_CAP)
            if parsed <= 0:
                options["num_predict"] = int(SAFE_GENERATE_NUM_PREDICT_CAP)
            else:
                options["num_predict"] = min(
                    parsed, int(SAFE_GENERATE_NUM_PREDICT_CAP))

    return payload


def _safe_cpu_load_percent() -> float | None:
    try:
        load_1m = float(os.getloadavg()[0])
    except Exception:
        return None
    cpu_count = os.cpu_count() or 1
    return round((load_1m / float(cpu_count)) * 100.0, 2)


def _safe_cpu_usage_percent_now() -> float | None:
    if platform.system().lower() != "linux":
        return None
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first = f.readline().strip()
    except Exception:
        return None

    parts = first.split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None

    try:
        values = [float(part) for part in parts[1:]]
    except Exception:
        return None

    total = float(sum(values))
    idle = float(values[3] + (values[4] if len(values) > 4 else 0.0))

    with CPU_SAMPLE_LOCK:
        prev_total = CPU_SAMPLE_PREV.get("total")
        prev_idle = CPU_SAMPLE_PREV.get("idle")
        CPU_SAMPLE_PREV["total"] = total
        CPU_SAMPLE_PREV["idle"] = idle

    if prev_total is None or prev_idle is None:
        return None

    delta_total = total - float(prev_total)
    delta_idle = idle - float(prev_idle)
    if delta_total <= 0:
        return None

    usage_pct = max(
        0.0, min(100.0, ((delta_total - delta_idle) / delta_total) * 100.0))
    return round(usage_pct, 2)


def _safe_gpu_snapshot_uncached() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "gpu_monitoring": "unavailable",
            "gpu_present": False,
        }

    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=utilization.gpu,memory.total,memory.used,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.2,
        )
    except subprocess.TimeoutExpired:
        return {
            "gpu_monitoring": "timeout",
            "gpu_present": False,
        }
    except Exception as exc:
        return {
            "gpu_monitoring": "error",
            "gpu_present": False,
            "gpu_error": str(exc)[:180],
        }

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {
            "gpu_monitoring": "error",
            "gpu_present": False,
            "gpu_error": detail[:180],
        }

    lines = [line.strip()
             for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        return {
            "gpu_monitoring": "ok",
            "gpu_present": False,
            "gpu_count": 0,
        }

    util_values: list[float] = []
    temp_values: list[float] = []
    power_values: list[float] = []
    mem_util_values: list[float] = []
    mem_total_sum = 0.0
    mem_used_sum = 0.0

    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue

        def _to_float(raw: str) -> float | None:
            try:
                return float(raw)
            except Exception:
                return None

        util = _to_float(parts[0])
        mem_total = _to_float(parts[1])
        mem_used = _to_float(parts[2])
        temp_c = _to_float(parts[3])
        power_w = _to_float(parts[4])

        if util is not None:
            util_values.append(util)
        if temp_c is not None:
            temp_values.append(temp_c)
        if power_w is not None:
            power_values.append(power_w)
        if mem_total is not None and mem_total > 0:
            mem_total_sum += mem_total
            if mem_used is not None and mem_used >= 0:
                mem_used_sum += mem_used
                mem_util_values.append((mem_used / mem_total) * 100.0)

    return {
        "gpu_monitoring": "ok",
        "gpu_present": True,
        "gpu_count": len(lines),
        "gpu_util_pct_max": round(max(util_values), 2) if util_values else None,
        "gpu_temp_c_max": round(max(temp_values), 2) if temp_values else None,
        "gpu_power_w_max": round(max(power_values), 2) if power_values else None,
        "gpu_mem_util_pct_max": round(max(mem_util_values), 2) if mem_util_values else None,
        "gpu_mem_used_mb": round(mem_used_sum, 2) if mem_used_sum > 0 else None,
        "gpu_mem_total_mb": round(mem_total_sum, 2) if mem_total_sum > 0 else None,
    }


def _safe_gpu_snapshot_cached(ttl_seconds: float = 2.0) -> dict:
    now = time.time()
    with GPU_SAMPLE_LOCK:
        cached_ts = float(GPU_SAMPLE_CACHE.get("ts", 0.0) or 0.0)
        cached_data = GPU_SAMPLE_CACHE.get("data")
        if isinstance(cached_data, dict) and now - cached_ts <= max(0.1, ttl_seconds):
            return dict(cached_data)

    snapshot = _safe_gpu_snapshot_uncached()

    with GPU_SAMPLE_LOCK:
        GPU_SAMPLE_CACHE["ts"] = now
        GPU_SAMPLE_CACHE["data"] = snapshot

    return dict(snapshot)


def _safe_mem_available_mb() -> float | None:
    if platform.system().lower() == "linux":
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kib = float(parts[1])
                            return round(kib / 1024.0, 2)
        except Exception:
            return None
    return None


def _safe_process_rss_mb() -> float | None:
    if platform.system().lower() == "linux":
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kib = float(parts[1])
                            return round(kib / 1024.0, 2)
        except Exception:
            pass

    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_kib = float(usage.ru_maxrss or 0)
        if platform.system().lower() == "darwin":
            # macOS reports ru_maxrss in bytes.
            rss_kib = rss_kib / 1024.0
        return round(rss_kib / 1024.0, 2)
    except Exception:
        return None


def _resource_snapshot() -> dict:
    disk_path = os.path.dirname(HISTORY_PATH) or str(DEFAULT_STATE_DIR)
    disk_free_mb = None
    try:
        _, _, free = shutil.disk_usage(disk_path)
        disk_free_mb = round(float(free) / (1024.0 * 1024.0), 2)
    except Exception:
        disk_free_mb = None

    snapshot = {
        "ts": int(time.time()),
        "cpu_load_pct_1m": _safe_cpu_load_percent(),
        "cpu_usage_pct_now": _safe_cpu_usage_percent_now(),
        "cpu_count": int(os.cpu_count() or 1),
        "mem_available_mb": _safe_mem_available_mb(),
        "process_rss_mb": _safe_process_rss_mb(),
        "disk_free_mb": disk_free_mb,
    }
    snapshot.update(_safe_gpu_snapshot_cached())
    return snapshot


def _append_monitor_event_jsonl(event: dict) -> None:
    if not MONITOR_LOG_JSONL:
        return
    try:
        parent = os.path.dirname(MONITOR_LOG_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(MONITOR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception:
        LOGGER.debug("Failed to append monitor event", exc_info=True)


def _record_request_metric(event: dict) -> None:
    if not MONITOR_ENABLED:
        return

    route_key = f"{event.get('method', 'GET')} {event.get('path', '/')}"
    status = int(event.get("status", 500) or 500)
    duration_ms = float(event.get("duration_ms", 0.0) or 0.0)

    with MONITOR_LOCK:
        MONITOR_STATE["requests_total"] = int(
            MONITOR_STATE.get("requests_total", 0) or 0
        ) + 1
        if status >= 500:
            MONITOR_STATE["requests_error"] = int(
                MONITOR_STATE.get("requests_error", 0) or 0
            ) + 1
        if duration_ms >= float(MONITOR_SLOW_MS):
            MONITOR_STATE["requests_slow"] = int(
                MONITOR_STATE.get("requests_slow", 0) or 0
            ) + 1

        by_route = MONITOR_STATE.get("by_route")
        if not isinstance(by_route, dict):
            by_route = {}
            MONITOR_STATE["by_route"] = by_route
        route_state = by_route.setdefault(
            route_key,
            {
                "count": 0,
                "errors": 0,
                "slow": 0,
                "last_status": 0,
                "last_duration_ms": 0.0,
                "last_seen": 0,
            },
        )
        route_state["count"] = int(route_state.get("count", 0) or 0) + 1
        if status >= 500:
            route_state["errors"] = int(route_state.get("errors", 0) or 0) + 1
        if duration_ms >= float(MONITOR_SLOW_MS):
            route_state["slow"] = int(route_state.get("slow", 0) or 0) + 1
        route_state["last_status"] = status
        route_state["last_duration_ms"] = round(duration_ms, 2)
        route_state["last_seen"] = int(
            event.get("ts", int(time.time())) or int(time.time()))

        recent = MONITOR_STATE.get("recent")
        if not isinstance(recent, list):
            recent = []
            MONITOR_STATE["recent"] = recent
        recent.append(event)
        max_events = max(20, int(MONITOR_MAX_EVENTS))
        if len(recent) > max_events:
            del recent[:-max_events]

        MONITOR_STATE["last_resource"] = event.get("resource_after")

    _append_monitor_event_jsonl(event)


def get_monitor_snapshot(limit: int = 200) -> dict:
    if not MONITOR_ENABLED:
        return {
            "ok": True,
            "enabled": False,
            "message": "Monitoring is disabled",
        }

    current_resource = _resource_snapshot()
    _maybe_release_safety_brake(resource=current_resource)
    _maybe_apply_safety_brake("Heavy operations", resource=current_resource)

    with MONITOR_LOCK:
        recent = MONITOR_STATE.get("recent")
        if not isinstance(recent, list):
            recent = []
        clipped = recent[-max(0, int(limit)):]
        by_route = MONITOR_STATE.get("by_route")
        if not isinstance(by_route, dict):
            by_route = {}

        hot_routes = sorted(
            [
                {
                    "route": str(route),
                    "count": int(stats.get("count", 0) or 0),
                    "errors": int(stats.get("errors", 0) or 0),
                    "slow": int(stats.get("slow", 0) or 0),
                    "last_status": int(stats.get("last_status", 0) or 0),
                    "last_duration_ms": float(stats.get("last_duration_ms", 0.0) or 0.0),
                    "last_seen": int(stats.get("last_seen", 0) or 0),
                }
                for route, stats in by_route.items()
                if isinstance(stats, dict)
            ],
            key=lambda item: (item["errors"], item["slow"], item["count"]),
            reverse=True,
        )

        snapshot = {
            "ok": True,
            "enabled": True,
            "slow_threshold_ms": int(MONITOR_SLOW_MS),
            "log_jsonl_enabled": bool(MONITOR_LOG_JSONL),
            "log_path": MONITOR_LOG_PATH,
            "started_at": int(MONITOR_STATE.get("started_at", 0) or 0),
            "requests_total": int(MONITOR_STATE.get("requests_total", 0) or 0),
            "requests_error": int(MONITOR_STATE.get("requests_error", 0) or 0),
            "requests_slow": int(MONITOR_STATE.get("requests_slow", 0) or 0),
            "last_resource": current_resource,
            "cooldown": _cooldown_status_snapshot(),
            "safety_brake": _safety_brake_status_snapshot(),
            "heavy_operation_guard": _heavy_operation_status_snapshot(),
            "hot_routes": hot_routes[:20],
            "recent_requests": list(reversed(clipped)),
        }
        MONITOR_STATE["last_resource"] = current_resource
    return snapshot


def reset_monitor_snapshot() -> dict:
    with MONITOR_LOCK:
        MONITOR_STATE["started_at"] = int(time.time())
        MONITOR_STATE["requests_total"] = 0
        MONITOR_STATE["requests_error"] = 0
        MONITOR_STATE["requests_slow"] = 0
        MONITOR_STATE["by_route"] = {}
        MONITOR_STATE["recent"] = []
        MONITOR_STATE["last_resource"] = _resource_snapshot()
    return {"ok": True, "enabled": bool(MONITOR_ENABLED)}


def _resource_failure_detail(text: object) -> bool:
    detail = str(text or "").strip().lower()
    if not detail:
        return False
    indicators = (
        "out of memory",
        "memory",
        "vram",
        "allocation",
        "killed",
        "signal",
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "unexpected eof",
    )
    return any(indicator in detail for indicator in indicators)


def _model_guard_state_for(model: str) -> dict[str, object]:
    now = time.time()
    with MODEL_GUARD_LOCK:
        normalized = _normalize_whitespace(model).lower()
        state = MODEL_GUARD_STATE.setdefault(
            normalized,
            {
                "failure_count": 0,
                "cooldown_until": 0.0,
                "last_error": "",
                "last_failed_at": 0.0,
            },
        )
        return {
            "model": normalized,
            "failure_count": int(state.get("failure_count", 0) or 0),
            "cooldown_until": float(state.get("cooldown_until", 0.0) or 0.0),
            "last_error": str(state.get("last_error", "") or ""),
            "last_failed_at": float(state.get("last_failed_at", 0.0) or 0.0),
            "now": now,
        }


def _model_guard_remaining_seconds(model: str) -> int:
    snapshot = _model_guard_state_for(model)
    cooldown_until = float(snapshot.get("cooldown_until", 0.0) or 0.0)
    now = float(snapshot.get("now", time.time()) or time.time())
    if cooldown_until <= now:
        return 0
    return max(1, int(cooldown_until - now) + 1)


def _model_guard_record_failure(model: str, detail: str) -> tuple[bool, int]:
    normalized = _normalize_whitespace(model).lower()
    now = time.time()
    with MODEL_GUARD_LOCK:
        state = MODEL_GUARD_STATE.setdefault(
            normalized,
            {
                "failure_count": 0,
                "cooldown_until": 0.0,
                "last_error": "",
                "last_failed_at": 0.0,
            },
        )
        failure_count = int(state.get("failure_count", 0) or 0) + 1
        state["failure_count"] = failure_count
        state["last_error"] = str(detail or "")[:400]
        state["last_failed_at"] = now

        threshold = max(1, int(MODEL_FAILURE_THRESHOLD))
        if failure_count >= threshold:
            cooldown_until = now + \
                float(max(1, int(MODEL_FAILURE_COOLDOWN_SECONDS)))
            state["cooldown_until"] = cooldown_until
            retry_after = max(1, int(cooldown_until - now) + 1)
            return True, retry_after

    return False, 0


def _model_guard_clear(model: str) -> None:
    normalized = _normalize_whitespace(model).lower()
    with MODEL_GUARD_LOCK:
        if normalized in MODEL_GUARD_STATE:
            del MODEL_GUARD_STATE[normalized]


def _model_guard_error_payload(
    model: str,
    detail: str,
    retry_after_seconds: int,
    guarded: bool,
) -> dict:
    retry_after = max(0, int(retry_after_seconds or 0))
    detail_text = str(detail or "").strip()
    if guarded:
        error = (
            f"Model '{model}' is temporarily paused after repeated failures. "
            f"Retry in about {retry_after} seconds."
        )
    else:
        error = detail_text or f"Model '{model}' request failed"

    payload = {
        "error": error,
        "model": str(model),
        "guarded": bool(guarded),
        "retry_after_seconds": retry_after,
    }
    if detail_text:
        payload["detail"] = detail_text[:500]
    return payload


def _load_pdf_source_override() -> str:
    try:
        if not PDF_SOURCE_OVERRIDE_PATH.is_file():
            return ""
        payload = json.loads(
            PDF_SOURCE_OVERRIDE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return ""
        value = str(payload.get("pdf_source", "") or "").strip()
        return os.path.expanduser(value) if value else ""
    except Exception as exc:
        LOGGER.warning("Failed to load PDF source override: %s", exc)
        return ""


def _persist_pdf_source_override_unlocked(source_path: str) -> None:
    PDF_SOURCE_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PDF_SOURCE_OVERRIDE_PATH.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps({"pdf_source": source_path}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, PDF_SOURCE_OVERRIDE_PATH)


def _bootstrap_pdf_source_override() -> None:
    global PDF_SOURCE

    override = _load_pdf_source_override()
    if not override:
        return

    try:
        resolved = Path(override)
        resolved.mkdir(parents=True, exist_ok=True)
        if not resolved.is_dir():
            raise RuntimeError("configured path is not a directory")
        PDF_SOURCE = str(resolved)
    except Exception as exc:
        LOGGER.warning(
            "Ignoring invalid PDF source override %r: %s", override, exc)


def get_pdf_source_path() -> str:
    with PDF_LOCK:
        return str(PDF_SOURCE)


def set_pdf_source_path(raw_path: str) -> dict:
    global PDF_SOURCE

    requested = str(raw_path or "").strip()
    if not requested:
        raise ValueError("source_path is required")

    resolved = Path(os.path.expanduser(requested)).resolve()
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("source_path must resolve to a directory")
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"source_path could not be prepared: {exc}") from exc
    if not resolved.is_dir():
        raise ValueError("source_path must resolve to a directory")
    normalized = str(resolved)

    with PDF_LOCK:
        if PDF_INDEX_STATE.get("running"):
            raise RuntimeError(
                "Cannot change library directory while indexing is running")

        changed = normalized != str(PDF_SOURCE)
        PDF_SOURCE = normalized
        PDF_SOURCE_SCAN_CACHE["source_path"] = ""
        PDF_SOURCE_SCAN_CACHE["total_documents"] = 0
        PDF_SOURCE_SCAN_CACHE["scanned_at"] = 0.0
        _persist_pdf_source_override_unlocked(normalized)

    return {
        "ok": True,
        "changed": bool(changed),
        "source_path": normalized,
    }


def _pick_directory_with_native_dialog() -> str | None:
    picker_timeout_seconds = 60
    system = platform.system().lower()

    if system == "windows":
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$dialog.Description = 'Select Library Directory'; "
                "$dialog.ShowNewFolderButton = $true; "
                "$result = $dialog.ShowDialog(); "
                "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { "
                "Write-Output $dialog.SelectedPath }"
            ),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=picker_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Windows folder dialog timed out after {picker_timeout_seconds}s. You can set the path manually."
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(detail or "Windows folder dialog failed")
        selected = (proc.stdout or "").strip()
        return selected or None

    if system == "darwin":
        cmd = [
            "osascript",
            "-e",
            (
                'tell application "Finder"\n'
                "activate\n"
                'set chosenFolder to choose folder with prompt "Select Library Directory" '
                "default location (path to home folder)\n"
                "set posixPath to POSIX path of chosenFolder\n"
                "return posixPath\n"
                "end tell"
            ),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=picker_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"macOS folder dialog timed out after {picker_timeout_seconds}s. You can set the path manually."
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            if "User canceled" in detail:
                return None
            raise RuntimeError(detail or "macOS folder dialog failed")
        selected = (proc.stdout or "").strip()
        return selected or None

    linux_pick_cmds = []
    if shutil.which("zenity"):
        linux_pick_cmds.append([
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Select Library Directory",
        ])
    if shutil.which("kdialog"):
        linux_pick_cmds.append([
            "kdialog",
            "--getexistingdirectory",
            str(Path.home()),
            "--title",
            "Select Library Directory",
        ])
    if shutil.which("yad"):
        linux_pick_cmds.append([
            "yad",
            "--file-selection",
            "--directory",
            "--title=Select Library Directory",
        ])

    if not linux_pick_cmds:
        raise RuntimeError(
            "No native folder picker found. Install zenity/kdialog/yad, or set the path manually."
        )

    last_error = ""
    for cmd in linux_pick_cmds:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=picker_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Linux folder dialog timed out after {picker_timeout_seconds}s. You can set the path manually."
            ) from exc
        if proc.returncode == 0:
            selected = (proc.stdout or "").strip()
            return selected or None
        if proc.returncode == 1:
            return None
        last_error = (proc.stderr or proc.stdout or "").strip()

    raise RuntimeError(last_error or "Linux folder dialog failed")


_bootstrap_pdf_source_override()


def _append_update_event_unlocked() -> None:
    UPDATE_EVENTS.append(
        {
            "ts": int(time.time()),
            "job_id": UPDATE_STATE.get("job_id"),
            "state": UPDATE_STATE.get("state"),
            "step": UPDATE_STATE.get("step"),
            "progress_pct": UPDATE_STATE.get("progress_pct"),
            "message": UPDATE_STATE.get("message"),
            "running": bool(UPDATE_STATE.get("running")),
            "target_version": UPDATE_STATE.get("target_version"),
            "latest_version": UPDATE_STATE.get("latest_version"),
            "source": UPDATE_STATE.get("source"),
            "release_notes_url": UPDATE_STATE.get("release_notes_url"),
            "update_available": bool(UPDATE_STATE.get("update_available")),
            "last_error": UPDATE_STATE.get("last_error"),
        }
    )
    if len(UPDATE_EVENTS) > UPDATE_EVENTS_MAX:
        del UPDATE_EVENTS[:-UPDATE_EVENTS_MAX]


def _persist_update_state_unlocked():
    try:
        UPDATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = UPDATE_STATE_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"state": UPDATE_STATE, "events": UPDATE_EVENTS},
                      f, ensure_ascii=True)
        os.replace(tmp_path, UPDATE_STATE_PATH)
    except Exception as exc:
        LOGGER.exception("Failed to persist update state")


def _set_update_state(**changes):
    with UPDATE_LOCK:
        UPDATE_STATE.update(changes)
        _append_update_event_unlocked()
        _persist_update_state_unlocked()


def _load_update_state():
    try:
        if not UPDATE_STATE_PATH.is_file():
            return
        data = json.loads(UPDATE_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return

        loaded_state = data.get("state") if isinstance(
            data.get("state"), dict) else data
        loaded_events = data.get("events") if isinstance(
            data.get("events"), list) else []

        with UPDATE_LOCK:
            for key in list(UPDATE_STATE.keys()):
                if key in loaded_state:
                    UPDATE_STATE[key] = loaded_state[key]

            UPDATE_EVENTS.clear()
            for item in loaded_events:
                if isinstance(item, dict):
                    UPDATE_EVENTS.append(item)
            if len(UPDATE_EVENTS) > UPDATE_EVENTS_MAX:
                del UPDATE_EVENTS[:-UPDATE_EVENTS_MAX]

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
                _append_update_event_unlocked()
                _persist_update_state_unlocked()
    except Exception as exc:
        LOGGER.exception("Failed to load persisted update state")
        with UPDATE_LOCK:
            UPDATE_STATE["last_error"] = f"Failed to load persisted update state: {exc}"


_load_update_state()


def _normalize_whitespace(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def _clamp_confidence(value: object, default: int = 50) -> int:
    try:
        num = int(round(float(value)))
    except Exception:
        num = default
    return max(0, min(100, num))


def _confidence_bucket(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 55:
        return "Moderate"
    return "Low"


def _normalize_recommendation(value: object, score_hint: int = 50) -> str:
    raw = _normalize_whitespace(value).lower()
    compact = raw.replace("-", "_").replace(" ", "_")
    if compact in {"download", "download_and_index", "index", "yes", "strong_yes"}:
        return "download_and_index"
    if compact in {"maybe", "unclear", "needs_review", "borderline"}:
        return "maybe"
    if compact in {"skip", "do_not_download", "no", "reject"}:
        return "skip"

    if score_hint >= 75:
        return "download_and_index"
    if score_hint >= 45:
        return "maybe"
    return "skip"


def _recommendation_label(code: str) -> str:
    if code == "download_and_index":
        return "Download and index"
    if code == "skip":
        return "Skip for now"
    return "Maybe / needs manual review"


def _extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        loaded = json.loads(match.group(0))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        return {}
    return {}


def _extract_reason_list(value: object, fallback_text: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for item in value:
            cleaned = _normalize_whitespace(item)
            if cleaned:
                out.append(cleaned)
            if len(out) >= 4:
                break
    elif isinstance(value, str):
        parts = [
            _normalize_whitespace(piece)
            for piece in re.split(r"\n+|;\s*", value)
        ]
        out.extend([piece for piece in parts if piece][:4])

    if out:
        return out[:4]

    fallback = _normalize_whitespace(fallback_text)
    if fallback:
        sentence_parts = [
            _normalize_whitespace(piece)
            for piece in re.split(r"(?<=[.!?])\s+", fallback)
        ]
        return [piece for piece in sentence_parts if piece][:3]
    return []


def build_abstract_eval_prompt(research_need: str, abstract_text: str) -> str:
    return (
        "You are assisting a researcher in deciding whether to download and index a paper based on its abstract. "
        "Return JSON only with this exact schema: "
        "{\"confidence\": number 0-100, \"recommendation\": \"download_and_index\"|\"maybe\"|\"skip\", "
        "\"reasons\": [string, ... up to 4], \"signals\": [string, ... up to 4], \"concerns\": [string, ... up to 4]}. "
        "Confidence should reflect match quality between the research need and abstract. "
        "Use concise, evidence-grounded points. Do not include markdown or extra keys.\n\n"
        f"Research need:\n{research_need}\n\n"
        f"Abstract:\n{abstract_text}\n"
    )


def evaluate_abstract_relevance(
    model: str,
    research_need: str,
    abstract_text: str,
    instructions: str = "",
) -> dict:
    prompt = build_abstract_eval_prompt(research_need, abstract_text)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": "60s",
    }
    if instructions:
        payload["system"] = instructions

    req = Request(
        f"{OLLAMA_BASE.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_BASE}: {exc}") from exc

    try:
        data = json.loads(body) if body else {}
    except Exception as exc:
        raise RuntimeError(
            "Invalid response from Ollama generate endpoint") from exc

    raw_response = str(data.get("response", "") or "").strip()
    parsed = _extract_json_object(raw_response)

    confidence = _clamp_confidence(parsed.get("confidence", 50))
    recommendation = _normalize_recommendation(
        parsed.get("recommendation", ""), confidence
    )
    reasons = _extract_reason_list(parsed.get("reasons", []), raw_response)
    signals = _extract_reason_list(parsed.get("signals", []), "")
    concerns = _extract_reason_list(parsed.get("concerns", []), "")

    return {
        "ok": True,
        "confidence": confidence,
        "confidence_label": _confidence_bucket(confidence),
        "recommendation": recommendation,
        "recommendation_label": _recommendation_label(recommendation),
        "reasons": reasons,
        "signals": signals,
        "concerns": concerns,
        "raw_response": raw_response,
    }


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
        "notes_url": _sanitize_release_notes_url(data.get("html_url")),
    }


def _sanitize_release_notes_url(raw_url: str | None) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        LOGGER.warning("Ignoring unsafe release notes URL: %r", value)
        return None
    return value


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


def get_update_events(limit: int = 50) -> dict:
    try:
        requested_limit = int(limit)
    except Exception:
        requested_limit = 50
    safe_limit = max(1, min(UPDATE_EVENTS_MAX, requested_limit))
    with UPDATE_LOCK:
        events = list(UPDATE_EVENTS)
    events.reverse()
    return {
        "ok": True,
        "count": min(safe_limit, len(events)),
        "total_count": len(events),
        "events": events[:safe_limit],
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
        release_notes_url=None,
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
        release = dict(fetch_latest_release())
        release["notes_url"] = _sanitize_release_notes_url(
            release.get("notes_url"))
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
            release_notes_url=_sanitize_release_notes_url(
                release.get("notes_url")),
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
            release_notes_url=None,
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
            release_notes_url=None,
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
        _append_update_event_unlocked()
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


def _build_pdf_rag_command(extra_args: list[str]) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    if os.path.isdir(src_path):
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            src_path
            if not existing_pythonpath
            else f"{src_path}{os.pathsep}{existing_pythonpath}"
        )
    cmd = [
        sys.executable,
        "-m",
        "ollama_librarian.indexer",
        "--ollama-base",
        OLLAMA_BASE,
        "--embed-model",
        PDF_EMBED_MODEL,
        "--embed-num-thread",
        str(PDF_EMBED_NUM_THREAD),
        "--embed-delay-ms",
        str(PDF_EMBED_DELAY_MS),
        "--doc-cooldown-seconds",
        str(PDF_DOC_COOLDOWN_SECONDS),
        "--dynamic-target-embed-ms",
        str(PDF_DYNAMIC_TARGET_EMBED_MS),
        "--dynamic-max-delay-ms",
        str(PDF_DYNAMIC_MAX_DELAY_MS),
        "--dynamic-delay-step-ms",
        str(PDF_DYNAMIC_DELAY_STEP_MS),
        "--dynamic-min-threads",
        str(PDF_DYNAMIC_MIN_THREADS),
        "--dynamic-max-threads",
        str(PDF_DYNAMIC_MAX_THREADS),
        "--index-db",
        PDF_INDEX_DB,
    ]
    cmd.append(
        "--dynamic-throttle" if PDF_DYNAMIC_THROTTLE else "--no-dynamic-throttle")
    cmd.extend(list(extra_args))
    return cmd, env


def run_pdf_rag(extra_args, timeout: int | None = 600):
    cmd, env = _build_pdf_rag_command(list(extra_args))
    timeout_arg: int | None
    if timeout is None:
        timeout_arg = None
    else:
        timeout_arg = int(timeout)
        if timeout_arg <= 0:
            timeout_arg = None
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_arg, env=env)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"Command failed: {' '.join(cmd)}")
    return out


def pause_pdf_index_job() -> dict:
    global PDF_INDEX_PROCESS

    with PDF_LOCK:
        proc = PDF_INDEX_PROCESS
        if not PDF_INDEX_STATE.get("running") or proc is None:
            return {"ok": True, "paused": False, "message": "Index job is not running"}
        PDF_INDEX_STATE["pause_requested"] = True
        PDF_INDEX_STATE["last_paused_at"] = int(time.time())
        pid = int(proc.pid or 0)

    try:
        if platform.system().lower() == "windows":
            proc.terminate()
        else:
            if pid > 0:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except Exception:
                    proc.terminate()
            else:
                proc.terminate()
    except Exception as exc:
        return {"ok": False, "paused": False, "error": str(exc)}

    return {"ok": True, "paused": True, "message": "Pause requested"}


def _count_source_documents(source_path: str) -> int:
    root = Path(source_path).expanduser()
    if not root.exists() or not root.is_dir():
        return 0

    total = 0
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in SUPPORTED_DOC_EXTENSIONS:
            total += 1
    return total


def _get_source_document_total(source_path: str) -> int:
    now = time.time()
    with PDF_LOCK:
        cached_source = str(PDF_SOURCE_SCAN_CACHE.get("source_path", ""))
        cached_total = int(PDF_SOURCE_SCAN_CACHE.get(
            "total_documents", 0) or 0)
        cached_at = float(PDF_SOURCE_SCAN_CACHE.get("scanned_at", 0.0) or 0.0)
        if (
            cached_source == str(source_path)
            and (now - cached_at) <= PDF_SOURCE_SCAN_CACHE_TTL_SECONDS
        ):
            return cached_total

    total = _count_source_documents(source_path)

    with PDF_LOCK:
        PDF_SOURCE_SCAN_CACHE["source_path"] = str(source_path)
        PDF_SOURCE_SCAN_CACHE["total_documents"] = int(total)
        PDF_SOURCE_SCAN_CACHE["scanned_at"] = float(now)
    return int(total)


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

    indexed_documents = max(0, int(status.get("documents", 0) or 0))
    source_path = get_pdf_source_path()
    total_documents = _get_source_document_total(source_path)
    remaining_documents = max(0, total_documents - indexed_documents)
    completion_pct = 0
    if total_documents > 0:
        completion_pct = max(
            0,
            min(100, int(round((indexed_documents / float(total_documents)) * 100))),
        )

    status["index_job"] = state
    status["source_path"] = source_path
    status["indexed_documents"] = indexed_documents
    status["total_documents"] = int(total_documents)
    status["remaining_documents"] = int(remaining_documents)
    status["completion_pct"] = int(completion_pct)
    status["adaptive_throttle"] = {
        "enabled": bool(PDF_DYNAMIC_THROTTLE),
        "target_embed_ms": int(PDF_DYNAMIC_TARGET_EMBED_MS),
        "max_delay_ms": int(PDF_DYNAMIC_MAX_DELAY_MS),
        "delay_step_ms": int(PDF_DYNAMIC_DELAY_STEP_MS),
        "min_threads": int(PDF_DYNAMIC_MIN_THREADS),
        "max_threads": int(PDF_DYNAMIC_MAX_THREADS),
    }
    return status


def _index_worker():
    global PDF_INDEX_PROCESS
    with PDF_LOCK:
        PDF_INDEX_STATE["running"] = True
        PDF_INDEX_STATE["last_started_at"] = int(time.time())
        PDF_INDEX_STATE["last_error"] = None
        PDF_INDEX_STATE["pause_requested"] = False
        PDF_INDEX_STATE["active_pid"] = None
    try:
        source_path = get_pdf_source_path()
        index_args = ["index", "--source",
                      source_path, "--prune", "--json-summary"]
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
        cmd, env = _build_pdf_rag_command(index_args)
        popen_kwargs = {
            "args": cmd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": env,
        }
        if platform.system().lower() != "windows":
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(**popen_kwargs)
        with PDF_LOCK:
            PDF_INDEX_PROCESS = proc
            PDF_INDEX_STATE["active_pid"] = int(proc.pid or 0)

        out, err = proc.communicate()
        if proc.returncode != 0:
            detail = (err or out or "").strip()
            paused = False
            with PDF_LOCK:
                paused = bool(PDF_INDEX_STATE.get("pause_requested"))
            if paused:
                with PDF_LOCK:
                    PDF_INDEX_STATE["last_result"] = {
                        "ok": True,
                        "paused": True,
                        "message": "Paused by user",
                    }
                    PDF_INDEX_STATE["last_error"] = None
                return
            raise RuntimeError(detail or f"Command failed: {' '.join(cmd)}")

        raw = (out or "").strip()
        parsed = json.loads(raw) if raw else {"ok": True}
        with PDF_LOCK:
            PDF_INDEX_STATE["last_result"] = parsed
    except Exception as exc:
        with PDF_LOCK:
            PDF_INDEX_STATE["last_error"] = str(exc)
    finally:
        with PDF_LOCK:
            PDF_INDEX_PROCESS = None
            PDF_INDEX_STATE["running"] = False
            PDF_INDEX_STATE["active_pid"] = None
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
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    debug_trace: bool = False,
):
    args = [
        "ask",
        "--query",
        query,
        "--top-k",
        str(top_k),
        "--answer-model",
        model,
        "--answer-timeout",
        str(PDF_ANSWER_TIMEOUT),
        "--json-output",
    ]
    for path in include_paths or []:
        if isinstance(path, str) and path.strip():
            args.extend(["--include-path", path.strip()])
    for path in exclude_paths or []:
        if isinstance(path, str) and path.strip():
            args.extend(["--exclude-path", path.strip()])
    if debug_trace:
        args.append("--debug-trace")

    raw = run_pdf_rag(args, timeout=max(600, int(PDF_ANSWER_TIMEOUT) + 120))
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise RuntimeError("Unexpected PDF ask response")
    return parsed


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _source_confidence_class_from_label(label: str) -> str:
    raw = str(label or "").strip().lower()
    if raw == "high":
        return "conf-high"
    if raw == "medium":
        return "conf-medium"
    if raw == "low":
        return "conf-low"
    return "conf-unknown"


def _score_bucket_by_rank(rank: int, total: int) -> str:
    if total <= 0:
        return "Unknown"
    if total == 1:
        return "Medium"
    if rank <= max(1, int(round(total * 0.30))):
        return "High"
    if rank <= max(2, int(round(total * 0.70))):
        return "Medium"
    return "Low"


def _source_confidence_from_scores(
    score: float | None,
    max_score: float | None,
    min_score: float | None,
    rank: int,
    total: int,
) -> dict:
    if score is None:
        return {
            "confidence_label": "Unknown",
            "confidence_class": "conf-unknown",
            "confidence_title": "Retrieval score unavailable",
        }

    if max_score is None or total <= 0:
        label = "High" if score >= 0.95 else (
            "Medium" if score >= 0.75 else "Low")
        return {
            "confidence_label": label,
            "confidence_class": _source_confidence_class_from_label(label),
            "confidence_title": f"Retrieval score: {score:.3f}",
        }

    min_value = min_score if min_score is not None else max_score
    spread = max(0.0, max_score - min_value)
    relative = max(0.0, min(1.0, score / max_score)) if max_score > 0 else 0.0

    if spread <= 0.18 and total >= 3:
        label = _score_bucket_by_rank(rank, total)
        title = (
            f"Retrieval score: {score:.3f} "
            f"(rank {rank}/{total}, tight score range {spread:.3f})"
        )
        return {
            "confidence_label": label,
            "confidence_class": _source_confidence_class_from_label(label),
            "confidence_title": title,
        }

    if relative >= 0.86:
        label = "High"
    elif relative >= 0.62:
        label = "Medium"
    else:
        label = "Low"

    title = (
        f"Retrieval score: {score:.3f} "
        f"(relative {(relative * 100):.0f}% of top, rank {rank}/{total})"
    )
    return {
        "confidence_label": label,
        "confidence_class": _source_confidence_class_from_label(label),
        "confidence_title": title,
    }


def _annotate_citation_confidence(citations: list[dict]) -> list[dict]:
    out = [dict(c) for c in citations]
    scored: list[tuple[int, float]] = []
    for idx, citation in enumerate(out):
        score = _safe_float(citation.get("score"))
        if score is not None:
            scored.append((idx, score))

    if not scored:
        for citation in out:
            citation.setdefault("confidence_label", "Unknown")
            citation.setdefault("confidence_class", "conf-unknown")
            citation.setdefault("confidence_title",
                                "Retrieval score unavailable")
        return out

    scores_only = [score for _, score in scored]
    max_score = max(scores_only)
    min_score = min(scores_only)
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)
    rank_lookup = {idx: rank for rank, (idx, _) in enumerate(ranked, start=1)}

    for idx, citation in enumerate(out):
        if (
            citation.get("confidence_label")
            and citation.get("confidence_class")
            and citation.get("confidence_title")
        ):
            continue

        score = _safe_float(citation.get("score"))
        rank = rank_lookup.get(idx, len(rank_lookup) + 1)
        metadata = _source_confidence_from_scores(
            score,
            max_score,
            min_score,
            rank,
            len(ranked),
        )
        citation.setdefault("confidence_label", metadata["confidence_label"])
        citation.setdefault("confidence_class", metadata["confidence_class"])
        citation.setdefault("confidence_title", metadata["confidence_title"])

    return out


def _build_structured_citations(sources: list[dict]) -> list[dict]:
    citations = []
    for idx, source in enumerate(sources, start=1):
        path = str(source.get("path", "") or "")
        location = source.get("location", source.get(
            "page", source.get("section", 0)))
        location_int = _safe_int(location)
        citation = {
            "citation_id": f"c{idx}",
            "path": path,
            "title": str(source.get("title", "") or ""),
            "location": location_int if location_int is not None else location,
            "location_type": str(source.get("location_type", "") or ""),
            "page": _safe_int(source.get("page")),
            "section": _safe_int(source.get("section")),
            "score": _safe_float(source.get("score")),
        }
        if not citation["location_type"]:
            suffix = Path(path).suffix.lower()
            citation["location_type"] = "page" if suffix == ".pdf" else "section"
        citations.append(citation)
    return _annotate_citation_confidence(citations)


def normalize_pdf_ask_response_contract(result: dict) -> dict:
    answer = str(result.get("answer", "") or "")
    answer_text_raw = result.get("answer_text", answer)
    answer_text = str(answer_text_raw or "")

    sources_raw = result.get("sources", [])
    sources = [s for s in sources_raw if isinstance(
        s, dict)] if isinstance(sources_raw, list) else []

    citations_raw = result.get("citations", None)
    if isinstance(citations_raw, list):
        citations = _annotate_citation_confidence(
            [c for c in citations_raw if isinstance(c, dict)]
        )
    else:
        citations = _build_structured_citations(sources)

    normalized = dict(result)
    # Backward-compatible fields retained for existing clients.
    normalized["answer"] = answer
    normalized["sources"] = sources

    # Structured contract fields for Phase 2+ clients.
    normalized["answer_text"] = answer_text
    normalized["citations"] = citations
    return normalized


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

    source_root = os.path.realpath(os.path.expanduser(get_pdf_source_path()))
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
        "source_path": get_pdf_source_path(),
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


def _load_template(name: str) -> str:
    template_path = TEMPLATE_ROOT / name
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


HTML = _load_template("index.html")
EPUB_READER_HTML = _load_template("epub-reader.html")


class Handler(BaseHTTPRequestHandler):
    def _set_request_meta(self, **values):
        existing = getattr(self, "_request_meta", {})
        if not isinstance(existing, dict):
            existing = {}

        for key, value in values.items():
            if value is None:
                continue
            if isinstance(value, str):
                existing[key] = value[:240]
            elif isinstance(value, (int, float, bool)):
                existing[key] = value
            else:
                existing[key] = str(value)[:240]

        self._request_meta = existing

    def _monitor_begin(self, method: str, route_path: str):
        self._monitor_method = method
        self._monitor_route = route_path
        self._monitor_started_monotonic = time.perf_counter()
        self._monitor_resource_before = _resource_snapshot()
        self._response_status = None
        self._response_bytes = 0
        self._request_meta = {}

    def _monitor_finalize(self):
        if not MONITOR_ENABLED:
            return

        started = getattr(self, "_monitor_started_monotonic", None)
        if started is None:
            return

        finished = time.perf_counter()
        duration_ms = max(0.0, (finished - float(started)) * 1000.0)
        status = int(getattr(self, "_response_status", 500) or 500)

        event = {
            "ts": int(time.time()),
            "method": str(getattr(self, "_monitor_method", "GET")),
            "path": str(getattr(self, "_monitor_route", "/")),
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "slow": bool(duration_ms >= float(MONITOR_SLOW_MS)),
            "response_bytes": int(getattr(self, "_response_bytes", 0) or 0),
            "resource_before": getattr(self, "_monitor_resource_before", None),
            "resource_after": _resource_snapshot(),
            "meta": getattr(self, "_request_meta", {}),
        }
        _record_request_metric(event)

    def _send_security_headers(self):
        script_src = "script-src 'self'"

        if self.path.startswith("/epub-reader") or self.path.startswith("/pdf-reader"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' blob:; "
                f"{script_src}; "
                "img-src 'self' data: blob:; font-src 'self' data: blob:; connect-src 'self' blob:; frame-src 'self' blob:; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        else:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; "
                f"{script_src}; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
            )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send(self, code, body, content_type="text/plain; charset=utf-8"):
        payload = body.encode("utf-8")
        self._response_status = int(code)
        self._response_bytes = len(payload)
        self.send_response(code)
        self._send_security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, code, payload, content_type, extra_headers=None):
        self._response_status = int(code)
        self._response_bytes = len(payload)
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
        self._response_status = 200
        self._response_bytes = int(size)
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

        resolved_root = os.path.realpath(
            os.path.expanduser(get_pdf_source_path()))
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

        root = Path(os.path.expanduser(get_pdf_source_path())).resolve()
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

    # GET route handlers
    def _handle_get_root(self):
        html = HTML.replace("%OLLAMA_BASE%", OLLAMA_BASE)
        html = html.replace("%API_KEY_REQUIRED%",
                            "true" if bool(API_KEY) else "false")
        html = html.replace("%MAX_UPLOAD_BYTES%", str(MAX_UPLOAD_BYTES))
        html = html.replace("%CURRENT_VERSION%", read_current_version())
        html = html.replace("%ASSET_CACHE_BUSTER%", ASSET_CACHE_BUSTER)
        return self._send(200, html, "text/html; charset=utf-8")

    def _handle_get_epub_reader(self):
        html = EPUB_READER_HTML.replace(
            "%API_KEY_REQUIRED%", "true" if bool(API_KEY) else "false"
        )
        html = html.replace("%ASSET_CACHE_BUSTER%", ASSET_CACHE_BUSTER)
        return self._send(200, html, "text/html; charset=utf-8")

    def _handle_get_pdf_reader(self, parsed_url):
        params = parse_qs(parsed_url.query)
        source_path = str(params.get("path", [""])[0] or "").strip()
        resolved_path, error, code = self._resolve_library_file_path(
            source_path)
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

        page_raw = str(params.get("page", ["1"])[0] or "1").strip()
        try:
            page_num = max(1, int(page_raw))
        except Exception:
            page_num = 1

        safe_query_path = quote(source_path, safe="")
        pdf_url = f"/api/pdf/file?path={safe_query_path}#page={page_num}"
        self._response_status = 302
        self._response_bytes = 0
        self.send_response(302)
        self._send_security_headers()
        self.send_header("Location", pdf_url)
        self.end_headers()
        return None

    def _handle_get_assets(self, route_path):
        rel_asset = unquote(route_path[len("/assets/"):]).lstrip("/")
        candidate = (ASSET_ROOT / rel_asset).resolve()
        asset_root_resolved = ASSET_ROOT.resolve()
        if (
            not str(candidate).startswith(str(asset_root_resolved) + os.sep)
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

    def _handle_get_tags(self):
        return self._proxy("GET", "/api/tags", None)

    def _handle_get_history(self):
        return self._send(
            200,
            json.dumps(load_history(), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_instructions(self):
        return self._send(
            200,
            json.dumps(load_instructions(), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_library_docs(self):
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

    def _handle_get_stash(self, parsed_url):
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

    def _handle_get_bibliography(self, parsed_url):
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

    def _handle_get_pdf_status(self):
        return self._send(
            200,
            json.dumps(get_pdf_status(), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_update_status(self):
        return self._send(
            200,
            json.dumps(get_update_status(), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_update_check(self):
        return self._send(
            200,
            json.dumps(get_update_status(), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_update_events(self, parsed_url):
        params = parse_qs(parsed_url.query)
        limit_raw = params.get("limit", ["50"])[0]
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 50
        return self._send(
            200,
            json.dumps(get_update_events(limit=limit), ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_metrics(self, parsed_url):
        params = parse_qs(parsed_url.query)
        limit_raw = params.get("limit", ["200"])[0]
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 200
        payload = get_monitor_snapshot(limit=max(0, limit))
        return self._send(
            200,
            json.dumps(payload, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_cooldown_status(self):
        payload = {"ok": True, "cooldown": _cooldown_status_snapshot()}
        return self._send(
            200,
            json.dumps(payload, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_get_pdf_file(self, parsed_url):
        params = parse_qs(parsed_url.query)
        pdf_path = params.get("path", [""])[0]
        resolved_path, error, code = self._resolve_library_file_path(pdf_path)
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

    def _handle_get_epub_file(self, parsed_url):
        params = parse_qs(parsed_url.query)
        epub_path = params.get("path", [""])[0]
        resolved_path, error, code = self._resolve_library_file_path(epub_path)
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

    # POST route handlers
    def _handle_post_generate(self):
        slot_block = _acquire_heavy_operation_slot("Generation")
        if isinstance(slot_block, dict):
            return self._send(
                429,
                json.dumps(slot_block, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            preflight_block = _preflight_heavy_operation_block("Generation")
            if isinstance(preflight_block, dict):
                return self._send(
                    429,
                    json.dumps(preflight_block, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            payload = self._read_json_body()
            if payload is None:
                return

            if not isinstance(payload, dict):
                return self._send(
                    400,
                    json.dumps({"error": "JSON body must be an object"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            model = _normalize_whitespace(payload.get("model", ""))
            if not model:
                return self._send(
                    400,
                    json.dumps({"error": "model is required"},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            remaining = _model_guard_remaining_seconds(model)
            if remaining > 0:
                return self._send(
                    503,
                    json.dumps(
                        _model_guard_error_payload(
                            model=model,
                            detail="",
                            retry_after_seconds=remaining,
                            guarded=True,
                        ),
                        ensure_ascii=True,
                    ),
                    "application/json; charset=utf-8",
                )

            payload["model"] = model
            payload = _apply_safe_generate_profile(payload)
            self._set_request_meta(
                model=model,
                prompt_chars=len(str(payload.get("prompt", "") or "")),
                stream=bool(payload.get("stream", False)),
            )
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            return self._proxy_generate(model, data)
        finally:
            _release_heavy_operation_slot()

    def _handle_post_abstract_evaluate(self):
        slot_block = _acquire_heavy_operation_slot("Abstract evaluation")
        if isinstance(slot_block, dict):
            return self._send(
                429,
                json.dumps(slot_block, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            preflight_block = _preflight_heavy_operation_block(
                "Abstract evaluation")
            if isinstance(preflight_block, dict):
                return self._send(
                    429,
                    json.dumps(preflight_block, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            payload = self._read_json_body()
            if payload is None:
                return

            model = _normalize_whitespace(payload.get("model", ""))
            research_need = str(payload.get("research_need", "") or "").strip()
            abstract_text = str(payload.get("abstract", "") or "").strip()
            instructions = str(payload.get("instructions", "") or "").strip()

            if not model:
                return self._send(
                    400,
                    json.dumps(
                        {"ok": False, "error": "model is required"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            if not research_need:
                return self._send(
                    400,
                    json.dumps(
                        {"ok": False, "error": "research_need is required"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            if not abstract_text:
                return self._send(
                    400,
                    json.dumps(
                        {"ok": False, "error": "abstract is required"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            if len(research_need) > ABSTRACT_NEED_MAX_CHARS:
                return self._send(
                    400,
                    json.dumps(
                        {
                            "ok": False,
                            "error": f"research_need exceeds {ABSTRACT_NEED_MAX_CHARS} characters",
                        },
                        ensure_ascii=True,
                    ),
                    "application/json; charset=utf-8",
                )
            if len(abstract_text) > ABSTRACT_TEXT_MAX_CHARS:
                return self._send(
                    400,
                    json.dumps(
                        {
                            "ok": False,
                            "error": f"abstract exceeds {ABSTRACT_TEXT_MAX_CHARS} characters",
                        },
                        ensure_ascii=True,
                    ),
                    "application/json; charset=utf-8",
                )

            self._set_request_meta(
                model=model,
                research_need_chars=len(research_need),
                abstract_chars=len(abstract_text),
            )

            try:
                result = evaluate_abstract_relevance(
                    model=model,
                    research_need=research_need,
                    abstract_text=abstract_text,
                    instructions=instructions,
                )
            except RuntimeError as exc:
                LOGGER.warning("Abstract evaluation failed: %s", exc)
                return self._send(
                    502,
                    json.dumps({"ok": False, "error": str(exc)},
                               ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception:
                LOGGER.exception("Unexpected abstract evaluation failure")
                return self._send(
                    500,
                    json.dumps(
                        {"ok": False, "error": "Unexpected evaluation error"}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            return self._send(
                200,
                json.dumps(result, ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        finally:
            _release_heavy_operation_slot()

    def _handle_post_history(self):
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

    def _handle_post_instructions(self):
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

    def _handle_post_pdf_index(self):
        slot_block = _acquire_heavy_operation_slot("PDF indexing")
        if isinstance(slot_block, dict):
            return self._send(
                429,
                json.dumps(slot_block, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            preflight_block = _preflight_heavy_operation_block("PDF indexing")
            if isinstance(preflight_block, dict):
                return self._send(
                    429,
                    json.dumps(preflight_block, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

            started = start_pdf_index_job()
            return self._send(
                200,
                json.dumps({"ok": True, "started": started},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        finally:
            _release_heavy_operation_slot()

    def _handle_post_pdf_index_pause(self):
        result = pause_pdf_index_job()
        code = 200 if result.get("ok") else 500
        return self._send(
            code,
            json.dumps(result, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_post_pdf_source(self):
        payload = self._read_json_body()
        if payload is None:
            return

        source_path = payload.get("source_path", "")
        if not isinstance(source_path, str):
            return self._send(
                400,
                json.dumps(
                    {"ok": False, "error": "source_path must be a string"}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            result = set_pdf_source_path(source_path)
            return self._send(
                200,
                json.dumps(result, ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except ValueError as exc:
            return self._send(
                400,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except RuntimeError as exc:
            return self._send(
                409,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except Exception as exc:
            return self._send(
                500,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )

    def _handle_post_update_apply(self):
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

    def _handle_post_update_check(self):
        payload = check_for_updates()
        code = 200 if payload.get("ok") else 502
        return self._send(
            code,
            json.dumps(payload, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_post_pdf_ask(self):
        slot_block = _acquire_heavy_operation_slot("PDF-grounded ask")
        if isinstance(slot_block, dict):
            return self._send(
                429,
                json.dumps(slot_block, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            preflight_block = _preflight_heavy_operation_block(
                "PDF-grounded ask")
            if isinstance(preflight_block, dict):
                return self._send(
                    429,
                    json.dumps(preflight_block, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )

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
            include_paths = payload.get("include_paths", [])
            exclude_paths = payload.get("exclude_paths", [])
            debug_trace = bool(payload.get("debug_trace", False))
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

            self._set_request_meta(
                model=str(model),
                query_chars=len(query.strip()),
                top_k=int(top_k),
                include_paths=len(include_paths),
                exclude_paths=len(exclude_paths),
                debug_trace=bool(debug_trace),
            )

            try:
                result = ask_pdf_library(
                    query.strip(),
                    str(model),
                    top_k,
                    include_paths=[str(x)
                                   for x in include_paths if isinstance(x, str)],
                    exclude_paths=[str(x)
                                   for x in exclude_paths if isinstance(x, str)],
                    debug_trace=debug_trace,
                )
                normalized = normalize_pdf_ask_response_contract(result)
                return self._send(
                    200,
                    json.dumps(normalized, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:
                return self._send(
                    502,
                    json.dumps({"error": str(exc)}, ensure_ascii=True),
                    "application/json; charset=utf-8",
                )
        finally:
            _release_heavy_operation_slot()

    def _handle_post_library_upload(self, parsed_url):
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
                json.dumps({"error": "Upload exceeds maximum size"},
                           ensure_ascii=True),
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
            json.dumps({"ok": True, "rel_path": rel_path,
                       "bytes": written}, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_post_stash(self):
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

    def _handle_post_metrics_reset(self):
        payload = reset_monitor_snapshot()
        return self._send(
            200,
            json.dumps(payload, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_post_cooldown(self):
        payload = self._read_json_body()
        if payload is None:
            return

        action = str(payload.get("action", "set") or "set").strip().lower()
        if action in {"clear", "resume", "off"}:
            result = clear_cooldown()
            return self._send(
                200,
                json.dumps(result, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        raw_seconds = payload.get("seconds")
        raw_minutes = payload.get("minutes")
        try:
            if raw_seconds is not None:
                seconds = int(raw_seconds)
            elif raw_minutes is not None:
                seconds = int(float(raw_minutes) * 60)
            else:
                seconds = 300
        except Exception:
            return self._send(
                400,
                json.dumps(
                    {"error": "minutes/seconds must be numeric"}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        seconds = max(30, min(7200, seconds))
        reason = str(payload.get("reason", "manual") or "manual")
        result = set_cooldown(seconds=seconds, reason=reason)
        return self._send(
            200,
            json.dumps(result, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    # DELETE route handlers
    def _handle_delete_history(self):
        save_history([])
        return self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")

    def _handle_delete_stash(self, parsed_url):
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

    def _handle_post_pdf_source_pick(self):
        try:
            selected = _pick_directory_with_native_dialog()
        except RuntimeError as exc:
            return self._send(
                200,
                json.dumps({"ok": False, "error": str(exc), "recoverable": True},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except Exception as exc:
            return self._send(
                500,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        if not selected:
            return self._send(
                200,
                json.dumps({"ok": True, "canceled": True}, ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        try:
            result = set_pdf_source_path(selected)
        except ValueError as exc:
            return self._send(
                400,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except RuntimeError as exc:
            return self._send(
                409,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        except Exception as exc:
            return self._send(
                500,
                json.dumps({"ok": False, "error": str(exc)},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )

        result["canceled"] = False
        return self._send(
            200,
            json.dumps(result, ensure_ascii=True),
            "application/json; charset=utf-8",
        )

    def _handle_delete_bibliography(self, parsed_url):
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

    def do_GET(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path
        self._monitor_begin("GET", route_path)

        try:
            if not self._require_api_auth_for_route(route_path):
                return

            if route_path.startswith("/assets/"):
                return self._handle_get_assets(route_path)

            get_routes = {
                "/": lambda: self._handle_get_root(),
                "/epub-reader": lambda: self._handle_get_epub_reader(),
                "/pdf-reader": lambda: self._handle_get_pdf_reader(parsed_url),
                "/api/tags": lambda: self._handle_get_tags(),
                "/api/history": lambda: self._handle_get_history(),
                "/api/instructions": lambda: self._handle_get_instructions(),
                "/api/library/docs": lambda: self._handle_get_library_docs(),
                "/api/stash": lambda: self._handle_get_stash(parsed_url),
                "/api/bibliography": lambda: self._handle_get_bibliography(parsed_url),
                "/api/pdf/status": lambda: self._handle_get_pdf_status(),
                "/api/metrics": lambda: self._handle_get_metrics(parsed_url),
                "/api/cooldown/status": lambda: self._handle_get_cooldown_status(),
                "/api/update/status": lambda: self._handle_get_update_status(),
                "/api/update/check": lambda: self._handle_get_update_check(),
                "/api/update/events": lambda: self._handle_get_update_events(parsed_url),
                "/api/pdf/file": lambda: self._handle_get_pdf_file(parsed_url),
                "/api/epub/file": lambda: self._handle_get_epub_file(parsed_url),
            }

            handler = get_routes.get(route_path)
            if handler:
                return handler()

            return self._send(404, "Not found")
        except Exception:
            LOGGER.exception("Unhandled GET error for path=%s", route_path)
            return self._send(
                500,
                json.dumps({"error": "Internal server error"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        finally:
            self._monitor_finalize()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path
        self._monitor_begin("POST", route_path)

        try:
            if not self._require_api_auth_for_route(route_path):
                return

            if not self._require_same_origin_for_state_change(route_path):
                return

            post_routes = {
                "/api/generate": lambda: self._handle_post_generate(),
                "/api/abstract/evaluate": lambda: self._handle_post_abstract_evaluate(),
                "/api/history": lambda: self._handle_post_history(),
                "/api/instructions": lambda: self._handle_post_instructions(),
                "/api/pdf/index": lambda: self._handle_post_pdf_index(),
                "/api/pdf/index/pause": lambda: self._handle_post_pdf_index_pause(),
                "/api/pdf/source": lambda: self._handle_post_pdf_source(),
                "/api/pdf/source/pick": lambda: self._handle_post_pdf_source_pick(),
                "/api/update/apply": lambda: self._handle_post_update_apply(),
                "/api/update/check": lambda: self._handle_post_update_check(),
                "/api/pdf/ask": lambda: self._handle_post_pdf_ask(),
                "/api/library/upload": lambda: self._handle_post_library_upload(parsed_url),
                "/api/stash": lambda: self._handle_post_stash(),
                "/api/metrics/reset": lambda: self._handle_post_metrics_reset(),
                "/api/cooldown": lambda: self._handle_post_cooldown(),
            }

            handler = post_routes.get(route_path)
            if handler:
                return handler()

            return self._send(404, "Not found")
        except Exception:
            LOGGER.exception("Unhandled POST error for path=%s", route_path)
            return self._send(
                500,
                json.dumps({"error": "Internal server error"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        finally:
            self._monitor_finalize()

    def do_DELETE(self):
        parsed_url = urlparse(self.path)
        route_path = parsed_url.path
        self._monitor_begin("DELETE", route_path)

        try:
            if not self._require_api_auth_for_route(route_path):
                return

            if not self._require_same_origin_for_state_change(route_path):
                return

            delete_routes = {
                "/api/history": lambda: self._handle_delete_history(),
                "/api/stash": lambda: self._handle_delete_stash(parsed_url),
                "/api/bibliography": lambda: self._handle_delete_bibliography(parsed_url),
            }

            handler = delete_routes.get(route_path)
            if handler:
                return handler()

            return self._send(404, "Not found")
        except Exception:
            LOGGER.exception("Unhandled DELETE error for path=%s", route_path)
            return self._send(
                500,
                json.dumps({"error": "Internal server error"},
                           ensure_ascii=True),
                "application/json; charset=utf-8",
            )
        finally:
            self._monitor_finalize()

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

    def _proxy_generate(self, model, data):
        req = Request(
            f"{OLLAMA_BASE}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=GENERATE_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                _model_guard_clear(model)
                return self._send(resp.status, body, "application/json; charset=utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code >= 500 or _resource_failure_detail(detail):
                guarded, retry_after_seconds = _model_guard_record_failure(
                    model, detail)
                if guarded:
                    return self._send(
                        503,
                        json.dumps(
                            _model_guard_error_payload(
                                model=model,
                                detail=detail,
                                retry_after_seconds=retry_after_seconds,
                                guarded=True,
                            ),
                            ensure_ascii=True,
                        ),
                        "application/json; charset=utf-8",
                    )
            return self._send(exc.code, detail, "application/json; charset=utf-8")
        except URLError as exc:
            detail = str(exc)
            guarded, retry_after_seconds = _model_guard_record_failure(
                model, detail)
            status = 503 if guarded else 502
            payload = _model_guard_error_payload(
                model=model,
                detail=detail,
                retry_after_seconds=retry_after_seconds,
                guarded=guarded,
            )
            return self._send(
                status,
                json.dumps(payload, ensure_ascii=True),
                "application/json; charset=utf-8",
            )


def main():
    host_for_check = HOST.strip()
    is_loopback = host_for_check in {
        "127.0.0.1", "::1"} or host_for_check.lower() == "localhost"
    if not is_loopback:
        raise SystemExit(
            "Refusing non-loopback bind. Ollama Librarian only supports loopback "
            "host bindings (127.0.0.1, localhost, or ::1)."
        )

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving UI at http://{HOST}:{PORT} (proxying {OLLAMA_BASE})")
    server.serve_forever()


if __name__ == "__main__":
    main()
