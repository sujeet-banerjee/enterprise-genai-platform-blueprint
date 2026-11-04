# Enterprise Roadmap Addendum: Remaining Gaps (Fact-Check Driven)
*(Created 2026-11-02. Reconciled 2026-11-04. To be kept in sync with issues/milestones.)*

## Gap Analysis (from fact check)

1. **Data connectors & ingestion** - No first-class ingestion pipelines for enterprise sources (SharePoint, Confluence, Google Drive, S3, Azure Blob, GCS, databases, Slack). Need connectors, chunking strategies, ACL-aware ingestion, and sync/orchestration.
2. **Scalability hardening / Multi-region/DR** - G5 (GitOps at scale) and G6 (multi-region/residency/DR foundations) landed 2026-11-03: Terraform modules, `config/dr.yaml`, `config/residency.yaml`, and `docs/dr-runbook.md` exist. Remaining work is operational: cross-region persistence, automated/verified backup-restore, and rehearsed failover/chaos.
3. **Policy-as-code engine** - Guardrail framework exists (allow/redact/block) but lacks a declarative policy language (Rego/CEL), policy bundles, versioning, dry-run, and HITL approval workflows.
4. **Larger/domain-specific eval datasets** - Benchmark exists but orgs need domain-specific labeled sets, regression gates in CI, continuous eval, and eval-as-product dashboards.
5. **Simplified onboarding / golden paths** - Many configs; need opinionated "golden path" templates, CLI scaffolding, and improved UX to lower learning curve.

## Proposed Additional Workstreams (H4 / new)

| Workstream | Goal | Priority | Issues | Acceptance (high-level) |
|---|---|---|---|---|
| H - Data Connectors & Ingestion | ACL-aware ingestion framework with pluggable connectors | P0 | `#115` Ingestion framework + base connector, `#116` SharePoint/Confluence, `#117` S3/Azure/GCS | Connectors registered via config, ACL metadata preserved, incremental sync, tests >=6 |
| I - Multi-region/DR operations | Operationalize the G5/G6 foundations: cross-region persistence, backup/restore, failover, DR runbooks | P0 | `#118` Cross-region persistence strategy, `#119` Backup/restore automation + verification, `#120` DR runbook + chaos tests | RTO/RPO documented, automated backup/restore tested, failover documented and rehearsed |
| J - Policy-as-Code | Declarative policies (CEL/Rego), bundles, dry-run, HITL | P1 | `#121` Policy engine interface, `#122` CEL evaluator + bundles, `#123` HITL approval workflow | Policies in git, versioned bundles, dry-run in audit, HITL gating for sensitive actions |
| K - Eval Expansion & CI Gates | Domain eval sets, regression gates, continuous eval | P1 | `#124` Eval dataset schema + loaders, `#125` CI regression gates, `#126` Eval dashboard enhancements | PR blocks on regression thresholds, domain sets pluggable, trend tracking in metrics |
| L - Onboarding & Golden Paths | Templates, scaffolding CLI, improved docs/UX | P2 | `#127` Golden path templates, `#128` `genai init` CLI, `#129` Onboarding guide + validation | `genai init` scaffolds valid config set, golden paths pass smoke tests, docs updated |

## Workstream M: UX Polish & Adoption (new)
*(From UX fact-check: docs/analysis/ux_roadmap_fact_check.md / .pdf)*

M is the UX refinement workstream for the existing console. It is deliberately **separate from
Workstream F** (enterprise console build-out): F delivers capabilities, M makes them adoptable.

| Issue | Title | Priority | Goal |
|---|---|---|---|
| #130 | UX1: IA simplification + role-based nav | P0 | **Landed** - Reduce cognitive load, role-based landing, Get started checklist |
| #131 | UX2: Query Studio workflow polish | P0 | Templates, history, compare with last run, result tabs |
| #132 | UX3: Evaluation UX improvements | P0 | Dataset picker, GT helper, comparison matrix/charts, metric explanations |
| #133 | UX4: Traces timeline/waterfall view | P1 | Timeline by stage, span filtering, redaction-safe view |
| #134 | UX5: Governance/metrics filters & export | P1 | Time range, filters, CSV/JSON export, alerts preview |
| #135 | UX6: Admin/tenancy safety UX | P1 | Tenant warnings, confirmations, audit export, scope indicators |
| #136 | UX7: UX polish, a11y, empty states, error remediation | P2 | Tooltips, keyboard nav, empty states, clearer errors |

**Notes:** Keep HTTP-only (`ui/` never imports `app.*`/`core.*`), extend `ui/client.py`/`ui/common.py`, add AST + client tests. Link to #43, Workstream M, milestone H2. Do not fold M into F.

## Tracking Updates
- Add to `docs/enterprise-roadmap.md` as Workstreams H-L and M (post-G6/H4)
- Issues `#115-#129` (H-L) target milestone `H4`; `#130-#136` (M) target milestone `H2`
- Update `~/.config/opencode/memory.md` with this addendum reference
- Update TODOs in memory/session context to reflect these items
- Ensure Project #8 board gets new items/workstream options if needed

## Sync Checklist
- [x] Add PDF and markdown analysis to repo (fact-check)
- [x] Add UX PDF and markdown analysis to repo
- [x] Update enterprise-roadmap.md with H-L and M
- [x] Create GitHub issues `#115-#129` (H-L)
- [x] Create GitHub issues `#130-#136` (M)
- [x] Update memory.md and TODO tracking
- [ ] Add to Project #8 (workstream field H-M) - deferred for a later decision
- [x] Keep CI green and docs reconciled
