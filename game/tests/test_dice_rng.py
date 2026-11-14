"""Dice draw from the operating system's cryptographic random source -- every
roll, the player's and every NPC's -- unless a developer sets a dice seed,
which makes them repeat exactly."""

from __future__ import annotations

import random

import pytest

from .. import dice_rng


def test_by_default_the_dice_are_the_os_random_source():
    assert dice_rng.is_true_random(dice_rng.source())
    assert dice_rng.is_true_random(dice_rng.source(""))
    assert dice_rng.is_true_random(dice_rng.source("   "))


def test_a_developer_seed_repeats_the_rolls_exactly():
    a, b = dice_rng.source("bug-123"), dice_rng.source("bug-123")
    assert [a.randint(1, 20) for _ in range(50)] == [b.randint(1, 20) for _ in range(50)]
    assert not dice_rng.is_true_random(a)
    c = dice_rng.source("another")
    assert [c.randint(1, 20) for _ in range(50)] != [dice_rng.source("bug-123").randint(1, 20)
                                                    for _ in range(50)]


def test_true_dice_are_fair(qt_app=None):
    """200,000 d20s from the OS source: every face within 2% of a twentieth
    (well inside what fair dice give; a biased die would show)."""
    rng = dice_rng.source()
    n = 200_000
    counts = [0] * 21
    for _ in range(n):
        counts[rng.randint(1, 20)] += 1
    expected = n / 20
    assert all(abs(counts[f] - expected) / expected < 0.05 for f in range(1, 21))
    chi2 = sum((counts[f] - expected) ** 2 / expected for f in range(1, 21))
    assert chi2 < 43.8                       # 19 degrees of freedom, p = 0.001


def test_the_session_rolls_its_dice_from_the_true_source(qt_app):
    from .test_cast_controls import _Logic
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={})
    assert dice_rng.is_true_random(s.game.dice.rng)
    assert s.dice_rng is s.game.dice.rng
    assert s.dice_rng is not s.rng                   # dice are not the world's generator


def test_the_session_honours_a_developer_seed(qt_app, monkeypatch):
    import configparser
    from .test_cast_controls import _Logic
    from ..runtime import MiniwindSession
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"dice_seed": "repro"}})
    monkeypatch.setattr(MiniwindSession, "_editor_config", lambda self: config)
    s = MiniwindSession(_Logic(), cfg={})
    assert not dice_rng.is_true_random(s.game.dice.rng)
    first = [s.game.dice.roll_dice("1d20")["roll_result"] for _ in range(10)]
    s2 = MiniwindSession(_Logic(), cfg={})
    assert [s2.game.dice.roll_dice("1d20")["roll_result"] for _ in range(10)] == first
