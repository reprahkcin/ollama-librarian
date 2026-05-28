# Quality Benchmark Rubric (Phase 0)

This document defines the baseline benchmark and pass/fail rubric for response and source quality.

## Scope

This rubric is used for:

- answer quality checks
- citation/source quality checks
- confidence label sanity checks
- regression comparisons across future phases

## Benchmark Dataset (v1)

- File: `tests/quality/fixtures/benchmark_v1.json`
- Prompt count in current expanded set: 40
- Categories in set:
  - broad_factual
  - narrow_entity
  - ambiguous_multi_doc
  - insufficient_evidence

Notes:

- Seed baseline capture was run on the initial 10-prompt seed for calibration history.
- Current fixture satisfies Phase 0 expansion scope (40-60 prompts) and category minimum checks.

## Response Quality Rubric

Each answer is scored per prompt as Pass/Fail on the following criteria.

1. Relevance

- Pass: directly addresses prompt intent.
- Fail: off-topic or ignores key asked entity/timeframe.

2. Completeness

- Pass: provides a usable answer in at least 2 sentences unless prompt asks for one-line output.
- Fail: empty, citation-only, or too sparse to answer user intent.

3. Groundedness

- Pass: claims are supported by provided retrieval context.
- Fail: unsupported or fabricated claims not present in evidence.

4. Clarity

- Pass: coherent prose with no obvious formatting corruption.
- Fail: malformed source fragments, broken markup, or unreadable structure.

A response is `answer_pass = true` only if all four criteria pass.

## Citation/Source Quality Rubric

1. Presence

- Pass: at least one citation for claim-bearing responses.
- Exception: explicit insufficient-evidence answer may pass without citation if no evidence exists.

2. Validity

- Pass: citation references a known source path and valid location type/page/section.
- Fail: malformed descriptor or non-resolvable source target.

3. Consistency

- Pass: citation location plausibly matches claim content.
- Fail: citation appears unrelated to claim span.

4. Render Quality

- Pass: no broken inline source artifacts in answer text.
- Fail: raw fragments such as `source path, location` or dangling placeholders.

A response is `citation_pass = true` only if all applicable criteria pass.

## Confidence Badge Sanity Rubric

This is a sanity check, not an absolute truth test.

1. Distribution

- Expected: benchmark run should not collapse to all High or all Low across citations.

2. Ordering

- Expected: top-scored citations should not be labeled lower than much weaker citations in the same answer.

3. Tooltip Integrity

- Expected: tooltip includes score and normalization details used by current policy.

## Metrics Definitions

- `answer_nonempty_rate`: non-empty prose responses / total responses
- `grounded_answer_pass_rate`: responses passing Response Quality Rubric / total
- `citation_link_valid_rate`: valid citations / total citations
- `source_format_error_rate`: malformed source artifacts / total responses
- `badge_distribution`: counts for High/Medium/Low over all citations
- `p95_response_latency_ms`: p95 end-to-end response latency

## Baseline Capture Procedure (Phase 0)

1. Run benchmark prompts against current build using:

- `python scripts/run_quality_benchmark.py`

2. Track live run state from status artifacts (do not rely on terminal buffering only):

- `tests/quality/results/baseline_v1_expanded_status.json`
- `tests/quality/results/baseline_v1_expanded_progress.log`

3. Save raw outputs and sources payload.
4. Score each output with this rubric.
5. Record metrics in a baseline report.

### Long-Run Visibility Contract

- Every prompt completion must update the status JSON and append one log line.
- The status JSON `state` must transition: `running` -> `completed`.
- If interrupted, rerun from a new command invocation and preserve prior progress log for audit.

## Exit Criteria for Phase 0

1. Fixture schema test passes.
2. Expanded benchmark (40-60 prompts) validates and loads.
3. At least 10 prompts each exist for broad_factual, narrow_entity, and ambiguous_multi_doc.
4. Rubric is frozen and referenced by the response quality phase plan.
5. Baseline capture report and raw result artifacts are available for comparison.
