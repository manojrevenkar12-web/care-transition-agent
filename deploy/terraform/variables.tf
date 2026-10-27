variable "region" {
  type    = string
  default = "eu-central-1"
  validation {
    condition     = startswith(var.region, "eu-")
    error_message = "Health data stays in an EU region."
  }
}
variable "environment" { type = string }
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "tenants" {
  description = "Hospitals served by this deployment; each gets its own KMS key for its data keys."
  type        = list(string)
}
variable "agent_image" { type = string }
variable "gateway_image" { type = string }
variable "certificate_arn" { type = string }
variable "allowed_cidrs" {
  description = "Hospital networks that may reach the console."
  type        = list(string)
}
variable "bedrock_models" {
  description = "Model and inference-profile ARNs the gateway may invoke."
  type        = list(string)
  default = [
    "arn:aws:bedrock:eu-central-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:eu-*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:eu-central-1:*:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:eu-central-1:*:inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "arn:aws:bedrock:eu-*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
  ]
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
