# Enterprise Roadmap Addendum: Remaining Gaps (Fact-Check Driven)
*(Created 2026-11-02. Reconciled 2026-11-04. To be kept in sync with issues/milestones.)*

## Gap Analysis (from fact check)

1. **Data connectors & ingestion** - No first-class ingestion pipelines for enterprise sources (SharePoint, Confluence, Google Drive, S3, Azure Blob, GCS, databases, Slack). Need connectors, chunking strategies, ACL-aware ingestion, and sync/orchestration.
2. **Scalability hardening / Multi-region/DR** - G5 (GitOps at scale) and G6 (multi-region/residency/DR foundations) landed 2026-11-03: Terraform modules, `config/dr.yaml`, `config/residency.yaml`, and `docs/dr-runbook.md` exist. Remaining work is operational: cross-region persistence, automated/verified backup-restore, and rehearsed failover/chaos.
3. **Policy-as-code engine** - Guardrail framework exists (allow/redact/block) but lacks a declarative policy language (Rego/CEL), policy bundles, versioning, dry-run, and HITL approval workflows.
4. **Larger/domain-specific eval datasets** - Benchmark exists but orgs need domain-specific labeled sets, regression gates in CI, continuous eval, and eval-as-product dashboards.
5. **Simplified onboarding / golden paths** - Many configs; need opinionated "golden path" templates, CLI scaffolding, and improved UX to lower learning curve.

## Additional Workstreams & Delivery (H4 / new)

| Workstream | Goal | Priority | Issues | Acceptance (high-level) |
|---|---|---|---|---|
| H - Data Connectors & Ingestion | ACL-aware ingestion framework with pluggable connectors | P0 | `#115` Ingestion framework + base connector, `#116` SharePoint/Confluence, `#117` S3/Azure/GCS | Connectors registered via config, ACL metadata preserved, incremental sync, tests >=6 |
| I - Multi-region/DR operations | Operationalize the G5/G6 foundations: cross-region persistence, backup/restore, failover, DR runbooks | P0 | `#118` Cross-region persistence strategy, `#119` Backup/restore automation + verification, `#120` DR runbook + chaos tests | RTO/RPO documented, automated backup/restore tested, failover documented and rehearsed |
| J - Policy-as-Code | Declarative policies (CEL/Rego), bundles, dry-run, HITL | P1 | `#121` Policy engine interface, `#122` CEL evaluator + bundles, `#123` HITL approval workflow | Policies in git, versioned bundles, dry-run in audit, HITL gating for sensitive actions |
| K - Eval Expansion & CI Gates | Domain eval sets, regression gates, continuous eval | P1 | `#124` Eval dataset schema + loaders, `#125` CI regression gates, `#126` Eval dashboard enhancements | PR blocks on regression thresholds, domain sets pluggable, trend tracking in metrics |
| L - Onboarding & Golden Paths | Templates, scaffolding CLI, improved docs/UX | P2 | `#127` **Landed** — golden path templates (`local-demo`, `rag-assistant`, `governed-enterprise`) in `deployment/templates/`, `#128` **Landed** — `genai init`/`templates`/`validate` CLI (`app/cli.py`, console script), `#129` **Landed** — onboarding guide (`docs/onboarding.md`) + validation | `genai init` scaffolds valid config set, golden paths pass smoke tests, docs updated |

**H delivery status (landed 2026-11-05):** `#115` framework + base connector (`a17a5cf`,
PR #140), `#116` SharePoint/Confluence (`abcd4a9`), `#117` S3/Azure Blob/GCS (`9bcd911`).
`config/ingestion.yaml` ships disabled by default; connectors are registry-selected and
preserve ACL metadata for permission-aware retrieval.

**I/J/K/L delivery status:** I `#118-#120` landed 2026-11-06; J `#121` (PR #150), `#122`
(PR #161) and `#123` (PR #166) landed 2026-11-08; K `#124` (PR #167), `#125` (PR #168) and
`#126` (PR #171) landed 2026-11-08. L `#127` **landed** — `deployment/templates/` ships
`local-demo`, `rag-assistant` and `governed-enterprise`, every file schema-validated in CI and
covered by boot smoke tests. L `#128` **landed** — the `genai` CLI (`genai init`,
`genai templates`, `genai validate`) scaffolds a project from a template, copies the sample
corpus, validates the result and is exercised in CI. L `#129` **landed** —
`docs/onboarding.md` (ten-minute path, golden path choice, config map, first edits,
validation, troubleshooting) plus structural/flow tests. **Workstream L is complete.**

## Workstream M: UX Polish & Adoption (new)
*(From UX fact-check: docs/analysis/ux_roadmap_fact_check.md / .pdf)*

M is the UX refinement workstream for the existing console. It is deliberately **separate from
Workstream F** (enterprise console build-out): F delivers capabilities, M makes them adoptable.

| Issue | Title | Priority | Goal |
|---|---|---|---|
| #130 | UX1: IA simplification + role-based nav | P0 | **Landed** - Reduce cognitive load, role-based landing, Get started checklist |
| #131 | UX2: Query Studio workflow polish | P0 | **Landed** - Templates, bounded history + restore, compare with last run, six result tabs, copy/share Markdown |
| #132 | UX3: Evaluation UX improvements | P0 | **Landed** - Dataset picker/summary, GT helper, comparison matrix, metric explanations |
| #145 | UX3 follow-up: execute evaluation datasets | P0 | **Landed** - Per-case query + evaluate, failure isolation, case-by-metric matrix, average-score chart, delta vs previous run |
| #133 | UX4: Traces timeline/waterfall view | P1 | **Landed** - Timeline by stage, span list, redaction-safe view |
| #134 | UX5: Governance/metrics filters & export | P1 | **Landed** - Time range, filters, CSV/JSON export, alerts preview |
| #135 | UX6: Admin/tenancy safety UX | P1 | **Landed** - Tenant warnings, confirmations, audit export, scope indicators |
| #136 | UX7: UX polish, a11y, empty states, error remediation | P2 | **Landed** - Tooltips, accessible labels, empty states, clearer errors |
| #151 | UX8: Persistent workspace and shareable deep links | P0 | **Landed** - URL-backed workspace (`ws` blob + direct keys), saved views/runs, redacted export/import, scope-safe apply |

### Remaining UX tranche (opened 2026-11-07)

| Issue | Title | Priority | Goal |
|---|---|---|---|
| #152 | UX9: Background evaluation jobs | P0 | **Landed** - Worker-thread dataset jobs (<=200 cases) with live progress, cancel between cases, retry failed/resume unfinished, partial results, bounded history, JSON/CSV export, deep-linkable focus |
| #153 | UX10: Dataset Studio authoring | P1 | **Landed** - Structured case/document editors with add/remove/reorder, reference/GT and tags, inline validation (invalid rows kept), preview, benchmark-shaped or bare-list import, round-trip export with redaction, save/duplicate/delete persisted via UX8 |
| #154 | UX11: Cross-link and compare operational evidence | P1 | **Landed** - Request-id copy/validation, trace/audit/metrics/governance cross-links, two-request diff (latency/failures/docs/guardrails/resilience/cost), client-side audit request filter, redacted JSON/Markdown evidence pack, deep links |
| #155 | UX12: Command palette and WCAG 2.2 AA hardening | P1 | Keyboard-first navigation, shortcuts, focus/ARIA, contrast and 200% zoom |
| #156 | UX13: Responsive, compact and theme system | P2 | Breakpoints, density, table-to-card, light/dark/high-contrast themes |
| #157 | UX14: Role-based journeys and demo mode | P2 | Persona tours, seeded demo data, reset and expanded onboarding checklist |
| #158 | UX15: Collaboration and feedback capture | P2 | Annotations/flags, promote-to-dataset, evidence-pack export, optional review queue |
| #163 | UX16: HITL Approvals review & decision console | P0 | **Delivered** - HTTP-only Approvals/HITL Review screen consuming #123 (`GET/POST /v1/approvals*`); queue/detail/approve-reject, RBAC/tenant-aware, redaction-safe; depends on #123 backend; owner `ui/` bot-win per split |
| #164 | UX17: HITL Approvals queue operations, SLA & evidence export | P1 | **Delivered** - client-side filters/search/sort/pagination, SLA/aging thresholds, safe metadata-only JSON/CSV export, sequential bulk approve/reject with explicit confirmation + partial-failure reporting; UI-only until backend #175 adds server-side pagination/filtering/tenant scope |

**Notes:** Keep HTTP-only (`ui/` never imports `app.*`/`core.*`), extend `ui/client.py`/`ui/common.py`, add AST + client tests. Link to #43, Workstream M. Delivered M work (#130-#136, #145) targeted milestone H2; #151 (UX8), #152 (UX9), #153 (UX10), #154 (UX11), #163 (UX16) and #164 (UX17) have since landed against milestone H4, and the remaining tranche (#155-#158) targets H4. #163/#164 close the roadmap B6 HITL queue/UI gap (backend #121-#123); server-side queue scale-out is #175. Do not fold M into F.

## Tracking Updates
- Add to `docs/enterprise-roadmap.md` as Workstreams H-L and M (post-G6/H4)
- Issues `#115-#129` (H-L) target milestone `H4`; `#130-#136` (M) target milestone `H2`; `#151-#158` (M) target milestone `H4`
- Update `~/.config/opencode/memory.md` with this addendum reference
- Update TODOs in memory/session context to reflect these items
- Ensure Project #8 board gets new items/workstream options if needed

## Sync Checklist
- [x] Add PDF and markdown analysis to repo (fact-check)
- [x] Add UX PDF and markdown analysis to repo
- [x] Update enterprise-roadmap.md with H-L and M
- [x] Create GitHub issues `#115-#129` (H-L)
- [x] Create GitHub issues `#130-#136` (M)
- [x] Create GitHub issues `#151-#158` (next UX tranche, 2026-11-07)
- [x] Update memory.md and TODO tracking
- [x] Add to Project #8 (Workstream field H-M; options + items assigned 2026-11-04; #151-#158 mapped to M)
- [x] Keep CI green and docs reconciled
