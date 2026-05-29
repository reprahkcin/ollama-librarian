# Ollama Librarian v1.0.7

This release ships the full response-quality phase rollout through Phase 6, including structured citation rendering, retrieval calibration, confidence calibration, and benchmark sign-off artifacts.

## Highlights

- Completed response quality phases 0 through 6 in the mainline branch.
- Added structured-first `/api/pdf/ask` rendering path in frontend assets.
- Calibrated retrieval/reranking to improve relevance on entity and ambiguous prompts.
- Added citation confidence calibration metadata and deterministic calibration tests.
- Added focused benchmark fixtures for ambiguous and narrow-entity failure slices.
- Added full benchmark sign-off artifacts and reports for regression visibility.

## Quality Outcomes (Sign-off Full Pass)

Source: `tests/quality/results/phase6_signoff_full_results.json`

- `grounded_answer_pass_rate`: 0.850
- `source_format_error_rate`: 0.050
- `citation_link_valid_rate`: 1.000
- `category_pass_rates`:
  - `broad_factual`: 1.0
  - `narrow_entity`: 1.0
  - `ambiguous_multi_doc`: 1.0
  - `insufficient_evidence`: 0.4

## Delta vs Baseline

- `grounded_answer_pass_rate`: +0.225 (0.625 -> 0.850)
- `source_format_error_rate`: -0.150 (0.200 -> 0.050)
- `citation_link_valid_rate`: unchanged at 1.000

## Validation

- Route, retrieval trace, retrieval calibration, security, and confidence calibration tests passed in phase runs.
- Full and focused benchmark runs recorded in `tests/quality/results/` and summarized in `docs/` phase reports.

## Known Residual Risk

- Full benchmark badge distribution still shows no naturally occurring `Low` citations in current corpus (`Low = 0`), though deterministic Low-path tests are in place.
