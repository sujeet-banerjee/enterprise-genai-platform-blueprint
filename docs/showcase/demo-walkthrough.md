# End-to-end demo walkthrough (#189)

> **Repeatable showcase walkthrough (3-5 minutes).** This is a maintainer-reviewed demo
> script for the Streamlit console. It uses the console's existing **Demo mode** (local
> fixtures only) so it can be run without a backend, without model downloads, and without
> any production data.

## Safety and disclosure

- **Mocked/seeded/non-production:** Demo mode serves built-in fixtures from
  `ui/journeys.py` via `ui/demo.py::DemoApi`. The console does **not** call the HTTP API
  or read/write production tenant data while demo mode is active.
- **No real PII:** All queries, traces, audit events, approvals, users, tenants and
  documents shown in demo mode are synthetic fixture data shipped with this repository.
- **No new demo implementation:** This walkthrough uses the existing console demo mode and
  role journeys; it does not add a new guided tour or demo mode.
- **External captures:** Screenshots and the recording are maintained outside this
  repository and linked below by the maintainer. If a link is missing, treat that capture
  as pending.

## Known-good demo setup

### Prerequisites

- Python 3.11+
- Repo checkout of `enterprise-genai-platform-blueprint`

### Install and start

```bash
# from the repository root
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# bash: source .venv/bin/activate
pip install -e ".[ui]"

streamlit run ui/app.py
```

Open the URL Streamlit prints (default `http://localhost:8501`). No backend process is
required for demo mode.

### Enter demo mode

1. In the sidebar, open **Role journeys & demo**.
2. Choose a persona (for example **Architect** or **Security / compliance**).
3. Click **Start demo** (or start the matching journey in demo mode).

Expected state: the console shows the demo banner/reset control and is populated with
seeded workspace data (query history, trace id, dataset, guardrail/audit/admin fixtures)
from `ui/journeys.py`.

## 3-5 minute walkthrough script

Use this flow in order. Each step notes what to show and which requirement it covers.

| Time | Screen / action | What to show | Requirement covered |
| --- | --- | --- | --- |
| 0:00-0:30 | **Overview / Health** | Demo banner, role journey context, readiness/topology tiles and Get started checklist populated from seeded demo state. | Setup context, repeatable starting point |
| 0:30-1:15 | **Query Studio** | Open a seeded/recent query run. Show the answer, retrieved documents/evidence, cost and latency metadata, and inspect Trace/Guardrails/Resilience/Cache tabs for the same run. | RAG query and inspect; quality/latency/cost context |
| 1:15-2:00 | **Evaluation** | Open the seeded dataset/job or run a dataset evaluation in demo mode. Show the case-by-metric matrix/averages and the run comparison/delta view (and experiment comparison where available). | Eval/experiment; quality metrics |
| 2:00-2:45 | **Governance & Cost** | Show spend/budget/limits, request cost and latency/failure/guardrail metrics or summaries for the demo window. | Quality/latency/cost, governance |
| 2:45-3:30 | **Guardrails** and **Access / RBAC** (or **Approvals/Admin** as role allows) | Show resolved guardrail chains/profile and a decision/hit-rate view; show role/capabilities/tenant scope (and approval/admin fixtures when present). | Governance, RBAC/guardrails |
| 3:30-4:00 | **Traces** and **Audit** | Open the demo trace by request id, inspect stage timeline/waterfall and redacted payload, then cross-link to audit/evidence for the same request. | Trace/audit |
| 4:00-4:30 | Wrap-up | Return to **Overview** or **Settings (read-only)** to show effective/redacted configuration context; click **Exit demo and reset** to leave a clean state. | Repeatability, clean reset |

> Tip: keep narration factual ("this is seeded demo data", "redacted by the console/API")
> and avoid claiming production certification, real customer data, or external integrations
> beyond what the demo fixtures show.

## External captures (maintainer-linked)

Add or update links here when captures are published. Links are external by design.

| Capture | Link | Notes |
| --- | --- | --- |
| Walkthrough recording (3-5 min) | _Pending - add external link_ | Full flow in table above |
| Overview / demo start | _Pending - add external link_ | Demo banner + readiness/topology |
| Query Studio inspect | _Pending - add external link_ | Answer, docs, cost/latency, trace tabs |
| Evaluation / comparison | _Pending - add external link_ | Metrics matrix/averages/delta |
| Governance & guardrails/RBAC | _Pending - add external link_ | Spend, guardrails, access scope |
| Trace / audit correlation | _Pending - add external link_ | Timeline/waterfall + audit evidence |

## Verification checklist (for reviewers)

- [ ] Walkthrough completes in ~3-5 minutes following the script.
- [ ] Covers RAG query/inspect, eval/experiment, quality/latency/cost, governance/RBAC/guardrails, and trace/audit.
- [ ] Uses existing demo mode / seeded fixtures only; no real PII; mocked/non-prod disclosed.
- [ ] Setup steps are reproducible from this document.
- [ ] External capture links are present (or explicitly marked pending) and linked from `README.md`.
