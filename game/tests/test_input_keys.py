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

from .. import host

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


def test_number_keys_are_claimed_by_modal_game_input():
    """The engine must yield weapon-slot keys while MiniWind UI is modal."""
    from types import SimpleNamespace
    from engine.game_input import modal_input_active
    from ..runtime import MiniwindSession

    session = SimpleNamespace(
        needs_char_creation=False, open_screen=None, dialogue=None
    )
    session.modal_input_active = lambda: MiniwindSession.modal_input_active(session)
    logic = SimpleNamespace(game_session=session)
    assert not modal_input_active(logic)

    session.dialogue = object()
    assert modal_input_active(logic)

    session.dialogue = None
    session.open_screen = "inventory"
    assert modal_input_active(logic)

    session.open_screen = None
    session.needs_char_creation = True
    assert modal_input_active(logic)


def test_engine_modal_input_capability_is_optional():
    """A game session without modal input ownership retains stock key handling."""
    from types import SimpleNamespace
    from engine.game_input import modal_input_active

    assert not modal_input_active(None)
    assert not modal_input_active(SimpleNamespace(game_session=None))
    assert not modal_input_active(
        SimpleNamespace(game_session=SimpleNamespace())
    )
    assert not modal_input_active(
        SimpleNamespace(game_session=SimpleNamespace(
            modal_input_active=lambda: False
        ))
    )

def test_engine_defers_escape_to_game_owned_modal_ui():
    """Escape routing should respect the session's existing modal contract."""
    from types import SimpleNamespace
    from engine.game_input import modal_escape_active

    assert not modal_escape_active(None)
    assert not modal_escape_active(SimpleNamespace(game_session=None))
    assert not modal_escape_active(
        SimpleNamespace(game_session=SimpleNamespace())
    )
    assert modal_escape_active(SimpleNamespace(
        game_session=SimpleNamespace(escape_closes_modal=lambda: True)
    ))
    assert not modal_escape_active(SimpleNamespace(
        game_session=SimpleNamespace(escape_closes_modal=lambda: False)
    ))
    assert not modal_escape_active(SimpleNamespace(
        game_session=SimpleNamespace(
            escape_closes_modal=lambda: (_ for _ in ()).throw(RuntimeError())
        )
    ))

