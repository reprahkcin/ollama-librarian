# Quality Baseline Report (Phase 0 Seed)

- Fixture: `tests/quality/fixtures/benchmark_v1.json`
- Raw results: `tests/quality/results/baseline_v1_results.json`
- Model: `qwen2.5:14b`
- Prompts evaluated: `10`
- Request timeout (per prompt): `60s`

## Metrics

- answer_nonempty_rate: `1.000`
- grounded_answer_pass_rate (heuristic): `0.800`
- citation_link_valid_rate: `1.000`
- source_format_error_rate: `0.000`
- p95_response_latency_ms: `35186`
- avg_response_latency_ms: `13795`

### Badge Distribution

- High: `57`
- Medium: `3`
- Low: `0`

### Category Pass Rates (Heuristic)

- ambiguous_multi_doc: `1.000`
- broad_factual: `0.667`
- insufficient_evidence: `0.500`
- narrow_entity: `1.000`

## Notes

- This baseline uses heuristic scoring to seed comparisons for later phases.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
