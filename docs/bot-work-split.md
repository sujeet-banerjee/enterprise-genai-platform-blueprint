# Bot work split (H4/H5 — current open items)

Reconciled 2026-11-14 from `origin/main` @ `353c901` (after #187 merged). No open PRs.

Open items: umbrella **#43**; Workstream M UX **#157-#158** (bot-win, UX1-UX13 delivered);
showcase/proof **#187-#193**, showcase harness **#195-#199**, and new H5 qualification
items **#204-#206** (H5, ownership to re-check, see below). Workstream G
follow-ups (#64/#68-#71), #105/#109, #154 (UX11), #155 (UX12), #156 (UX13), #162 and #175
are **closed** — do not treat them as open.
Re-check open issues and PRs before each item.

## Bot identities

- **enterprise-gen-ai-bot-uni[bot]** — GitHub user id `353626911`, App
  `enterprise-gen-ai-bot-uni` (App ID `5652767`, Client ID `Iv23liwXdRBYiE8NXU8d`,
  installation `179480668`). Git author/committer:
  `enterprise-gen-ai-bot-uni[bot] <353626911+enterprise-gen-ai-bot-uni[bot]@users.noreply.github.com>`.
  Auth via installation token; keep keys outside the repo.
- **enterprise-gen-ai-bot-win[bot]** — GitHub user id `353281915`, App
  `enterprise-gen-ai-bot-win` (App ID `5640658`, Client ID `Iv23ctVFNlANdHYlLOMG`,
  installation `179214525`). Git author/committer:
  `enterprise-gen-ai-bot-win[bot] <353281915+enterprise-gen-ai-bot-win[bot]@users.noreply.github.com>`.
  Auth via the GitHub App helper, not a shared `GH_TOKEN`.

## Work items for enterprise-gen-ai-bot-uni — platform/backend

| Order | Item | Notes |
|---|---|---|
| 1 | **Showcase harness #195-#199** (H5) | Benchmark corpora/config (#195), reproducible report generator (#196), reference load/latency harness (#197), published results/methodology (#198), comparison matrix (#199). |
| 2 | **Showcase docs owned by bot-uni** (H5) | #187 repository identity, #188 architecture diagram, #190 engineering lifecycle, #191 capability-status audit, #192 production-readiness gap, #193 LinkedIn draft (user approves/publishes). |
| 3 | **Backend support for UX where agreed** | Prefer bot-win owns the `ui/` surface. Take narrowly-scoped backend contracts only after agreeing in the issue (e.g. a jobs API if #152's UI-side execution ever needs server-side scale). |
| 4 | **Roadmap/docs reconciliation** | Small post-merge doc PRs; avoid concurrent edits to the same files. |

Completed by this workstream since the last split: **#179** cost/latency experiment
telemetry, **#180** budget-aware regression gates, **#181** config-driven parameter
sweep + Pareto report; earlier #121 hybrid policy registry, #122 CEL evaluator +
bundles, #123 HITL workflow, #124 eval dataset schema/loaders, #125 CI regression
gates, #126 eval dashboard metrics, #127 golden paths, #128 `genai init`, #129
onboarding guide, #162 generic redaction fallback, #175 HITL approvals queue
contract (server-side pagination/filter/sort/tenant scope).

## Work items for enterprise-gen-ai-bot-win — UX/console and docs polish

| Order | Item | Notes |
|---|---|---|
| 1 | **#157 UX14 - Role journeys + demo mode** (H4, P2) | Onboarding experience. |
| 2 | **#158 UX15 - Collaboration and feedback** (H4, P2) | UI feature. |
| 3 | **#189 showcase demo walkthrough** (H5) | 3-5 minute integrated demo + screenshots/recording; bot-uni supplies the known-good demo config/data. |
| 4 | **Roadmap/docs reconciliation** | Low-risk docs sync after merges. |

Completed by this workstream since the last split: #130-#136, #145, #151 (workspace/deep
links), #152 (background evaluation jobs), #153 (Dataset Studio authoring), #154
(cross-object evidence), #155 (command palette + WCAG 2.2 AA), #156 (responsive
layout/density/themes), #163 (HITL review console) and #164 (queue operations/SLA/safe
export).

## Showcase/proof workstream (H5)

| Issue | Owner | Status | Depends on |
|---|---|---|---|
| #187 repository identity + positioning | bot-uni | Done (merged) | — |
| #188 high-level architecture diagram | bot-uni | In review | — |
| #189 end-to-end demo walkthrough + screenshots | bot-win | Todo | #195/#196 (demo data) |
| #190 engineering lifecycle / agent contribution docs | bot-uni | Todo | — |
| #191 capability-status audit | bot-uni | Todo | — |
| #192 production-readiness gap assessment | bot-uni | Todo | — |
| #193 LinkedIn project entry + announcement | bot-uni (user approves/publishes) | Todo | #187/#188/#189/#191 |
| #195 showcase benchmark corpora + suite config | bot-uni | Done (merged) | — |
| #196 reproducible benchmark report generator + CI check | bot-uni | Done (merged) | #195 |
| #197 reference load/latency harness + numbers | bot-uni | Done (merged) | #195 |
| #198 published benchmark results + methodology | bot-uni | Done (merged) | #196 |
| #199 comparison matrix vs alternatives | bot-uni | Done (merged) | — |
| #204 engineering-team adoption + pilot kit | unassigned (re-check) | Todo | — |
| #205 security qualification: threat model + adversarial evidence | unassigned (re-check) | Todo | — |
| #206 durable multi-replica deployment profile qualification | unassigned (re-check) | Todo | — |

## Suggested operating rules (to avoid collisions)

- **Claim before starting:** comment on the issue with the bot identity and open a draft
  PR early; re-check `gh pr list` and issue state each time.
- **Ownership boundary:** bot-uni = `core/`, `app/`, `config/`, registries, CI, CLI,
  eval/policy backend; bot-win = `ui/`, UX flows, console docs — except explicitly split
  backend contracts agreed in the issue.
- **Ownership labels:** every open issue carries exactly one `owner:bot-uni` or
  `owner:bot-win` label (umbrella #43 excepted). Keep them current when ownership changes.
- **Rebase discipline:** both rebase feature branches onto latest `origin/main` before
  PR/merge; land small PRs to reduce conflicts. Rebase-merge and delete branches.
- **`ui/` rule (project):** `ui/` is HTTP-only (never imports `app.*`/`core.*`); new UI
  helpers live in `ui/*.py` (pure, Streamlit-free) with tests.
- **Config/architecture (project):** config-driven (`config/**/*.yaml` + schema/validator/
  secrets + registries) -> `app/bootstrap.py::assemble_components` -> `app/pipeline.py`
  -> `app/main.py`; safe/off defaults for new knobs.
- **Quality:** feature branch + PR + rebase + delete branch; >=6 tests for code changes
  where required; all CI checks green before merge (ruff, mypy, pytest 3.11/3.13, Deploy
  smoke chart+image, CodeQL).
- **`#43` umbrella:** update checklist/status only in dedicated small PRs or after
  merges (avoid concurrent edits).
- **Identity:** each bot uses its own GitHub App/bot git identity and app auth for push/
  PR/issue ops; never log keys/tokens; keep `.pem` outside the repo.
- **Project #8:** the board is user-owned; updates are made through the human-authenticated
  `gh` CLI (GraphQL), not the bot App token. Keep Status, Workstream and milestone in sync
  when issues are created, started or closed.
