# Reference load / latency methodology

This page describes how the committed reference load numbers
(`docs/benchmarks/load.md`, machine-readable `docs/benchmarks/load.json`) are
produced, and how to regenerate them. It is part of the showcase/proof
workstream (issues #195-#199) alongside the quality benchmark report
(`docs/benchmarks/` from #196).

> **These are reference CPU baselines on a single machine.** They are not
> production throughput, capacity or SLO claims. Re-measure on your own
> hardware and configuration before making capacity decisions.

## What is measured

The harness (`core/evaluation/load_harness.py`, CLI
`benchmarks/load/run_load.py`) drives HTTP requests against the API and reports,
per scenario and concurrency level:

| Metric | Meaning |
| --- | --- |
| `p50_ms`, `p95_ms`, `p99_ms` | Client-observed latency percentiles (linear interpolation) |
| `mean_ms`, `min_ms`, `max_ms` | Client-observed latency summary |
| `requests_per_second` | `count / wall_ms` for the timed phase |
| `errors`, `error_rate` | Failed requests (`status == 0` or `>= 400`) as a share of sent requests |
| `status_counts` | HTTP status distribution |
| `stages` | Per-stage latency (mean / p95) parsed from the `/v1/query` observability `latency` block (`*_ms` keys only) |
| `wall_ms` | Total wall time for the timed phase |

Latency is wall-clock time from the client, so it includes HTTP and JSON
serialization, not only in-process pipeline time.

## Scenarios

Scenarios are fixed so numbers are comparable across runs:

| Name | Method | Path | Notes |
| --- | --- | --- | --- |
| `health` | `GET` | `/health` | Liveness probe (no pipeline work) |
| `ready` | `GET` | `/ready` | Readiness; the pipeline is already built in the lifespan |
| `query` | `POST` | `/v1/query` | Single RAG query (`top_k: 3`) |
| `batch` | `POST` | `/v1/query:batch` | Two queries per request (`top_k: 3`) |

The plan is bounded and deterministic: `scenarios x concurrency levels` runs,
`requests` per run, plus uncounted `warmup` requests at the start of each run.
Limits are enforced (`MAX_CONCURRENCY = 64`,
`MAX_REQUESTS_PER_SCENARIO = 5000`, `MAX_PLAN_RUNS = 64`).

## Reproduce

The committed report uses the dummy-provider smoke config
(`deployment/smoke/config`), so no model downloads are needed. It boots the API
with uvicorn and drives it over HTTP (the same path a real deployment sees):

```bash
python benchmarks/load/run_load.py \
  --config-dir deployment/smoke/config \
  --host 127.0.0.1 --port 8055 \
  --concurrency 1,4,8,16 \
  --requests 30 --warmup 3 \
  --scenarios health,ready,query,batch \
  --out docs/benchmarks/load.json \
  --markdown docs/benchmarks/load.md
```

Other modes:

```bash
# Fast in-process run (no port binding; used by tests and CI)
python benchmarks/load/run_load.py --in-process \
  --config-dir deployment/smoke/config \
  --concurrency 1 --requests 2 --warmup 1 --scenarios health,ready,query

# Attach to an already-running API
python benchmarks/load/run_load.py --base-url http://localhost:8000

# To exercise real models, point --config-dir at a config dir whose models.yaml
# uses real providers. Expect much higher latency; still a single-machine baseline.
```

Exit codes: `0` success, `1` runtime failure, `2` invalid configuration.

## Output contract

`load.json` is the source of truth:

```json
{
  "schema_version": "1.0",
  "kind": "reference_load",
  "reference_baselines": true,
  "label": "Reference CPU baselines ...",
  "caveats": ["..."],
  "provenance": {
    "git_sha": "...", "timestamp": "...", "platform": "...",
    "machine": "...", "processor": "...", "cpu_count": 16,
    "python_version": "3.13.x", "config_dir": "...", "target": "..."
  },
  "configuration": {
    "concurrencies": [1, 4, 8, 16], "requests_per_scenario": 30,
    "warmup": 3, "scenarios": ["health", "ready", "query", "batch"]
  },
  "runs": [{"scenario": "query", "concurrency": 4, "count": 30, "errors": 0,
            "latency": {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}, "..."}],
  "summary": {"total_requests": 480, "total_errors": 0, "error_rate": 0.0,
              "runs": 16, "scenarios": ["batch", "health", "query", "ready"]}
}
```

`load.md` is rendered from `load.json` by the same module; it never introduces
numbers that are not in the JSON. Every published number must carry the
`provenance.git_sha` and `provenance.timestamp`.

## Interpreting the committed numbers

The committed `load.md` / `load.json` were generated on WSL2 (16 logical CPU
cores, Python 3.13, dummy providers) at the git commit recorded in the
`Provenance` table. Because the providers are deterministic dummies, the
`query` and `batch` scenarios measure the **pipeline plumbing** (validation,
redaction, token budget, prompt construction, serialization), not model
inference. They are useful for regression tracking of the request path, not for
sizing a GPU fleet.

Reading notes:

- Latency at low concurrency is dominated by fixed per-request overhead; do not
  read a single run as a capacity number.
- Beyond the point where the single process saturates, throughput plateaus and
  p95/p99 grow (visible in the `batch` rows at concurrency 16).
- The `stages` table isolates pipeline stages; sums may differ from end-to-end
  latency due to client/HTTP overhead.
- These numbers are a **lower bound** for real workloads: adding real embedder,
  LLM and reranker calls increases latency substantially.

## Guardrails

- The harness is bounded; it refuses plans above the configured limits.
- Failed requests are counted, not hidden; `error_rate` covers exceptions and
  non-2xx/3xx responses.
- Warmup requests are excluded from the timed phase.
- The label and caveats are emitted into every report so a number cannot be
  quoted without the "reference CPU baselines" context.
