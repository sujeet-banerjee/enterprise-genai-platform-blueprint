# Pilot brief template

> Copy this page into your own workspace, fill in the bracketed fields and delete what does
> not apply. The pilot is one bounded RAG workload with a fixed decision date. It is an
> evaluation, not an endorsement: see [README.md](README.md) for what this repository does
> and does not claim.

## 1. Scope

| Field | Value |
| --- | --- |
| Adopting team | `[team and owning business unit]` |
| Workload | `[one sentence: who asks what, and what a good answer enables]` |
| Users in scope | `[count and user groups; start small]` |
| Corpus | `[source, size, owner, update cadence]` |
| Out of scope | `[everything explicitly excluded, e.g. write actions, multi-region, streaming]` |
| Decision date | `[date]` |
| Decision owner | `[name/role]` |

Write down what a failed pilot looks like as well. A pilot that cannot fail is a demo.

## 2. Prerequisites

- Python 3.11+ environment, or a container runtime; see
  [deployment.md](../deployment.md) for the runtime contract.
- A validated config set: `genai init <dir> --template rag-assistant` or
  `governed-enterprise`, then `genai validate <dir>/config`.
- Model access: either local HuggingFace models (CPU is enough for the demo) or provider
  credentials supplied through secrets, never committed YAML.
- A corpus the adopter is allowed to use, in the documented `documents_path` format, or an
  enabled connector from `config/ingestion.yaml`.
- An evaluation set: queries plus expected documents or reference answers where available.
  Synthetic demo corpora are for smoke tests, not pilot evidence.
- Named roles from [README.md](README.md#roles).

## 3. Data handling and security constraints

- No customer or personal data is required to reproduce the demo. Use synthetic or
  cleared data first.
- Decide before ingesting: classification, retention, residency, deletion procedure and who
  may query the corpus. Configuration alone does not create a compliance posture.
- Redaction, PII/DLP and guardrails are configurable and ship **off** or conservative by
  default; confirm which are enabled for the pilot.
- Permission-aware retrieval (`acl.yaml`) is available but must be tested with the adopter's
  own group model; it is not an identity provider.
- Secrets come from the environment or a secret manager (`${VAR}` / `env:VAR`). Do not put
  keys in the repository or in issue reports.
- Network egress: local models avoid third-party inference. Provider-backed pilots must
  document what leaves the environment.
- Audit and trace retention are process-local by default; choose a durable backend if the
  pilot needs evidence after restart.

## 4. Deployment options

| Mode | When it fits | Notes |
| --- | --- | --- |
| Local / developer machine | First evaluation, demo | Fastest; not multi-user. |
| Docker Compose (single node) | Small internal pilot | Hardened image + healthchecks; see [deployment.md](../deployment.md). |
| Kubernetes (Helm/Kustomize) | Team pilot with probes and autoscaling | Durable shared state is adopter-validated (#206); start with one replica. |
| Air-gapped / on-prem | Restricted network | Pre-populate model and package caches. |
| Managed cloud + BYO model | Existing cloud estate | Provider terms and data residency remain the adopter's responsibility. |

## 5. Configuration and identity assumptions

- Behaviour is selected in `config/*.yaml`; there is no requirement to edit application code.
- Identity, RBAC, tenancy and attribution are **off by default**. If the pilot needs them,
  enable and test the relevant files before the evaluation window.
- `governed-enterprise` demonstrates the policy posture; its dummy providers make it fast to
  boot and are not a quality baseline.
- The runtime rebuild endpoint is a configuration experiment, not a deployment mechanism; use
  the normal promotion process for production.

## 6. Time-boxed plan

Adapt the durations; keep the sequence.

| Phase | Duration | Activities | Exit artefact |
| --- | --- | --- | --- |
| 0. Scope | 2-3 days | Fill in this brief; agree decision owner and date; pick cleared data. | Signed-off scope |
| 1. Reproduce | 2-3 days | Codespaces or local demo; `/health`, `/ready`, `/v1/query`; inspect traces and `/v1/metrics`. | Working demo note |
| 2. Baseline | 1-2 weeks | Point at the pilot corpus; build the evaluation set; record quality, latency and cost. | First [scorecard](scorecard.md) |
| 3. Harden | 1 week | Enable the guardrails, identity, tenancy and ACL entries the pilot needs; run security and isolation checks. | Security review notes |
| 4. Decide | 1-2 days | Compare against the adopter's thresholds; record go/no-go and next step. | Signed decision |

Week labels are relative to the pilot start, not calendar dates.

## 7. Success criteria (adopter-owned)

The adopter sets every threshold; this repository does not prescribe business targets.

| Dimension | Metric | Threshold | Source of measurement |
| --- | --- | --- | --- |
| Answer quality | `context_precision`, `context_recall`, MRR, nDCG | `[adopter threshold]` | [scorecard](scorecard.md), `app/eval_gate.py` |
| Answer correctness | `answer_correctness` where references exist | `[adopter threshold]` | `/v1/evaluate` or experiment run |
| Latency | p50 / p95 / p99 under stated concurrency | `[adopter threshold]` | [load harness](../benchmarks/load-methodology.md) |
| Cost | Cost per request and projected monthly cost | `[adopter budget]` | Trace `cost`, experiment summary |
| Security | Guardrail and ACL test outcomes | `[adopter requirement]` | Guardrail decisions, ACL isolation tests |
| Operations | Backup/restore, restart, observability checks | `[adopter requirement]` | Runbook rehearsal |

## 8. Exit and rollback

- Keep the pilot configuration in its own directory; reverting is a config change, not a code
  change. Record the commit and config revision used.
- Do not delete evidence before the decision is recorded: traces, scorecards and audit
  exports may be needed.
- If the pilot stops early, document why. A "no" with evidence is a successful pilot.
- Decommissioning: remove the deployment, revoke provider credentials, delete adopter data
  according to the agreed retention policy, and close the workspace.
