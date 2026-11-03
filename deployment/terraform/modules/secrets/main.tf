terraform {
  required_version = ">= 1.5.0"
}

variable "namespace" {
  type    = string
  default = "genai-platform"
}

variable "enable_external_secrets" {
  type    = bool
  default = true
}

resource "helm_release" "external_secrets" {
  count            = var.enable_external_secrets ? 1 : 0
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  namespace        = "external-secrets"
  create_namespace = true
  version          = "0.10.5"
}
