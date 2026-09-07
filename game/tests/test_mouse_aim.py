"""
Aiming with the pointer (Settings ▸ GAME ▸ Mouse control).

With mouse control on, the visible cursor *is* the crosshair: the view publishes
where it is aiming every frame and every projectile the player looses — arrow or
spell bolt — flies at that point. A creature that merely happens to stand in
front no longer steals the shot, because the player is no longer aiming with
their chest. With mouse control off nothing changes: the old lock-on target
wins, and a shot at nothing goes straight ahead.

Escape's other half lives here too — which of MiniWind's screens will actually
close on it, so the editor knows when the key is the game's and when it is its
own (see editor/tests/test_play_mode_escape.py).

Run:  python -m pytest game/tests/test_mouse_aim.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.runtime import MiniwindSession


class _GameState:
    """The slice of ThreadedGameState the aim helpers touch."""

    def __init__(self, aim=None):
        self.aim = aim

    def get_aim_direction(self):
        return self.aim


class _Logic:
    def __init__(self, aim=None, angle=0.0):
        self.game_state = _GameState(aim)
        self.player = type("P", (), {"pos": [0.0, 0.0, 0.0], "angle": angle})()


class _Thing:
    def __init__(self, pos):
        self.pos = pos


class _Session:
    _pointer_aim = MiniwindSession._pointer_aim
    _projectile_aim_point = MiniwindSession._projectile_aim_point
    _player_forward = MiniwindSession._player_forward
    escape_closes_modal = MiniwindSession.escape_closes_modal

    def __init__(self, aim=None, angle=0.0):
        self.logic = _Logic(aim, angle)
        self.open_screen = None
        self.dialogue = None


START = [0.0, 48.0, 0.0]


# ------------------------------------------------------------------ the pointer
def test_no_pointer_aim_when_mouse_control_is_off():
    """Nothing published means the pointer is not the crosshair."""
    assert _Session(aim=None)._pointer_aim() is None


def test_pointer_aim_is_normalised():
    aim = _Session(aim=(0.0, 0.0, 4.0))._pointer_aim()
    assert aim == (0.0, 0.0, 1.0)


def test_a_degenerate_aim_is_ignored():
    assert _Session(aim=(0.0, 0.0, 0.0))._pointer_aim() is None
    assert _Session(aim=("x", 1, 2))._pointer_aim() is None


def test_a_game_state_without_the_hook_is_harmless():
    """An engine build predating mouse control simply never aims by pointer."""
    session = _Session()
    session.logic.game_state = object()
    assert session._pointer_aim() is None


# --------------------------------------------------------------- the aim point
def test_the_pointer_beats_a_locked_on_target():
    """The whole point of aiming by hand: the shot goes where the cursor is."""
    session = _Session(aim=(1.0, 0.0, 0.0))
    target = _Thing([0.0, 0.0, 900.0])          # dead ahead, and irrelevant now
    x, y, z = session._projectile_aim_point(START, target)
    assert x > 100.0 and abs(z) < 1e-6


def test_the_pointer_carries_height():
    """A cursor on a rooftop launches the bolt upward, not along the ground."""
    up = 1.0 / math.sqrt(2.0)
    session = _Session(aim=(0.0, up, up))
    _x, y, _z = session._projectile_aim_point(START, None)
    assert y > START[1] + 100.0


def test_without_the_pointer_a_locked_target_still_wins():
    session = _Session(aim=None)
    target = _Thing([120.0, 30.0, 40.0])
    assert session._projectile_aim_point(START, target) == (120.0, 94.0, 40.0)


def test_without_the_pointer_or_a_target_the_shot_goes_ahead():
    session = _Session(aim=None, angle=math.pi / 2)   # facing +x
    x, y, z = session._projectile_aim_point(START, None)
    assert x > 1000.0 and abs(z) < 1e-6
    assert y == START[1]                              # level, as it always was


# ---------------------------------------------------------------- Escape's owner
def test_escape_closes_an_ordinary_screen():
    session = _Session()
    session.open_screen = "inventory"
    assert session.escape_closes_modal()


def test_escape_closes_a_conversation():
    session = _Session()
    session.dialogue = object()
    assert session.escape_closes_modal()


def test_escape_does_not_close_character_creation():
    """It steps back a page and then sits still — it is not a way out."""
    session = _Session()
    session.open_screen = "charcreate"
    assert not session.escape_closes_modal()


def test_escape_does_not_close_the_level_up_screen():
    session = _Session()
    session.open_screen = "levelup"
    assert not session.escape_closes_modal()


def test_escape_is_nobodys_with_nothing_open():
    assert not _Session().escape_closes_modal()
