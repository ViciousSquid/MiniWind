"""
Where the player's projectiles go: the way the player faces.

Every projectile the player looses -- arrow or spell bolt -- leaves straight
ahead along the player's facing, level with the ground (the game is played
top-down). With Settings > GAME > Mouse control on, the player turns to face
the pointer every tick, so the shot goes toward the pointer too; a creature
standing near the line of fire does not pull it off course.

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

from ..runtime import MiniwindSession
from .fio_logic import FioLogic


class _Logic(FioLogic):
    def __init__(self, angle=0.0):
        self.player = type("P", (), {"pos": [0.0, 0.0, 0.0], "angle": angle})()


class _Session:
    _projectile_aim_point = MiniwindSession._projectile_aim_point
    _player_forward = MiniwindSession._player_forward
    escape_closes_modal = MiniwindSession.escape_closes_modal

    def __init__(self, angle=0.0):
        self.logic = _Logic(angle)
        self.open_screen = None
        self.dialogue = None


START = [0.0, 48.0, 0.0]


# --------------------------------------------------------------- the aim point
def test_the_shot_goes_the_way_the_player_faces():
    session = _Session(angle=math.pi / 2)            # facing +x
    x, y, z = session._projectile_aim_point(START)
    assert x > 1000.0 and abs(z) < 1e-6


def test_the_shot_flies_level():
    for angle in (0.0, 1.0, math.pi, 4.0):
        _x, y, _z = _Session(angle=angle)._projectile_aim_point(START)
        assert y == START[1]


def test_facing_away_shoots_away():
    session = _Session(angle=math.pi)                # facing -z
    _x, _y, z = session._projectile_aim_point(START)
    assert z < -1000.0


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
