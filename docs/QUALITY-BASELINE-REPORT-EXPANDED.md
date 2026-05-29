# Quality Baseline Report

- Fixture: tests\quality\fixtures\benchmark_v1.json
- Raw results: tests\quality\results\baseline_v1_expanded_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 40
- Request timeout (per prompt): 60s

## Metrics

- answer_nonempty_rate: 1.000
- grounded_answer_pass_rate (heuristic): 0.625
- citation_link_valid_rate: 1.000
- source_format_error_rate: 0.200
- p95_response_latency_ms: 18488
- avg_response_latency_ms: 11771

### Badge Distribution

- High: 210
- Medium: 30
- Low: 0

### Category Pass Rates (Heuristic)

- ambiguous_multi_doc: 0.700
- broad_factual: 0.800
- insufficient_evidence: 0.100
- narrow_entity: 0.900

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
