# GitOps example (roadmap G2)

A minimal Argo CD `Application` that reconciles the **Kustomize prod overlay** into the
`genai-platform` namespace. The delivery loop is: edit `config/**` or a manifest in git → PR → CI
(config validation + tests + image build/health smoke) → merge to `main` → Argo CD syncs.

```bash
kubectl apply -f deployment/gitops/argocd/application.yaml
argocd app get genai-platform-prod            # or: kubectl -n argocd get applications
```

## Why Kustomize here

The overlay's `configMapGenerator` reads the repository's **real** `config/` directory (no copies),
so a config change is a normal git change and produces a new ConfigMap hash. Kustomize's
nameReference rewrites the Deployment's volume, which rolls the pods and makes the config change
visible on restart (there is no hot reload).

`config/` sits above the overlay root, so both the local CLI and Argo CD must allow loading outside
the kustomization root:

- local: `kubectl kustomize --load-restrictor LoadRestrictionsNone deployment/kustomize/overlays/prod`
- Argo CD: `spec.source.kustomize.buildOptions: --load-restrictor LoadRestrictionsNone` (already set)

## Helm alternative

If you deploy with Helm instead, Argo CD can point at the chart with a values file:

```yaml
spec:
  source:
    repoURL: https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint.git
    targetRevision: main
    path: deployment/helm/genai-platform
    helm:
      valueFiles:
        - values.prod.yaml
```

The chart does not generate the ConfigMap from the repo: mount an existing one
(`config.existingConfigMap`) or rely on the config baked into the image. Use Kustomize when you want
the config-in-git loop above; use Helm when you need chart parameterization/rollbacks.

## Secrets

Never commit secret material. Create the Secret once per environment (or let External Secrets
project it), then reference it from the overlay/chart:

```bash
kubectl -n genai-platform create secret generic genai-platform-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=HF_TOKEN="$HF_TOKEN" \
  --from-literal=GENAI_API_KEY="$GENAI_API_KEY"
```

The overlays set `envFrom.secretRef.name: genai-platform-secrets` with `optional: true`, so a
missing Secret does not block startup (providers that need keys will fail on first use, which the
failure taxonomy reports).
