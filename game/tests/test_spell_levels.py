"""
Two schools of magic, spell levels bought with experience, and every spell's
values in game/data/spells.json.

Run:  python -m pytest game/tests/test_spell_levels.py -q
"""

from __future__ import annotations

import json
import os

from ..rpg import classes, magic, skills as sk
from ..rpg.character import Character


def test_there_are_two_schools_and_every_spell_is_in_one():
    magic_skills = [s for s, d in sk.SKILLS.items() if d.spec == sk.MAGIC]
    assert set(magic_skills) == {sk.OFFENSIVE, sk.DEFENSIVE, sk.ALCHEMY}
    for spell in magic.SPELLS.values():
        assert spell.school in (sk.OFFENSIVE, sk.DEFENSIVE), spell.id
    assert magic.get("flare").school == sk.OFFENSIVE
    assert magic.get("heal_minor").school == sk.DEFENSIVE


def test_a_higher_level_is_stronger_lasts_longer_and_costs_more():
    flare = magic.get("flare")
    one, three = flare.at_level(1), flare.at_level(3)
    assert three.damage > one.damage
    assert three.base_cost > one.base_cost
    shield = magic.get("sp_shield")
    assert shield.at_level(4).effects[0]["duration"] > shield.effects[0]["duration"]
    assert flare.at_level(99).level == flare.max_level


def test_switch_effects_and_instant_kills_do_not_scale():
    knock = magic.get("knock").at_level(5)
    assert knock.effects[0]["magnitude"] == 1
    assert magic.get("disintegrate").at_level(5).damage == magic.get("disintegrate").damage


def test_the_player_raises_a_spell_with_experience():
    c = Character.create("T", "breton", "mage", "none")
    cost = c.spell_upgrade_cost("flare")
    assert cost == magic.get("flare").xp_per_level
    assert not c.upgrade_spell("flare")              # no experience yet
    c.xp = cost
    assert c.upgrade_spell("flare")
    assert c.spell_level("flare") == 2 and c.xp == 0
    assert c.spell_upgrade_cost("flare") == 2 * magic.get("flare").xp_per_level
    assert magic.for_caster(c, "flare").damage > magic.get("flare").damage
    # Levels are saved.
    assert Character.from_dict(c.to_dict()).spell_level("flare") == 2


def test_a_mastered_spell_cannot_rise():
    c = Character.create("T", "breton", "mage", "none")
    c.spell_levels["flare"] = magic.get("flare").max_level
    c.xp = 10 ** 6
    assert c.spell_upgrade_cost("flare") == 0 and not c.upgrade_spell("flare")


def test_rarer_spells_cost_more_to_raise():
    assert magic.RARITY_XP["legendary"] > magic.RARITY_XP["common"]
    assert magic.default_rarity(100) == "legendary" and magic.default_rarity(8) == "common"


def test_an_old_save_keeps_its_best_magic():
    c = Character.from_dict({"skills": {"destruction": 40, "conjuration": 55,
                                        "restoration": 30, "mysticism": 20},
                             "major_skills": ["destruction", "conjuration", "blade"]})
    assert c.skills[sk.OFFENSIVE] == 55 and c.skills[sk.DEFENSIVE] == 30
    assert c.major_skills == [sk.OFFENSIVE, "blade"]
    custom = classes.make_custom("Old", sk.MAGIC, [], ["illusion", "alteration"])
    assert custom.major_skills[0] == sk.DEFENSIVE
    assert magic.Spell.from_dict({"id": "x", "school": "destruction"}).school == sk.OFFENSIVE


def test_the_data_file_holds_every_spell_and_its_numbers():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "spells.json")
    with open(path, "r", encoding="utf-8") as fh:
        rows = {r["id"]: r for r in json.load(fh)}
    # Every spell the game ships (other tests register extras of their own).
    assert {"flare", "firebolt", "heal_minor", "knock", "sp_shield", "wisp",
            "summon_wolf", "disintegrate", "resurrection", "sp_woad"} <= set(rows)
    assert len(rows) >= 30
    for key in ("cost", "effects", "rarity", "max_level", "xp_per_level",
                "level_power", "level_duration", "level_cost", "school"):
        assert key in rows["flare"], key
    assert magic.Spell.from_dict(rows["flare"]).to_dict() == rows["flare"]
