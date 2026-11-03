module "cluster_addons" {
  source         = "../../modules/cluster-addons"
  namespace      = "argocd"
  install_argocd = true
  install_flux   = false
}

module "secrets" {
  source                   = "../../modules/secrets"
  namespace                = "genai-platform"
  enable_external_secrets  = true
}

module "storage" {
  source                   = "../../modules/storage"
  enable_persistent_storage = true
}
