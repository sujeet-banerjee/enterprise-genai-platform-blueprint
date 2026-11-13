# Benchmark methodology

This page documents how the **quality** benchmark results under
[`results/`](results/) are produced, so an architect can judge (and reproduce)
the numbers instead of trusting a table.

Load/throughput numbers are documented separately in
[`load-methodology.md`](load-methodology.md).

## What is measured

The reference run sweeps the retrieval configuration matrix defined by the
`reference` suite in [`config/benchmarks.yaml`](../../config/benchmarks.yaml):

- corpora: `enterprise-it`, `product-docs`, `support`
- cases per corpus: 6 (a bounded, deterministic subset)
- parameters: `top_k ∈ {3, 5}` × `reranker ∈ {false, true}`
- combinations: 4

Quality is an **information-retrieval** measurement over the retrieved
documents: each case carries labelled `relevant_doc_ids`, and the report
aggregates per-case metrics across all corpora and combinations:

| Metric | Meaning |
| --- | --- |
| `context_precision` | share of retrieved documents that are relevant |
| `context_recall` | share of relevant documents that were retrieved |
| `mrr` | mean reciprocal rank of the first relevant document |
| `ndcg` | rank-weighted relevance (`ndcg_at_ids`) |

Cost and latency are recorded per combination so the report can compute a
Pareto frontier and a recommendation. Because the local models are small and
CPU-bound, **treat cost as a relative signal, not a cloud invoice**.

## Models and generation settings

The reference run uses the real config in [`config/`](../../config) (see
[`config/models.yaml`](../../config/models.yaml)) rather than dummy providers:

- LLM: `local-qwen` (`Qwen/Qwen2.5-0.5B-Instruct`) — used for answer generation
  and cost accounting; it does **not** affect the IR metrics above
- Embeddings: `all-MiniLM-L6-v2`
- Retriever: `faiss`, reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`

Generation parameters are taken from the model config, not hard-coded.

## Hardware and environment

The committed results record their own provenance block: git commit, UTC
timestamp, OS/platform, Python version, seed, package versions, the SHA-256 of
every dataset, and a snapshot of the benchmark config. The reference profile is
a **WSL2 CPU-only container** with 16 logical cores and no GPU; see each
result's `provenance` block for the exact machine that produced it.

Absolute latency is therefore **not transferable** to production hardware. Use
the committed numbers to compare configurations on the same machine, and run
the harness in your own environment for capacity planning.

## Reproduce

```bash
# from the repository root
python -m app.benchmark_report --suite reference --config-dir config \
    --out docs/benchmarks/results/$(date -u +%F)-<sha>.json \
    --markdown docs/benchmarks/results/$(date -u +%F)-<sha>.md \
    --csv docs/benchmarks/results/$(date -u +%F)-<sha>.csv \
    --svg-dir docs/benchmarks/results

# validate every committed report and regenerate the index
python -m app.benchmark_results --check
```

Use the **same commit and config snapshot** recorded in the report's
`provenance` block. The `--check` command fails if a dataset or the config
snapshot has drifted from what a report claims, or if the generated index is
stale.

For a fast smoke run (dummy providers, one combination):

```bash
python -m app.benchmark_report --quick --config-dir deployment/smoke/config --check
```

## Caveats

- Small synthetic corpora (dozens of documents) — directionally useful for
  configuration comparisons, not a substitute for a domain benchmark.
- The 0.5B local model is not representative of a frontier model's latency or
  cost; swap `active_model` in `config/models.yaml` and re-run to measure yours.
- IR metrics ignore answer quality. Pair this report with the evaluation
  endpoints (`POST /v1/evaluate`) and ground-truth scoring for answer-level
  checks.
- Numbers are single-run and CPU-bound; treat differences smaller than normal
  run-to-run variance as noise, and increase `max_cases` for tighter estimates.
- The harness never fabricates metrics. If a run cannot produce a metric it is
  reported as missing rather than filled with a placeholder.
