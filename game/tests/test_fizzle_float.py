"""A fizzled spell says so over the caster's head: "*fizzled*" floats up from
the player, or from any NPC whose cast came to nothing, and fades."""

from ..rpg import equipment, magic, skills
from .test_corpse_loot import _Logic, _Thing
from .test_sim import _FakeGlobals


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(list(things)), cfg={}, globals_store=_FakeGlobals())
    s.game.dice = None
    s.needs_char_creation = False
    c = s.game.character
    c.class_id = "mage"
    c.known_spells = ["flare"]
    c.active_spell = "flare"
    equipment.equip_spell(c, "flare", "main")
    c.magicka = c.max_magicka = 500
    c.skills[skills.OFFENSIVE] = 5
    return s


def test_the_players_fizzle_floats_over_their_head(monkeypatch):
    from ..runtime import FIZZLE_TEXT
    s = _session()
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (False, {}))
    assert not s.do_cast(aim="facing")
    floats = s.live_floats()
    assert [(f[0].properties.get("is_player"), f[1]) for f in floats] == [(True, FIZZLE_TEXT)]
    assert FIZZLE_TEXT == "*fizzled*"


def test_a_cast_that_works_floats_nothing(monkeypatch):
    s = _session()
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (True, {}))
    s.do_cast(aim="facing")
    assert s.live_floats() == []


def test_an_npcs_fizzle_floats_over_its_head_when_the_player_is_near():
    from ..runtime import FIZZLE_TEXT
    near = _Thing("Cultist", (100, 0, 0), type="npc")
    far = _Thing("Hermit", (90000, 0, 0), type="npc")
    s = _session(near, far)
    s.fizzled(near)
    s.fizzled(far)
    assert [(f[0], f[1]) for f in s.live_floats()] == [(near, FIZZLE_TEXT)]

