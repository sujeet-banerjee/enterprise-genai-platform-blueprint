# Bot work split (current open items)

Reconciled 2026-11-18 after #265 merged via PR #266 (`origin/main` @ `9d268d3`), the UI look/feel plan tracker audit, and maintainer reassignment of #268 to bot-uni. #240-#257 remain bot-win implementation items in Project #8 Workstream M; bot-uni's cross-cutting guard/support half (#265) is done.

Open items: umbrella **#43**; **#193** (LinkedIn package, MANUAL, maintainer approves/publishes); **#232** (external demo capture links, MANUAL, bot-win); UI look/feel plan **#240-#257** (bot-win). Cross-cutting support **#265** (bot-uni) is done (PR #266). **#268** (README console walkthrough cleanup) is a one-off bot-uni docs exception; bot-win must not edit the same README section. Workstreams A-L are closed except the manifest-driven open umbrellas noted above. Re-check open issues and PRs before each item.

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

## Work items for enterprise-gen-ai-bot-uni — platform, backend, CI and docs

| Order | Item | Notes |
|---|---|---|
| 1 | **#268 README console walkthrough cleanup** (H4, Workstream M, maintainer-assigned exception) | Done in this docs PR: README console section reduced to a quickstart/navigation pointer; detailed feature reference and renderable Mermaid mock-up wireframes moved to `docs/console-walkthrough.md`; structural guards added. No `ui/` or screenshot changes; #232 still owns external captures. |
| 2 | **#265 UI look/feel cross-cutting guards** (H4, Workstream M) | Done via PR #266: 10 focused tests in `tests/test_ui_plan_guards.py` for plan/tracker mapping, ownership boundary, HTTP-only rule, API paths, declared client methods, typed schemas and redaction/tenant-scope guards. No `ui/` edits. |
| 3 | **Docs reconciliation after bot-win UI merges** | After each #240-#257 merge, update this split, `docs/ux-and-api.md`, `docs/capability-status.md`, `docs/enterprise-roadmap.md` and README links when behaviour changes. Avoid concurrent edits to files bot-win is editing. |
| 4 | **Manual #193 / umbrella #43 monitoring** | #193 draft is merged; only maintainer approval/publish remains. Update #43 checklist/status in small dedicated PRs. |
| 5 | **Backend support for UX where explicitly agreed** | Prefer bot-win owns the `ui/` surface. Take narrowly scoped backend contracts only after agreement in the relevant issue (e.g. a jobs API if UI execution needs server-side scale). |

Completed by this workstream since the last split: **#179** cost/latency experiment
telemetry, **#180** budget-aware regression gates, **#181** config-driven parameter
sweep + Pareto report, **#195-#199** showcase harness/results/comparison, **#187/#188/
#190-#192** showcase docs, **#204** adoption kit, **#205** security qualification,
**#206** durable multi-replica profile (PR #263), **#223** identity-bound tenant
selection (PR #237), **#224** API rate limits (PR #261), **#225** supply-chain gates
(PR #239), **#265** UI look/feel cross-cutting guards (PR #266), docs
follow-ups #260/#262/#264, and Dependabot PRs #258/#259.

## Work items for enterprise-gen-ai-bot-win — UX/console

| Order | Item | Notes |
|---|---|---|
| 1 | **UI look/feel plan #240-#257** (H4, Workstream M) | All 18 UI implementation trackers. P0 #240-#241 (shell/design-system), P1 #242-#248 (structured screens and visualizations), P2 #249-#255 (screen parity, responsiveness, density), P3 #256-#257 (trust/copy/loading polish, QA and captures). Owner `owner:bot-win`, Status Todo, Project #8 Workstream M. |
| 2 | **#232 showcase external capture links** (H5, MANUAL) | Replace `_Pending - add external link_` placeholders in `docs/showcase/demo-walkthrough.md` once the maintainer publishes captures; then close. |
| 3 | **UI plan document upkeep** | Keep `docs/ui-enterprise-look-and-feel-plan.md` consistent with implemented screen changes; do not edit backend/CI files without agreement. |

Completed by this workstream since the last split: #130-#136, #145, #151 (workspace/deep
links), #152 (background evaluation jobs), #153 (Dataset Studio authoring), #154
(cross-object evidence), #155 (command palette + WCAG 2.2 AA), #156 (responsive
layout/density/themes), #157 (role journeys + safe demo mode), #158 (collaboration/feedback,
PR #230), #163 (HITL review console), #164 (queue operations/SLA/safe export), #189
(showcase demo walkthrough, PR #231), the enterprise look-and-feel plan (PR #234) and #235
(merge-artifact repairs).

## UI look/feel redistribution (2026-11-18)

| Plan area | Issues | Owner | Boundary |
|---|---|---|---|
| P0 branded shell, metadata, typography | #240 | bot-win | `ui/` app shell/theme only |
| P0 design-system primitives | #241 | bot-win | `ui/` components/theme only |
| P1 structured screens and visualizations | #242-#248 | bot-win | `ui/` screens; bot-uni verifies API contracts in #265 |
| P2 screen parity and responsiveness | #249-#255 | bot-win | `ui/` screens/components; bot-uni verifies contracts/docs after merge |
| P3 trust/copy/loading polish, QA, captures | #256-#257 | bot-win | `ui/` polish and visual QA; bot-uni verifies CI/API guards in #265 |
| Cross-cutting contract, AST and docs guards | #265 (done, PR #266) | bot-uni | `tests/`, docs and backend contracts only; never `ui/` |
| README console walkthrough cleanup | #268 (maintainer-assigned exception) | bot-uni | README + `docs/` only; no `ui/` edits; external capture links stay with #232/bot-win |

All #240-#257 and #265 are Project #8 items, Workstream **M UX polish &
adoption**. #240-#257 remain Status Todo with `owner:bot-win`; #265 is Status Done with
`owner:bot-uni`.

## Showcase/proof workstream (H5)

| Issue | Owner | Status | Depends on |
|---|---|---|---|
| #187 repository identity + positioning | bot-uni | Done (merged) | — |
| #188 high-level architecture diagram | bot-uni | Done (merged) | — |
| #189 end-to-end demo walkthrough + screenshots | bot-win | Done (merged, PR #231) | #195/#196 (demo data) |
| #190 engineering lifecycle / agent contribution docs | bot-uni | Done (merged) | — |
| #191 capability-status audit | bot-uni | Done (merged) | — |
| #192 production-readiness gap assessment | bot-uni | Done (merged) | — |
| #193 LinkedIn project entry + announcement | bot-uni (user approves/publishes) | In review (MANUAL; draft merged, awaiting maintainer approval/publish) | #187/#188/#191 (all merged) |
| #195 showcase benchmark corpora + suite config | bot-uni | Done (merged) | — |
| #196 reproducible benchmark report generator + CI check | bot-uni | Done (merged) | #195 |
| #197 reference load/latency harness + numbers | bot-uni | Done (merged) | #195 |
| #198 published benchmark results + methodology | bot-uni | Done (merged) | #196 |
| #199 comparison matrix vs alternatives | bot-uni | Done (merged) | — |
| #204 engineering-team adoption + pilot kit | bot-uni | Done (merged) | — |
| #205 security qualification: threat model + adversarial evidence | bot-uni | Done (merged, PR #226) | — |
| #206 durable multi-replica deployment profile qualification | bot-uni | Done (merged, PR #263) | — |
| #223 bind tenant header to authenticated identity | bot-uni | Done (merged, PR #237) | — |
| #224 configurable API rate limits and quotas | bot-uni | Done (merged, PR #261) | — |
| #225 required CodeQL + dependency/image scanning gates | bot-uni | Done (merged, PR #239; 7 required checks) | — |
| #232 showcase external capture links | bot-win | Todo (MANUAL; awaiting maintainer captures) | #189 (merged) |

## Suggested operating rules (to avoid collisions)

- **Claim before starting:** comment on the issue with the bot identity and open a draft
  PR early; re-check `gh pr list` and issue state each time.
- **Ownership boundary:** bot-uni = `core/`, `app/`, `config/`, registries, CI, `tests/`,
  CLI, eval/policy backend and reconciliation docs; bot-win = `ui/`, UX flows and
  console docs — except explicitly reassigned docs work (#268) or backend contracts
  agreed in the relevant issue.
- **UI look/feel split:** bot-win implements #240-#257; bot-uni handles #265 and the
  maintainer-reassigned #268 README/docs cleanup only. Bot-uni must not edit `ui/*.py`
  for this tranche.
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
  where required; all required CI checks green before merge (ruff, mypy, pytest 3.11/3.13,
  CodeQL, SCA pip-audit, Image scan Trivy). Deploy smoke and Eval gates are advisory.
- **`#43` umbrella:** update checklist/status only in dedicated small PRs or after
  merges (avoid concurrent edits).
- **Identity:** each bot uses its own GitHub App/bot git identity and app auth for push/
  PR/issue ops; never log keys/tokens; keep `.pem` outside the repo.
- **Manual decisions (`MANUAL`):** when a choice belongs to the maintainer, post a
  `## MANUAL INPUT NEEDED` comment with the options, recommendation and effect, and add
  the `MANUAL` label. Continue only on documented safe defaults; never automate the
  human action itself. Remove the label once the maintainer replies.
- **Project #8:** the board is user-owned; updates are made through the human-authenticated
  `gh` CLI (GraphQL), not the bot App token. Keep Status, Workstream and milestone in sync
  when issues are created, started or closed.
