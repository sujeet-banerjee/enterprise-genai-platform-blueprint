# Bot work split (current open items)

Reconciled 2026-11-26 after #256 merge (`origin/main` @ `996ef57`). Bot-win merged #249-#256 from the UI look/feel plan and #280 (async operations console); remaining UI look/feel item #257 plus daily-review follow-up #290 stay in Project #8 Workstream M. Bot-uni cross-cutting guard/support #265, maintainer-assigned docs exception #268, and backend #279 are done.

Open items: umbrella **#43**; **#193** (LinkedIn package, MANUAL, maintainer approves/publishes); **#232** (external demo capture links, MANUAL, bot-win); remaining UI look/feel item **#257** (bot-win); **#290** (bot-win, fixes from daily review of #249-#252); new H4 operations/auth/admin tranche **#297-#304** (bot-uni backend/contracts #297-#302, bot-win UI #303-#304). Re-check open issues and PRs before each item.

## Live reconciliation (2026-11-26)

| Issue | Owner | Project #8 Status | Workstream | Milestone |
|---|---|---|---|---|
| **#43** | unassigned (umbrella) | Todo | Cross-cutting | — |
| **#193** | bot-uni | In Progress | Cross-cutting | H5 - Proof & showcase |
| **#232** | bot-win | Todo | Cross-cutting | — |
| **#257** | bot-win | Todo | M UX polish & adoption | H4 - Post-G6 hardening & UX |
| **#290** | bot-win | Todo | M UX polish & adoption | — |
| **#297** | bot-uni | Todo | E Platform engineering | H4 - Post-G6 hardening & UX |
| **#298** | bot-uni | Todo | D Serving & scale | H4 - Post-G6 hardening & UX |
| **#299** | bot-uni | Todo | A Multi-tenancy & identity | H4 - Post-G6 hardening & UX |
| **#300** | bot-uni | Todo | A Multi-tenancy & identity | H4 - Post-G6 hardening & UX |
| **#301** | bot-uni | Todo | A Multi-tenancy & identity | H4 - Post-G6 hardening & UX |
| **#302** | bot-uni | Todo | Cross-cutting | H4 - Post-G6 hardening & UX |
| **#303** | bot-win | Todo | M UX polish & adoption | H4 - Post-G6 hardening & UX |
| **#304** | bot-win | Todo | M UX polish & adoption | H4 - Post-G6 hardening & UX |

New H4 tranche: durable ongoing tasks and admin identity state. Bot-uni owns backend/repositories/APIs/config/contracts/docs (#297-#302); bot-win owns HTTP-only UI consumers (#303-#304). New issues carry `owner:bot-uni` or `owner:bot-win` labels and are Project #8 Todo items. Umbrella #43 was updated with the tranche checklist.

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
| 1 | **#279 Async operations API/contracts** (H4, D3/M, `owner:bot-uni`) | Done via PR #289 (`216a3c5`): bounded async query service, `POST /v1/operations/query` / `GET /v1/operations/{id}` / `GET /v1/operations`, owner+tenant scoping, unified experiment listing, `BaseStore` TTL, and no raw payload persistence. Sync `/v1/query` and `/v1/query:batch` remain unchanged. |
| 2 | **#297 Typed persistence repositories** (H4, E, `owner:bot-uni`) | Todo. Foundation for durable operations and admin entities; typed repository layer above `BaseStore`, versioned records, tenant/owner predicates, TTL/retention, pagination, shared SQLite/Postgres store, separate in-memory namespaces. |
| 3 | **#298 Ongoing-task APIs** (H4, D, `owner:bot-uni`) | Todo. Depends on #297: operations list filters/sort/pagination/total, queued-only cancel, optional redacted progress events. Enables bot-win #303. |
| 4 | **#299 Third-party auth provider registry** (H4, A, `owner:bot-uni`) | Todo. Depends on #297: `config/auth_providers.yaml`, generic OIDC/Keycloak/Okta/Azure AD/Google, SCIM persistence, SAML bridge, redacted admin APIs. |
| 5 | **#300 Per-tenant API keys + API auth** (H4, A, `owner:bot-uni`) | Todo. Depends on #297/#299: auth precedence, `X-API-Key`, digest-only key storage, rotate/revoke, key metadata, audit redaction. |
| 6 | **#301 Org/tenant RBAC and superusers** (H4, A, `owner:bot-uni`) | Todo. Depends on #297/#299/#300: org scope, role hierarchy, admin user/role/superuser APIs, least-privilege capability checks, admin auth fixes. |
| 7 | **#302 Contract/docs/qualification guards** (H4, Cross-cutting, `owner:bot-uni`) | Todo. After backend contracts and with bot-win #303/#304: route allowlist, typed schemas, redaction/tenant guards, docs reconciliation, multi-replica qualification boundary. |
| 8 | **Docs reconciliation after bot-win UI merges** | After each remaining #240-#257, #280, #303 and #304 merge, update this split, `docs/ux-and-api.md`, `docs/capability-status.md`, `docs/enterprise-roadmap.md`, and README links when behaviour changes. Avoid concurrent edits to files bot-win is editing. |
| 9 | **Manual #193 / umbrella #43 monitoring** | #193 draft is merged; only maintainer approval/publish remains. Update #43 checklist/status in small dedicated PRs. |
| 10 | **Standing daily review of bot-win work** | Check new bot-win PRs/check-ins (especially #256-#257, #303-#304) for API coherence and contract regressions. Add inline PR review comments for discrepancies; for merged check-ins that are not coherent with shipped APIs, open an `owner:bot-win` issue with file:line evidence and expected-vs-actual behaviour. Latest result is **#290** (opened after #249-#252 review). Bot-uni stays read-only on `ui/*.py`. |

Completed by this workstream since the last split: **#179** cost/latency experiment
telemetry, **#180** budget-aware regression gates, **#181** config-driven parameter
sweep + Pareto report, **#195-#199** showcase harness/results/comparison, **#187/#188/
#190-#192** showcase docs, **#204** adoption kit, **#205** security qualification,
**#206** durable multi-replica profile (PR #263), **#223** identity-bound tenant
selection (PR #237), **#224** API rate limits (PR #261), **#225** supply-chain gates
(PR #239), **#265** UI look/feel cross-cutting guards (PR #266), **#279** async
operations API (PR #289), docs follow-ups #260/#262/#264, and Dependabot PRs #258/#259.

## Work items for enterprise-gen-ai-bot-win — UX/console

| Order | Item | Notes |
|---|---|---|
| 1 | **#303 Ongoing tasks UI** (H4, M, `owner:bot-win`) | Todo. Depends on #297/#298: HTTP-only operations list/get/cancel/events client methods, `X-Client-Session`, filters/sort/pagination, progress timeline, cancel confirmation, redacted error/empty states. |
| 2 | **#304 Admin auth/RBAC UI** (H4, M, `owner:bot-win`) | Todo. Depends on #297/#299/#300/#301: auth provider, tenant users/roles, API key lifecycle, superuser/admin screens; no raw keys/tokens/claims; capability-gated controls. |
| 3 | **UI look/feel plan #257** (H4, Workstream M) | Remaining P3 item: #257 QA pass/capture refresh. #240-#256 are merged; #257 is Todo with `owner:bot-win` in Project #8 Workstream M. Bot-win can run QA, but final capture refresh needs maintainer-provided external URLs or approval to commit images. |
| 4 | **#290 daily-review fixes** | Address Admin audit CSV formula-injection, approval evidence-id routing, Access admin-capability display, approval decision-history rendering, and Audit docs drift from #249-#252. |
| 5 | **#232 showcase external capture links** (H5, MANUAL) | Maintainer runs the demo walkthrough in demo mode and publishes a 3-5 min recording plus screenshots externally, or approves committing image files; then replace `_Pending - add external link_` placeholders in `docs/showcase/demo-walkthrough.md` and close. |
| 6 | **UI plan document upkeep** | Keep `docs/ui-enterprise-look-and-feel-plan.md` consistent with implemented screen changes; do not edit backend/CI files without agreement. |

Completed by this workstream since the last split: #130-#136, #145, #151 (workspace/deep
links), #152 (background evaluation jobs), #153 (Dataset Studio authoring), #154
(cross-object evidence), #155 (command palette + WCAG 2.2 AA), #156 (responsive
layout/density/themes), #157 (role journeys + safe demo mode), #158 (collaboration/feedback,
PR #230), #163 (HITL review console), #164 (queue operations/SLA/safe export), #189
(showcase demo walkthrough, PR #231), the enterprise look-and-feel plan (PR #234), #235
(merge-artifact repairs), structured Approval/Audit/Access/Admin/Settings/Feedback/
responsive presentations (#249-#255), trust/copy/loading polish (#256, PR #306), and the #280 async operations console (PR #292).

## UI look/feel redistribution (2026-11-18)

| Plan area | Issues | Owner | Boundary |
|---|---|---|---|
| P0 branded shell, metadata, typography | #240 | bot-win | `ui/` app shell/theme only |
| P0 design-system primitives | #241 | bot-win | `ui/` components/theme only |
| P1 structured screens and visualizations | #242-#248 | bot-win | `ui/` screens; bot-uni verifies API contracts in #265 |
| P2 screen parity and responsiveness | #249-#255 (done) | bot-win | `ui/` screens/components; bot-uni verified contracts/docs in #265 |
| P3 trust/copy/loading polish, QA, captures | #256 (done, PR #306); #257 (open) | bot-win | `ui/` polish and visual QA; capture links/images need maintainer input; bot-uni verifies CI/API guards in #265 |
| Async operations backend/contracts | #279 (done, PR #289) | bot-uni | `core/`, `app/`, `config/`, schemas/tests/docs; no `ui/` edits; keep sync query endpoints |
| Async operations console UX | #280 (done, PR #292) | bot-win | `ui/` HTTP-only; no `app.*`/`core.*` imports; consume public operation APIs only |
| Cross-cutting contract, AST and docs guards | #265 (done, PR #266) | bot-uni | `tests/`, docs and backend contracts only; never `ui/` |
| README console walkthrough cleanup | #268 (maintainer-assigned exception) | bot-uni | README + `docs/` only; no `ui/` edits; external capture links stay with #232/bot-win |

#240-#257, #265, #279, #280 and #290 are Project #8 items in Workstream **M UX polish & adoption** (or D3/M for async ops). #257 and #290 remain Todo with `owner:bot-win`; #240-#256, #265, #279 and #280 are Done.

## Operations/auth/admin tranche (2026-11-26)

| Area | Issues | Owner | Boundary |
|---|---|---|---|
| Typed persistence repositories | #297 | bot-uni | `core/`, `app/`, `config/`, `tests/`, backend docs; no `ui/` edits |
| Ongoing-task APIs/contracts | #298 | bot-uni | operations list/filter/sort/paginate, queued-only cancel, redacted progress events; no `ui/` edits |
| Third-party auth/identity providers | #299 | bot-uni | OIDC presets, SCIM persistence, SAML bridge, provider registry/config/admin APIs; no `ui/` edits |
| Per-tenant API keys and API auth | #300 | bot-uni | digest-only key storage, auth precedence, key lifecycle APIs; no `ui/` edits |
| Org/tenant RBAC and superusers | #301 | bot-uni | admin roles/users/superuser APIs, capability checks, audit redaction; no `ui/` edits |
| Contract/docs/qualification guards | #302 | bot-uni | `tests/` and docs only; coordinates with #303/#304, never edits `ui/` |
| Ongoing tasks console | #303 | bot-win | `ui/` HTTP-only; consumes public operation APIs only; no backend/config edits |
| Admin auth/RBAC console | #304 | bot-win | `ui/` HTTP-only; consumes public admin APIs only; no backend/config edits |

#297-#304 are Project #8 Todo items in milestone **H4 - Post-G6 hardening & UX**. Workstreams: #297 E, #298 D, #299-#301 A, #302 Cross-cutting, #303-#304 M. Bot-uni must not edit `ui/*.py`; bot-win must not edit `core/`, `app/`, `config/`, or backend docs for this tranche.

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
  maintainer-reassigned #268 README/docs cleanup only. Bot-win also owns the #290 follow-up
  fixes. Bot-uni must not edit `ui/*.py` for this tranche.
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

Baseline 2026-11-26: no open PRs; `origin/main` @ `3d90325`. Latest bot-win merges were
#280 async operations console (PR #292), #253 Settings view (PR #293), #254 Feedback view
(PR #294), and #255 responsive/density parity (PR #295). Daily review produced open **#290**;
focused review evidence is recorded in the relevant PR/issue comments.
