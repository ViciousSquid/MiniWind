"""Headless tests for the engine-native dice integration."""

from __future__ import annotations

import random

from game.diceroll import DiceNotationError, DiceRoller, dicerollAPI, parse_dice_notation


def test_parser_supports_shorthand_terms_and_modifiers():
    terms, source = parse_dice_notation("d20 + 2d6 - 3")
    assert source == "d20 + 2d6 - 3"
    assert [(term.count, term.sides, term.sign, term.modifier) for term in terms] == [
        (1, 20, 1, 0), (2, 6, 1, 0), (0, 0, -1, 3)
    ]


def test_seeded_roll_is_bounded_and_tracks_history():
    roller = DiceRoller(rng=random.Random(7))
    result = roller.roll_dice("2d6+2")
    assert result["roll_details"] == [3, 2]
    assert result["roll_result"] == 7
    for _ in range(8):
        roller.roll_dice("1d20")
    assert len(roller.get_last_5_rolls()) == 5
    assert roller.get_last_roll_total() is not None


def test_probability_distribution_is_exact():
    probabilities = DiceRoller().get_dice_probabilities("2d6")
    assert sum(probabilities.values()) == 1.0
    assert probabilities[2] == 1 / 36
    assert probabilities[7] == 6 / 36
    assert probabilities[12] == 1 / 36


def test_invalid_notation_does_not_silently_roll():
    try:
        parse_dice_notation("1d20oops")
    except DiceNotationError:
        pass
    else:
        raise AssertionError("invalid notation should raise DiceNotationError")


def test_compatibility_facade_uses_injected_rng():
    api = dicerollAPI(rng=random.Random(1))
    result = api.roll_single_dice("d6")
    assert 1 <= result["roll_result"] <= 6
    assert api.get_roll_sum(result) == result["roll_result"]
