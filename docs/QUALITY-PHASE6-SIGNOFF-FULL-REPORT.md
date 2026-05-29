# Quality Baseline Report

- Fixture: tests\quality\fixtures\benchmark_v1.json
- Raw results: tests\quality\results\phase6_signoff_full_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 40
- Request timeout (per prompt): 60s

## Metrics

- answer_nonempty_rate: 1.000
- grounded_answer_pass_rate (heuristic): 0.850
- citation_link_valid_rate: 1.000
- source_format_error_rate: 0.050
- p95_response_latency_ms: 20374
- avg_response_latency_ms: 14543

### Badge Distribution

- High: 203
- Medium: 37
- Low: 0

### Category Pass Rates (Heuristic)

- ambiguous_multi_doc: 1.000
- broad_factual: 1.000
- insufficient_evidence: 0.400
- narrow_entity: 1.000

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
