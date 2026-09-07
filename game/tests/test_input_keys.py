"""
MiniWind's play-mode key bindings must not sit on the movement keys.

WASD is read by the engine directly, so a game binding on one of those letters
does not replace movement — it fires *as well as* it. A manual dice roller lived
on 'd', which meant every side-step to the right also threw a die.

Run:  python -m pytest game/tests/test_input_keys.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import host

#: The letters the engine reads as movement (see LogicThread._tick_play_mode).
MOVEMENT_KEYS = {"w", "a", "s", "d"}


def _bindings():
    """Every single-letter key MiniWind binds, as {constant name: key}."""
    return {name: value for name, value in vars(host).items()
            if name.startswith("K_") and isinstance(value, str)}


def test_no_binding_sits_on_a_movement_key():
    clashes = {name: key for name, key in _bindings().items()
               if key.lower() in MOVEMENT_KEYS}
    assert not clashes, f"these bindings would fire while moving: {clashes}"


def test_there_is_no_key_for_rolling_dice_by_hand():
    """Gameplay rolls animate on their own; a manual roller earns no key."""
    assert not [name for name in _bindings() if "DICE" in name]


def test_every_binding_is_a_distinct_key():
    keys = [k.lower() for k in _bindings().values()]
    assert len(keys) == len(set(keys)), "two actions share one key"
