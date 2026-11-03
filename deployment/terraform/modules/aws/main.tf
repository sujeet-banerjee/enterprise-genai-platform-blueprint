terraform {
  required_version = ">= 1.5.0"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  type    = string
  default = "genai-platform"
}

variable "enable_eks" {
  type    = bool
  default = false
}

variable "enable_rds_postgres" {
  type    = bool
  default = false
}

variable "enable_s3" {
  type    = bool
  default = false
}

variable "enable_secrets_manager" {
  type    = bool
  default = false
}

# Skeleton module for AWS (G6). Apply in demo only with valid credentials.
# Uses generic patterns; cloud-agnostic core remains default.

output "module" {
  value = "aws"
}

output "region" {
  value = var.region
}
