# Phase 6 Narrow Entity Prompt Failures

Source run: tests/quality/results/phase6_full_pass_results.json

## Summary

- Narrow entity category pass rate: 0.70 (7/10)
- Failed narrow_entity prompts: 3
- Common failure marker in all three: `has_source_format_error = true`

## Failed Prompt IDs

1. `ne_005`

- Prompt: What was the Federal Home Loan Bank Act intended to accomplish?
- Latency: 12967 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

2. `ne_006`

- Prompt: Who was Franklin D. Roosevelt in relation to Hoover-era economic policy debates?
- Latency: 12541 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

3. `ne_010`

- Prompt: Who was Andrew Mellon and why does he appear in Depression-era policy discussions?
- Latency: 13729 ms
- Failure flags: `answer_pass_heuristic=false`, `has_source_format_error=true`

## Next Tuning Focus

- Re-run these three prompts with `debug_trace=true` to compare ranking spread versus successful narrow_entity cases.
- Check whether source-format artifacts originate in model answer text or renderer output path.
- Use tests/quality/fixtures/phase6_narrow_entity_focus.json for short-loop validation.
