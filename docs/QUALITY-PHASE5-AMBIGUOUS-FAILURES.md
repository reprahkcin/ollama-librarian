# Phase 5 Ambiguous Prompt Failures

Source run: tests/quality/results/phase5_pass_results.json

## Summary

- Ambiguous category pass rate: 0.60 (6/10)
- Failed ambiguous prompts: 4
- Common failure marker in all four: `has_source_format_error = true`

## Failed Prompt IDs

1. `amb_003`

- Prompt: If two sources disagree on causes of recovery, summarize both views and note uncertainty.
- Latency: 10494 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

2. `amb_004`

- Prompt: What seems to be consensus versus debate in the library about Hoover's policy effectiveness?
- Latency: 10776 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

3. `amb_008`

- Prompt: Reconcile conflicting descriptions of federal relief speed in early Depression years.
- Latency: 17471 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

4. `amb_010`

- Prompt: What are the most defensible claims we can make when the evidence base is mixed?
- Latency: 13926 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

## Next Retrieval Tuning Focus

- Re-run with `debug_trace=true` for these four prompts and inspect score/rank spread per citation.
- Verify whether malformed source artifacts originate from model text generation versus renderer stitching.
- Use tests/quality/fixtures/phase6_ambiguous_focus.json as the short-loop fixture for tuning and smoke validation.
