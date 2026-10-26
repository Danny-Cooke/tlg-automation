# Remote state, same bucket as the other stacks, own key.
terraform {
  backend "s3" {
    bucket       = "tlg-automation-terraform-state"
    key          = "tlg-automation/prod/academy.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
