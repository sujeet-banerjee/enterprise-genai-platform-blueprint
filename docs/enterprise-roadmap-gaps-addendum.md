# Enterprise Roadmap Addendum: Remaining Gaps (Fact-Check Driven)
*(Created 2026-11-02. To be kept in sync with issues/milestones.)*

## Gap Analysis (from fact check)

1. **Data connectors & ingestion** - No first-class ingestion pipelines for enterprise sources (SharePoint, Confluence, Google Drive, S3, Azure Blob, GCS, databases, Slack). Need connectors, chunking strategies, ACL-aware ingestion, and sync/orchestration.
2. **Scalability hardening / Multi-region/DR** - G5/G6 planned but not implemented. Need active-active or warm-standby, cross-region persistence, backup/restore automation, RTO/RPO targets, and failover runbooks.
3. **Policy-as-code engine** - Guardrail framework exists (allow/redact/block) but lacks a declarative policy language (Rego/CEL), policy bundles, versioning, dry-run, and HITL approval workflows.
4. **Larger/domain-specific eval datasets** - Benchmark exists but orgs need domain-specific labeled sets, regression gates in CI, continuous eval, and eval-as-product dashboards.
5. **Simplified onboarding / golden paths** - Many configs; need opinionated "golden path" templates, CLI scaffolding, and improved UX to lower learning curve.

## Proposed Additional Workstreams (H4 / new)

| Workstream | Goal | Priority | Suggested Issues | Acceptance (high-level) |
|---|---|---|---|---|
| H - Data Connectors & Ingestion | ACL-aware ingestion framework with pluggable connectors | P0 | `#114` Ingestion framework + base connector, `#115` SharePoint/Confluence, `#116` S3/Azure/GCS | Connectors registered via config, ACL metadata preserved, incremental sync, tests >=6 |
| I - Multi-region/DR (G5/G6 execution) | Cross-region persistence, backup/restore, failover, DR runbooks | P0 | `#117` Cross-region persistence strategy, `#118` Backup/restore automation + verification, `#119` DR runbook + chaos tests | RTO/RPO documented, automated backup/restore tested, failover documented and rehearsed |
| J - Policy-as-Code | Declarative policies (CEL/Rego), bundles, dry-run, HITL | P1 | `#120` Policy engine interface, `#121` CEL evaluator + bundles, `#122` HITL approval workflow | Policies in git, versioned bundles, dry-run in audit, HITL gating for sensitive actions |
| K - Eval Expansion & CI Gates | Domain eval sets, regression gates, continuous eval | P1 | `#123` Eval dataset schema + loaders, `#124` CI regression gates, `#125` Eval dashboard enhancements | PR blocks on regression thresholds, domain sets pluggable, trend tracking in metrics |
| L - Onboarding & Golden Paths | Templates, scaffolding CLI, improved docs/UX | P2 | `#126` Golden path templates, `#127` `genai init` CLI, `#128` Onboarding guide + validation | `genai init` scaffolds valid config set, golden paths pass smoke tests, docs updated |

## Workstream M: UX Polish & Adoption (new)
*(From UX fact-check: docs/analysis/ux_roadmap_fact_check.md / .pdf)*

| Issue | Title | Priority | Goal |
|---|---|---|---|
| #129 | UX1: IA simplification + role-based nav | P0 | Reduce cognitive load, role-based landing, Get started checklist |
| #130 | UX2: Query Studio workflow polish | P0 | Templates, history, compare with last run, result tabs |
| #131 | UX3: Evaluation UX improvements | P0 | Dataset picker, GT helper, comparison matrix/charts, metric explanations |
| #132 | UX4: Traces timeline/waterfall view | P1 | Timeline by stage, span filtering, redaction-safe view |
| #133 | UX5: Governance/metrics filters & export | P1 | Time range, filters, CSV/JSON export, alerts preview |
| #134 | UX6: Admin/tenancy safety UX | P1 | Tenant warnings, confirmations, audit export, scope indicators |
| #135 | UX7: UX polish, a11y, empty states, error remediation | P2 | Tooltips, keyboard nav, empty states, clearer errors |

**Notes:** Keep HTTP-only (`ui/` never imports `app.*`/`core.*`), extend `ui/client.py`/`ui/common.py`, add AST + client tests. Link to #43, Workstream F (UI/UX), H2/H3.

## Tracking Updates
- Add to `docs/enterprise-roadmap.md` as Workstreams H-L and M (post-G6/H4)
- Create issues #114-#128 (H-L) and #129-#135 (M) with labels `roadmap`, appropriate workstream, and milestones `H4`/`H2-H3`
- Update `~/.config/opencode/memory.md` with this addendum reference
- Update TODOs in memory/session context to reflect these items
- Ensure Project #8 board gets new items/workstream options if needed

## Sync Checklist
- [x] Add PDF and markdown analysis to repo (fact-check)
- [x] Add UX PDF and markdown analysis to repo
- [x] Update enterprise-roadmap.md with H-L and M
- [ ] Create GitHub issues #114-#128
- [ ] Create GitHub issues #129-#135
- [ ] Update memory.md and TODO tracking
- [ ] Add to Project #8 (if possible) with workstream field
- [ ] Keep CI green and docs reconciled
