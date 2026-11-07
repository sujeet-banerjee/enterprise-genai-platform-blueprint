# Bot work split (H4 / current open items)
Reconciled 2026-11-07 from `origin/main` @ `86f5fc0` (PR #159 merged). No open PRs. Open H4: J #122-#123, K #124-#126, L #127-#129, M/UX #151-#158; umbrella #43. No assignees/claim PRs. Re-check open PRs/issues before each item.

## Bot identities
- **enterprise-gen-ai-bot-uni[bot]** (this agent) — GitHub user id `353626911`, App `enterprise-gen-ai-bot-uni` (App ID `5652767`, Client ID `Iv23liwXdRBYiE8NXU8d`, installation `179480668` on `sujeet-banerjee/enterprise-genai-platform-blueprint`). Git author/committer: `enterprise-gen-ai-bot-uni[bot] <353626911+enterprise-gen-ai-bot-uni[bot]@users.noreply.github.com>`. Auth via installation token (JWT signed with key outside repo). Co-author hook kept.
- **enterprise-gen-ai-bot-win** (parallel agent) — author of PR #159 (`docs/ux8-ux15-roadmap`); confirm its canonical git/app identity from its own session before it commits.

## Work items for enterprise-gen-ai-bot-uni  — platform/backend (low `ui/*` conflict)
| Order | Item | Notes |
|---|---|---|
| 1 | **#122 J - CEL evaluator + policy bundles** (H4, security/platform/roadmap) | Builds on #121 interface; backend/policy core. Local branch `feature/122-cel-policy-bundles` exists — rebase onto `origin/main` (`86f5fc0`) before work. |
| 2 | **#123 J - HITL approval workflow** (H4) | Security/policy path; follows #122. |
| 3 | **#124 K - Eval dataset schema + loaders** (H4) | Core/eval plumbing; unblocks #125/#126. |
| 4 | **#125 K - CI regression gates for eval** (H4) | CI/workflow + eval; follows #124. |
| 5 | **#127 L - Golden path templates** (H4) | Config/templates; enables #128. |
| 6 | **#128 L - `genai init` CLI scaffolding** (H4) | CLI/tooling (outside `ui/*`). |
| 7 | **#129 L - Onboarding guide + validation** (H4) | Docs + config validation hooks (coordinate if docs PRs appear). |
| 8 | **Backend support for UX where needed (split, by agreement)** | e.g. APIs/persistence hooks required by **#152** background eval jobs — prefer bot-win owns UX surface; I take narrowly-scoped backend contract PR only if agreed up front in the issue. |

## Work items for enterprise-gen-ai-bot-win — UX/console, docs polish, cross-link UI
| Order | Item | Notes |
|---|---|---|
| 1 | **#151 UX8 - Persistent workspace + shareable deep links** (H4, P0, ui/ux) | `ui/*` heavy; foundation for other UX. |
| 2 | **#152 UX9 - Background eval jobs with progress/cancel/resume** (H4, P0, ui/ux) | UX surface + state; may need a small backend contract (bot-uni can pair on that slice if requested/agreed). |
| 3 | **#153 UX10 - Dataset Studio authoring** (H4, ui/ux) | UI workflow; align schema with #124. |
| 4 | **#154 UX11 - Cross-link and compare operational evidence** (H4, ui/ux) | Console cross-linking; `ui/*` conflict-prone. |
| 5 | **#155 UX12 - Command palette + WCAG 2.2 AA hardening** (H4, ui/ux) | A11y/UI shell. |
| 6 | **#156 UX13 - Responsive/compact/theme system** (H4, ui/ux) | UI polish. |
| 7 | **#157 UX14 - Role-based guided journeys + demo mode** (H4, ui/ux) | UX/onboarding experience. |
| 8 | **#158 UX15 - Collaboration and feedback capture** (H4, ui/ux) | UI feature. |
| 9 | **#126 K - Eval dashboard enhancements** (H4, observability/platform) | Observability UI; backend metrics come from K/#124-#125. *Alternative split by agreement:* bot-uni backend metrics, bot-win dashboard. |
| 10 | **Roadmap/docs reconciliation PRs** (like #159) | Low-risk docs sync after merges. |

## Suggested operating rules (to avoid collisions)
- **Claim before starting:** comment on the issue "taking this as bot-uni" / "taking this as bot-win" (shared convention) + open a draft PR early; re-check `gh pr list` and issue state each time.
- **Ownership boundary:** bot-uni = `core/`, `app/`, `config/`, registries, CI, CLI, eval/policy backend; bot-win = `ui/`, UX flows, console docs — **except** explicitly split items (#126, #152 backend contract) agreed in the issue.
- **Rebase discipline:** both rebase feature branches onto latest `origin/main` before PR/merge; land small PRs to reduce conflicts.
- **`ui/` rule (project):** `ui/` is HTTP-only (never imports `app.*`/`core.*`); new UI helpers in `ui/*.py` (pure, Streamlit-free) with tests.
- **Config/architecture (project):** config-driven (`config/**/*.yaml` + schema/validator/secrets + registries) -> `app/bootstrap.py::assemble_components` -> `app/pipeline.py` -> `app/main.py`; safe/off defaults for new knobs.
- **Quality:** feature branches + PR + rebase + delete branch; >=6 tests for code changes where required; all CI checks green before merge (lint/ruff, mypy, pytest 3.11/3.13, Deploy smoke chart+image, CodeQL/Analyze).
- **`#43` umbrella:** update checklist/status only in dedicated small PRs or after merges (avoid concurrent edits).
- **Identity:** each bot uses its own verified GitHub App/bot git identity and app auth for push/PR/issue ops; never log keys/tokens; keep `.pem` outside repo.
