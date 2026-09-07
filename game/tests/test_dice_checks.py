"""
Tests for chance checks being rolled on real dice.

This game owns six dice — d4, d6, d8, d10, d12, d20 — and every roll is put on
screen for the player to watch. Skill, luck and loot checks used to be resolved
on ``1d100``, which meant attacking showed the player a die that does not exist.
They now go through :data:`game.diceroll.CHECK_NOTATION` and
:func:`game.diceroll.check_threshold`.

These tests pin the mapping from a probability to a threshold, prove the
resulting success rates still match the probabilities they came from, and guard
against a percentile die creeping back into combat, magic or loot.

Run:  python -m pytest game/tests/test_dice_checks.py -q
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import diceroll
from game.diceroll import CHECK_DIE, CHECK_NOTATION, DICE_TYPES, check_threshold


def test_the_check_die_is_one_of_the_games_own_dice():
    assert CHECK_DIE in DICE_TYPES
    assert CHECK_NOTATION == "1d20"


def test_threshold_maps_a_probability_onto_the_die():
    assert check_threshold(0.0) == 0
    assert check_threshold(0.25) == 5
    assert check_threshold(0.5) == 10
    assert check_threshold(0.75) == 15
    assert check_threshold(1.0) == CHECK_DIE


def test_a_long_shot_keeps_a_winning_face_and_a_near_certainty_a_losing_one():
    assert check_threshold(0.001) == 1               # never unrollable
    assert check_threshold(0.999) == CHECK_DIE - 1   # never a free pass


def test_threshold_survives_nonsense_input():
    assert check_threshold(None) == 0
    assert check_threshold("nope") == 0
    assert check_threshold(-5.0) == 0
    assert check_threshold(12.0) == CHECK_DIE


def test_observed_success_rate_matches_the_probability():
    roller = diceroll.DiceRoller()
    roller.rng = random.Random(1234)
    for chance in (0.25, 0.5, 0.75):
        threshold = check_threshold(chance)
        trials = 4000
        wins = sum(1 for _ in range(trials)
                   if roller.roll_dice(CHECK_NOTATION)["roll_result"] <= threshold)
        assert abs(wins / trials - chance) < 0.03


def test_no_rule_module_writes_a_die_that_does_not_exist():
    """The regression: attacking put a d100 on screen.

    Scans the rule modules for literal dice notation and insists every die named
    is one the game actually owns. Prose in a comment is not notation, so only
    quoted expressions are checked.
    """
    import re

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    notation = re.compile(r"""['"]\s*\d*\s*d(\d+)\s*['"]""")
    for rel in ("game/rpg/combat.py", "game/rpg/magic.py", "game/rpg/loot.py",
                "game/rpg/game_state.py", "engine/monster_ai.py"):
        with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
            source = fh.read()
        for sides in notation.findall(source):
            assert int(sides) in DICE_TYPES, f"{rel} rolls a d{sides}"


def test_every_die_a_loot_quantity_roll_shows_is_a_real_one():
    """An odd quantity span must not invent a die (there is no d37)."""
    from game.rpg import loot

    shown = []

    class _Dice:
        def request_roll(self, notation, **_kw):
            shown.append(notation)
            return {"roll_result": 1}

    rng = random.Random(0)
    for lo, hi in ((1, 3), (1, 6), (2, 40), (0, 20), (5, 5)):
        loot._roll_range(lo, hi, rng, _Dice(), "table", "item")
    for notation in shown:
        assert int(notation.split("d")[1]) in DICE_TYPES, notation


def test_a_cast_check_succeeds_at_the_rate_its_chance_asks_for():
    from game.rpg import magic

    # cast_check turns a 0..1 chance into a "roll at or above target" on the
    # check die; the winning faces must number check_threshold(chance).
    for chance in (0.05, 0.5, 0.9):
        target = CHECK_DIE - check_threshold(chance) + 1
        winning_faces = CHECK_DIE - target + 1
        assert winning_faces == check_threshold(chance)
    assert magic.CHECK_DIE == CHECK_DIE
