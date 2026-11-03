terraform {
  required_version = ">= 1.5.0"
}

variable "namespace" {
  type    = string
  default = "argocd"
}

variable "install_argocd" {
  type    = bool
  default = true
}

variable "install_flux" {
  type    = bool
  default = false
}

resource "helm_release" "argocd" {
  count            = var.install_argocd ? 1 : 0
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  namespace        = var.namespace
  create_namespace = true
  version          = "7.7.0"
  values           = [file("${path.module}/values-argocd.yaml")]
}

resource "helm_release" "flux" {
  count            = var.install_flux ? 1 : 0
  name             = "flux2"
  repository       = "https://fluxcd-community.github.io/helm-charts"
  chart            = "flux2"
  namespace        = "flux-system"
  create_namespace = true
  version          = "2.14.0"
}
