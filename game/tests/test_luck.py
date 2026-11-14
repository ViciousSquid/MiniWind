"""Luck: everyone has it, it turns saving throws at the extremes (the fate
die), and the player is always told what happened."""

from __future__ import annotations

import random

import pytest

from ..diceroll import DiceRoller
from ..rpg import armour_class as ac, blocking, charisma, luck
from ..rpg import attributes as attr


class Faces(random.Random):
    """Dice that come up the given faces, in order."""

    def __init__(self, *faces):
        super().__init__(0)
        self.faces = iter(faces)

    def randint(self, low, high):
        return next(self.faces)


def save(faces, luck_score, level, damage=20.0):
    return blocking.block_save(damage, 50, 50, dice=DiceRoller(rng=Faces(*faces)),
                               defender="Hunter", luck=luck_score, level=level)


# ------------------------------------------------------------ everyone has it
@pytest.mark.parametrize("role", ["wolf", "hen", "bandit", "guard", "dragon", "villager"])
def test_everyone_has_a_luck_animals_too(role):
    props = {"name": role.title(), "npc_role": role}
    score = charisma.core(props, attr.LUCK)
    assert 0 <= score <= 100 and props["luck"] == score          # rolled once, kept
    assert charisma.core(props, attr.LUCK) == score


def test_a_luck_already_set_is_kept():
    assert charisma.core({"name": "Ed", "luck": 3}, attr.LUCK) == 3


def test_adding_luck_did_not_change_anyones_other_attributes():
    """Luck is rolled after Strength, Endurance and Charisma, so a creature
    rolled before Luck existed keeps the same three."""
    props = {"name": "Old Wolf", "creature_role": "wolf"}
    charisma.core(props, attr.STRENGTH)
    old = {k: props[k] for k in ("strength", "endurance", "charisma")}
    again = {"name": "Old Wolf", "creature_role": "wolf"}
    charisma.core(again, attr.LUCK)
    assert {k: again[k] for k in old} == old


# --------------------------------------------------------- the attack bonus
def test_luck_moves_the_attack_bonus_both_ways():
    assert ac.luck_bonus(40) == 0 and ac.luck_bonus(59) == 0
    assert ac.luck_bonus(60) == 1 and ac.luck_bonus(100) == 3
    assert ac.luck_bonus(21) == 0 and ac.luck_bonus(20) == -1 and ac.luck_bonus(0) == -2


def test_an_unlucky_creature_lands_fewer_blows():
    lucky = {"name": "A", "strength": 40, "luck": 100}
    unlucky = {"name": "B", "strength": 40, "luck": 0}
    assert ac.npc_attack_bonus(lucky) - ac.npc_attack_bonus(unlucky) == 5


def test_an_unlucky_player_lands_fewer_blows():
    from ..rpg.character import Character
    c = Character()
    c.attrs[attr.LUCK] = 40
    even = ac.player_attack_bonus(c, 30, melee=False)
    c.attrs[attr.LUCK] = 0
    assert ac.player_attack_bonus(c, 30, melee=False) == even - 2


# -------------------------------------------------------------- the fate die
def test_ordinary_luck_never_rolls_a_fate_die():
    res = save([1], 40, 30)                               # a failed save
    assert res["fate"] is None and "luck_roll" not in res["block_roll"]
    res = save([20], 40, 30)                              # a good one
    assert res["fate"] is None and "luck_roll" not in res["block_roll"]


def test_luck_only_reaches_saves_at_high_level():
    assert luck.lucky_chance(100, luck.LUCKY_LEVEL - 1) == 0.0
    assert luck.lucky_chance(100, luck.LUCKY_LEVEL) > 0.0
    assert luck.lucky_chance(luck.LUCKY_FROM - 1, 50) == 0.0
    assert luck.lucky_chance(100, 100) == luck.FATE_MAX


def test_bad_luck_strikes_at_any_level():
    assert luck.unlucky_chance(luck.UNLUCKY_TO) == pytest.approx(luck.FATE_BASE)
    assert luck.unlucky_chance(0) == pytest.approx(luck.FATE_MAX)
    assert luck.unlucky_chance(luck.UNLUCKY_TO + 1) == 0.0


def test_a_lucky_failed_save_turns_the_whole_blow_aside():
    res = save([1, 20], 100, 20)                          # failed, then the fate die
    roll = res["block_roll"]
    assert not roll["success"] and res["fate"] == "lucky"
    assert res["damage"] == 0.0 and res["blocked"] == 20.0
    assert roll["luck_roll"]["fate"] == "lucky" and roll["fate_line"] in luck.LUCKY_LINES
    assert "LUCK!" in roll["luck_roll"]["detail"]


def test_an_unlucky_good_save_lets_the_whole_blow_through():
    res = save([20, 20], 0, 1)
    assert res["block_roll"]["success"] and res["fate"] == "unlucky"
    assert res["damage"] == 20.0 and res["blocked"] == 0.0
    assert res["fate_line"] in luck.UNLUCKY_LINES


def test_when_fate_lets_it_be_the_save_stands_and_its_die_is_still_shown():
    res = save([1, 2], 100, 20)                           # fate die fails
    assert res["fate"] is None and res["damage"] == 20.0
    assert res["block_roll"]["luck_roll"]["fate"] is None  # rolled, and shown
    assert "fate lets it be" in res["block_roll"]["luck_roll"]["detail"]


def test_npc_shields_carry_luck_too():
    props = {"name": "Guard", "npc_role": "guard", "offhand_weapon": "iron_shield",
             "equipped_weapon": "iron_longsword", "_shield_blocking": True,
             "creature_level": 20, "luck": 100}
    res = blocking.npc_block(props, 30.0, dice=DiceRoller(rng=Faces(1, 20)))
    assert res["fate"] == "lucky" and res["damage"] == 0.0


# ------------------------------------------------------- the player is told
def test_the_roll_box_shows_both_dice_and_says_what_happened(qt_app):
    from ..ui import hud
    res = save([1, 20], 100, 20)
    roll = res["block_roll"]
    box = {"result": roll, "elapsed": 0.0, "actor": None, "side": "foe", "seed": 3}
    visuals = hud._prepare_dice_animation(box, roll)
    assert [v["role"] for v in visuals] == ["save", "luck"]
    layout = hud._roll_box_layout(box, 1200)
    assert any("LUCK!" in d for d in layout["details"])
    assert roll["fate_line"] in layout["details"]


def test_luck_floats_over_the_lucky_and_the_player_is_told(qt_app, monkeypatch):
    import time
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    guard = _Thing("Guard", (60.0, 0.0, 0.0), type="npc", npc_role="guard")
    s = MiniwindSession(_Logic([guard]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    told = []
    monkeypatch.setattr(s, "notify", lambda text, *a, **k: told.append(text))
    res = save([1, 20], 100, 20)
    s.show_roll_box(guard, res["block_roll"])
    assert s.shows_crit(guard)                            # LUCK! hushes its speech
    later = time.monotonic() + s._reveal_delay(guard, every_die=True) + 0.05   # dice landed
    monkeypatch.setattr(time, "monotonic", lambda: later)
    s._run_reveals()
    assert told and told[-1].startswith("LUCK! Guard: ")
    assert res["fate_line"] in told[-1]
    floats = {text for _t, text, *_ in s.live_floats()}
    assert "LUCK!" in floats
