# Working on this repo

## Project knowledge lives here, not in memory

All facts about the salon, the team, Fresha, Meta and past decisions are files
in this repo and are served by the `tlg-knowledge` MCP server (`.mcp.json`).
Before answering or coding against any salon fact, query it:

- `search_knowledge` for anything in docs, decisions, persona or notes.
- `find_services`, `who_does`, `team_member`, `team`, `salon_facts`,
  `service_categories` for structured salon data.
- `read_source` to read a whole file. `reload_index` after editing a source.

Do not answer salon questions from recall. If a fact is missing, add it to the
repo (see below) and reload, rather than carrying it in auto-memory. Auto-memory
is for how the user likes to work, not for salon facts.

## Where things go

| What | Where |
|---|---|
| Hours, address, general link, notes to the bot | `terraform/salon.auto.tfvars` (hand-written, committed) |
| Staff, services, prices, who does what | `terraform/fresha-menu.auto.tfvars.json` (generated from Fresha by `src/menu_sync`; fix in Fresha, not here) |
| Fresha facts, ids, how to read Fresha | `knowledge/fresha.md` |
| Things Jess still needs to confirm | `knowledge/open-questions.md` |
| Design and why | `docs/architecture.md`, `docs/decisions.md` |
| Agreed jobs, open decisions, what is parked | `docs/plan.md` (read first in a new session) |
| Operator steps (Meta, AWS, calendar) | `docs/setup.md`, `docs/calendar-sync.md` |
| Jess's voice and hand-over rules | `persona/jess.md` (identity, rules), `persona/voice-guide.md` (how a reply is built), `persona/vocabulary.md` (word bank); all built from the real message history, see `docs/voice-analysis.md` |
| Facts the team told clients in chat, not yet confirmed | `knowledge/from-messages.md` |
| CPD course accreditation (The CPD Group): what they want, where our courses and their material are | `knowledge/cpd-accreditation.md`, then `cpd-tlg/` and `cpddocs/` |

## Conventions

- The user is an AWS DevOps engineer. Default to AWS and Terraform; explain
  salon systems (Fresha, Meta), not AWS.
- Fresha has no public write API. The bot books nails through Fresha's
  internal dashboard API with the owner's stored session (`src/bot/fresha.py`,
  `knowledge/fresha-internal-api.md`); everything else it links to Fresha.
- Fresha category names are kept exactly as Fresha spells them.
- Run `python -m pytest -q` and `terraform validate` before calling work done.
- Nothing is committed unless the user asks.

## Setup for the MCP server

```
python -m pip install -r requirements-mcp.txt
```

Claude Code starts it automatically from `.mcp.json` when this folder is the
project. Check with `/mcp`.
