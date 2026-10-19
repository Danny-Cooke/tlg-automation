# Remote state for the bot stack. Same bucket as the menu sync stack, its own
# key. Not applied by the deploy pipeline yet (the menu sync goes first).
terraform {
  backend "s3" {
    bucket       = "tlg-automation-terraform-state"
    key          = "tlg-automation/prod/bot.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
