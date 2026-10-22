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

Agent-authored commits are co-attributed via a tracked git hook. The hook lives in
`.githooks/prepare-commit-msg` and appends:

```
Co-authored-by: ai-opencode-big-pickle <agent-smith@opencode.local>
```

It is **idempotent** (skips if the trailer is already present) so amends and rebase replays do
not stack duplicates. The human author/committer identity is unchanged — this only adds the
agent's co-authorship to the commit metadata.

Git does **not** run committed hooks automatically (a deliberate security decision), so after
cloning, opt in **once**:

```bash
git config --local core.hooksPath .githooks
```

CI only checks out and tests, so the hook never fires there and the pipeline is unaffected.

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
  `H2 - Product surface`, `H3 - Enterprise scale & compliance`.
- Pick up an open issue from the active horizon. H0 (observability, config validation,
  resilience, deployment playbook and delivery artifacts, plus the first guardrail slices)
  is complete; the current focus is **H1 - Multi-tenant & governed** (#48-#57), with
  Workstream G follow-ups (#64, #68-#71) after that. The roadmap document and the GitHub
  Project board are the source of truth for ordering.

## License

By contributing, you agree your contributions are licensed under the MIT License (see
[`LICENSE`](LICENSE) / the README).
