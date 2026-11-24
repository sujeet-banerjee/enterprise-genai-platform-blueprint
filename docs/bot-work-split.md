# Bot work split (current open items)

Reconciled 2026-11-20 after async-operations recalibration (`origin/main` @ `1fa67c7` baseline; no open PRs at reconcile). #240-#257 remain bot-win UI look/feel implementation items in Project #8 Workstream M; bot-uni cross-cutting guard/support #265 and maintainer-assigned docs exception #268 are done.

Open items: umbrella **#43**; **#193** (LinkedIn package, MANUAL, maintainer approves/publishes); **#232** (external demo capture links, MANUAL, bot-win); UI look/feel plan **#240-#257** (bot-win); **#279** (bot-uni, async operations API/contracts, D3/M); **#280** (bot-win, async operations console UX, depends on #279). Re-check open issues and PRs before each item.

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
| 1 | **#279 Async operations API/contracts** (H4, D3/M, `owner:bot-uni`) | Add server-side async operation/job service for long-running query execution; keep `/v1/query` and `/v1/query:batch` synchronous. Accepted defaults: owner=`principal.subject` else tenant-scoped `X-Client-Session` fallback (no cross-caller enumeration/spoofable sole authz); v1 = query async + unified in-progress listing including experiments; coarse `queued|running|completed|failed|cancelled` + timestamps + optional stage; bounded in-memory + honor `BaseStore` when configured, in-progress + recent-completed window. Recommend `operation id == request_id` for query ops. |
| 2 | **Docs reconciliation after bot-win UI merges** | After each #240-#257 and #280 merge, update this split, `docs/ux-and-api.md`, `docs/capability-status.md`, `docs/enterprise-roadmap.md`, and README links when behaviour changes. Avoid concurrent edits to files bot-win is editing. |
| 3 | **Manual #193 / umbrella #43 monitoring** | #193 draft is merged; only maintainer approval/publish remains. Update #43 checklist/status in small dedicated PRs. |
| 4 | **Backend support for UX where explicitly agreed** | Prefer bot-win owns the `ui/` surface. Take narrowly scoped backend contracts only after agreement in the relevant issue. |
| 5 | **Standing daily review of bot-win work** | Check new bot-win PRs/check-ins (especially #240-#257, #280) for API coherence and contract regressions. Add inline PR review comments for discrepancies; for merged check-ins that are not coherent with shipped APIs, open an `owner:bot-win` issue with file:line evidence and expected-vs-actual behaviour. Bot-uni stays read-only on `ui/*.py`. |

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
| 1 | **UI look/feel plan #240-#257** (H4, Workstream M) | 18 UI implementation trackers: P0 #240-#241, P1 #242-#248, P2 #249-#255, P3 #256-#257. Owner `owner:bot-win`, Status Todo, Project #8 Workstream M. |
| 2 | **#280 Async operations console** (H4, D3/M, `owner:bot-win`, depends on #279) | HTTP-only UI: submit async query op -> show instant `request_id`; poll lifecycle; server-backed in-flight operations panel visible across navigation/refresh (owner+tenant scoped), including experiments in v1; coarse status/timestamps/stage; handle 401/403/404/503 envelopes; no `app.*`/`core.*` imports. |
| 3 | **#232 showcase external capture links** (H5, MANUAL) | Replace `_Pending - add external link_` placeholders in `docs/showcase/demo-walkthrough.md` once the maintainer publishes captures; then close. |
| 4 | **UI plan document upkeep** | Keep `docs/ui-enterprise-look-and-feel-plan.md` consistent with implemented screen changes; do not edit backend/CI files without agreement. |

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
| Async operations backend/contracts | #279 | bot-uni | `core/`, `app/`, `config/`, schemas/tests/docs; no `ui/` edits; keep sync query endpoints |
| Async operations console UX | #280 (depends on #279) | bot-win | `ui/` HTTP-only; no `app.*`/`core.*` imports; consume public operation APIs only |
| Cross-cutting contract, AST and docs guards | #265 (done, PR #266) | bot-uni | `tests/`, docs and backend contracts only; never `ui/` |
| README console walkthrough cleanup | #268 (maintainer-assigned exception) | bot-uni | README + `docs/` only; no `ui/` edits; external capture links stay with #232/bot-win |

#240-#257, #265, #279, #280 are Project #8 items in Workstream **M UX polish & adoption** (or D3/M for async ops). #240-#257 and #280 remain Todo with `owner:bot-win`; #279 is Todo with `owner:bot-uni`; #265 is Done.

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

## Standing bot-win review protocol (bot-uni)

Owner: bot-uni. Cadence: every day / each new session, and immediately after any new bot-win
PR or merged check-in. Scope: all bot-win PRs/commits, especially UI look/feel #240-#257,
bot-win docs/showcase changes, and any change to client/API consumption.

For each new bot-win PR/check-in:

1. List open PRs and recent commits; identify only bot-win-owned changes.
2. Run focused guards: `tests/test_ui_plan_guards.py`, `tests/test_ui_console.py`,
   `tests/test_ui_new_features.py`, `tests/test_api_contract.py`,
   `tests/test_docs_reconciliation.py`, `tests/test_readme_console_section.py`.
3. Verify HTTP-only `ui/` imports, endpoint/method/schema parity with `EXPECTED_PATHS` and
   `app/schemas.py`, error-envelope/failure taxonomy, redaction/tenant/API-key safety,
   docs links, and required CI evidence.
4. For an open PR, add inline review comments at the exact file:line with expected vs actual
   behaviour and a requested change. For a merged check-in, open a GitHub issue labelled
   `owner:bot-win` plus relevant `ui`/`ux`/`documentation`/`bug` labels, with PR/commit link,
   file:line evidence, reproduction/check command and expected-vs-actual behaviour.
5. Do not edit `ui/*.py` or implement bot-win fixes unless explicitly reassigned. Keep this
   protocol and persistent memory in sync if the user changes cadence or scope.

Baseline 2026-11-19: no open PRs; latest bot-win commits were #235 docs repairs (`b9245d2`),
look/feel plan (`76a625e`), #158 feedback (`dc2d7af`), #189 demo walkthrough (`3ba6b09`),
and #157 role journeys (`1017dd3`). Focused review checks: 105 passed; no PR comments or
issues filed.
