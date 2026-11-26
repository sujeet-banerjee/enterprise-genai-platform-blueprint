# UI look & feel QA and target captures (#257)

> **Status:** structural QA complete; external visual captures are maintained outside
> the repository and linked by the maintainer (#232).

## Scope

- Viewports: 375 px, 768 px, 1280 px
- Themes: Light, Dark, High contrast
- Modes: normal, demo, restricted role
- Matrix rows: 27 ({'documented': 27})

## QA matrix

| Viewport | Theme | Mode | Result | Evidence |
| --- | --- | --- | --- | --- |
| 375 | Light | normal | documented | structural checks only; external visual capture pending #232 |
| 375 | Light | demo | documented | structural checks only; external visual capture pending #232 |
| 375 | Light | restricted role | documented | structural checks only; external visual capture pending #232 |
| 375 | Dark | normal | documented | structural checks only; external visual capture pending #232 |
| 375 | Dark | demo | documented | structural checks only; external visual capture pending #232 |
| 375 | Dark | restricted role | documented | structural checks only; external visual capture pending #232 |
| 375 | High contrast | normal | documented | structural checks only; external visual capture pending #232 |
| 375 | High contrast | demo | documented | structural checks only; external visual capture pending #232 |
| 375 | High contrast | restricted role | documented | structural checks only; external visual capture pending #232 |
| 768 | Light | normal | documented | structural checks only; external visual capture pending #232 |
| 768 | Light | demo | documented | structural checks only; external visual capture pending #232 |
| 768 | Light | restricted role | documented | structural checks only; external visual capture pending #232 |
| 768 | Dark | normal | documented | structural checks only; external visual capture pending #232 |
| 768 | Dark | demo | documented | structural checks only; external visual capture pending #232 |
| 768 | Dark | restricted role | documented | structural checks only; external visual capture pending #232 |
| 768 | High contrast | normal | documented | structural checks only; external visual capture pending #232 |
| 768 | High contrast | demo | documented | structural checks only; external visual capture pending #232 |
| 768 | High contrast | restricted role | documented | structural checks only; external visual capture pending #232 |
| 1280 | Light | normal | documented | structural checks only; external visual capture pending #232 |
| 1280 | Light | demo | documented | structural checks only; external visual capture pending #232 |
| 1280 | Light | restricted role | documented | structural checks only; external visual capture pending #232 |
| 1280 | Dark | normal | documented | structural checks only; external visual capture pending #232 |
| 1280 | Dark | demo | documented | structural checks only; external visual capture pending #232 |
| 1280 | Dark | restricted role | documented | structural checks only; external visual capture pending #232 |
| 1280 | High contrast | normal | documented | structural checks only; external visual capture pending #232 |
| 1280 | High contrast | demo | documented | structural checks only; external visual capture pending #232 |
| 1280 | High contrast | restricted role | documented | structural checks only; external visual capture pending #232 |

## Area checklist

| Area | Checks | Targets |
| --- | --- | --- |
| Shell & nav | Branded header, active nav, sticky sidebar at >=1024, palette/help reachable, no clipped text | overview-health, settings-readonly |
| Status semantics | Consistent ok/warn/error/blocked/disabled badges across screens | query-studio-result, guardrails-decisions, approvals-queue |
| Raw-data discipline | Primary view structured; raw JSON only in labeled redacted expanders | query-studio-result, settings-readonly, governance-cost, audit-timeline |
| Tables & cards | Dense tables degrade to cards with all fields and actions; no page-level horizontal scroll | guardrails-decisions, approvals-queue, audit-timeline |
| Charts/timelines | Latency, cost and guardrail visuals render with readable legends and high-contrast safe colors | traces-waterfall-compare, governance-cost |
| States | Empty, loading, error and taxonomy failures show structured remediation | overview-health, query-studio-result, audit-timeline, approvals-queue |
| Trust cues | Demo, redaction, tenant scope and destructive confirmation cues are visible | approvals-queue, settings-readonly |
| Accessibility | Skip link, focus-visible, keyboard palette/nav, 200% zoom reflow, reduced motion | query-studio-result, traces-waterfall-compare, approvals-queue |

## Target capture manifest

| Capture | Title | Screen | Variants | Link |
| --- | --- | --- | --- | --- |
| overview-health | Overview / Health | Overview / Health | overview-health-light-1280 / overview-health-compact / overview-health-high-contrast | _Pending - add external link (#232)_ |
| query-studio-result | Query Studio result | Query Studio | query-studio-result-light-1280 / query-studio-result-compact / query-studio-result-high-contrast | _Pending - add external link (#232)_ |
| traces-waterfall-compare | Traces waterfall + compare | Traces | traces-waterfall-compare-light-1280 / traces-waterfall-compare-compact / traces-waterfall-compare-high-contrast | _Pending - add external link (#232)_ |
| governance-cost | Governance & Cost | Governance & Cost | governance-cost-light-1280 / governance-cost-compact / governance-cost-high-contrast | _Pending - add external link (#232)_ |
| guardrails-decisions | Guardrails decisions | Guardrails | guardrails-decisions-light-1280 / guardrails-decisions-compact / guardrails-decisions-high-contrast | _Pending - add external link (#232)_ |
| approvals-queue | Approvals queue | Approvals | approvals-queue-light-1280 / approvals-queue-compact / approvals-queue-high-contrast | _Pending - add external link (#232)_ |
| audit-timeline | Audit timeline | Audit | audit-timeline-light-1280 / audit-timeline-compact / audit-timeline-high-contrast | _Pending - add external link (#232)_ |
| settings-readonly | Settings (read-only) | Settings (read-only) | settings-readonly-light-1280 / settings-readonly-compact / settings-readonly-high-contrast | _Pending - add external link (#232)_ |

## How to refresh captures

1. Run `streamlit run ui/app.py` and enter demo mode as described in
   [demo-walkthrough.md](demo-walkthrough.md).
2. Capture each manifest row in Light @1280, one compact/mobile sample, and one
   High-contrast sample.
3. Publish the captures outside this repository and replace the pending links in
   [demo-walkthrough.md](demo-walkthrough.md) and this manifest.

## Known exceptions

- Screenshots and recordings are linked, not committed, per the #257 guardrail.
- CI has no browser capture harness, so the executable evidence is structural:
  HTTP-only AST guards, theme-token checks, capture-manifest checks, and QA matrix
  tests in `tests/test_ui_qa_checks.py`.
- External capture URLs are maintained by the maintainer under #232; this report
  records the refreshed target names and expected variants until those links land.
