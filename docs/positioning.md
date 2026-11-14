# Repository identity and positioning

> **Canonical source of truth** for the project name, tagline, GitHub metadata and
> maturity vocabulary. Update this file and the surfaces below together; the guards in
> `tests/test_repo_identity.py` fail when they drift. Last reviewed **2026-11-14** (#187).

## Canonical fields

- **Name:** `Enterprise GenAI Platform Blueprint`
- **One-liner:** A modular, vendor-neutral, self-hostable reference implementation for enterprise GenAI and RAG workloads.
- **GitHub About:** Modular, vendor-neutral, self-hostable reference implementation for enterprise GenAI/RAG: config-driven models and retrieval, evaluation, guardrails, governance, observability and operations. MIT licensed; a blueprint to extend, not a production-certified product.
- **Topics:** `genai`, `rag`, `llm`, `ai-platform`, `reference-architecture`, `evaluation`, `guardrails`, `governance`, `observability`, `opentelemetry`, `prometheus`, `fastapi`, `python`, `self-hosted`

## Surfaces that must stay consistent

| Surface | Where | Owner |
| --- | --- | --- |
| Repository title | `README.md` H1, `docs/architecture.md` H1 | #187 |
| Opening positioning and maturity boundaries | `README.md` first screen | #187 |
| GitHub About and topics | repository settings | #187 |
| Comparison status banner | `docs/comparison.md` | #187 / #199 |
| Capability status language | `docs/capability-status.md` (#191) | #191 |
| Production-readiness language | `docs/production-readiness.md` (#192) | #192 |
| Showcase and LinkedIn copy | `docs/showcase/` (#193) | #193 |

## Maturity vocabulary

Use these terms consistently across README, roadmap, architecture and showcase copy:

- **reference implementation** or **blueprint** — a codebase to fork, extend and operate,
  not a hosted product or a commercial offering.
- **self-hostable** — the operator runs the API, console, stores and observability stack
  inside their own environment.
- **configuration-driven** — behaviour is selected among registered interfaces in
  `config/*.yaml`; a new vendor still requires an implementation plus registration.
- **implemented / tested / partial / planned / external-optional** — the status
  vocabulary owned by the capability-status audit (#191). Do not promote a capability's
  status because an interface or stub exists.

Avoid unsupported claims: `production-ready`, `production-certified`, `enterprise-grade`,
`battle-tested`, `proven at scale`, `customer deployment`, `SLA-backed`, or any wording
that implies managed-service scale or independent certification.

## What this repository is

- A reference implementation of a governed RAG/agent platform you can run yourself.
- Config-driven plumbing for retrieval, generation, evaluation, guardrails, cost control,
  identity, observability, audit and deployment.
- A test-backed codebase: interfaces, registries, API contracts, benchmarks and CI gates.
- A blueprint for AI platform engineers to fork, extend with vendor integrations and own
  in their own infrastructure.

## What this repository is not

- A production-certified product, managed service or drop-in replacement for a managed AI
  platform.
- A model provider, connector catalogue or zero-code plugin marketplace.
- Evidence of customer adoption, commercial scale or independent security certification.
- A finished platform: partial and planned capabilities are tracked in #191/#192 and the
  roadmap issues, not implied by the opening copy.

## Related documents

- [Architecture](architecture.md) — layers, contracts, registries and runtime composition.
- [Comparison with alternatives](comparison.md) — where this fits and where alternatives
  are stronger.
- [Enterprise roadmap](enterprise-roadmap.md) — north star, workstreams and horizons.
- [Deployment playbook](deployment.md) — operating modes and hard boundaries.
- [Benchmarks](benchmarks/README.md) — reproducible reference numbers, not vendor claims.
