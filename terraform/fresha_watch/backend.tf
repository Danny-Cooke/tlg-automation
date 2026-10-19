# Remote state. Same bucket as the other stacks, one key per stack:
# <repo>/<environment>/<stack>.tfstate. Locking uses the S3 lockfile, so
# Terraform 1.10 or later is required.
terraform {
  backend "s3" {
    bucket       = "tlg-automation-terraform-state"
    key          = "tlg-automation/prod/fresha-watch.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
