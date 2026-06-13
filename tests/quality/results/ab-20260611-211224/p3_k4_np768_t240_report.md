# Quality Baseline Report

- Fixture: /home/nick/GIT/ollama-librarian/tests/quality/fixtures/benchmark_v1.json
- Raw results: /home/nick/GIT/ollama-librarian/tests/quality/results/ab-20260611-211224/p3_k4_np768_t240_results.json
- Model: qwen2.5:14b
- Prompts evaluated: 2
- Request timeout (per prompt): 60s

## Metrics

- answer_nonempty_rate: 0.000
- grounded_answer_pass_rate (heuristic): 0.000
- citation_link_valid_rate: 0.000
- source_format_error_rate: 0.000
- p95_response_latency_ms: 85652
- avg_response_latency_ms: 45042

### Badge Distribution

- High: 0
- Medium: 0
- Low: 0

### Category Pass Rates (Heuristic)

- broad_factual: 0.000

## Notes

- This run includes persistent status checkpoints for long-process visibility.
- Any timeout/error responses are counted as non-pass for grounded answer checks.
