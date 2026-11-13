# Reference load/latency report

> Reference CPU baselines measured on a single machine. These are not production throughput, capacity or SLO claims.

> - Single-process API; results do not describe a multi-replica deployment.
> - Dummy providers (unless a real-model config is supplied) so quality is not measured here.
> - Latency is wall-clock client time and includes HTTP and serialization.
> - Re-measure on your own hardware before making capacity decisions.

## Provenance

| Field | Value |
| --- | --- |
| Git commit | `66d6d5ee5622fb2b69323f1a32e30062bfb01070` |
| Generated (UTC) | 2026-11-13T05:49:23.337714+00:00 |
| Platform | Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.43 |
| CPU | unknown (16 cores) |
| Python | 3.13.15 |
| Target | http://127.0.0.1:8055 |
| Config dir | `deployment/smoke/config` |

## Configuration

- Scenarios: health, ready, query, batch
- Concurrency levels: 1, 4, 8, 16
- Requests per scenario: 30
- Warmup requests (uncounted): 3

## Results

| Scenario | Concurrency | Requests | Errors | Error rate | Req/s | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| health | 1 | 30 | 0 | 0.0000 | 22.19 | 44.21 | 47.95 | 48.03 | 45.05 |
| health | 4 | 30 | 0 | 0.0000 | 81.48 | 48.89 | 56.15 | 57.57 | 44.62 |
| health | 8 | 30 | 0 | 0.0000 | 157.22 | 46.27 | 59.38 | 61.54 | 41.30 |
| health | 16 | 30 | 0 | 0.0000 | 292.70 | 36.48 | 59.31 | 60.88 | 41.94 |
| ready | 1 | 30 | 0 | 0.0000 | 22.46 | 44.03 | 47.71 | 47.79 | 44.50 |
| ready | 4 | 30 | 0 | 0.0000 | 78.87 | 49.00 | 54.96 | 55.38 | 45.30 |
| ready | 8 | 30 | 0 | 0.0000 | 160.28 | 50.52 | 59.60 | 60.38 | 42.03 |
| ready | 16 | 30 | 0 | 0.0000 | 273.04 | 32.71 | 59.46 | 60.97 | 40.99 |
| query | 1 | 30 | 0 | 0.0000 | 19.58 | 51.69 | 55.69 | 56.10 | 51.03 |
| query | 4 | 30 | 0 | 0.0000 | 78.95 | 48.14 | 54.38 | 62.29 | 45.82 |
| query | 8 | 30 | 0 | 0.0000 | 122.71 | 54.08 | 76.44 | 77.82 | 53.81 |
| query | 16 | 30 | 0 | 0.0000 | 146.16 | 79.19 | 99.96 | 107.01 | 79.76 |
| batch | 1 | 30 | 0 | 0.0000 | 18.75 | 52.17 | 58.35 | 60.10 | 53.29 |
| batch | 4 | 30 | 0 | 0.0000 | 71.33 | 55.20 | 63.41 | 65.87 | 51.35 |
| batch | 8 | 30 | 0 | 0.0000 | 103.38 | 66.93 | 85.78 | 91.71 | 65.24 |
| batch | 16 | 30 | 0 | 0.0000 | 95.79 | 129.97 | 198.18 | 204.88 | 136.47 |

## Per-stage latency (mean / p95, ms)

| Scenario | Concurrency | Stage | Mean | p95 |
| --- | ---: | --- | ---: | ---: |
| query | 1 | embedding_ms | 0.00 | 0.00 |
| query | 1 | evaluation_ms | 0.00 | 0.00 |
| query | 1 | input_redaction_ms | 0.03 | 0.05 |
| query | 1 | llm_generation_ms | 0.05 | 0.09 |
| query | 1 | prompt_construction_ms | 0.01 | 0.01 |
| query | 1 | query_validation_ms | 0.01 | 0.01 |
| query | 1 | reranking_ms | 0.00 | 0.00 |
| query | 1 | retrieval_ms | 0.06 | 0.09 |
| query | 1 | token_budget_ms | 0.02 | 0.03 |
| query | 1 | total_ms | 3.00 | 3.95 |
| query | 1 | total_pipeline_ms | 3.00 | 3.95 |
| query | 4 | embedding_ms | 0.00 | 0.00 |
| query | 4 | evaluation_ms | 0.00 | 0.00 |
| query | 4 | input_redaction_ms | 0.02 | 0.03 |
| query | 4 | llm_generation_ms | 0.03 | 0.05 |
| query | 4 | prompt_construction_ms | 0.01 | 0.01 |
| query | 4 | query_validation_ms | 0.00 | 0.01 |
| query | 4 | reranking_ms | 0.00 | 0.00 |
| query | 4 | retrieval_ms | 0.04 | 0.06 |
| query | 4 | token_budget_ms | 0.01 | 0.02 |
| query | 4 | total_ms | 2.65 | 5.27 |
| query | 4 | total_pipeline_ms | 2.65 | 5.27 |
| query | 8 | embedding_ms | 0.00 | 0.00 |
| query | 8 | evaluation_ms | 0.00 | 0.00 |
| query | 8 | input_redaction_ms | 0.02 | 0.02 |
| query | 8 | llm_generation_ms | 0.03 | 0.04 |
| query | 8 | prompt_construction_ms | 0.01 | 0.01 |
| query | 8 | query_validation_ms | 0.00 | 0.00 |
| query | 8 | reranking_ms | 0.00 | 0.00 |
| query | 8 | retrieval_ms | 0.03 | 0.05 |
| query | 8 | token_budget_ms | 0.01 | 0.02 |
| query | 8 | total_ms | 6.61 | 16.20 |
| query | 8 | total_pipeline_ms | 6.61 | 16.20 |
| query | 16 | embedding_ms | 0.00 | 0.00 |
| query | 16 | evaluation_ms | 0.00 | 0.00 |
| query | 16 | input_redaction_ms | 0.01 | 0.02 |
| query | 16 | llm_generation_ms | 0.03 | 0.04 |
| query | 16 | prompt_construction_ms | 0.00 | 0.01 |
| query | 16 | query_validation_ms | 0.00 | 0.00 |
| query | 16 | reranking_ms | 0.00 | 0.00 |
| query | 16 | retrieval_ms | 0.03 | 0.04 |
| query | 16 | token_budget_ms | 0.01 | 0.02 |
| query | 16 | total_ms | 16.34 | 32.31 |
| query | 16 | total_pipeline_ms | 16.34 | 32.31 |

## Summary

- Total requests: 480
- Total errors: 0 (error rate 0.0000)
- Runs: 16

These are reference CPU baselines; do not present them as production throughput or SLO compliance.
