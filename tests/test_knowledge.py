"""The knowledge index is built from the real repo files. The menu file is
generated from Fresha and changes whenever the salon does, so these tests
check the index against that file rather than against fixed counts."""
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MENU_FILE = ROOT / "terraform" / "fresha-menu.auto.tfvars.json"

pytest.importorskip("hcl2")
pytest.importorskip("rank_bm25")

from knowledge_mcp.index import KnowledgeIndex  # noqa: E402


@pytest.fixture(scope="module")
def index() -> KnowledgeIndex:
    return KnowledgeIndex(ROOT)


@pytest.fixture(scope="module")
def menu() -> dict:
    return json.loads(MENU_FILE.read_text(encoding="utf-8"))


def test_indexes_every_source(index, menu):
    stats = index.stats()
    assert "docs/decisions.md" in stats["sources"]
    assert "knowledge/fresha.md" in stats["sources"]
    assert "persona/jess.md" in stats["sources"]
    assert "terraform/fresha-menu.auto.tfvars.json" in stats["sources"]
    assert stats["by_kind"]["service"] == len(menu["services"])
    assert stats["by_kind"]["staff"] == len(menu["staff"])


def test_menu_file_is_not_empty(menu):
    assert len(menu["staff"]) >= 1
    assert len(menu["services"]) >= 1


def test_categories_are_fresha_spelling(index, menu):
    """Category names reach the index exactly as the menu file (and so Fresha)
    spells them, with the same service count per category."""
    expected = Counter(s["category"] for s in menu["services"])
    assert index.categories() == dict(expected)


def test_every_service_has_staff(index):
    missing = [s["name"] for s in index.salon["services"] if not s.get("staff")]
    assert missing == []


def test_who_does_matches_menu_file(index, menu):
    """who_does answers from the menu file's staff list for that service."""
    multi = next(s for s in menu["services"] if len(s["staff"]) >= 2)
    hit = index.who_does(multi["name"])[0]
    assert hit["service"] == multi["name"]
    assert hit["category"] == multi["category"]
    assert hit["staff"] == multi["staff"]


def test_team_members_match_menu_file(index, menu):
    """Every person in the menu file is findable by slug, keeps their Fresha
    employee id in the booking link, and 'does' only lists services whose
    staff list names them."""
    for slug, person in menu["staff"].items():
        member = index.team_member(slug)
        assert member is not None, slug
        assert member["name"] == person["name"]
        assert member["booking_link"].endswith(f"employeeId={person['employee_id']}")
        expected = sorted(
            f"{s['category']} | {s['name']}" for s in menu["services"] if person["name"] in s["staff"]
        )
        assert sorted(member["does"]) == expected, slug
        assert member["service_count"] == len(expected)


def test_search_finds_decisions_and_data(index):
    top = index.search("why not Bedrock")[0]
    assert top["source"] == "docs/decisions.md"
    tattoo = index.search("tiny tattoo tuesday price")[0]
    assert "£40" in tattoo["text"] or "Tuesday" in tattoo["text"]


def test_read_source_stays_inside_repo(index):
    assert "Decisions" in index.read_source("docs/decisions.md")
    with pytest.raises(ValueError):
        index.read_source("../secrets.txt")
