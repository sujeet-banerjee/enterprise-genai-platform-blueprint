module "aws_primary" {
  source    = "../../modules/aws"
  region    = "us-east-1"
  enable_eks = false
}

module "aws_secondary" {
  source    = "../../modules/aws"
  region    = "us-west-2"
  enable_eks = false
}

module "cluster_addons" {
  source         = "../../modules/cluster-addons"
  namespace      = "argocd"
  install_argocd = true
  install_flux   = false
}

module "secrets" {
  source                  = "../../modules/secrets"
  namespace               = "genai-platform"
  enable_external_secrets = true
}

module "storage" {
  source                   = "../../modules/storage"
  enable_persistent_storage = true
}
