# Quality Baseline Report

- Fixture: tests\quality\fixtures\phase6_ambiguous_focus.json
- Raw results: tests\quality\results\phase6_ambiguous_focus_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 4
- Request timeout (per prompt): 60s

## Metrics

- answer_nonempty_rate: 1.000
- grounded_answer_pass_rate (heuristic): 1.000
- citation_link_valid_rate: 1.000
- source_format_error_rate: 0.000
- p95_response_latency_ms: 23034
- avg_response_latency_ms: 14830

### Badge Distribution

- High: 21
- Medium: 3
- Low: 0

### Category Pass Rates (Heuristic)

- ambiguous_multi_doc: 1.000

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
