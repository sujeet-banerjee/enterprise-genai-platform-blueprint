# Engineering lifecycle

> How work moves from an issue to `main`: issue structure, branch and PR
> conventions, the checks that actually block a merge, evidence expectations, and
> the working agreement for human contributors and coding agents.
>
> This document describes the repository as configured on **2026-11-14**. Verify
> branch protection and workflow names before relying on a number; see
> [Verifying the gates](#verifying-the-gates).

## Audience and ground rules

This is the lifecycle for anyone changing the repository, including independent
agents that pick up a single issue. It assumes the design rules in
[CONTRIBUTING.md](../CONTRIBUTING.md): config-driven and vendor-neutral, new
backends behind an interface plus a registry, `app/main.py` free of concrete
implementation imports, and tests that exercise real behaviour.

The unit of work is **one issue -> one branch -> one pull request**. If you find
an unrelated defect, open or link an issue instead of widening the current change.

## 1. The work item

Every non-trivial change starts as a GitHub issue (the roadmap umbrella is #43;
work is grouped into horizons via milestones and the GitHub Project board).

A useful issue has four sections:

| Section | Purpose |
| --- | --- |
| **Summary** | The problem, who is affected and why it matters now. |
| **Scope** | The specific behaviour, files or surfaces in play. |
| **Acceptance criteria** | Observable, checkable outcomes - not implementation steps. |
| **Out of scope** | What a reviewer should *not* expect this issue to change. |

Labels describe type/area (`bug`, `enhancement`, `documentation`, `security`,
`deployment`, `roadmap`, ...), and an owner label where a lane is split. Before
starting:

1. Read the issue, `docs/bot-work-split.md` (if present) and the roadmap entry.
2. Search open and closed issues and open PRs for duplicates or prior attempts.
3. Inspect the current code, tests and configs the issue touches. Do not assume
   the issue text is still accurate.
4. Check the issue is unclaimed; claim it with a short comment describing your
   plan and intended scope.

**Definition of ready:** the problem is reproducible or the gap is demonstrable,
acceptance criteria are testable, and the touched interfaces/config are known.

## 2. Branch and implementation

```bash
git fetch origin
git checkout -b feature/<issue>-<slug> origin/main
# fix/<issue>-<slug> for defects
```

- Branch from the latest `origin/main`; keep branches short-lived.
- Keep commits focused and use conventional scoped messages (`feat(area): ...`,
  `fix(area): ...`, `docs(area): ...`), with the issue reference in the body
  (`Closes #123` when the PR should close it).
- Prefer additive changes. Breaking interface changes need a note in the PR, a
  migration path, and an update to `INTERFACE_CHANGES.md`.
- New configurable behaviour belongs in `config/*.yaml`, a model in
  `core/config/schema.py`, and a registry/factory - with a safe, usually disabled,
  default. The full matrix of config files and knobs is in
  [architecture.md](architecture.md) and the README.
- Do not import concrete `core.implementations.*` classes from `app/main.py`
  (the composition root in `app/bootstrap.py` is the assembly point). `ui/*` must
  stay HTTP-only: no `app.*` or `core.*` imports.
- Never commit secrets, tokens, keys or `.env` files.

## 3. Local verification

Run the same commands CI runs before opening a PR:

```bash
python -m ruff check .
python -m mypy app core
python -m pytest
```

The test job adds coverage (`--cov=app --cov=core --cov-fail-under=78`). For
non-trivial behavioural changes, add **at least 6 meaningful test cases** and
prefer real model/pipeline paths over mocks. If a capability cannot be exercised
locally (for example a CLI that is not installed), write a structural guard and
document why it skips.

## 4. Pull request

Open a **draft PR early** so CI starts while you finish the description, then mark
it ready. A PR description should state:

- `Closes #<issue>` (or `Refs #<issue>` for partial work).
- What changed and why, including config/interface impact.
- **Verification evidence**: focused tests, full-suite result, lint/type result,
  and any render/smoke check.
- Known limitations and deliberate non-goals.

Keep the diff limited to the issue. Documentation and config tables that describe
changed behaviour are part of the change, not a follow-up: update README,
`docs/architecture.md`, API contracts (`tests/test_api_contract.py::EXPECTED_PATHS`)
and `INTERFACE_CHANGES.md` where applicable.

## 5. Checks: required vs advisory

Branch protection on `main` is **strict** (the branch must be up to date), force
pushes and branch deletion are disabled, and **no approving review is required**
(0 approvals). Administrators are exempt from branch protection
(`enforce_admins=false`). Self-merge is therefore possible after the required
checks pass.

These four status checks are **required** and block merge:

| Required check | Workflow job | What it proves |
| --- | --- | --- |
| `Lint (ruff)` | `lint` | Style/import errors are absent. |
| `Type check (mypy)` | `typecheck` | `app` and `core` type-check. |
| `Tests (Python 3.11)` | `test` matrix | Full suite + coverage gate on 3.11. |
| `Tests (Python 3.13)` | `test` matrix | Full suite + coverage gate on 3.13. |

These jobs run on the PR but are **not** configured as required status checks:

| Advisory check | Why it still matters |
| --- | --- |
| `Deploy smoke (chart + image)` | Helm/Kustomize render, image build, `/health` + `/ready` smoke. |
| `Eval regression gates` | Config-driven eval/benchmark/golden-path/scaffold checks. |
| `CodeQL` / `Analyze (python)` / `Analyze (actions)` | Security analysis (default setup; not a branch-protection context). |

Treat advisory failures as blocking anyway; they catch deployment and security
regressions that unit tests do not. Do not describe the PR as "reviewed" or
"approved" unless a human actually reviewed it - GitHub does not enforce an
approval.

## 6. Merge, close and track

1. Rebase on the latest `origin/main` if the branch is behind (the required checks
   are strict).
2. Wait for the four required checks to pass. Do not merge red.
3. Use **rebase merge** to keep a linear trunk, and delete the branch:

   ```bash
   gh pr merge <pr> --rebase --delete-branch
   ```

4. Confirm the issue closed (the `Closes #...` trailer auto-closes it). If work was
   partial, leave it open and comment with what remains.
5. Move the GitHub Project item to **Done** and update roadmap/checklists in the
   same or a follow-up docs PR. Do not mark a capability Done because an interface
   or stub exists.

If a required check fails after a commit, push a new fix commit; do not force-push
or rewrite published history. If `main` advances, rebase rather than merging
`main` into the branch.

## 7. Agent working agreement

Coding agents follow the same lifecycle plus these rules:

- **Inspect first.** Read the issue, open PRs/issues, `docs/bot-work-split.md`,
  and the relevant code/tests/configs before writing anything. State assumptions.
- **Stay in scope.** One issue per branch and PR. File a new issue (after a
  duplicate check) for unrelated defects instead of bundling fixes.
- **Use the lane boundaries.** `ui/` is HTTP-only and may be owned separately;
  backend work goes through interfaces, registries and `app/bootstrap.py`.
- **Evidence over assertion.** Report commands and results; never claim a check
  passed without running it, and never claim human review.
- **Config safety.** New knobs ship with schema validation and safe/off defaults;
  secret references use `${VAR}`/`env:VAR`, never literals.
- **Commit identity.** Use the agent's dedicated GitHub App bot identity
  (`user.name <app-slug>[bot]`, noreply email). Never use or expose the App
  private key.
- **Clean up.** Delete the merged branch, update the issue and Project status, and
  leave the working tree clean.

## 8. Worked example: #188 architecture diagram -> PR #215

A representative end-to-end cycle from this repository:

1. **Issue:** [#188 high-level architecture diagram](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/188)
   with Summary/Scope/Acceptance/Out of scope.
2. **Claim:** a comment describing the planned artifact, legend and guards; branch
   `feature/188-architecture-diagram` from `main`.
3. **Implement:** `docs/architecture-diagram.md` (Mermaid source, legend,
   component-to-code map), links from README and `docs/architecture.md`, and
   `tests/test_architecture_diagram.py` (10 structural guards).
4. **Verify:** focused tests, full suite (1401 passed / 9 skipped), Ruff, mypy, and
   an independent Mermaid render via Kroki.
5. **PR:** [#215](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/pull/215)
   opened as a draft with `Closes #188`, then marked ready with evidence and a
   documented limitation (`mmdc` render skips when the CLI is absent).
6. **Merge:** rebase merge -> `2f66d8a`, branch deleted; the issue auto-closed and
   the Project item moved to Done.

The corresponding PR check list shows the four required contexts plus the advisory
Deploy smoke, Eval gates, Analyze and CodeQL results; only the four required
contexts above gate the merge.

## 9. Verifying the gates

Do not trust this document blindly - branch protection is repository settings, not
versioned code. Check it with:

```bash
gh api repos/:owner/:repo/branches/main/protection \
  --jq '{required: .required_status_checks.contexts, strict: .required_status_checks.strict,
         approvals: .required_pull_request_reviews.required_approving_review_count,
         force_push: .allow_force_pushes.enabled, deletions: .allow_deletions.enabled}'
```

Workflow job names live in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml);
the `name:` field is the status context. If you change a job name, update branch
protection and this table in the same change.

## 10. Where to start

Pick an open issue from the GitHub Project board or the roadmap. Prefer issues
with an owner label matching your lane, clear acceptance criteria and no open PR.
If the issue is stale, comment with what you found before expanding scope; if the
design is unclear, ask in the issue rather than guessing.
