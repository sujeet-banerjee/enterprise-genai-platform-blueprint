# UX Roadmap Fact-Check & Plan
*(Generated 2026-11-03. Streamlit console at `ui/`, HTTP-only, API-driven.)*

## Assessment: "Don't make me think"

### What works well
- **HTTP-only client**: Clean separation (`ui/client.py`), testable, matches backend API contract.
- **Information architecture**: Screens cover Overview/Health, Query Studio, Compare (what-if), Evaluation, Governance & Cost, Guardrails, Audit, Access/RBAC, Admin, Traces, Settings (read-only).
- **Guided tour + help**: `ui/tour.py` helps first-time users discover features.
- **API-first introspection**: Settings pulls from real endpoints; redaction respected.
- **Failure taxonomy**: Errors surfaced with failure types and tags.
- **Feature parity**: Guardrails/Audit/Access/Admin added to match shipped backend capabilities.

### Friction / gaps
- **Cognitive load**: 11 screens; no role-based defaults, no progressive disclosure.
- **Discoverability**: No guided workflows ("run query → see trace → check governance/cost/guardrails").
- **Query Studio**: Lacks templates, history, "compare with last run", inline hints for tenancy/ACL/guardrails/resilience/cache.
- **Evaluation**: Needs dataset browser, better GT guidance, run comparison matrix/charts, metric explanations.
- **Governance & Cost**: Has Prometheus/raw + breakdown but no time range/filtering/CSV export/alerts preview.
- **Traces**: Dense JSON; needs timeline/waterfall, span filtering, copy/share, link to metrics.
- **Admin/Tenancy**: Useful but needs confirmations/scope warnings and safer defaults.
- **Error handling**: 503/401 need clearer remediation steps and links to docs.
- **Accessibility/responsiveness**: Streamlit constraints; missing keyboard shortcuts, empty states, better tooltips.
- **Persistence**: No saved views/bookmarks/favorites or recent runs across sessions.

## Proposed UX Workstreams

| ID | Workstream | Priority | Goal | Key Deliverables | Acceptance |
|---|---|---|---|---|---|
| UX1 | Simplify IA & onboarding | P0 | Reduce cognitive load, role-based defaults | Collapsible nav/groups, role-based landing, "Get started" checklist, quick actions | New users complete first query in <2 min; reduced clicks to core flows |
| UX2 | Query Studio workflow polish | P0 | Make "don't make me think" real | Templates, local history, "compare with last run", result tabs (Answer/Documents/Trace/Guardrails/Resilience/Cache), copy/share | Common flow guided; guardrail/resilience/cache visible inline |
| UX3 | Evaluation UX improvements | P0 | Make eval approachable | Dataset picker (benchmark/local), GT helper, comparison matrix/charts, metric tooltips/explain, run links to traces | Non-expert can run eval + compare; ground-truth guidance clear |
| UX4 | Traces timeline/waterfall | P1 | Debuggability | Timeline/waterfall by stage, span filtering, redaction-safe view, link to metrics/governance, shareable trace view | Time-to-insight improved; stages/latency/cost visible at a glance |
| UX5 | Governance/metrics filters & export | P1 | FinOps/ops readiness | Time range, filters (tenant/app/user), CSV/JSON export, alerts preview, guardrail hit-rate focus | Exportable reports; SRE/FinOps can answer spend/cost questions |
| UX6 | Admin/tenancy safety UX | P1 | Prevent mistakes | Tenant switcher with context/warnings, confirmations, audit export, policy preview, scope indicators | Safer multi-tenant ops; mistakes harder to make |
| UX7 | Polish, a11y, empty states | P2 | Professional UX | Remediation on errors, empty states, tooltips, keyboard nav, theme considerations, loading states | Better error recovery; consistent UX across screens |

## Suggested GitHub Issues
- #130 UX1: IA simplification + role-based nav
- #131 UX2: Query Studio workflow polish (templates/history/compare)
- #132 UX3: Evaluation UX improvements (dataset/GT/comparison/charts)
- #133 UX4: Traces timeline/waterfall view
- #134 UX5: Governance/metrics filters, time range, export
- #135 UX6: Admin/tenancy safety UX + confirmations
- #136 UX7: UX polish, a11y, empty states, error remediation

All issues: label `ux`, link to umbrella #43, add to Project #8 with **Workstream M** (UX polish),
milestone **H2**, and keep the HTTP-only rule with AST + client tests per change.

Workstream **M** is deliberately separate from **F**: F builds out the enterprise console;
M makes the existing console adoptable (IA, workflows, trace/waterfall, filters, a11y).

## Delivery Status
- **#130 UX1 - shipped (2026-11-04):** grouped sidebar navigation, role/capability-aware
  landing, role-filtered screens with a **Show all screens** override, Quick actions, and a
  five-step **Get started** checklist derived from completed actions. The pure contract lives
  in `ui/navigation.py` and is covered by `tests/test_ux_navigation.py`; the tour gained a
  checklist step (13 total).
- **#131 UX2 - shipped (2026-11-04):** six task templates, a bounded session history with
  restore/clear, a **Compare with last run** delta table (latency, cost, docs, cache,
  guardrail decisions/blocks, answer), six result tabs (Answer/Documents/Trace/Guardrails/
  Resilience/Cache), and a copy/share + download Markdown export. The pure contract lives in
  `ui/query_studio.py` and is covered by `tests/test_query_studio.py`.
- #132-#136 remain open.

## Implementation Notes
- Stay HTTP-only (enforced by `tests/test_ui_console.py`).
- Prefer additive components in `ui/` (no `app.*`/`core.*` imports).
- Reuse `ui/client.py`, `ui/common.py`; extend schemas only if API changes needed.
- Add structural tests for new screens/components.
- Keep tour in sync (`ui/tour.py`).

## Bottom Line
The console is functional and API-aligned. With focused polish (IA simplification, guided workflows, better observability views, safer admin UX), it becomes significantly more intuitive for enterprise architects and speeds up adoption of the platform's evaluation/governance/observability capabilities.
