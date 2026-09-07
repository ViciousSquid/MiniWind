"""
Mouse control: the pointer stays on screen and steers the head.

With Settings ▸ GAME ▸ Mouse control on, play mode stops hiding and
centre-locking the cursor. What replaces mouselook depends on the camera:

  * Overhead, the pointer lands on the ground the player is standing on, so the
    head can be turned to face it outright — an absolute heading, published for
    the logic thread to apply.
  * First person, there is no such point: the pointer is a direction out of the
    eye. So it steers instead — held inside a central deadzone it does nothing
    (which is what makes close aiming usable), and pushed outside it turns the
    view at a rate that grows with the deflection.

Either way the aim direction is published for the game plugin, which launches
every projectile along it (see game/tests/test_mouse_aim.py).

Run:  python -m pytest engine/tests/test_mouse_control.py -q
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from conftest import install_gl_stubs          # noqa: E402

install_gl_stubs()

from engine.threaded_game_state import ThreadedGameState   # noqa: E402

QtCore = pytest.importorskip("PyQt5.QtCore")

try:
    from engine.qt_game_view import QtGameView
except Exception as exc:                       # pragma: no cover - env-specific
    pytest.skip(f"engine.qt_game_view is not importable here ({exc})",
                allow_module_level=True)


# ===========================================================================
# The aim channel
# ===========================================================================
def test_aim_starts_unset():
    """No aim published means mouse control is off — every reader tests this."""
    state = ThreadedGameState()
    assert state.get_aim_direction() is None
    assert state.get_aim_yaw() is None


def test_aim_round_trips():
    state = ThreadedGameState()
    state.set_aim((1.0, 0.0, 0.0), yaw=1.25)
    assert state.get_aim_direction() == (1.0, 0.0, 0.0)
    assert state.get_aim_yaw() == 1.25


def test_aim_clears_with_no_arguments():
    state = ThreadedGameState()
    state.set_aim((1.0, 0.0, 0.0), yaw=1.25)
    state.set_aim()
    assert state.get_aim_direction() is None
    assert state.get_aim_yaw() is None


def test_a_direction_without_a_yaw_leaves_the_head_alone():
    """First person publishes a direction only; the logic thread must not snap."""
    state = ThreadedGameState()
    state.set_aim((0.0, 0.0, 1.0))
    assert state.get_aim_direction() == (0.0, 0.0, 1.0)
    assert state.get_aim_yaw() is None


# ===========================================================================
# First-person steering
# ===========================================================================
class _Steerer:
    """A QtGameView stand-in carrying just the steering maths."""

    MOUSE_CONTROL_DEADZONE = QtGameView.MOUSE_CONTROL_DEADZONE
    MOUSE_CONTROL_TURN_RATE = QtGameView.MOUSE_CONTROL_TURN_RATE
    MOUSE_CONTROL_PITCH_RATE = QtGameView.MOUSE_CONTROL_PITCH_RATE
    _steer_toward_pointer = QtGameView._steer_toward_pointer
    _overhead_aim = QtGameView._overhead_aim

    def __init__(self, player=None):
        self.game_state = ThreadedGameState()
        self.player = player


W, H = 800.0, 600.0


def _steer(x, y, delta=1.0):
    view = _Steerer()
    view._steer_toward_pointer(QtCore.QPoint(int(x), int(y)), W, H, delta)
    return view.game_state.consume_mouse_delta()


def test_the_deadzone_holds_the_view_still():
    """Aiming near the middle of the screen must not drag the camera around."""
    assert _steer(W / 2, H / 2) == (0.0, 0.0)
    just_inside = W / 2 + (W / 2) * (QtGameView.MOUSE_CONTROL_DEADZONE - 0.05)
    assert _steer(just_inside, H / 2) == (0.0, 0.0)


def test_pushing_right_turns_right():
    dx, dy = _steer(W, H / 2)
    assert dx > 0.0
    assert dy == 0.0


def test_pushing_left_turns_left():
    dx, _dy = _steer(0, H / 2)
    assert dx < 0.0


def test_the_edge_turns_faster_than_the_deadzone_rim():
    edge, _ = _steer(W, H / 2)
    rim_x = W / 2 + (W / 2) * (QtGameView.MOUSE_CONTROL_DEADZONE + 0.1)
    rim, _ = _steer(rim_x, H / 2)
    assert 0.0 < rim < edge


def test_the_turn_is_framerate_independent():
    """Twice the frame time, twice the turn — never per-frame steps."""
    slow, _ = _steer(W, H / 2, delta=1.0)
    fast, _ = _steer(W, H / 2, delta=0.5)
    assert slow == pytest.approx(fast * 2.0)


def test_pushing_down_tilts_down():
    _dx, dy = _steer(W / 2, H)
    assert dy > 0.0


def test_deflection_is_clamped_at_the_edge():
    """A pointer dragged past the widget cannot turn faster than its edge does."""
    at_edge, _ = _steer(W, H / 2)
    beyond, _ = _steer(W * 3, H / 2)
    assert beyond == pytest.approx(at_edge)


# ===========================================================================
# Overhead: the head faces the pointer outright
# ===========================================================================
class _Player:
    def __init__(self, x, z):
        self.pos = type("V", (), {"x": x, "y": 0.0, "z": z})()
        self.camera_height = 40.0


class _Vec:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = float(x), float(y), float(z)


def _overhead(origin, direction, player=None):
    view = _Steerer(player or _Player(0.0, 0.0))
    return view._overhead_aim(origin, direction)


def test_the_head_faces_the_ground_spot_under_the_pointer():
    """Straight down from a camera east of the player: face east."""
    yaw, aim = _overhead(_Vec(500.0, 1000.0, 0.0), _Vec(0.0, -1.0, 0.0))
    assert yaw == pytest.approx(math.pi / 2)          # +x, engine yaw is atan2(x, z)
    assert aim == pytest.approx((1.0, 0.0, 0.0))


def test_the_overhead_aim_is_always_horizontal():
    """An overhead view cannot express up or down, so a bolt never tilts."""
    _yaw, aim = _overhead(_Vec(300.0, 900.0, 300.0), _Vec(0.0, -1.0, 0.0))
    assert aim[1] == 0.0
    assert math.hypot(aim[0], aim[2]) == pytest.approx(1.0)


def test_a_ray_that_never_reaches_the_ground_aims_at_nothing():
    """Level or upward rays have no ground spot — leave the head where it is."""
    assert _overhead(_Vec(0.0, 1000.0, 0.0), _Vec(1.0, 0.0, 0.0)) == (None, None)
    assert _overhead(_Vec(0.0, 1000.0, 0.0), _Vec(0.0, 1.0, 0.0)) == (None, None)


def test_the_pointer_on_top_of_the_player_leaves_the_head_alone():
    """No direction to face, and no spin from floating-point noise."""
    assert _overhead(_Vec(0.0, 1000.0, 0.0), _Vec(0.0, -1.0, 0.0)) == (None, None)


def test_no_player_means_no_aim():
    view = _Steerer(None)
    assert view._overhead_aim(_Vec(0, 100, 0), _Vec(0, -1, 0)) == (None, None)
