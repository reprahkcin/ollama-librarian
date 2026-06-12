from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import re
import subprocess
from typing import Any, Iterable, Mapping


BYTES_PER_GB = 1024 ** 3


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    machine: str
    processor: str
    cpu_count: int
    total_memory_bytes: int | None
    available_memory_bytes: int | None
    load_average_1m: float | None
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        total_gb = _bytes_to_gb(self.total_memory_bytes)
        available_gb = _bytes_to_gb(self.available_memory_bytes)
        return {
            "os": self.os_name,
            "machine": self.machine,
            "processor": self.processor,
            "cpu_count": self.cpu_count,
            "total_memory_bytes": self.total_memory_bytes,
            "total_memory_gb": total_gb,
            "available_memory_bytes": self.available_memory_bytes,
            "available_memory_gb": available_gb,
            "load_average_1m": self.load_average_1m,
            "notes": list(self.notes),
        }


def _bytes_to_gb(value: int | None) -> float | None:
    if value is None or value <= 0:
        return None
    return round(float(value) / BYTES_PER_GB, 2)


def _run_text(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _darwin_total_memory() -> int | None:
    raw = _run_text(["sysctl", "-n", "hw.memsize"])
    try:
        return int(raw)
    except Exception:
        return None


def _darwin_available_memory() -> int | None:
    page_size_raw = _run_text(["sysctl", "-n", "hw.pagesize"])
    try:
        page_size = int(page_size_raw)
    except Exception:
        page_size = 4096

    raw = _run_text(["vm_stat"])
    if not raw:
        return None
    pages: dict[str, int] = {}
    for line in raw.splitlines():
        match = re.match(
            r"Pages (free|inactive|speculative):\s+(\d+)\.", line.strip())
        if match:
            pages[match.group(1)] = int(match.group(2))
    count = pages.get("free", 0) + pages.get("inactive",
                                             0) + pages.get("speculative", 0)
    return count * page_size if count > 0 else None


def _linux_memory() -> tuple[int | None, int | None]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            raw = fh.read()
    except Exception:
        return None, None

    values: dict[str, int] = {}
    for line in raw.splitlines():
        match = re.match(r"^(MemTotal|MemAvailable):\s+(\d+)\s+kB", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values.get("MemTotal"), values.get("MemAvailable")


def _windows_memory() -> tuple[int | None, int | None]:
    raw = _run_text([
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance Win32_OperatingSystem | Select-Object -ExpandProperty TotalVisibleMemorySize; Get-CimInstance Win32_OperatingSystem | Select-Object -ExpandProperty FreePhysicalMemory",
    ])
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return None, None
    try:
        return int(lines[0]) * 1024, int(lines[1]) * 1024
    except Exception:
        return None, None


def detect_hardware_profile() -> HardwareProfile:
    os_name = platform.system().lower()
    notes: list[str] = []
    total_memory: int | None = None
    available_memory: int | None = None

    if os_name == "darwin":
        total_memory = _darwin_total_memory()
        available_memory = _darwin_available_memory()
        if platform.machine().lower() in {"arm64", "aarch64"}:
            notes.append("apple_silicon_unified_memory")
    elif os_name == "linux":
        total_memory, available_memory = _linux_memory()
    elif os_name == "windows":
        total_memory, available_memory = _windows_memory()

    try:
        load_average = float(os.getloadavg()[0])
    except Exception:
        load_average = None

    return HardwareProfile(
        os_name=os_name or "unknown",
        machine=platform.machine() or "unknown",
        processor=platform.processor() or "unknown",
        cpu_count=max(1, int(os.cpu_count() or 1)),
        total_memory_bytes=total_memory,
        available_memory_bytes=available_memory,
        load_average_1m=load_average,
        notes=notes,
    )


def _model_name(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, Mapping):
        return str(item.get("name") or item.get("model") or "").strip()
    return ""


def _model_size_bytes(item: Any) -> int | None:
    if not isinstance(item, Mapping):
        return None
    raw = item.get("size") or item.get("size_bytes")
    try:
        parsed = int(raw)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _parse_param_billions(value: object) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    try:
        raw_number = float(text)
        if raw_number > 100_000_000:
            return raw_number / 1_000_000_000.0
    except Exception:
        pass
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", text)
    if matches:
        try:
            return float(matches[-1])
        except Exception:
            return None
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*m\b", text)
    if matches:
        try:
            return float(matches[-1]) / 1000.0
        except Exception:
            return None
    return None


def _model_param_billions(name: str) -> float | None:
    return _parse_param_billions(name)


def _model_param_billions_from_item(item: Any, name: str) -> float | None:
    if isinstance(item, Mapping):
        details = item.get("details") if isinstance(
            item.get("details"), Mapping) else {}
        parsed = _parse_param_billions(details.get("parameter_size"))
        if parsed is not None:
            return parsed
        model_info = item.get("model_info") if isinstance(
            item.get("model_info"), Mapping) else {}
        for key in ("general.parameter_count", "parameter_count"):
            parsed = _parse_param_billions(model_info.get(key))
            if parsed is not None:
                return parsed
    return _model_param_billions(name)


def _model_quantization(item: Any) -> str:
    if not isinstance(item, Mapping):
        return ""
    details = item.get("details") if isinstance(
        item.get("details"), Mapping) else {}
    raw = details.get("quantization_level") or item.get(
        "quantization_level") or ""
    return str(raw).strip().lower()


def _quantization_memory_factor(quantization: str) -> float:
    text = str(quantization or "").lower()
    if text.startswith("q2") or text.startswith("iq2"):
        return 0.45
    if text.startswith("q3") or text.startswith("iq3"):
        return 0.52
    if text.startswith("q4") or text.startswith("iq4"):
        return 0.62
    if text.startswith("q5") or text.startswith("iq5"):
        return 0.74
    if text.startswith("q6"):
        return 0.9
    if text.startswith("q8"):
        return 1.15
    if "f16" in text or "fp16" in text:
        return 2.2
    if "f32" in text or "fp32" in text:
        return 4.2
    return 0.72


def _is_embedding_model(name: str) -> bool:
    text = name.lower()
    return "embed" in text or "embedding" in text


def estimate_model_memory_gb(
    name: str,
    size_bytes: int | None = None,
    param_billions: float | None = None,
    quantization: str = "",
) -> float:
    params_b = param_billions if param_billions is not None else _model_param_billions(
        name)
    if params_b is not None:
        return round(max(2.0, (params_b * _quantization_memory_factor(quantization)) + 2.0), 2)
    if size_bytes:
        return round(max(2.0, (float(size_bytes) / BYTES_PER_GB) * 1.35 + 1.0), 2)

    text = name.lower()
    if any(token in text for token in ("tiny", "mini", "small")):
        return 4.0
    return 8.0


def _model_family(item: Any) -> str:
    if not isinstance(item, Mapping):
        return ""
    details = item.get("details") if isinstance(
        item.get("details"), Mapping) else {}
    family = str(details.get("family") or "").strip().lower()
    if family:
        return family
    families = details.get("families")
    if isinstance(families, list) and families:
        return str(families[0] or "").strip().lower()
    model_info = item.get("model_info") if isinstance(
        item.get("model_info"), Mapping) else {}
    return str(model_info.get("general.architecture") or "").strip().lower()


def _context_length(item: Any) -> int | None:
    if not isinstance(item, Mapping):
        return None
    model_info = item.get("model_info") if isinstance(
        item.get("model_info"), Mapping) else {}
    for key, value in model_info.items():
        if not str(key).endswith(".context_length"):
            continue
        try:
            parsed = int(value)
        except Exception:
            continue
        return parsed if parsed > 0 else None
    return None


def _quality_score(name: str, estimated_memory_gb: float) -> float:
    text = name.lower()
    score = estimated_memory_gb
    if any(token in text for token in ("qwen", "llama", "mistral", "gemma")):
        score += 1.0
    if "instruct" in text or "chat" in text:
        score += 0.4
    return score


def recommend_model(
    models: Iterable[Any],
    hardware: HardwareProfile | Mapping[str, Any],
    preferred_model: str = "qwen2.5:14b",
) -> dict[str, Any]:
    if isinstance(hardware, HardwareProfile):
        hardware_dict = hardware.to_dict()
    else:
        hardware_dict = dict(hardware)

    total_memory_gb = hardware_dict.get("total_memory_gb")
    if total_memory_gb is None:
        total_bytes = hardware_dict.get("total_memory_bytes")
        total_memory_gb = _bytes_to_gb(
            int(total_bytes)) if total_bytes else None
    try:
        total_memory = float(total_memory_gb or 0.0)
    except Exception:
        total_memory = 0.0

    if total_memory > 0:
        safe_budget_gb = max(3.0, round(total_memory * 0.55, 2))
        caution_budget_gb = max(safe_budget_gb, round(total_memory * 0.75, 2))
    else:
        safe_budget_gb = 8.0
        caution_budget_gb = 12.0

    candidates: list[dict[str, Any]] = []
    for item in models:
        name = _model_name(item)
        if not name or _is_embedding_model(name):
            continue
        size_bytes = _model_size_bytes(item)
        param_billions = _model_param_billions_from_item(item, name)
        quantization = _model_quantization(item)
        family = _model_family(item)
        context_length = _context_length(item)
        estimated_gb = estimate_model_memory_gb(
            name,
            size_bytes,
            param_billions=param_billions,
            quantization=quantization,
        )
        if estimated_gb <= safe_budget_gb:
            safety = "safe"
        elif estimated_gb <= caution_budget_gb:
            safety = "caution"
        else:
            safety = "unsafe"
        candidates.append(
            {
                "name": name,
                "size_bytes": size_bytes,
                "parameter_size_b": round(param_billions, 3) if param_billions is not None else None,
                "quantization": quantization,
                "family": family,
                "context_length": context_length,
                "estimated_memory_gb": estimated_gb,
                "safety": safety,
                "is_preferred": name == preferred_model,
                "quality_score": round(_quality_score(name, estimated_gb), 2),
            }
        )

    safe = [candidate for candidate in candidates if candidate["safety"] == "safe"]
    caution = [
        candidate for candidate in candidates if candidate["safety"] == "caution"]
    unsafe = [
        candidate for candidate in candidates if candidate["safety"] == "unsafe"]

    def sort_best(candidate: dict[str, Any]) -> tuple[float, int, str]:
        preferred_bonus = 1 if candidate.get("is_preferred") else 0
        return (float(candidate.get("quality_score") or 0.0), preferred_bonus, str(candidate.get("name") or ""))

    selected: dict[str, Any] | None = None
    reason = "no_chat_models_installed"
    if safe:
        selected = sorted(safe, key=sort_best, reverse=True)[0]
        reason = "best_safe_installed_model"
    elif caution:
        selected = sorted(caution, key=lambda c: (
            float(c["estimated_memory_gb"]), str(c["name"])))[0]
        reason = "no_safe_model_installed_using_smallest_caution_model"
    elif unsafe:
        selected = sorted(unsafe, key=lambda c: (
            float(c["estimated_memory_gb"]), str(c["name"])))[0]
        reason = "no_safe_model_installed_using_smallest_unsafe_model"

    return {
        "recommended_model": selected.get("name") if selected else "",
        "recommended": selected,
        "reason": reason,
        "safe_budget_gb": safe_budget_gb,
        "caution_budget_gb": caution_budget_gb,
        "models": candidates,
    }


def classify_resource_pressure(hardware: HardwareProfile | Mapping[str, Any]) -> str:
    if isinstance(hardware, HardwareProfile):
        hardware_dict = hardware.to_dict()
    else:
        hardware_dict = dict(hardware)

    total = hardware_dict.get("total_memory_bytes")
    available = hardware_dict.get("available_memory_bytes")
    try:
        memory_ratio = float(available) / \
            float(total) if available is not None and total else None
    except Exception:
        memory_ratio = None

    cpu_count = max(1, int(hardware_dict.get("cpu_count") or 1))
    load_raw = hardware_dict.get("load_average_1m")
    try:
        load_ratio = float(load_raw) / \
            float(cpu_count) if load_raw is not None else None
    except Exception:
        load_ratio = None

    memory_pressure = "unknown"
    if memory_ratio is not None:
        if memory_ratio < 0.12:
            memory_pressure = "critical"
        elif memory_ratio < 0.20:
            memory_pressure = "throttled"
        elif memory_ratio < 0.30:
            memory_pressure = "warm"
        else:
            memory_pressure = "ok"

    load_pressure = "unknown"
    if load_ratio is not None:
        if load_ratio >= 2.0:
            load_pressure = "critical"
        elif load_ratio >= 1.5:
            load_pressure = "throttled"
        elif load_ratio >= 1.0:
            load_pressure = "warm"
        else:
            load_pressure = "ok"

    rank = {"unknown": 0, "ok": 1, "warm": 2, "throttled": 3, "critical": 4}
    pressure = max((memory_pressure, load_pressure),
                   key=lambda name: rank[name])
    return pressure if pressure != "unknown" else "ok"


def safety_policy_for_pressure(pressure: str) -> dict[str, Any]:
    normalized = str(pressure or "ok").strip().lower()
    if normalized == "critical":
        return {
            "pressure": "critical",
            "allow_new_work": False,
            "allow_index_start": False,
            "pause_index": True,
            "max_generation_slots": 0,
            "embed_num_thread": 1,
            "dynamic_max_threads": 1,
            "embed_delay_ms": 2000,
            "doc_cooldown_seconds": 60,
            "ocr_jobs": 1,
            "message": "System pressure is critical; new heavy work is paused.",
        }
    if normalized == "throttled":
        return {
            "pressure": "throttled",
            "allow_new_work": True,
            "allow_index_start": True,
            "pause_index": False,
            "max_generation_slots": 1,
            "embed_num_thread": 1,
            "dynamic_max_threads": 1,
            "embed_delay_ms": 1500,
            "doc_cooldown_seconds": 45,
            "ocr_jobs": 1,
            "message": "System pressure is high; work is limited to low-and-slow settings.",
        }
    if normalized == "warm":
        return {
            "pressure": "warm",
            "allow_new_work": True,
            "allow_index_start": True,
            "pause_index": False,
            "max_generation_slots": 1,
            "embed_num_thread": 1,
            "dynamic_max_threads": 2,
            "embed_delay_ms": 750,
            "doc_cooldown_seconds": 20,
            "ocr_jobs": 1,
            "message": "System is warming up; safer throttles are active.",
        }
    return {
        "pressure": "ok",
        "allow_new_work": True,
        "allow_index_start": True,
        "pause_index": False,
        "max_generation_slots": 1,
        "embed_num_thread": None,
        "dynamic_max_threads": None,
        "embed_delay_ms": None,
        "doc_cooldown_seconds": None,
        "ocr_jobs": None,
        "message": "System pressure is normal.",
    }


def build_system_profile(models: Iterable[Any]) -> dict[str, Any]:
    hardware = detect_hardware_profile()
    recommendation = recommend_model(models, hardware)
    pressure = classify_resource_pressure(hardware)
    policy = safety_policy_for_pressure(pressure)

    return {
        "ok": True,
        "hardware": hardware.to_dict(),
        "recommendation": recommendation,
        "resource_state": {
            "pressure": pressure,
            "monitoring": "snapshot",
            "policy": policy,
        },
    }
