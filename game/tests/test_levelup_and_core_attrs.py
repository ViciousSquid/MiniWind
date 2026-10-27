"""
Three core attributes for every living thing, Agility and Willpower folded
into Endurance, and the level-up page's STRENGTH / ENDURANCE / MAGICKA choice
with its line of encouragement.

Run:  python -m pytest game/tests/test_levelup_and_core_attrs.py -q
"""

from __future__ import annotations

import configparser

import pytest

from .. import runtime
from ..rpg import attributes as attr, charisma, classes, combat, quotes, races, skills as sk
from ..rpg.character import LEVEL_ATTR_GAIN, Character


# ------------------------------------------------------------ the fold
def test_agility_and_willpower_are_gone():
    assert "agility" not in attr.ATTRIBUTES and "willpower" not in attr.ATTRIBUTES
    assert attr.FOLDED == {"agility": attr.ENDURANCE, "willpower": attr.ENDURANCE}
    for race in races.RACES.values():
        assert set(race.attr_bonuses) <= set(attr.ATTRIBUTES)
    for klass in classes.CLASSES.values():
        assert set(klass.favored_attrs) <= set(attr.ATTRIBUTES)
    for skill in sk.SKILLS.values():
        assert skill.governing_attr in attr.ATTRIBUTES


def test_an_old_save_naming_them_still_loads():
    c = Character.from_dict({"attrs": {"agility": 90, "willpower": 10, "endurance": 55}})
    assert c.attrs["endurance"] == 55 and "agility" not in c.attrs
    custom = classes.make_custom("Old", sk.COMBAT, ["agility", "willpower"], [])
    assert custom.favored_attrs == [attr.ENDURANCE]


def test_endurance_now_steadies_the_aim():
    c = Character()
    c.attrs[attr.ENDURANCE] = 40
    low = combat.hit_chance(c, 30, 40)
    c.attrs[attr.ENDURANCE] = 90
    assert combat.hit_chance(c, 30, 40) > low


# ------------------------------------------- every living thing has three
def test_a_creature_rolls_its_three_once_and_keeps_them():
    wolf = {"name": "Grey Wolf", "npc_role": "wolf"}
    strength = charisma.core(wolf, attr.STRENGTH)
    assert {"strength", "endurance", "charisma"} <= set(wolf)
    assert charisma.core(wolf, attr.STRENGTH) == strength
    again = {"name": "Grey Wolf", "npc_role": "wolf"}
    assert charisma.core(again, attr.STRENGTH) == strength      # stable roll


def test_kinds_differ_and_authored_values_win():
    bear = {"name": "Bear", "npc_role": "bear"}
    hen = {"name": "Hen", "npc_role": "hen"}
    assert charisma.core(bear, attr.STRENGTH) > charisma.core(hen, attr.STRENGTH)
    assert charisma.core({"strength": 77}, attr.STRENGTH) == 77
    assert charisma.core({"personality": 66}, attr.PERSONALITY) == 66


def test_a_tougher_target_is_harder_to_hit():
    c = Character()
    weak = combat.attack_odds(c, {"endurance": 10})["hit_chance"]
    tough = combat.attack_odds(c, {"endurance": 100})["hit_chance"]
    assert tough < weak


def test_strength_scales_the_damage_a_creature_deals():
    assert combat.strength_factor(50) == pytest.approx(1.0)
    assert combat.strength_factor(100) > combat.strength_factor(10)


# ---------------------------------------------------------------- level up
def _ready(class_id):
    c = Character.create("T", "nord", class_id, "none")
    c.xp = c.xp_needed
    return c


def test_magic_users_choose_from_three_and_warriors_from_two():
    assert _ready("sorcerer").level_choices() == ["strength", "endurance", "magicka"]
    assert _ready("warrior").level_choices() == ["strength", "endurance"]


def test_the_choice_grows_its_attribute():
    c = _ready("sorcerer")
    before = dict(c.attrs)
    magicka = c.max_magicka
    res = c.level_up(choice="magicka")
    assert res["choice"] == "magicka" and res["choice_gain"] == LEVEL_ATTR_GAIN
    assert c.attrs[attr.INTELLIGENCE] >= before[attr.INTELLIGENCE] + LEVEL_ATTR_GAIN
    assert c.max_magicka > magicka


def test_a_warrior_cannot_take_magicka():
    c = _ready("warrior")
    intelligence = c.attrs[attr.INTELLIGENCE]
    res = c.level_up(choice="magicka")
    assert res["choice"] == "" and c.attrs[attr.INTELLIGENCE] == intelligence


def test_every_quote_is_used_and_neighbours_never_repeat():
    seen = {quotes.for_level(n) for n in range(2, 2 + len(quotes.QUOTES))}
    assert seen == set(quotes.QUOTES)
    for n in range(2, 60):
        assert quotes.for_level(n) != quotes.for_level(n + 1)


@pytest.fixture
def config():
    config = configparser.ConfigParser()
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def test_quotes_are_on_unless_settings_ini_turns_them_off(config):
    from .test_ember_tome import _FakePlayer, _session
    from .. import integration
    s = _session([], _FakePlayer([0, 0, 0]))
    assert s.motivational_quotes_enabled()
    config.read_dict({"GAME": {"motivational_quotes": "False"}})
    assert not s.motivational_quotes_enabled()
    # Not offered in the in-game settings.
    assert "motivational_quotes" not in [k for k, *_ in integration.GAME_SETTINGS]


@pytest.mark.qt
def test_the_level_up_page_offers_what_the_character_may_choose(qt_app):
    from types import SimpleNamespace
    from PyQt5 import QtGui
    from ..ui import hits, screens
    for class_id, expected in (("sorcerer", 3), ("warrior", 2)):
        c = _ready(class_id)
        s = SimpleNamespace(game=SimpleNamespace(character=c), open_screen="levelup",
                            motivational_quotes_enabled=lambda: True, sel={})
        image = QtGui.QImage(820, 600, QtGui.QImage.Format_ARGB32)
        painter = QtGui.QPainter(image)
        hits.begin()
        try:
            screens.draw_in_rect(painter, s, 0, 0, 820, 600)
        finally:
            painter.end()
        hits.end()
        rows = [label for _r, label in hits.targets() if str(label).startswith("levelup:")]
        assert len(rows) == expected
        hits.clear()


def test_the_level_up_page_takes_the_mouse(monkeypatch):
    from types import SimpleNamespace
    from ..ui import hits
    monkeypatch.setattr(hits, "has_targets", lambda: True)
    session = SimpleNamespace(game=SimpleNamespace(character=SimpleNamespace(is_dead=False)),
                              open_screen="levelup", needs_char_creation=False)
    view = SimpleNamespace(logic_thread=SimpleNamespace(_miniwind=session))
    assert hits.GamePointer(view).wants_pointer()
