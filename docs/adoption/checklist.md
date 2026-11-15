# Adopter checklist

> Use this alongside the [pilot brief](pilot-brief.md). It deliberately separates what the
> repository demonstrates from what the adopter must validate. A checked repository item is
> evidence, not an approval. Start at the [adoption landing page](README.md).

Legend: **Repo evidence** means a link in this repository; **Adopter-owned** means the
adopting team must produce the evidence in its own environment.

## A. Demo prerequisites

- [ ] Can run one path: Codespaces, `local-demo`, or the local RAG template.
- [ ] `/health` and `/ready` return healthy; `/ready` shows the expected config revision.
- [ ] One `/v1/query` returns an answer with retrieved documents and a trace.
- [ ] Console (optional) runs as an HTTP-only client.
- [ ] No customer or personal data was used for the demo.
- [ ] Models: local cache is populated, or provider credentials are provided via secrets.

Evidence: [onboarding.md](../onboarding.md), [Codespaces guide](../../deployment/codespace/README.md),
[architecture-diagram.md](../architecture-diagram.md).

- [ ] **Adopter-owned:** a note recording which path was run, the commit, and the config set.

## B. Technical evaluation

- [ ] The pilot corpus is loaded from the adopter's source, not the bundled sample.
- [ ] An evaluation set (queries plus expected documents or references) exists and is owned.
- [ ] Quality metrics are recorded: `context_precision`, `context_recall`, MRR, nDCG.
- [ ] Ground-truth scoring is used where references exist (`answer_correctness`).
- [ ] Retrieval choices were evaluated, for example retriever, `top_k`, reranking, chunking.
- [ ] Latency is measured under a stated concurrency with the [load harness](../../benchmarks/load/run_load.py).
- [ ] Cost per request and a monthly projection are recorded.
- [ ] Regression thresholds are configured for the pilot dataset.

Evidence: [capability-status.md](../capability-status.md),
[benchmarks/README.md](../benchmarks/README.md), [methodology](../benchmarks/methodology.md).

- [ ] **Adopter-owned:** a completed [scorecard](scorecard.md) with thresholds and results.

## C. Security review

- [ ] Authentication and authorization posture is decided: default-off, API key, or the OIDC
      resolver; RBAC roles match the pilot's users.
- [ ] Secrets are supplied by environment or a secret manager and are absent from YAML, logs
      and issue reports.
- [ ] Prompt-injection and jailbreak behavior is tested against the chosen guardrail profile.
- [ ] PII/DLP behavior is tested on representative, cleared samples.
- [ ] Permission-aware retrieval is tested with the adopter's group model.
- [ ] Input redaction and trace redaction are confirmed against the observability config.
- [ ] Audit events are verified, and their retention location is acceptable.
- [ ] Data classification, residency and deletion procedures are documented.

Evidence: [deployment.md](../deployment.md) (runtime contract and secrets),
[production-readiness.md](../production-readiness.md) (security gaps),
[capability-status.md](../capability-status.md) (guardrails, identity, audit).

- [ ] **Adopter-owned:** security sign-off, or a list of accepted risks. Independent
      penetration testing is not provided (tracked by #205).

## D. Production qualification (adopter-owned)

Raising the pilot to production is the adopter's decision and validation work.

- [ ] Durable shared persistence is selected and tested (`config/persistence.yaml`).
- [ ] Multi-replica behavior is validated if more than one replica will run (tracked by #206).
- [ ] Backup and restore drill is executed and timed.
- [ ] Failure modes are rehearsed: provider timeout, model unavailable, circuit breaker open.
- [ ] Load and soak tests match the expected traffic envelope.
- [ ] SLOs and alert-to-runbook mapping are defined.
- [ ] Upgrade, rollback and config promotion are rehearsed.
- [ ] Security findings from section C are closed or formally accepted.

Evidence: [production-readiness.md](../production-readiness.md), [deployment.md](../deployment.md),
[dr-runbook.md](../dr-runbook.md).

## E. Adopter-owned responsibilities

- [ ] Own the corpus, its access rules and its lifecycle.
- [ ] Own identity provider configuration, keys and rotation.
- [ ] Own the model/provider contracts, data processing terms and residency.
- [ ] Own monitoring, on-call and incident response.
- [ ] Own the decision to run this in production and any certification the business needs.
- [ ] Keep configuration under version control and review changes.

## Sign-off

| Checkpoint | Owner | Evidence | Date |
| --- | --- | --- | --- |
| Demo reproduced | `[owner]` | `[link/note]` | `[date]` |
| Technical evaluation | `[owner]` | `[scorecard]` | `[date]` |
| Security review | `[owner]` | `[sign-off]` | `[date]` |
| Go/no-go decision | `[owner]` | `[decision record]` | `[date]` |
