terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State bucket created by hand 2026-10-19. Key is <repo>/<environment>.
  # Locking uses the S3 lockfile, which needs Terraform 1.10 or later.
  # backend "s3" {
  #   bucket       = "tlg-automation-terraform-state"
  #   key          = "tlg-automation/prod/terraform.tfstate"
  #   region       = "eu-west-2"
  #   encrypt      = true
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "tlg"
      Repository  = "tlg-automation"
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner_email
    }
  }
}
