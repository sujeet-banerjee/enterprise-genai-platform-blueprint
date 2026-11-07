# Contributing

Thanks for contributing to the enterprise-genai-platform-blueprint. This project is a
config-driven, vendor-neutral GenAI/RAG platform; contributions should keep it that way.

## Ground rules

- **Config-driven, vendor-neutral.** New backends are added behind a `core/interfaces/`
  contract, exposed through a `core/registry/` factory, and selected in `config/*.yaml`.
  `app/main.py` (the composition root) must never import a concrete implementation directly.
- **Interfaces stay stable.** Prefer additive changes to interfaces; breaking changes need a
  note in the PR and a migration path.
- **Tests are required.** Every behavioural change needs tests, and they should exercise real
  behaviour (a real local model / real pipeline path where practical), not just mocks. Aim for
  **at least 6 new test cases** per non-trivial issue.
- **Keep the suite green.** Do not push while lint, mypy, or tests fail.

## Branching model (trunk-based)

- `main` is the trunk and is **protected** (no direct pushes; PR required).
- Work on a short-lived branch named `feature/<issue>-<slug>` (e.g.
  `feature/44-prometheus-metrics`). Fix branches may be `fix/<issue>-<slug>`.
- One issue -> one branch -> one PR. Keep branches small and short-lived; rebase on `main`
  rather than merging `main` in.
- One logical change per commit, ideally one commit per fix.

```bash
git checkout -b feature/<issue>-<slug>
# ...make changes...
git -c core.editor=true pull --rebase origin main
git push -u origin feature/<issue>-<slug>
gh pr create --fill
```

### Before every commit

```bash
python -m ruff check .
python -m mypy app core
python -m pytest
```

CI additionally runs the coverage gate: `--cov-fail-under=78`.

> On Windows, remove the untracked Word lock file before committing:
> `Remove-Item -LiteralPath "docs/~`$-and-api.md" -Force -ErrorAction SilentlyContinue`.

## Pull request checklist

- [ ] Branch is rebased on the latest `main`.
- [ ] `ruff check .`, `mypy app core`, and `pytest` are all green locally.
- [ ] New behaviour is covered by real tests (>= 6 for a non-trivial issue).
- [ ] No concrete implementation is imported by `app/main.py`.
- [ ] Any `ui/*` change is HTTP-only (never imports `app.*` or `core.*`).
- [ ] `tests/test_api_contract.py::EXPECTED_PATHS` updated if a route was added.
- [ ] Docs/config tables updated (`README.md`, `docs/architecture.md`).
- [ ] No secrets, keys, tokens, or credentials committed.
- [ ] The linked issue references the change and is closed once merged.

## Commit messages

Use a conventional, scoped prefix mirroring the existing history:

```
feat(<area>): <what changed>
fix(<area>): <what changed>
docs(<area>): <what changed>
```

Reference the issue number in the body (`Refs #44` / `Closes #44`).

## Commit attribution

Agent commits are authored by a dedicated GitHub App bot identity, not by the human
maintainer. Each agent should use its own GitHub App installed on this repository with only
the permissions it needs.

The bot identity is configured in that agent's dedicated working copy:

- `user.name`: `<app-slug>[bot]`
- `user.email`: `<bot-user-id>+<app-slug>[bot]@users.noreply.github.com`

Installation tokens are minted locally from the App private key and expire after one hour.
Private keys and installation tokens are never committed, pasted into issues or pull
requests, or stored in the repository. The human maintainer owns the App and can revoke its
keys or installation at any time.

GitHub links these commits to the App's bot account. They are not signed or marked
**Verified** unless they are created through GitHub's API; this repository does not require
signed commits.

The previous fake co-author hook (`.githooks/prepare-commit-msg`) has been removed. Commits
that already contain the historical co-author trailer should not be rewritten.

## Releases

- Releases are annotated git tags following **semantic versioning**: `v<major>.<minor>.<patch>`.
- Tag the trunk after a milestone (horizon) completes.

```bash
git tag -a v0.4.0 -m "H0 - Observability & hardening"
git push origin v0.4.0
```

Existing tags: `v0.2.0-pluggable-vendors` (foundations era) and `v0.3.0` (reference-blueprint
era complete).

## Roadmap & tracking

- The enterprise roadmap lives in [`docs/enterprise-roadmap.md`](docs/enterprise-roadmap.md)
  and is tracked by umbrella issue **#43**.
- Work is organized into **horizons** (GitHub milestones):
  `H0 - Observability & hardening`, `H1 - Multi-tenant & governed`,
  `H2 - Product surface`, `H3 - Enterprise scale & compliance`,
  `H4 - Post-G6 hardening & UX`.
- H0/H1, Workstream G (deployment/delivery), Workstream H (ingestion #115-#117),
  operational DR (#118-#120) and workstream M UX polish (#130-#136, #145) are complete.
  The open bridge is workstreams I-L (#121-#129: policy-as-code, eval expansion/CI gates,
  onboarding/golden paths) plus the next UX tranche (#151-#158). Pick an open issue from
  that set; the roadmap document and the GitHub Project board are the source of truth for
  ordering.

## License

By contributing, you agree your contributions are licensed under the MIT License (see
[`LICENSE`](LICENSE) / the README).
