# Enterprise UI Look & Feel Review & Uplift Plan

**Status:** Proposed (review artifact)  
**Date:** 2026-11-16  
**Scope:** Streamlit console (`ui/`) — visual design, information hierarchy, and perceived enterprise polish. Functional capability, accessibility baseline (UX12), and HTTP-only API contract are out of scope except where they affect presentation.

## 1. Review basis and verdict

**Basis (code/structure review, not a rendered pixel audit):** `ui/app.py` (12 registered screens, ~3.7k LOC), `ui/theme.py`, `ui/a11y.py`, `ui/common.py`, `ui/polish.py`, `ui/navigation.py`, `docs/layout-and-theme.md`, `docs/accessibility.md`.

| Dimension | Current state | Enterprise expectation | Verdict |
| --- | --- | --- | --- |
| Capability & workflows | Strong (role-aware nav, workspace/share, demo mode, approvals/audit/trace flows) | Complete, coherent workflows | **Good** |
| App shell & branding | Streamlit default chrome, `layout="wide"`, no branded header/logo/product identity | Recognizable product shell, restrained branding, consistent chrome | **Weak** |
| Information hierarchy | Mixed metrics/tables/expanders with frequent raw `st.json`/`st.code` payloads | Curated summaries first, drill-down details second, clear status semantics | **Weak** |
| Visual system | Tokenized colors/density/breakpoints exist but applied lightly; stock widgets dominate | Consistent spacing/typography, surfaces, badges, cards, charts used systematically | **Moderate-Weak** |
| Data visualization | Minimal (occasional dataframe/bar chart); traces/metrics/cost often raw | Timelines/waterfalls, trend/health indicators, comparative charts | **Weak** |
| States & feedback | Basic success/warn/error/info; remediation helpers exist but presentation is utilitarian | Polished empty/loading/error states, inline status, actionable guidance | **Moderate** |
| Accessibility/responsiveness baseline | Skip/focus/reduced-motion, breakpoints, Light/Dark/High-contrast, table→card helper | Maintained and extended (not regressed) | **Good baseline** |

**Overall verdict:** the console is **functionally capable but not yet enterprise-grade in look & feel**. It presents as a capable internal/admin/reference tool (Streamlit prototype polish) rather than a polished enterprise product UI. The fastest path to an enterprise impression is **P0 shell + design-system consistency** and **P1 replacing raw payloads with structured, visual summaries on key workflows**.

## 2. Design principles (target)

1. **Summary before raw:** show status, key metrics, and outcomes first; put full JSON/payloads behind “Raw/Details” expanders.
2. **Status is visual:** use consistent semantic badges/pills and colored indicators (success/warn/danger/neutral/info) mapped to `ui/theme.py` status tokens.
3. **One surface system:** cards/panels with consistent border/radius/padding (`--genai-*`) for groups; avoid ad-hoc column soup.
4. **Progressive disclosure:** default views answer “is it healthy / what happened / what do I do next?”; drill-down answers “why/exactly”.
5. **Data has shape:** timelines for traces/stages, bars/trends for latency/cost/failures/guardrail hits, comparison deltas for what-if/eval.
6. **Trust & safety cues:** clearly label demo/seeded data, redacted content, tenant/scope, and destructive/admin actions.
7. **No capability regression:** keep HTTP-only rule, existing screens/routes, workspace/share behavior, and a11y contract intact.

## 3. Prioritized uplift plan

| Priority | Goal | Outcome | Effort (rough) |
| --- | --- | --- | --- |
| **P0** | App shell & visual system | Immediate “product” impression, consistent chrome | M |
| **P1** | Key workflow presentation | Enterprise feel on the most demoed/used screens | L |
| **P2** | Remaining screens & parity | Consistent experience everywhere | M |
| **P3** | Polish, charts depth, QA & captures | Release-quality finish and repeatable verification | M |

## 4. Global / cross-cutting work

### P0 — App shell & branding
- **Branded header:** compact top banner (product name “Enterprise GenAI Platform Console”, environment/scope chip, backend health dot, tenant/role) replacing bare per-screen `st.header` as the primary identity; keep screen title as subheader. (Streamlit constraints: implement via styled container/markdown + `st.columns`; avoid fragile hacks.)
- **Sidebar polish:** tighten logo/icon treatment (text mark if no asset), consistent section spacing, active-state emphasis aligned to `--genai-accent`, quieter captions.
- **Page metadata:** `st.set_page_config(page_title=..., page_icon=...)` aligned to brand; ensure titles consistent.
- **Typography rhythm:** define heading scale/muted text/caption usage in `ui/theme.py`/CSS (already has tokens) and apply consistently (avoid random `st.write` vs `st.markdown`).

### P0 — Component patterns (reusable, pure where possible)
- **Status badge/pill:** helper rendering semantic state (ok/warn/error/blocked/pending/disabled) using `STATUS_TONES`/`status_color`.
- **KPI strip:** standardized metric row (label, value, delta/hint, status) to replace scattered `st.metric` groups.
- **Key-value panel:** labeled fields in a card/grid for config/identity/scope objects instead of raw dict dumps.
- **Section card:** consistent container pattern (title, description, body, optional actions) using `.genai-card`/surface tokens.
- **Detail drawer pattern:** “Summary” + collapsible “Raw payload (redacted)” for every place that currently emits full `st.json`.
- **Empty/error states:** route `show_error`/`error_remediation` through a structured alert block (title, failure_type/tags, request_id, hint/action) instead of plain `st.error`/`st.warning` text.

### P1 — Replace raw payloads with structured views
High-impact instances observed (non-exhaustive): `ready.data.components`, query batch/trace/resilience/obs, rebuild components, experiment launch/poll, governance spend window & failures/metrics, guardrail decisions, approval context/policy, audit events, traces raw, settings effective config & providers, access/admin payloads.
- For each: render **curated fields + table/timeline**; keep `with st.expander("Raw (redacted)"):` + `st.json(...)` as secondary.
- Normalize timestamps, durations (`*_ms`), costs (USD), counts, and booleans (yes/no badges).

### P1 — Visualization upgrades
- **Latency/cost:** stage latency bars and totals (Query Studio/Traces), spend/cost distribution where available.
- **Guardrails/governance:** hit-rate and decision breakdown charts; clear block/redact/allow legend using semantic palette.
- **Compare/Eval:** side-by-side deltas (green/red/neutral) and comparison matrix highlighting winners/regressions.
- **Traces:** waterfall/timeline view for stages (start/latency ordering) with correlation to request_id/tenant; keep raw trace as drill-down.
- Prefer built-in `st.bar_chart`/`st.line_chart`/`st.altair_chart` (no new deps) unless a dependency is already approved.

### P2 — Responsiveness & density parity
- Apply table→card degradation consistently to all dense tables (not just selected Guardrails/Governance cases).
- Verify no horizontal page scroll at 375/768/1280; ensure sticky/primary actions remain usable in compact mode.
- Tune compact density for operational screens (Approvals, Audit, Traces, Admin) without hiding actions.

### P3 — Trust, copy, and micro-polish
- Consistent banners: demo/seeded, redacted, read-only, tenant-scoped, admin/destructive confirmation.
- Action language and button hierarchy (primary/secondary/destructive) standardized.
- Loading/skeleton/progress cues for long operations (eval jobs, batch, rebuild).

## 5. Screen-by-screen plan

| Screen | Current presentation (observed) | Gaps | Planned uplift | Priority |
| --- | --- | --- | --- | --- |
| **Global shell / nav** | Sidebar expanders, quick actions, palette/help buttons, appearance/demo panels; plain headers | Default Streamlit feel, limited brand/status context | P0 branded header + scope/health chips, refined sidebar active states, consistent page intro pattern | P0 |
| **Overview / Health** (`screen_overview`) | Health/ready messages, components JSON, 4 coarse metrics, onboarding checklist | Components dumped as JSON; KPI strip minimal; no at-a-glance system status | KPI/status strip (API, config revision, tenant, model/retriever/reranker/evaluator) with badges; components as key-value cards; health timeline/readiness detail in expander; checklist as guided card | P1 |
| **Query Studio** (`screen_query_studio`) | Templates/history, batch support, answer/docs/trace/guardrails/resilience/cache tabs, markdown export, comparison | Dense tabs, raw trace/resilience JSON, limited visual diff/latency story | Prominent answer card + status badges (outcome/cache/guardrail); stage latency chart; docs as ranked cards/table with score bars; structured trace/resilience summary then raw expander; clearer batch result cards and comparison deltas | P1 |
| **Compare (what-if)** (`screen_compare`) | Controls + rebuild, components JSON, bar chart/summary, change vs previous | Raw components; comparison readability varies | Side-by-side config/component diff cards, delta table with semantic coloring, keep raw in expander; stronger “before/after” layout | P1 |
| **Evaluation** (`screen_evaluation`) | Dataset studio cases/docs/import tabs, background jobs, comparison matrix, launch/poll experiment JSON | Complex, form-heavy; experiment payloads raw; matrix dense | Sectioned cards (dataset, run, results), progress/status badges for jobs, matrix with highlights and charts, structured experiment status (id/state/metrics) before raw JSON | P2 |
| **Governance & Cost** (`screen_governance`) | Spend window JSON, metrics filters/export, alerts, KPI metrics, failures/guardrail tables+JSON, Prometheus raw | Many raw blocks; weak visual spend/risk story | Spend/cost KPI cards + trend/breakdown chart, alerts as severity banner list, failures/guardrails as charts + tables, Prometheus as advanced expander only | P1 |
| **Guardrails** (`screen_guardrails`) | Resolved chains, inspect decisions, hit-rate metrics/table/cards, decision history JSON | Effective but technical; history raw | Chain visualization (ordered edge cards), decision outcome badges, hit-rate chart, structured decision history table with expandable raw record | P1 |
| **Approvals (HITL)** (`screen_approvals`) | Queue table/filters/pagination, detail, context/policy JSON, decision flow, export | Context/policy dumped as JSON; high cognitive load | Request summary header (status/SLA/action/requester/tenant), structured context/policy key-values, evidence/correlation as linked chips, clear approve/reject confirmation state | P2 |
| **Audit** (`screen_audit`) | Filters and raw event list/table/JSON patterns | Operational but hard to scan | Timeline/list with event-type badges, actor/tenant/request correlation columns, expandable redacted detail per event, export affordance prominence | P2 |
| **Access / RBAC** (`screen_access`) | Access context and capabilities payloads | Raw/technical | Identity/tenant/role summary card, capabilities as grouped checklist/badges, policy notes in plain language | P2 |
| **Admin** (`screen_admin`) | Tenants/users tables, audit export, proposal/update flows | Powerful but dense; risk actions need stronger cues | Segmented admin sections, tenant/user cards/tables with status, explicit destructive/change confirmations and banners, recent audit as structured table | P2 |
| **Traces** (`screen_traces`) | Lookup/compare, trace views, resilience, comparison rows, evidence pack, raw trace JSON | Core debug screen but JSON-heavy | Waterfall/timeline of stages, summary card (outcome, latency, cost, guardrail, cache, request/tenant), side-by-side diff highlights, raw trace/evidence in expanders | P1 |
| **Settings (read-only)** (`screen_settings`) | Effective config JSON, providers payloads/lists | Entirely raw | Grouped config sections (models/retrieval/reranking/eval/guardrails/observability/cache) as key-value cards/tables; raw YAML/JSON as advanced expander | P2 |
| **Feedback** (`screen_feedback`, #158) | Review queue, flags/reasons/notes, promote/export (per #158 wiring) | Needs to match new visual system | Apply card/table/badge patterns, redaction/privacy cues, consistent export/share affordances | P2 |

## 6. QA checklist & target captures

**Viewports:** 375 px (compact), 768 px (tablet), 1280 px (desktop/wide). **Themes:** Light, Dark, High contrast. **Modes:** normal, demo/seeded, read-only/restricted role where applicable.

| Area | Checks | Target captures |
| --- | --- | --- |
| Shell & nav | Branded header visible, active nav state, sidebar sticky at >=1024, palette/help reachable, no clipped text | Overview @ 375/768/1280, Light/Dark |
| Status semantics | Badges/colors consistent for ok/warn/error/blocked/disabled across screens | Query (success/cache/blocked), Guardrails, Approvals |
| Raw-data discipline | Primary view structured; raw JSON only in expanders labeled “Raw/Details (redacted)” | Query trace tab, Settings, Governance, Audit |
| Tables & cards | Dense tables degrade to cards with all fields/actions; no horizontal page scroll | Guardrails, Approvals, Audit @ 375/768 |
| Charts/timelines | Latency/cost/guardrail visuals render, legends readable, high-contrast safe | Traces waterfall, Governance, Compare/Eval |
| States | Empty, loading, error (401/403/404/422/503/5xx taxonomy) show structured remediation | Overview not-ready, Query error, empty Audit/Approvals |
| Trust cues | Demo banner, redaction labels, tenant/scope, destructive confirmations visible | Demo mode, Admin, Approvals decision |
| Accessibility (no regression) | Skip link, focus-visible, keyboard palette/nav, 200% zoom reflow, reduced motion | Keyboard pass + 200% zoom on Query/Traces/Approvals |

**Suggested capture set (README/docs/showcase, when maintained):** `overview-health`, `query-studio-result`, `traces-waterfall-compare`, `governance-cost`, `guardrails-decisions`, `approvals-queue`, `audit-timeline`, `settings-readonly` — each in Light @1280 plus one compact/mobile and one High contrast sample.

## 7. Implementation notes & guardrails

- **Keep** `ui/` HTTP-only (no `app.*`/`core.*` imports) and preserve existing AST/contract tests; extend tests for new pure helpers (badge/status mapping, formatters, view-model transforms).
- **Prefer** pure helpers in `ui/` modules (e.g. extend `ui/theme.py`/`ui/common.py` or add `ui/components.py`) + thin Streamlit renderers in `ui/app.py`.
- **No new dependencies** without approval; use Streamlit/Altair/built-ins already available.
- **Incremental delivery:** land P0 shell/components first (visual lift, low behavior risk), then P1 screens, then P2/P3; rebaseline screenshots per slice.
- **Out of scope for this plan:** backend/API changes, new guided tour/demo-mode features, and non-UI product capabilities.

## 8. Recommended execution order

1. P0: design tokens refinement + shell/header/sidebar + badge/KPI/key-value/alert primitives + raw-expander convention.
2. P1: Overview, Query Studio, Traces, Governance & Cost, Guardrails, Compare (highest demo/value impact).
3. P2: Approvals, Audit, Access/RBAC, Admin, Evaluation, Settings, Feedback parity.
4. P3: chart/timeline depth, microcopy, empty/loading polish, QA pass and capture refresh.
