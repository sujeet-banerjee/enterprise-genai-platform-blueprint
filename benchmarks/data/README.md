# Showcase benchmark corpora

Synthetic, license-clean corpora used by the showcase benchmark harness
(`config/benchmarks.yaml`, issues #195-#198). They are intentionally small
enough to run on a CPU and are **not** production datasets.

## Layout

| Suite | Path | Docs | Cases | Focus |
| --- | --- | --- | --- | --- |
| `enterprise-it` | `benchmarks/data/enterprise-it/benchmark.json` | 50 | 42 | Identity, RBAC, audit, crypto, resilience, vendor risk, FinOps |
| `product-docs` | `benchmarks/data/product-docs/benchmark.json` | 46 | 36 | Fictional "Atlas" API platform docs |
| `support` | `benchmarks/data/support/benchmark.json` | 40 | 33 | Support runbooks and FAQs |

## Schema

```json
{
  "name": "Enterprise IT benchmark",
  "description": "...",
  "domain": "enterprise-it",
  "version": "1.0.0",
  "license": "Apache-2.0",
  "synthetic": true,
  "docs": [
    {"id": 0, "title": "...", "category": "...", "content": "..."}
  ],
  "cases": [
    {
      "id": "enterprise-it-001",
      "query": "...",
      "relevant_doc_ids": [0, 1],
      "reference": "...",
      "tags": ["multi_hop"]
    }
  ]
}
```

- `docs[*].id` equals the zero-based corpus index; `relevant_doc_ids` refers to
  that index. Both the IR runner (`core/evaluation/benchmark_runner.py`) and the
  eval-dataset loader (`core/evaluation/eval_datasets.py`) use this convention.
- `reference` is a short ground-truth answer used by ground-truth scoring.
- `relevant_doc_ids: []` marks an **unanswerable** case; it is not an error.
- Tag vocabulary: `multi_hop`, `unanswerable`, `injection`, `pii`, `numeric`,
  `policy`, plus domain tags (`auth`, `audit`, `webhooks`, ...). Every suite
  contains at least one `multi_hop`, `unanswerable`, `injection` and `pii` case.

## Provenance and licensing

- All documents and cases are **synthetic**, written for this repository. They
  do not describe a real company, product or person.
- Distributed under the repository license (Apache-2.0). No third-party text is
  included, so the corpora can be redistributed and committed to results.
- Any published result must record the dataset SHA-256 and the git commit that
  produced it (see `docs/benchmarks/` once #198 lands).

## Maintenance rules

- Keep documents distinct and self-contained; do not duplicate content across
  suites.
- Update `version` for any change that could move metrics; regenerate published
  results in the same PR.
- Validate with:

```bash
python -m app.config_validate config/benchmarks.yaml
python - <<'PY'
from core.evaluation.eval_datasets import load_eval_dataset
for name in ("enterprise-it", "product-docs", "support"):
    print(load_eval_dataset(f"benchmarks/data/{name}/benchmark.json", name=name).to_dict())
PY
```
