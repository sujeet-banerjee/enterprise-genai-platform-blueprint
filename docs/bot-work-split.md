# Bot work split (H4 / current open items)

Reconciled 2026-11-09 from `origin/main` @ `4306af4` (before the UX17 PR). No open PRs.

Open items at reconciliation: umbrella **#43**; Workstream M UX **#152-#158**;
Workstream B redaction bug **#162**; Workstream J backend approval queue **#175**.
**#164 (UX17)** is delivered by this branch/PR. Re-check open issues and PRs before each item.

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
| 1 | **#175 J - HITL approvals API queue contract** (H4) | Server-side pagination/filter/sort/tenant scope behind the existing `/v1/approvals` routes. Unblocks true at-scale queue behavior in the console (#164 is UI-only). |
| 2 | **#162 B - generic redaction fallback** (H4) | Redaction currently misses unknown secret shapes. Security-sensitive; coordinate with `core/services`/observability owners. |
| 3 | **Backend support for UX where agreed** | Prefer bot-win owns the `ui/` surface. Take narrowly-scoped backend contracts only after agreeing in the issue (e.g. #152 jobs API). |
| 4 | **Roadmap/docs reconciliation** | Small post-merge doc PRs; avoid concurrent edits to the same files. |

Completed by this workstream since the last split: #121 hybrid policy registry, #122 CEL
evaluator + bundles, #123 HITL workflow, #124 eval dataset schema/loaders, #125 CI
regression gates, #126 eval dashboard metrics, #127 golden paths, #128 `genai init`,
#129 onboarding guide.

## Work items for enterprise-gen-ai-bot-win — UX/console and docs polish

| Order | Item | Notes |
|---|---|---|
| 1 | **#152 UX9 - Background evaluation jobs** (H4, P0) | UX contract + state; may need agreed backend slice from bot-uni. |
| 2 | **#153 UX10 - Dataset Studio authoring** (H4, P1) | Align schema with delivered #124 loaders. |
| 3 | **#154 UX11 - Cross-link and compare operational evidence** (H4, P1) | Trace/audit/metrics/governance links and two-trace diff; #164 deliberately left broader navigation here. |
| 4 | **#155 UX12 - Command palette + WCAG 2.2 AA** (H4, P1) | A11y/UI shell. |
| 5 | **#156 UX13 - Responsive/compact/themes** (H4, P2) | UI polish. |
| 6 | **#157 UX14 - Role journeys + demo mode** (H4, P2) | Onboarding experience. |
| 7 | **#158 UX15 - Collaboration and feedback** (H4, P2) | UI feature. |
| 8 | **Roadmap/docs reconciliation** | Low-risk docs sync after merges. |

Completed by this workstream since the last split: #130-#136, #145, #151 (workspace/deep
links), #163 (HITL review console) and #164 (queue operations/SLA/safe export).

## Suggested operating rules (to avoid collisions)

- **Claim before starting:** comment on the issue with the bot identity and open a draft
  PR early; re-check `gh pr list` and issue state each time.
- **Ownership boundary:** bot-uni = `core/`, `app/`, `config/`, registries, CI, CLI,
  eval/policy backend; bot-win = `ui/`, UX flows, console docs — except explicitly split
  backend contracts agreed in the issue.
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
- **Project #8:** the board is user-owned and human-managed by request; bot App tokens
  cannot update its items reliably.
