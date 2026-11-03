# Environment promotion pipeline (G5)

## Flow
1. **Dev**: Auto-sync on merge to `main` (Argo CD/Flux). Config/prompt changes trigger rolling restart via ConfigMap hash.
2. **Staging**: Promote after dev health checks pass (`/health`, `/ready`) and optional eval regression gate.
3. **Prod**: Manual approval gate required. Canary/blue-green via Argo Rollouts (#69) with observability gates.

## Gates
- Config validation: `python -m app.config_validate`
- Tests: lint, mypy, pytest
- Smoke: `/health`, `/ready`, `/v1/query`
- Eval regression: compare against baseline (ties to K workstream)
- Security/policy: guardrail/policy checks (ties to J)

## Process
- Open PR with changes to `config/**`, prompts, or policies
- CI validates and builds image
- Merge → dev syncs
- Run promotion job (documented) to promote to staging, then prod with approval
- Rollback via git revert + image rollback as documented in `docs/deployment.md`
