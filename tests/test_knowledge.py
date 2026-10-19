"""The knowledge index is built from the real repo files, so these tests also
guard the salon data: counts, category spelling and who-does-what."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytest.importorskip("hcl2")
pytest.importorskip("rank_bm25")

from knowledge_mcp.index import KnowledgeIndex  # noqa: E402


@pytest.fixture(scope="module")
def index() -> KnowledgeIndex:
    return KnowledgeIndex(ROOT)


def test_indexes_every_source(index):
    stats = index.stats()
    assert "docs/decisions.md" in stats["sources"]
    assert "knowledge/fresha.md" in stats["sources"]
    assert "persona/jess.md" in stats["sources"]
    assert "terraform/fresha-menu.auto.tfvars.json" in stats["sources"]
    assert stats["by_kind"]["service"] == 166  # Fresha snapshot 2026-10-19
    assert stats["by_kind"]["staff"] == 8


def test_categories_are_fresha_spelling(index):
    cats = index.categories()
    assert cats["Senior Nail Services - TLG"] == 19
    assert cats["Nails by TLG"] == 6
    assert cats["Bernadettes ReFresh aethetics"] == 60
    assert len(cats) == 8


def test_every_service_has_staff(index):
    missing = [s["name"] for s in index.salon["services"] if not s.get("staff")]
    assert missing == []


def test_who_does_make_up(index):
    hits = index.who_does("Make up by the lash goblin")
    assert hits[0]["staff"] == ["Amber", "Carmen"]


def test_carmen_does_no_lashes(index):
    carmen = index.team_member("carmen")
    assert carmen["booking_link"].endswith("employeeId=3440872")
    assert not any("lash" in d.lower() and "lash goblin" not in d.lower() for d in carmen["does"])
    assert any(d.startswith("Tattoos by Skin deep canvas") for d in carmen["does"])


def test_search_finds_decisions_and_data(index):
    top = index.search("why not Bedrock")[0]
    assert top["source"] == "docs/decisions.md"
    tattoo = index.search("tiny tattoo tuesday price")[0]
    assert "£40" in tattoo["text"] or "Tuesday" in tattoo["text"]


def test_read_source_stays_inside_repo(index):
    assert "Decisions" in index.read_source("docs/decisions.md")
    with pytest.raises(ValueError):
        index.read_source("../secrets.txt")
