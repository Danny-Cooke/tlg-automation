import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SAMPLE_CONFIG = {
    "salon_name": "The Looking Glass",
    "address": "1 High Street, Testville",
    "phone": "01234 567890",
    "opening_hours": {"monday": "Closed", "tuesday": "9am-6pm", "saturday": "9am-4pm"},
    "general_booking_link": "https://www.fresha.com/a/tlg",
    "services": [
        {
            "category": "Nails",
            "name": "Gel nails",
            "price": "£30",
            "duration": "45 min",
            "staff": ["Jess", "Amy"],
            "notes": "patch test not needed",
        },
        {
            "category": "Beauty",
            "name": "Lash lift",
            "price": "£45",
            "duration": "1 hr",
            "booking_link": "https://www.fresha.com/a/tlg?service=lashlift",
            "notes": "patch test 48h before",
        },
    ],
    "staff": [
        {"name": "Jess", "role": "Manager", "services": ["Gel nails", "Lash lift"]},
        {"name": "Amy", "role": "Nail tech", "booking_link": "https://www.fresha.com/a/tlg?staff=amy", "services": ["Gel nails"]},
    ],
    "extra_notes": "Free parking behind the salon.",
}


@pytest.fixture
def salon_config_json() -> str:
    return json.dumps(SAMPLE_CONFIG)


@pytest.fixture
def persona_text() -> str:
    return (ROOT / "persona" / "jess.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def env(monkeypatch, salon_config_json):
    monkeypatch.setenv("SALON_CONFIG_JSON", salon_config_json)
    monkeypatch.setenv("PERSONA_PATH", str(ROOT / "persona" / "jess.md"))
    monkeypatch.delenv("ESCALATION_TOPIC_ARN", raising=False)
    yield
