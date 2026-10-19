"""MCP server exposing the project's knowledge base to Claude Code.

Run from the repo root:  python -m knowledge_mcp
Registered for this project in .mcp.json as `tlg-knowledge`.
"""
from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer

from .index import KnowledgeIndex

INDEX = KnowledgeIndex()

server = MCPServer(
    "tlg-knowledge",
    version="0.1.0",
    instructions=(
        "Project knowledge for The Looking Glass salon automation. Use these tools for any "
        "fact about the salon, team, services, prices, Fresha, Meta setup or past decisions "
        "instead of recalling from memory. Everything comes from files in the repo, so an "
        "answer here can be traced to a file."
    ),
)


@server.tool()
def search_knowledge(query: str, limit: int = 5) -> list[dict]:
    """Full-text search over docs, decisions, persona, knowledge notes and salon data.
    Returns chunks with source path, heading, text and score."""
    return INDEX.search(query, limit=limit)


@server.tool()
def find_services(query: str, limit: int = 20) -> list[dict]:
    """Find Fresha services by name, category or keyword. Each result has category, name,
    price, duration, staff (who can be booked for it) and notes."""
    return INDEX.find_services(query, limit=limit)


@server.tool()
def who_does(service_name: str) -> list[dict]:
    """Which team members Fresha lets a client book for a service."""
    return INDEX.who_does(service_name)


@server.tool()
def team_member(name: str) -> dict:
    """One team member: role, booking link, the categories they appear in and every
    service they are bookable for."""
    found = INDEX.team_member(name)
    if found is None:
        return {"error": f"no team member called {name!r}", "team": [m["name"] for m in INDEX.team()]}
    return found


@server.tool()
def team() -> list[dict]:
    """All team members with role, categories and personal booking link."""
    return INDEX.team()


@server.tool()
def salon_facts() -> dict:
    """Name, address, phone, opening hours, general booking link and standing notes."""
    return INDEX.salon_facts()


@server.tool()
def service_categories() -> dict[str, int]:
    """Fresha category names, spelled as Fresha shows them, with service counts."""
    return INDEX.categories()


@server.tool()
def read_source(path: str) -> str:
    """Read a whole repo file by relative path, e.g. docs/decisions.md or
    terraform/salon.auto.tfvars."""
    return INDEX.read_source(path)


@server.tool()
def list_sources() -> dict:
    """What is indexed: chunk counts by kind and the list of source files."""
    return INDEX.stats()


@server.tool()
def reload_index() -> dict:
    """Re-read every source file after edits. Returns the new stats."""
    return INDEX.reload()


def main() -> None:
    # Prices contain "£"; make sure the stdio transport is UTF-8 on Windows too.
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
