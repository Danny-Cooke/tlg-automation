# tlg-automation

Automation for **The Looking Glass** salon (TLG Beauty Limited).

The goal is to take admin off the salon manager, Jess, by:

1. Answering Facebook Messenger and Instagram DMs in Jess's voice, handling the
   booking conversation and pointing clients at the right Fresha booking link.
2. Escalating anything out of the ordinary (complaints, refunds, unusual requests)
   to Jess so she can step in.
3. Keeping each staff member's Google Calendar in step with Fresha, driven by
   config rather than clicks.

See `docs/architecture.md` for the design and `docs/decisions.md` for the
reasoning behind the main choices.

## Layout

| Path | What it is |
|---|---|
| `docs/` | Architecture, decisions, setup notes, calendar sync guide |
| `knowledge/` | Facts that are not code: Fresha ids and how to read it, open questions for Jess |
| `knowledge_mcp/` | Local MCP server + BM25 index over the repo, so Claude Code queries files instead of memory (`.mcp.json`, `CLAUDE.md`) |
| `persona/jess.md` | Jess's voice and salon rules. Versioned prompt asset, loaded by the bot |
| `src/bot/` | Python Lambda: Meta webhook, conversation state, Claude call, replies, escalation |
| `src/menu_sync/` | Scheduled Lambda: reads Fresha's team and menu, regenerates `terraform/fresha-menu.auto.tfvars.json`, opens a PR when it differs |
| `src/monitor/` | Scheduled Lambda: checks the webhook, Meta token, Fresha links and Fresha dashboard code, alerts the ops topic on change or failure |
| `tests/` | Unit tests for the bot (no network) |
| `terraform/` | AWS infrastructure (API Gateway, Lambdas, DynamoDB, SNS, IAM). `salon.auto.tfvars` is hand-written; `fresha-menu.auto.tfvars.json` is generated |
| `scripts/` | Lambda bundle build, and the Meta webhook wiring done over the Graph API |

## Quick start

```bash
# Python
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash
pip install -r src/requirements.txt -r requirements-dev.txt -r requirements-mcp.txt
pytest

# Knowledge MCP server (Claude Code starts it from .mcp.json; run by hand to check)
python -m knowledge_mcp

# Terraform
cd terraform
cp example.tfvars terraform.tfvars   # fill in page IDs, staff, Jess's contact details
terraform init && terraform plan
```

## Status

Scaffold only. Nothing is deployed yet. See `docs/architecture.md` for the
build order.
