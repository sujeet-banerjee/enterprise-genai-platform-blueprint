terraform {
  required_version = ">= 1.5.0"
}

variable "enable_persistent_storage" {
  type    = bool
  default = true
}

# Skeleton module - cloud-specific storage classes configured in environments
output "storage_ready" {
  value = var.enable_persistent_storage
}
