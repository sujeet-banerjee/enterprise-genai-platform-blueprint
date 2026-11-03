terraform {
  required_version = ">= 1.5.0"
}

variable "project_id" {
  type    = string
  default = ""
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "enable_gke" {
  type    = bool
  default = false
}

variable "enable_cloudsql" {
  type    = bool
  default = false
}

variable "enable_gcs" {
  type    = bool
  default = false
}

variable "enable_secret_manager" {
  type    = bool
  default = false
}

output "module" {
  value = "gcp"
}

output "region" {
  value = var.region
}
