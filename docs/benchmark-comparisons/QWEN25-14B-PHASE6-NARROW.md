# Quality Baseline Report

- Fixture: tests/quality/fixtures/phase6_narrow_entity_focus.json
- Raw results: tests/quality/results/qwen25_14b_phase6_narrow_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 3
- Request timeout (per prompt): 600s

## Metrics

- answer_nonempty_rate: 1.000
- grounded_answer_pass_rate (heuristic): 1.000
- citation_link_valid_rate: 1.000
- source_format_error_rate: 0.000
- p95_response_latency_ms: 177868
- avg_response_latency_ms: 173016

### Badge Distribution

- High: 11
- Medium: 7
- Low: 0

### Category Pass Rates (Heuristic)

- narrow_entity: 1.000

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
