# Response and Source Quality Phase Plan

This plan defines a test-first rollout to improve answer quality and citation reliability without repeated regressions.

## Goals

- Answers are complete, relevant, and grounded.
- Citations are correct, clickable, and consistently formatted.
- Confidence badges are meaningful and stable.
- Changes ship only after passing objective quality gates.

## Quality Gates (Global)

Every phase must meet all active gates before moving forward:

1. No regression in existing test suite.
2. Phase-specific tests pass.
3. Manual smoke checks pass for 5 representative prompts.
4. No new malformed source output in rendered assistant text.

## Metrics We Track

- `answer_nonempty_rate`: percent of responses with non-empty prose.
- `citation_link_valid_rate`: percent of citations opening correct document/location.
- `source_format_error_rate`: malformed source fragments in rendered output.
- `grounded_answer_pass_rate`: benchmark pass rate for factual grounding checks.
- `badge_distribution`: ratio of High/Medium/Low for benchmark queries.
- `p95_response_latency_ms`: response latency health during quality runs.

## Phase 0 - Benchmark and Rubric Baseline

Objective:

- Define exactly how quality is measured before behavior changes.

Scope:

- Build a benchmark set of 40-60 prompts covering:
  - broad factual
  - narrow entity
  - standalone follow-up-like prompts
  - ambiguous/multi-document prompts
  - insufficient-evidence prompts
- For each prompt, define expected answer intent and expected source coverage.

Deliverables:

- `docs/QUALITY-BENCHMARK.md` with rubric and prompt set.
- `tests/quality/fixtures/*.json` benchmark fixtures.

Acceptance checks:

1. Benchmark fixture schema validated by tests.
2. At least 10 prompts each for broad, entity, and ambiguous categories.
3. Rubric includes pass/fail rules for answer and source quality.

Suggested test command:

- `python -m unittest discover -s tests -p "test_*.py"`

## Phase 1 - Retrieval Observability and Diagnostics

Objective:

- Make ranking failures explainable.

Scope:

- Add optional debug trace for top-k retrieval score components:
  - vector score
  - lexical score
  - rerank/final score
- Add deterministic logging toggle for local troubleshooting.

Deliverables:

- Trace payload in ask path behind debug flag.
- Unit tests for trace shape and toggle behavior.

Acceptance checks:

1. Debug mode shows top-k score breakdown per chunk.
2. Non-debug mode output unchanged.
3. Tests assert no trace leakage in default mode.

## Phase 2 - Structured Response Contract

Objective:

- Eliminate fragile citation parsing from free-form prose.

Scope:

- Backend returns structured response fields:
  - `answer_text`
  - `citations[]`
  - `sources[]`
  - optional `claims[]` and `claim_citation_map`
- Keep backward compatibility with legacy fields during transition.

Deliverables:

- Updated API response contract docs.
- Contract tests for `/api/pdf/ask` response shape.

Acceptance checks:

1. Contract tests pass with required structured fields.
2. Legacy clients still function during compatibility window.
3. At least 95 percent of benchmark responses include structured citations.

## Phase 3 - Frontend Renderer Simplification

Objective:

- Render citations directly from structured payload, not text surgery.

Scope:

- Replace regex-heavy source extraction pipeline on primary path.
- Keep legacy cleanup as fallback path only.
- Preserve markdown rendering for answer prose while separating citation UI.

Deliverables:

- Frontend code path split into:
  - structured renderer
  - legacy fallback renderer
- UI tests for citation cards and links.

Acceptance checks:

1. No malformed inline source artifacts on benchmark set.
2. Citation links open correct target page/section.
3. Legacy fallback only triggers when structured payload absent.

## Phase 4 - Retrieval and Reranking Calibration

Objective:

- Improve relevance for standalone and entity-focused prompts.

Scope:

- Calibrate lexical/entity weighting and rerank policy with benchmark feedback.
- Add protection against semantic drift (high vector score but irrelevant chunk).

Deliverables:

- Updated retrieval scoring policy.
- Tests covering known historical failure prompts.

Acceptance checks:

1. Grounded answer pass rate improves by agreed threshold (target +20 percent from baseline).
2. Entity prompt category passes at target rate (>=90 percent).
3. No drop in broad factual category.

## Phase 5 - Confidence Badge Calibration

Objective:

- Ensure High/Medium/Low are interpretable and stable.

Scope:

- Calibrate confidence rules against benchmark outcomes.
- Add snapshot tests for representative score distributions.

Deliverables:

- Confidence calibration doc with rationale.
- Tests for expected label distribution on known score sets.

Acceptance checks:

1. Badge distribution includes all three bands on benchmark corpus where expected.
2. No persistent all-High or all-Low collapse.
3. Tooltip data matches computed thresholds.

## Phase 6 - Hardening and Regression Shield

Objective:

- Prevent repeat break/fix cycles.

Scope:

- Add integration tests for end-to-end query -> answer -> citation render.
- Add targeted manual smoke plan for release candidates.
- Add release checklist with explicit quality gates.

Deliverables:

- `tests/test_quality_end_to_end.py` (or equivalent).
- `docs/QUALITY-RELEASE-CHECKLIST.md`.

Acceptance checks:

1. End-to-end quality tests pass in CI/local.
2. Manual checklist completed for release candidate.
3. All global gates pass with no open critical quality defects.

## Execution Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6

Do not skip phases. Each phase requires explicit pass/fail sign-off.

## Start-Here Checklist (Phase 0 Kickoff)

1. Confirm benchmark categories and prompt count.
2. Freeze rubric definitions for answer and source pass/fail.
3. Add fixture schema and first 10 benchmark prompts.
4. Run baseline capture and record current metrics.
