from bot.config import SalonConfig, load_persona
from bot.prompt import build_system_prompt


def test_prompt_contains_persona_and_salon_facts(persona_text, salon_config_json):
    cfg = SalonConfig.from_json(salon_config_json)
    prompt = build_system_prompt(persona_text, cfg)

    assert "You are Jess" in prompt
    assert "The Looking Glass" in prompt
    assert "### Nails" in prompt
    assert "Gel nails: £30, 45 min, with Jess or Amy (patch test not needed)" in prompt
    assert "Lash lift: £45, 1 hr (patch test 48h before). Book: https://www.fresha.com/a/tlg?service=lashlift" in prompt
    assert "Book with Amy: https://www.fresha.com/a/tlg?staff=amy" in prompt
    assert "Book with Jess" not in prompt  # no per-person link set, falls back to the main link
    assert "Free parking" in prompt
    # Days render in week order, not dict order
    assert prompt.index("Monday") < prompt.index("Tuesday") < prompt.index("Saturday")


def test_prompt_is_stable_for_caching(persona_text, salon_config_json):
    cfg = SalonConfig.from_json(salon_config_json)
    assert build_system_prompt(persona_text, cfg) == build_system_prompt(persona_text, cfg)


def test_persona_has_the_rules_jess_relies_on(persona_text):
    for phrase in ["escalate", "Never make up a booking", "patch test", "British English"]:
        assert phrase in persona_text


def test_load_persona_from_env():
    assert "You are Jess" in load_persona()


def test_rendered_salon_config_loads_from_file(monkeypatch, tmp_path):
    """The bundle ships bot/salon_config.json; it must parse into SalonConfig
    and carry the whole Fresha menu."""
    import json
    import sys
    from pathlib import Path

    import pytest

    ROOT = Path(__file__).resolve().parent.parent
    pytest.importorskip("hcl2")
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_salon_config import render

    from bot.config import SalonConfig

    doc = render(ROOT / "terraform")
    menu = json.loads((ROOT / "terraform" / "fresha-menu.auto.tfvars.json").read_text(encoding="utf-8"))
    assert len(doc["services"]) == len(menu["services"]) and len(doc["staff"]) == len(menu["staff"])

    path = tmp_path / "salon_config.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.delenv("SALON_CONFIG_JSON", raising=False)
    monkeypatch.setenv("SALON_CONFIG_PATH", str(path))
    cfg = SalonConfig.from_env()
    assert cfg.salon_name == "The Looking Glass Beauty"
    assert len(cfg.services) == len(menu["services"])
    assert {m.name for m in cfg.staff} == {m["name"] for m in menu["staff"].values()}
