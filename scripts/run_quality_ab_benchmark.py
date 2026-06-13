#!/usr/bin/env python3
"""Run A/B profile benchmarks with automatic reset between runs.

This runner executes the existing quality benchmark script across multiple
runtime profiles and writes a comparison summary.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Profile:
    name: str
    top_k: int
    num_predict: int
    answer_timeout: int


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run A/B benchmark matrix with clean reset between profiles.")
    parser.add_argument(
        "--model",
        default="qwen2.5:14b",
        help="Model used for benchmark requests.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=120,
        help="Per-request client timeout passed to benchmark script.",
    )
    parser.add_argument(
        "--fixture",
        default="tests/quality/fixtures/benchmark_v1.json",
        help="Benchmark fixture path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional prompt cap for smoke runs.",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Warm up the model after each reset before running benchmark.",
    )
    parser.add_argument(
        "--out-dir",
        default="tests/quality/results",
        help="Directory for output JSON/MD artifacts.",
    )
    parser.add_argument(
        "--reset-script",
        default="scripts/librarian-reset-linux.sh",
        help="Reset script used before each profile run.",
    )
    parser.add_argument(
        "--benchmark-script",
        default="scripts/run_quality_benchmark.py",
        help="Benchmark script to execute for each profile.",
    )
    parser.add_argument(
        "--profile-timeout-seconds",
        type=int,
        default=0,
        help=(
            "Hard timeout for each profile benchmark subprocess. "
            "0 means auto-compute based on request-timeout and limit."
        ),
    )
    return parser.parse_args()


def default_profiles() -> list[Profile]:
    return [
        Profile("p1_k4_np512_t240", top_k=4,
                num_predict=512, answer_timeout=240),
        Profile("p2_k4_np512_t360", top_k=4,
                num_predict=512, answer_timeout=360),
        Profile("p3_k4_np768_t240", top_k=4,
                num_predict=768, answer_timeout=240),
        Profile("p4_k4_np768_t360", top_k=4,
                num_predict=768, answer_timeout=360),
        Profile("p5_k6_np512_t240", top_k=6,
                num_predict=512, answer_timeout=240),
        Profile("p6_k6_np512_t360", top_k=6,
                num_predict=512, answer_timeout=360),
        Profile("p7_k6_np768_t240", top_k=6,
                num_predict=768, answer_timeout=240),
        Profile("p8_k6_np768_t360", top_k=6,
                num_predict=768, answer_timeout=360),
    ]


def run_cmd(cmd: list[str], env: dict[str, str], timeout: int | None = None) -> None:
    subprocess.run(cmd, env=env, check=True, timeout=timeout)


def read_metrics(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError(f"Missing metrics in {path}")
    return metrics


def read_error_rates(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        return {
            "error_rate": 1.0,
            "http_429_rate": 0.0,
        }

    total = len(runs)
    errors = 0
    errors_429 = 0
    for item in runs:
        if not isinstance(item, dict):
            errors += 1
            continue
        err = str(item.get("error", "") or "")
        if err:
            errors += 1
            if "429" in err:
                errors_429 += 1

    return {
        "error_rate": float(errors) / float(total),
        "http_429_rate": float(errors_429) / float(total),
    }


def profile_score(metrics: dict[str, Any], error_rate: float) -> float:
    pass_rate = float(metrics.get("grounded_answer_pass_rate", 0.0) or 0.0)
    nonempty_rate = float(metrics.get("answer_nonempty_rate", 0.0) or 0.0)
    citation_rate = float(metrics.get("citation_link_valid_rate", 0.0) or 0.0)
    fmt_penalty = float(metrics.get("source_format_error_rate", 0.0) or 0.0)
    p95 = float(metrics.get("p95_response_latency_ms", 0.0) or 0.0)

    # Heavier weight on grounded quality than latency.
    latency_penalty = min(1.0, p95 / 120000.0)
    return (
        (0.55 * pass_rate)
        + (0.20 * nonempty_rate)
        + (0.15 * citation_rate)
        - (0.07 * fmt_penalty)
        - (0.05 * latency_penalty)
        - (0.40 * max(0.0, min(1.0, error_rate)))
    )


def compute_profile_timeout_seconds(args: argparse.Namespace) -> int:
    if int(args.profile_timeout_seconds) > 0:
        return int(args.profile_timeout_seconds)

    if int(args.limit) > 0:
        expected_prompts = int(args.limit)
    else:
        # Fixture default currently contains 40 prompts.
        expected_prompts = 40

    per_prompt_budget = max(30, int(args.request_timeout)) + 15
    # Add headroom for reset/startup/warmup and serialization overhead.
    return max(180, (expected_prompts * per_prompt_budget) + 240)


def write_summary(
    summary_path: Path,
    run_id: str,
    model: str,
    fixture: str,
    request_timeout: int,
    rows: list[dict[str, Any]],
    winner: dict[str, Any] | None,
) -> None:
    lines = [
        "# A/B Benchmark Summary",
        "",
        f"- Run ID: {run_id}",
        f"- Model: {model}",
        f"- Fixture: {fixture}",
        f"- Request timeout: {request_timeout}s",
        "",
        "## Results",
        "",
        "| Profile | top_k | num_predict | answer_timeout | pass_rate | nonempty_rate | error_rate | 429_rate | p95_ms | avg_ms | score | timed_out | error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|",
    ]

    for row in rows:
        lines.append(
            "| {name} | {top_k} | {num_predict} | {answer_timeout} | {pass_rate:.3f} | {nonempty_rate:.3f} | {error_rate:.3f} | {rate_429:.3f} | {p95} | {avg} | {score:.4f} | {timed_out} | {error} |".format(
                name=row["name"],
                top_k=row["top_k"],
                num_predict=row["num_predict"],
                answer_timeout=row["answer_timeout"],
                pass_rate=row["pass_rate"],
                nonempty_rate=row["nonempty_rate"],
                error_rate=row["error_rate"],
                rate_429=row["http_429_rate"],
                p95=row["p95_ms"],
                avg=row["avg_ms"],
                score=row["score"],
                timed_out=("yes" if row.get("timed_out") else "no"),
                error=str(row.get("error", "") or "").replace("|", "/"),
            )
        )

    if winner is not None:
        lines += [
            "",
            "## Winner",
            "",
            f"- Profile: {winner['name']}",
            f"- Reason: highest viable composite score ({winner['score']:.4f}) with pass_rate={winner['pass_rate']:.3f}, nonempty_rate={winner['nonempty_rate']:.3f}, error_rate={winner['error_rate']:.3f}, and p95={winner['p95_ms']}ms.",
        ]
    elif rows:
        lines += [
            "",
            "## Winner",
            "",
            "- No viable winner in this run.",
            "- Reason: all profiles had zero grounded pass rate and/or complete request failure.",
        ]

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = (repo_root / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    reset_script = (repo_root / args.reset_script).resolve()
    benchmark_script = (repo_root / args.benchmark_script).resolve()
    fixture_path = (repo_root / args.fixture).resolve()

    if not reset_script.exists():
        raise FileNotFoundError(f"Reset script not found: {reset_script}")
    if not benchmark_script.exists():
        raise FileNotFoundError(
            f"Benchmark script not found: {benchmark_script}")
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")

    run_id = f"ab-{utc_stamp()}"
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    profiles = default_profiles()
    per_profile_timeout = compute_profile_timeout_seconds(args)

    print(f"Starting A/B run: {run_id}", flush=True)
    print(f"Profiles: {len(profiles)}", flush=True)
    print(
        f"Per-profile benchmark timeout: {per_profile_timeout}s",
        flush=True,
    )

    for index, profile in enumerate(profiles, start=1):
        print(
            f"[{index}/{len(profiles)}] Profile {profile.name} (k={profile.top_k}, np={profile.num_predict}, t={profile.answer_timeout})",
            flush=True,
        )

        env = os.environ.copy()
        env["OLLAMA_WEB_PDF_TOP_K"] = str(profile.top_k)
        env["OLLAMA_WEB_PDF_ANSWER_NUM_PREDICT"] = str(profile.num_predict)
        env["OLLAMA_WEB_PDF_ANSWER_TIMEOUT"] = str(profile.answer_timeout)

        reset_cmd = [str(reset_script)]
        if args.warmup:
            reset_cmd.extend(["--warmup-model", args.model])

        started = time.time()
        run_cmd(reset_cmd, env=env)

        output_json = run_dir / f"{profile.name}_results.json"
        output_report = run_dir / f"{profile.name}_report.md"
        status_json = run_dir / f"{profile.name}_status.json"
        progress_log = run_dir / f"{profile.name}_progress.log"

        bench_cmd = [
            sys.executable,
            str(benchmark_script),
            "--fixture",
            str(fixture_path),
            "--model",
            args.model,
            "--top-k",
            str(profile.top_k),
            "--request-timeout",
            str(args.request_timeout),
            "--output-json",
            str(output_json),
            "--output-report",
            str(output_report),
            "--status-json",
            str(status_json),
            "--progress-log",
            str(progress_log),
        ]
        if args.limit > 0:
            bench_cmd.extend(["--limit", str(args.limit)])

        timed_out = False
        profile_error = ""
        try:
            run_cmd(bench_cmd, env=env, timeout=per_profile_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            profile_error = (
                f"benchmark subprocess timed out after {per_profile_timeout}s"
            )
            print(
                f"Profile {profile.name} timed out after {per_profile_timeout}s",
                flush=True,
            )
        except subprocess.CalledProcessError as exc:
            profile_error = f"benchmark subprocess failed with exit {exc.returncode}"
            print(
                f"Profile {profile.name} failed: {profile_error}",
                flush=True,
            )

        elapsed_s = int(time.time() - started)

        metrics: dict[str, Any]
        if output_json.exists():
            metrics = read_metrics(output_json)
            err_rates = read_error_rates(output_json)
        else:
            metrics = {
                "grounded_answer_pass_rate": 0.0,
                "answer_nonempty_rate": 0.0,
                "citation_link_valid_rate": 0.0,
                "source_format_error_rate": 0.0,
                "p95_response_latency_ms": int(args.request_timeout * 1000),
                "avg_response_latency_ms": int(args.request_timeout * 1000),
            }
            err_rates = {
                "error_rate": 1.0,
                "http_429_rate": 0.0,
            }
        row = {
            "name": profile.name,
            "top_k": profile.top_k,
            "num_predict": profile.num_predict,
            "answer_timeout": profile.answer_timeout,
            "pass_rate": float(metrics.get("grounded_answer_pass_rate", 0.0) or 0.0),
            "nonempty_rate": float(metrics.get("answer_nonempty_rate", 0.0) or 0.0),
            "citation_rate": float(metrics.get("citation_link_valid_rate", 0.0) or 0.0),
            "error_rate": float(err_rates.get("error_rate", 1.0) or 1.0),
            "http_429_rate": float(err_rates.get("http_429_rate", 0.0) or 0.0),
            "p95_ms": int(metrics.get("p95_response_latency_ms", 0) or 0),
            "avg_ms": int(metrics.get("avg_response_latency_ms", 0) or 0),
            "elapsed_s": elapsed_s,
            "timed_out": bool(timed_out),
            "error": profile_error,
        }
        row["score"] = profile_score(metrics, row["error_rate"])
        rows.append(row)

    rows.sort(key=lambda r: r["score"], reverse=True)

    winner = next(
        (
            r
            for r in rows
            if r["pass_rate"] > 0.0 and r["nonempty_rate"] > 0.0 and r["error_rate"] < 1.0
        ),
        None,
    )

    summary_json = run_dir / "summary.json"
    summary_md = run_dir / "summary.md"

    summary_payload = {
        "run_id": run_id,
        "model": args.model,
        "fixture": str(fixture_path),
        "request_timeout": args.request_timeout,
        "profiles": rows,
        "winner": winner,
    }
    summary_json.write_text(json.dumps(
        summary_payload, indent=2, ensure_ascii=True), encoding="utf-8")
    write_summary(summary_md, run_id, args.model, str(
        fixture_path), args.request_timeout, rows, winner)

    print(f"Completed A/B run: {run_id}", flush=True)
    print(f"Summary JSON: {summary_json}", flush=True)
    print(f"Summary MD: {summary_md}", flush=True)
    if winner is not None:
        print(
            "Best profile: {name} (score={score:.4f}, pass_rate={pass_rate:.3f}, p95={p95}ms)".format(
                name=winner["name"],
                score=winner["score"],
                pass_rate=winner["pass_rate"],
                p95=winner["p95_ms"],
            ),
            flush=True,
        )
    else:
        print(
            "Best profile: none (all profiles failed viability checks)",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
