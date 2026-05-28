#!/usr/bin/env python3
"""Run quality benchmark prompts with persistent status checkpoints.

This script is designed for long-running benchmark jobs where progress must
remain visible even when terminal output is buffered or disconnected.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BAD_SOURCE_PATTERNS = [
    "source path, location",
    "(source)",
    "source [",
    "source path ]",
]

INSUFFICIENT_MARKERS = [
    "insufficient",
    "cannot",
    "not available",
    "not in context",
    "cannot verify",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True,
                   indent=2), encoding="utf-8")
    tmp.replace(path)


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def classify_badge(score: float, max_score: float | None) -> str:
    if max_score is None or max_score <= 0:
        if score >= 0.95:
            return "High"
        if score >= 0.8:
            return "Medium"
        return "Low"

    relative = max(0.0, min(1.0, score / max_score))
    gap = max(0.0, max_score - score)
    if relative >= 0.9 and gap <= 0.2:
        return "High"
    if relative >= 0.55 and gap <= 1.25:
        return "Medium"
    return "Low"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run expanded quality benchmark with live status checkpoints.")
    parser.add_argument(
        "--fixture",
        default="tests/quality/fixtures/benchmark_v1.json",
        help="Path to benchmark fixture JSON.",
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8088/api/pdf/ask",
        help="Ask endpoint URL.",
    )
    parser.add_argument("--model", default="qwen2.5:14b",
                        help="Model name to send in ask payload.")
    parser.add_argument("--top-k", type=int, default=6,
                        help="Top-k retrieval value.")
    parser.add_argument("--request-timeout", type=int,
                        default=60, help="Per-request timeout in seconds.")
    parser.add_argument(
        "--output-json",
        default="tests/quality/results/baseline_v1_expanded_results.json",
        help="Raw result output JSON path.",
    )
    parser.add_argument(
        "--output-report",
        default="docs/QUALITY-BASELINE-REPORT-EXPANDED.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--status-json",
        default="tests/quality/results/baseline_v1_expanded_status.json",
        help="Live status output JSON path.",
    )
    parser.add_argument(
        "--progress-log",
        default="tests/quality/results/baseline_v1_expanded_progress.log",
        help="Append-only progress log path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional prompt cap for smoke runs. 0 means run all prompts.",
    )
    return parser.parse_args()


def append_progress(progress_log: Path, message: str) -> None:
    progress_log.parent.mkdir(parents=True, exist_ok=True)
    with progress_log.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def emit_status(
    status_json: Path,
    *,
    run_state: str,
    started_at: str,
    fixture: str,
    completed: int,
    total: int,
    last_prompt_id: str | None,
    last_latency_ms: int | None,
    last_error: str | None,
) -> None:
    payload = {
        "state": run_state,
        "started_at_utc": started_at,
        "updated_at_utc": utc_now_iso(),
        "fixture": fixture,
        "completed_prompts": completed,
        "total_prompts": total,
        "percent_complete": round((completed / total) * 100, 2) if total else 0.0,
        "last_prompt_id": last_prompt_id,
        "last_latency_ms": last_latency_ms,
        "last_error": last_error,
    }
    write_json_atomic(status_json, payload)


def main() -> int:
    args = parse_args()

    fixture_path = Path(args.fixture)
    output_json = Path(args.output_json)
    output_report = Path(args.output_report)
    status_json = Path(args.status_json)
    progress_log = Path(args.progress_log)

    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")

    bench = json.loads(fixture_path.read_text(encoding="utf-8"))
    prompts = bench.get("prompts", [])
    if not isinstance(prompts, list):
        raise ValueError("Fixture field 'prompts' must be a list.")
    if args.limit > 0:
        prompts = prompts[: args.limit]

    started_at = utc_now_iso()
    write_text_atomic(progress_log, "")
    append_progress(
        progress_log, f"[{started_at}] START total_prompts={len(prompts)}")
    emit_status(
        status_json,
        run_state="running",
        started_at=started_at,
        fixture=str(fixture_path),
        completed=0,
        total=len(prompts),
        last_prompt_id=None,
        last_latency_ms=None,
        last_error=None,
    )

    print(f"Starting benchmark run: {len(prompts)} prompts", flush=True)
    print(f"Live status file: {status_json}", flush=True)
    print(f"Progress log file: {progress_log}", flush=True)

    runs: list[dict[str, Any]] = []
    latencies: list[int] = []
    source_total = source_valid = source_format_errors = 0
    nonempty = answer_pass = 0
    category_counts: dict[str, int] = {}
    category_pass: dict[str, int] = {}
    badge_counts = {"High": 0, "Medium": 0, "Low": 0}

    for idx, item in enumerate(prompts, start=1):
        prompt_id = str(item.get("id", f"prompt_{idx}"))
        category = str(item.get("category", "unknown"))
        prompt = str(item.get("prompt", ""))
        expected_signals = [str(s).lower()
                            for s in item.get("expected_signals", [])]
        requires_citation = bool(item.get("requires_citation", True))

        category_counts[category] = category_counts.get(category, 0) + 1

        payload = json.dumps(
            {
                "query": prompt,
                "model": args.model,
                "top_k": args.top_k,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            args.api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        started = time.perf_counter()
        http_status = None
        error = None
        response_obj = None
        try:
            with urllib.request.urlopen(req, timeout=args.request_timeout) as resp:
                http_status = int(resp.getcode())
                response_obj = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover
            error = str(exc)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        latencies.append(elapsed_ms)

        ok = False
        answer = ""
        sources: list[dict[str, Any]] = []
        if isinstance(response_obj, dict):
            ok = bool(response_obj.get("ok", True))
            answer = str(response_obj.get("answer", "") or "")
            src = response_obj.get("sources", [])
            if isinstance(src, list):
                sources = [s for s in src if isinstance(s, dict)]

        answer_clean = answer.strip()
        lower_answer = answer_clean.lower()
        is_nonempty = len(answer_clean) >= 40
        if is_nonempty:
            nonempty += 1

        valid_here = 0
        for s in sources:
            source_total += 1
            path_ok = bool(str(s.get("path", "")).strip())
            loc = s.get("location", s.get("page", s.get("section", 0)))
            try:
                loc_ok = int(loc) > 0
            except Exception:
                loc_ok = False
            if path_ok and loc_ok:
                source_valid += 1
                valid_here += 1

        bad_artifact = any(p in lower_answer for p in BAD_SOURCE_PATTERNS)
        if bad_artifact:
            source_format_errors += 1

        has_signal = any(
            sig in lower_answer for sig in expected_signals) if expected_signals else True
        has_citation = len(sources) > 0 and valid_here > 0
        insufficient_ok = any(
            tok in lower_answer for tok in INSUFFICIENT_MARKERS)
        if requires_citation:
            passed = is_nonempty and has_signal and has_citation and not bad_artifact and ok
        else:
            passed = is_nonempty and (
                has_signal or insufficient_ok) and not bad_artifact and ok
        if passed:
            answer_pass += 1
            category_pass[category] = category_pass.get(category, 0) + 1

        scores: list[float] = []
        for s in sources:
            try:
                scores.append(float(s.get("score")))
            except Exception:
                continue
        max_score = max(scores) if scores else None
        for sc in scores:
            badge_counts[classify_badge(sc, max_score)] += 1

        runs.append(
            {
                "id": prompt_id,
                "category": category,
                "http_status": http_status,
                "ok": ok,
                "latency_ms": elapsed_ms,
                "answer_chars": len(answer_clean),
                "answer_nonempty": is_nonempty,
                "requires_citation": requires_citation,
                "sources_count": len(sources),
                "valid_citations_count": valid_here,
                "has_source_format_error": bad_artifact,
                "signal_match": has_signal,
                "answer_pass_heuristic": passed,
                "error": error,
            }
        )

        progress_line = (
            f"[{utc_now_iso()}] {idx}/{len(prompts)} id={prompt_id} "
            f"latency_ms={elapsed_ms} ok={ok} error={'yes' if error else 'no'}"
        )
        append_progress(progress_log, progress_line)
        print(progress_line, flush=True)

        emit_status(
            status_json,
            run_state="running",
            started_at=started_at,
            fixture=str(fixture_path),
            completed=idx,
            total=len(prompts),
            last_prompt_id=prompt_id,
            last_latency_ms=elapsed_ms,
            last_error=error,
        )

    prompt_count = len(prompts)
    if len(latencies) >= 2:
        p95 = int(statistics.quantiles(latencies, n=20)[18])
    else:
        p95 = latencies[0] if latencies else 0

    metrics = {
        "prompt_count": prompt_count,
        "request_timeout_seconds": args.request_timeout,
        "answer_nonempty_rate": (nonempty / prompt_count) if prompt_count else 0.0,
        "grounded_answer_pass_rate": (answer_pass / prompt_count) if prompt_count else 0.0,
        "citation_link_valid_rate": (source_valid / source_total) if source_total else 0.0,
        "source_format_error_rate": (source_format_errors / prompt_count) if prompt_count else 0.0,
        "badge_distribution": badge_counts,
        "p95_response_latency_ms": p95,
        "avg_response_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "category_pass_rates": {
            c: (category_pass.get(c, 0) / n) if n else 0.0
            for c, n in sorted(category_counts.items())
        },
    }

    output = {
        "version": "1.0",
        "captured_at_epoch": int(time.time()),
        "api_url": args.api_url,
        "model": args.model,
        "top_k": args.top_k,
        "metrics": metrics,
        "runs": runs,
    }
    write_json_atomic(output_json, output)

    lines = [
        "# Quality Baseline Report",
        "",
        f"- Fixture: {fixture_path}",
        f"- Raw results: {output_json}",
        f"- Model: {args.model}",
        f"- Prompts evaluated: {prompt_count}",
        f"- Request timeout (per prompt): {args.request_timeout}s",
        "",
        "## Metrics",
        "",
        f"- answer_nonempty_rate: {metrics['answer_nonempty_rate']:.3f}",
        f"- grounded_answer_pass_rate (heuristic): {metrics['grounded_answer_pass_rate']:.3f}",
        f"- citation_link_valid_rate: {metrics['citation_link_valid_rate']:.3f}",
        f"- source_format_error_rate: {metrics['source_format_error_rate']:.3f}",
        f"- p95_response_latency_ms: {metrics['p95_response_latency_ms']}",
        f"- avg_response_latency_ms: {metrics['avg_response_latency_ms']}",
        "",
        "### Badge Distribution",
        "",
        f"- High: {metrics['badge_distribution'].get('High', 0)}",
        f"- Medium: {metrics['badge_distribution'].get('Medium', 0)}",
        f"- Low: {metrics['badge_distribution'].get('Low', 0)}",
        "",
        "### Category Pass Rates (Heuristic)",
        "",
    ]
    for category, value in metrics["category_pass_rates"].items():
        lines.append(f"- {category}: {value:.3f}")
    lines += [
        "",
        "## Notes",
        "",
        "- This run includes persistent status checkpoints for long-process visibility.",
        "- Any timeout/error responses are counted as non-pass for grounded answer checks.",
    ]
    write_text_atomic(output_report, "\n".join(lines) + "\n")

    completed_at = utc_now_iso()
    emit_status(
        status_json,
        run_state="completed",
        started_at=started_at,
        fixture=str(fixture_path),
        completed=prompt_count,
        total=prompt_count,
        last_prompt_id=runs[-1]["id"] if runs else None,
        last_latency_ms=runs[-1]["latency_ms"] if runs else None,
        last_error=runs[-1]["error"] if runs else None,
    )
    append_progress(
        progress_log, f"[{completed_at}] COMPLETE prompts={prompt_count}")

    print("Completed benchmark run", flush=True)
    print(json.dumps(metrics, ensure_ascii=True, indent=2), flush=True)
    print(f"Wrote raw results: {output_json}", flush=True)
    print(f"Wrote report: {output_report}", flush=True)
    print(f"Wrote status: {status_json}", flush=True)
    print(f"Wrote progress log: {progress_log}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
