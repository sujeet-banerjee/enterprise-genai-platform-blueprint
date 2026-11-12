# UX Roadmap Fact-Check & Plan

*Updated 2026-11-11. Streamlit console at `ui/`, HTTP-only, API-driven.*

> **Status: UX1-UX11 delivered and closed.** Workstream M (UX polish) shipped in
> #130-#136, with the Evaluation dataset-runner follow-up #145, persistent
> workspace/deep links #151, background evaluation jobs #152 and Dataset Studio
> authoring #153. This document now
> (a) records the delivered state, and
> (b) tracks the remaining next UX/UI tranche, **UX12-UX15**, opened as #155-#158 and
> mapped to Project #8 Workstream M.

## Assessment: "Don't make me think"

### What works well after UX1-UX7

- **HTTP-only client**: clean separation (`ui/client.py`), testable, and aligned
  with the public API contract.
- **Information architecture**: 11 screens grouped into Start here, Experiment,
  Governance & security, Operate and Reference; role-aware landing and capability
  filtering reduce the default surface.
- **Guided onboarding**: a 14-step tour, a Get started checklist derived from real
  completed actions, filtered quick actions and in-context help.
- **Query Studio**: six task templates, bounded session history, restore/clear,
  Compare with last run, six result tabs (Answer, Documents, Trace, Guardrails,
  Resilience, Cache), and copy/share/download.
- **Evaluation**: built-in benchmark or pasted dataset execution as background jobs
  (live progress, cancel, retry/resume, partial results, 200-case cap, export),
  per-case failure isolation, case-by-metric matrix, averages, delta vs the previous
  run, evaluator dropdown and ground-truth guidance.
- **Observability**: trace timeline/waterfall, span filtering, redaction-safe view,
  OTel context, latency/cost/failure correlations.
- **Governance and security**: time-range and tenant/app/user filters, alerts
  preview, CSV/JSON export, guardrail hit-rate, audit filtering and admin safety
  confirmations.
- **Error handling**: failure taxonomy plus remediation hints instead of raw errors.
- **Contract safety**: the HTTP-only rule and UI screens are covered by AST/client
  tests, so the console cannot drift into importing backend modules.

### Remaining friction / gaps

- **Persistence and continuity**: addressed by UX8 (#151) for client-side state; reloads
  and shared links now reproduce the screen, filters, selected trace and saved views.
  Cross-device/team-shared workspaces and server-side run lists remain out of scope.
- **Long-running work**: dataset evaluation is synchronous, capped at 20 cases, and
  has no progress, cancel, resume or background-job view.
- **Dataset authoring**: cases are built-in or pasted as JSON; there is no structured
  editor, inline validation, doc authoring, save/duplicate, or round-trip export.
- **Cross-object navigation**: trace, audit, metrics and governance evidence are
  separate screens; there is no universal request-id search or trace-to-trace diff.
- **Accessibility and responsiveness**: a formal WCAG 2.2 AA audit, keyboard-first
  navigation, focus management, high-contrast mode and mobile/compact layouts are
  still missing.
- **Power-user speed**: no command palette or keyboard shortcuts to jump to screens,
  request ids, tenants or actions.
- **Role-specific journeys**: one generic tour serves architects, analysts, security
  reviewers and operators; there is no demo mode or safe reset.
- **Collaboration and feedback**: bad answers cannot be annotated, flagged, or
  promoted into an evaluation case from the console.
- **Executive/ops views**: no saved dashboard layouts, budget forecast, SLO/error
  budget, or scheduled/exportable evidence packs.

## Delivered UX workstreams (closed)

| ID | Workstream | Issue | Status | Evidence |
|---|---|---|---|---|
| UX1 | Simplify IA and onboarding | #130 | Shipped 2026-11-04 | `ui/navigation.py`, `tests/test_ux_navigation.py`, tour with checklist step |
| UX2 | Query Studio workflow polish | #131 | Shipped 2026-11-04 | `ui/query_studio.py`, `tests/test_query_studio.py` |
| UX3 | Evaluation UX improvements | #132 | Shipped 2026-11-05 | `ui/evaluation.py`, `tests/test_ui_evaluation_ux.py` |
| UX3b | Dataset execution follow-up | #145 | Shipped 2026-11-06 | `ui/evaluation.py`, `tests/test_ui_dataset_evaluation.py` |
| UX4 | Traces timeline/waterfall | #133 | Shipped 2026-11-05 | `ui/traces.py`, `tests/test_ui_traces_timeline.py` |
| UX5 | Governance/metrics filters and export | #134 | Shipped 2026-11-05 | `ui/governance.py`, `tests/test_ui_governance_filters.py` |
| UX6 | Admin/tenancy safety UX | #135 | Shipped 2026-11-05 | `ui/admin.py`, `tests/test_ui_admin_safety.py` |
| UX7 | Polish, a11y, empty states | #136 | Shipped 2026-11-05 | `ui/polish.py`, `tests/test_ui_polish.py` |
| UX8 | Persistent workspace and shareable deep links | #151 | Shipped 2026-11-07 | `ui/workspace.py`, `tests/test_ui_workspace.py`, workspace URL/sync wiring in `ui/app.py` |
| UX9 | Background evaluation jobs | #152 | Shipped 2026-11-11 | `ui/eval_jobs.py`, `tests/test_ui_eval_jobs.py`, jobs panel + auto-refresh fragment in `ui/app.py` |
| UX10 | Dataset Studio authoring | #153 | Shipped 2026-11-12 | `ui/dataset_studio.py`, `tests/test_ui_dataset_studio.py`, Studio section + source option in `ui/app.py`, saved datasets in `ui/workspace.py` |
| UX11 | Cross-link and compare operational evidence | #154 | Shipped 2026-11-12 | `ui/evidence.py`, `tests/test_ui_evidence.py`, evidence links/compare/evidence pack in `ui/app.py`, request-id deep links in `ui/workspace.py` |

The delivered scope is also recorded in `docs/ux-and-api.md` section 6 and the
delivery record in section 7.

## New UX/UI proposals (UX12-UX15 opened; UX8-UX11 delivered)

UX8 (#151), UX9 (#152), UX10 (#153) and UX11 (#154) are delivered. UX12-UX15 remain opened as #155-#158. Tracking:
label `ux`, link to umbrella #43, Project #8 **Workstream M**, milestone **H4**, and keep the
HTTP-only rule plus AST/client tests for every change.

| ID | Proposal | Priority | User problem | Key deliverables | Acceptance | Dependencies |
|---|---|---|---|---|---|---|
| UX8 (#151, **shipped**) | Persistent workspace and shareable deep links | P0 | Reloading or sharing a screen loses query history, filters, selected runs, datasets and comparisons. | URL state for screen/request id/tenant/filters; saved views and saved runs; recent-runs panel; copy-link; export/import workspace JSON. | Reload resumes the same screen and filters; a deep link reproduces a trace or governance view; no secrets in URLs; bounded saved-item cap. | Possible `/v1/runs` list or client-side persistence; URL/state contract. |
| UX9 (#152, **shipped**) | Background evaluation jobs with progress, cancel and resume | P0 | Dataset runs block the UI, stop at 20 cases, and cannot be cancelled or resumed after a failure. | Job submission, per-case progress, cancel, retry failed cases, partial results, job history, >20-case runs, export. | 100-case run stays responsive; cancel takes effect within one case; resume retries only failures; results survive refresh; failures remain isolated. | Delivered UI-side (`ui/eval_jobs.py` + console panel); a backend job/queue API remains optional follow-up. |
| UX10 (#153, **shipped**) | Dataset Studio authoring | P1 | Users must hand-write JSON; there is no way to edit cases, references, docs, tags or validation errors in the console. | Case table editor; add/remove/reorder; document editor; reference/GT field; tags; inline validation; preview; import/export; save/duplicate. | Author a 20-case/10-doc dataset without JSON; validation is inline; export round-trips; no secrets or raw config leakage. | Delivered UI-side (`ui/dataset_studio.py` + console Studio section, saved via UX8); optional dataset persistence API remains follow-up. |
| UX11 (#154, **shipped**) | Cross-link and compare operational evidence | P1 | Trace, audit, metrics and governance views are disconnected; comparing two requests is manual. | Universal request-id search/copy; trace -> audit -> metrics -> governance links; two-trace side-by-side diff; saved filter context; evidence-pack export. | Reach audit/metrics from a trace in <=2 clicks; trace diff highlights stage latency/failure/document/guardrail deltas; links preserve tenant/role scope. | Delivered UI-side (`ui/evidence.py` + console cross-links/diff/evidence pack, request-id deep links via UX8); trace search/list endpoint remains an optional backend follow-up. |
| UX12 (#155) | Command palette and accessibility hardening | P1 | Navigation is mouse-first; keyboard/screen-reader flows and WCAG 2.2 AA are not formally verified. | Ctrl/Cmd+K palette for screens, request ids, tenants and actions; shortcuts and help overlay; skip link; focus states; ARIA labels; reduced motion; contrast fixes; WCAG checklist. | All primary flows work keyboard-only; no critical/serious automated a11y findings; usable at 200% zoom; palette actions are keyboard-completable. | UX8 for deep-link targets. |
| UX13 (#156) | Responsive, compact and theme system | P2 | Wide desktop layouts break on small screens; tables and colors are inconsistent across screens. | Responsive breakpoints; compact/density mode; sticky actions; table-to-card degradation; light/dark/high-contrast themes; semantic chart colors. | 375/768/1280 px layouts have no horizontal scroll on core flows; contrast >=4.5:1; themes pass checks; tables degrade without losing actions. | UX12 accessibility tokens. |
| UX14 (#157) | Role-based guided journeys and demo mode | P2 | One generic tour serves every persona; there is no safe sample data or reset for demos and onboarding. | Tours for architect, analyst, security, ops and admin; guided sample scenario; demo mode with seeded state and reset; checklist extended to guardrails/audit/admin; doc deep links. | Each persona completes its journey in <10 minutes; reset returns a clean state; tour covers new screens; no production data is touched. | UX8/UX10; demo config/API fixtures. |
| UX15 (#158) | Collaboration and feedback capture | P2 | Bad answers cannot be annotated or promoted into evaluation data; sharing evidence is copy/paste. | Run annotations/flags; comments/notes; "promote to dataset" from a bad answer; evidence-pack export (Markdown/JSON); optional review queue; share link. | Flagging a run creates an evaluation case in one click; annotations survive reload with UX8; exports are redacted; no PII or secrets. | UX8/UX10; optional annotation store. |

### Recommended execution order

1. **UX8** - persistence and deep links unlock the rest. **Done (#151).**
2. **UX9** - removes the biggest evaluation workflow blocker. **Done (#152).**
3. **UX10** - dataset authoring turns evaluation into a repeatable workflow. **Done (#153).**
4. **UX11** - cross-object evidence reduces debugging time. **Done (#154).**
5. **UX12** - accessibility and keyboard access are enterprise adoption gates.
6. **UX13-UX15** - presentation, persona onboarding and collaboration polish.

## Implementation notes

- Stay HTTP-only (enforced by `tests/test_ui_console.py`).
- Prefer additive components in `ui/`; never import `app.*` or `core.*`.
- Put pure workflow logic in Streamlit-free helpers so it can be unit-tested.
- Extend `ui/client.py` only for documented API endpoints; if the API is
  insufficient, extend the API first.
- Add structural tests for new screens/components and keep `ui/tour.py` in sync.
- Do not put secrets, raw config values or unredacted traces in URLs, exports or
  screenshots.

## Bottom line

UX1-UX7 turned the console from a functional API demo into a role-aware, guided
workflow surface. UX8-UX11 (persistence, background jobs, dataset authoring,
cross-object evidence) are delivered, leaving UX12 as the enterprise accessibility
gate.
