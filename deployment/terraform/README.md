# Terraform modules for GitOps at scale (G5/G6)

Cloud-agnostic core modules. **G6 adds cloud-specific modules** (AWS/Azure/GCP) and multi-region environment skeletons.

## Modules
- `modules/cluster-addons`: Argo CD/Flux, ingress, cert-manager, monitoring basics
- `modules/secrets`: External Secrets / secret store integration (no plaintext)
- `modules/storage`: PVC/storage classes for model cache and persistence
- `modules/aws|azure|gcp`: Cloud-specific skeletons (enable flags, default off)

## Environments
- `environments/dev|staging|prod`: reference usage
- `environments/multi-region`: primary/secondary with cloud modules

## Usage
```bash
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply
```

All modules are documentation + skeletons to keep the repo reviewable without cloud credentials. See `docs/dr-runbook.md` and `config/residency.yaml`.
