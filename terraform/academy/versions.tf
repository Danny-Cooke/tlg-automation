terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "tlg"
      Repository  = "tlg-automation"
      Environment = var.environment
      Stack       = "academy"
      ManagedBy   = "terraform"
      Owner       = var.owner_email
    }
  }
}

# CloudFront only accepts certificates from us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "tlg"
      Repository  = "tlg-automation"
      Environment = var.environment
      Stack       = "academy"
      ManagedBy   = "terraform"
      Owner       = var.owner_email
    }
  }
}
