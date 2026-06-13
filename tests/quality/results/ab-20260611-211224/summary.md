# A/B Benchmark Summary

- Run ID: ab-20260611-211224
- Model: qwen2.5:14b
- Fixture: /home/nick/GIT/ollama-librarian/tests/quality/fixtures/benchmark_v1.json
- Request timeout: 60s

## Results

| Profile | top_k | num_predict | answer_timeout | pass_rate | citation_rate | p95_ms | avg_ms | score | timed_out | error |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---|
| p5_k6_np512_t240 | 6 | 512 | 240 | 0.000 | 0.000 | 86 | 24 | -0.0000 | no |  |
| p7_k6_np768_t240 | 6 | 768 | 240 | 0.000 | 0.000 | 89 | 25 | -0.0000 | no |  |
| p8_k6_np768_t360 | 6 | 768 | 360 | 0.000 | 0.000 | 99 | 27 | -0.0000 | no |  |
| p6_k6_np512_t360 | 6 | 512 | 360 | 0.000 | 0.000 | 117 | 32 | -0.0000 | no |  |
| p4_k4_np768_t360 | 4 | 768 | 360 | 0.000 | 0.000 | 85608 | 45030 | -0.0214 | no |  |
| p2_k4_np512_t360 | 4 | 512 | 360 | 0.000 | 0.000 | 85638 | 45048 | -0.0214 | no |  |
| p1_k4_np512_t240 | 4 | 512 | 240 | 0.000 | 0.000 | 85650 | 45041 | -0.0214 | no |  |
| p3_k4_np768_t240 | 4 | 768 | 240 | 0.000 | 0.000 | 85652 | 45042 | -0.0214 | no |  |

## Winner

- Profile: p5_k6_np512_t240
- Reason: highest composite score (-0.0000) with pass_rate=0.000 and p95=86ms.
