# Config versioning and rollback (G4 / issue #69)

All YAML under `config/` is validated by `core/config/validator.py` with an optional
`config_version` (currently `1`). Version drift emits a warning; unknown keys are
rejected at the top level.

## Rollback procedure

1. **Revert the git commit** that changed the config/prompt/model values (or restore
   the previous file contents) and open a PR.
2. **CI** runs `python -m app.config_validate` against the repo configs.
3. **Merge and roll out**: the Kustomize overlay regenerates the ConfigMap with a new
   hash (rolling pods) or redeploy the Helm release with the previous image tag.
4. **Verify**: `GET /ready` returns `config_revision` and a component summary;
   `/v1/config` shows the redacted effective config.
5. **Roll back images** if the new image is bad: redeploy the previous immutable tag
   (Helm `--set image.tag=<previous>` or revert the GitOps manifest). No database
   migration is required to undo config changes; audit JSONL is append-only.

## Progressive delivery

Use Argo Rollouts with `deployment/helm/genai-platform/templates/rollout.yaml` when
`rollout.enabled: true`. Steps include health checks via `/health`/`/ready` and
observability gates (Prometheus metrics/alerts). Keep `autoscaling.enabled` and
`rollout.enabled` mutually compatible via the chart templates.
