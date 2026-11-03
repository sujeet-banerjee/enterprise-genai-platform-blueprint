# Terraform modules for GitOps at scale (G5)

Cloud-agnostic core modules. Cloud-specific overlays are deferred to G6.

## Modules
- `modules/cluster-addons`: Argo CD/Flux, ingress, cert-manager, monitoring basics
- `modules/secrets`: External Secrets / secret store integration (no plaintext)
- `modules/storage`: PVC/storage classes for model cache and persistence

## Environments
- `environments/dev|staging|prod`: reference usage

## Usage
```bash
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply
```

All modules are documentation + skeletons to keep the repo reviewable without cloud credentials.
