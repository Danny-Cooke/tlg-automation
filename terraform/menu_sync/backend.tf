# Remote state. Bucket created by hand 2026-10-19 (London, versioned,
# encrypted, public access blocked). One key per stack:
# <repo>/<environment>/<stack>.tfstate. Locking uses the S3 lockfile, so
# Terraform 1.10 or later is required.
terraform {
  backend "s3" {
    bucket       = "tlg-automation-terraform-state"
    key          = "tlg-automation/prod/menu-sync.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
