# Quality Baseline Report

- Fixture: tests\quality\fixtures\phase6_narrow_entity_focus.json
- Raw results: tests\quality\results\phase6_narrow_entity_focus_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 3
- Request timeout (per prompt): 60s

## Metrics

- answer_nonempty_rate: 1.000
- grounded_answer_pass_rate (heuristic): 0.667
- citation_link_valid_rate: 1.000
- source_format_error_rate: 0.333
- p95_response_latency_ms: 53972
- avg_response_latency_ms: 21807

### Badge Distribution

- High: 14
- Medium: 4
- Low: 0

### Category Pass Rates (Heuristic)

- narrow_entity: 0.667

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
