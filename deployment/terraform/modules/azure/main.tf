terraform {
  required_version = ">= 1.5.0"
}

variable "location" {
  type    = string
  default = "eastus"
}

variable "resource_group" {
  type    = string
  default = "genai-platform"
}

variable "enable_aks" {
  type    = bool
  default = false
}

variable "enable_postgres" {
  type    = bool
  default = false
}

variable "enable_blob" {
  type    = bool
  default = false
}

variable "enable_keyvault" {
  type    = bool
  default = false
}

output "module" {
  value = "azure"
}

output "location" {
  value = var.location
}
