# AWS deployment in eu-central-1 (Frankfurt). Patient data, model inference (Bedrock through a VPC endpoint) and logs
# stay in the EU region; nothing has a route to the internet except the console's load balancer.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.80" }
  }
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "care-transition-agent", environment = var.environment } }
}
