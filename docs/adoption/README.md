# Adoption and pilot kit (#204)

> **What this is:** a practical path for a platform engineering team to decide whether this
> reference implementation is worth evaluating for one bounded RAG workload.
>
> **What this is not:** a production certification, a support contract, an SLA, a customer
> reference, or evidence of commercial adoption. Those are not offered unless separately
> established in writing.

This page assembles the existing evidence; it does not repeat it. Start here, then follow the
links. Canonical positioning and maturity language live in
[positioning.md](../positioning.md); per-capability evidence lives in
[capability-status.md](../capability-status.md).

## Who this is for

- A platform or AI engineering team evaluating build-vs-buy for a governed RAG service.
- An architect who needs to see the seams (models, retrieval, evaluation, guardrails,
  identity, observability) rather than a vendor demo.
- A security or operations reviewer who needs to know what is implemented versus what the
  adopter must validate.

It assumes Python and container familiarity. It does not assume prior knowledge of this
repository.

## Reproduce something real first

Run the zero-download demo, then the recommended golden path. Both are bounded and reversible;
neither needs customer data.

| Path | Command | What it demonstrates |
| --- | --- | --- |
| Codespaces (no local install) | Open **Code -> Codespaces -> Create codespace on `main`**; see [Codespaces guide](../../deployment/codespace/README.md) | API on `:8000`, console on `:8501`, `/health`, `/ready`, `/v1/query` |
| Local deterministic demo | `genai init my-app --template local-demo && genai validate my-app/config && GENAI_CONFIG_DIR="$PWD/my-app/config" uvicorn app.main:app` | Composition root, registries, pipeline stages with dummy providers, no model downloads |
| Local RAG path | `genai init my-app && genai validate my-app/config && GENAI_CONFIG_DIR="$PWD/my-app/config" uvicorn app.main:app` | Local Qwen2.5-0.5B + MiniLM, FAISS, reranking, semantic evaluation, standard guardrails |
| Reference numbers | `python -m app.benchmark_report --quick --config-dir deployment/smoke/config --out /tmp/showcase.json --check` | Reproducible quality/cost/latency report and provenance |

The first-run local path downloads small open models. Use `local-demo` for an offline smoke
test. Follow [onboarding.md](../onboarding.md) for the guided walkthrough and
[deployment/templates/README.md](../../deployment/templates/README.md) for the three golden
paths.

## Evidence index

| Question | Read |
| --- | --- |
| What does the system look like end to end? | [architecture-diagram.md](../architecture-diagram.md), [architecture.md](../architecture.md) |
| What is actually implemented, and how well tested? | [capability-status.md](../capability-status.md) |
| What is missing before production? | [production-readiness.md](../production-readiness.md) |
| How does it compare with alternatives? | [comparison.md](../comparison.md) |
| How do I deploy it? | [deployment.md](../deployment.md) |
| How were the published numbers produced? | [benchmarks/README.md](../benchmarks/README.md), [methodology](../benchmarks/methodology.md), [load methodology](../benchmarks/load-methodology.md) |
| How is the project presented publicly? | [showcase/linkedin.md](../showcase/linkedin.md) |
| How do I contribute or raise a defect? | [CONTRIBUTING.md](../../CONTRIBUTING.md), [engineering-lifecycle.md](../engineering-lifecycle.md) |

The end-to-end demo walkthrough (#189) is still pending; use the Codespaces guide and the
quickstart until it lands.

## The bounded pilot

A pilot is one workload, one dataset the adopter owns, one deployment topology and a fixed
decision date. The kit has three parts:

1. [pilot-brief.md](pilot-brief.md) - scope, prerequisites, security constraints, roles,
   time-boxed steps and exit/rollback plan.
2. [checklist.md](checklist.md) - separates demo prerequisites, technical evaluation, security
   review, production qualification and adopter-owned responsibilities.
3. [scorecard.md](scorecard.md) - measurable quality, latency, cost, security and operational
   fields the adopter fills in; no pre-filled success numbers.

## Roles

| Role | Owns |
| --- | --- |
| Platform engineer | Deployment, configuration, model/provider choice, observability. |
| Data owner | Corpus, access rules, evaluation set, retention constraints. |
| Security reviewer | Identity, secrets, PII/DLP, injection controls, audit evidence. |
| Product owner | Pilot scope, success thresholds, go/no-go decision. |

One person can hold several roles in a small team; the point is that each decision has an
owner.

## Known limitations and escalation

- **Maturity:** a reference implementation. Implemented is not production-validated; see
  [production-readiness.md](../production-readiness.md).
- **Support:** no SLA, on-call rotation, indemnity or commercial support is offered.
- **Certification:** no independent security certification or penetration test is claimed
  (tracked by #205).
- **References:** there are no customer references or adoption claims.
- **Scale:** default persistence and caches are process-local; validate multi-replica
  behaviour before relying on it (tracked by #206).
- **Demo data:** the bundled corpora are synthetic; use your own evaluation data for a pilot.

Escalate through a GitHub issue using the templates in [CONTRIBUTING.md](../../CONTRIBUTING.md).
State the commit, config set, deployment mode and reproduction steps. Do not include secrets,
customer data or personal data in issues.

## Related

- [Production-readiness assessment](../production-readiness.md) - operational gaps by risk.
- [Capability status](../capability-status.md) - implemented versus partial versus planned.
- [Deployment playbook](../deployment.md) - runtime contract and operating modes.
- [Onboarding guide](../onboarding.md) - first edits after the demo.
- [Comparison](../comparison.md) - where alternatives are stronger.
