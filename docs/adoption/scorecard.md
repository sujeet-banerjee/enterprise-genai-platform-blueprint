# Pilot scorecard template

> Fill this in with the adopter's own data. Every threshold is set by the adopting team;
> this template ships **no success numbers** on purpose. See the
> [pilot brief](pilot-brief.md) for scope and the [checklist](checklist.md) for the review
> gates. Published reference numbers in [benchmarks](../benchmarks/README.md) are for
> methodology only and were not produced on your hardware.

## 0. Decision metadata

| Field | Value |
| --- | --- |
| Adopter / team | `[fill in]` |
| Workload | `[fill in]` |
| Decision owner | `[fill in]` |
| Decision date | `[set during scoping]` |
| Repository commit | `[git rev-parse HEAD]` |
| Config set / revision | `[config directory and revision]` |
| Deployment mode | `[local / Compose / Kubernetes / other]` |
| Dataset (name, version, owner) | `[fill in]` |
| Evaluation cases | `[number]` |

## 1. Quality (adopter-provided evaluation data)

Produce these with the evaluation and experiment paths; do not copy reference numbers.

| Metric | Measured value | Adopter threshold | Pass? | Notes |
| --- | --- | --- | --- | --- |
| `context_precision` | `[value]` | `[adopter to set]` | `[ ]` | |
| `context_recall` | `[value]` | `[adopter to set]` | `[ ]` | |
| MRR | `[value]` | `[adopter to set]` | `[ ]` | |
| nDCG | `[value]` | `[adopter to set]` | `[ ]` | |
| `answer_correctness` (if references exist) | `[value]` | `[adopter to set]` | `[ ]` | |
| `answer_relevance` | `[value]` | `[adopter to set]` | `[ ]` | |
| `faithfulness` | `[value]` | `[adopter to set]` | `[ ]` | |

Commands (substitute your dataset and config):

```bash
# Evaluate a dataset and write a report
python -m app.eval_gate --config-dir <config-dir> --json > eval-report.json

# Gate a pre-computed report against adopter thresholds
python -m app.eval_gate --report eval-report.json \
  --threshold context_recall=<adopter-threshold>
```

## 2. Latency (adopter hardware and concurrency)

| Scenario | Concurrency | Requests | Errors | p50 | p95 | p99 | Threshold | Pass? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| query | `[set]` | `[set]` | `[value]` | `[value]` | `[value]` | `[value]` | `[adopter to set]` | `[ ]` |
| `query:batch` | `[set]` | `[set]` | `[value]` | `[value]` | `[value]` | `[value]` | `[adopter to set]` | `[ ]` |
| health / ready | `[set]` | `[set]` | `[value]` | `[value]` | `[value]` | `[value]` | `[adopter to set]` | `[ ]` |

```bash
python benchmarks/load/run_load.py --config-dir <config-dir> \
  --concurrency <levels> --requests <count> --scenarios query,batch \
  --out /tmp/pilot-load.json --markdown /tmp/pilot-load.md
```

Record the hardware, CPU/GPU, memory and topology. Latency without hardware context is not a
result.

## 3. Cost

| Field | Value |
| --- | --- |
| Cost per request (measured) | `[value]` |
| Monthly request volume assumption | `[adopter to set]` |
| Projected monthly cost | `[value]` |
| Budget threshold | `[adopter to set]` |
| Pass? | `[ ]` |

Costs come from the trace `cost` block and experiment summaries. Provider pricing changes;
record the date and price source used.

## 4. Security and isolation

| Check | Repository coverage | Adopter result | Pass? |
| --- | --- | --- | --- |
| Prompt-injection handling | Guardrail framework + `injection` provider | `[result]` | `[ ]` |
| PII/DLP behavior | Regex + optional NER detectors | `[result]` | `[ ]` |
| Input/trace redaction | Config-driven redaction | `[result]` | `[ ]` |
| ACL isolation | Permission-aware retrieval tests | `[result]` | `[ ]` |
| Tenant isolation | Tenancy + ops scoping | `[result]` | `[ ]` |
| Authentication / RBAC | API key, OIDC, capability map | `[result]` | `[ ]` |
| Audit integrity | Hash-chained store + verify endpoint | `[result]` | `[ ]` |
| Secrets handling | `${VAR}` / `env:VAR`, no keys in YAML | `[result]` | `[ ]` |

Independent penetration testing is not provided by this repository (tracked by #205). Record
which controls the adopter enabled and which risks were accepted.

## 5. Operational fit

| Check | Result | Notes |
| --- | --- | --- |
| Chosen persistence backend | `[memory / SQLite / Postgres]` | |
| Restart behavior and state loss | `[observed]` | |
| Backup and restore drill | `[time / outcome]` | |
| Provider failure / circuit breaker rehearsal | `[outcome]` | |
| Observability: `/v1/metrics`, `/metrics`, traces, audit | `[verified]` | |
| Alert-to-runbook mapping | `[covered / gaps]` | |
| Upgrade and rollback rehearsal | `[outcome]` | |

## 6. Decision

| Decision | Owner | Rationale | Follow-up |
| --- | --- | --- | --- |
| `[Go / Go with conditions / No-go]` | `[name]` | `[evidence summary]` | `[next steps]` |

A no-go with evidence is a completed pilot. If the decision is "go with conditions", list the
conditions and their owners explicitly; production qualification remains the adopter's work
(section D of the [checklist](checklist.md)).

## 7. Caveats

- These results describe one workload on one topology at one point in time.
- Published reference numbers are reproducible baselines, not targets or guarantees.
- Unit tests and demo runs do not establish capacity, security certification or regulatory
  fitness; see [production-readiness.md](../production-readiness.md).
- Keep the raw reports with the decision record; regenerate rather than hand-edit numbers.
