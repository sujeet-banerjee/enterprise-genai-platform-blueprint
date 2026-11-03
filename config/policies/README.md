# Policy-as-code delivery (G5)

Policies are versioned under `config/policies/` and reconciled by GitOps. 
The guardrail framework (B1) and policy engine (J, H4) will consume these bundles.
Never commit secrets. Use `env:` or external secret references.

## Structure
- `input/` - input policies (injection/PII/access)
- `output/` - output policies (redaction/deny lists)
- `bundles/` - policy bundles with version and checksum
- `schema.json` - policy schema (to be added in #121)
