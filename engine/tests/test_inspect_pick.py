"""
Tests for the ``inspect`` console command's click-to-pick.

Clicking an NPC in inspect mode did nothing, for two independent reasons:

* the pick ray took its *direction* from the play camera but its *origin* from
  the editor camera, so in play mode it started somewhere else entirely; and
* an actor's pick sphere was a flat 32 units, while the billboard on screen is
  128x192 — aiming at the head hit nothing.

These tests pin both fixes, plus the rules the pick now follows: only actors
are picked (a floor brush under their feet must not win the click), an actor
behind a wall is not clickable, and hovering one marks it for the highlight.

Run:  python -m pytest engine/tests/test_inspect_pick.py -q
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from conftest import install_gl_stubs          # noqa: E402

glm = pytest.importorskip("glm")

# The viewport module pulls in the whole render stack at import time; the pick
# geometry under test touches none of it, so GL is stubbed where there is no
# driver. The methods exercised below are still QtGameView's own.
install_gl_stubs()
try:
    from engine.qt_game_view import QtGameView
except Exception as exc:                     # pragma: no cover - env-specific
    pytest.skip(f"engine.qt_game_view is not importable here ({exc})",
                allow_module_level=True)


class _Thing:
    def __init__(self, pos, props=None):
        self.pos = list(pos)
        self.properties = {"type": "npc", "name": "Villager", "health": 30}
        if props:
            self.properties.update(props)


class _State:
    def __init__(self, things=(), brushes=()):
        self.things = list(things)
        self.brushes = list(brushes)


class _Editor:
    def __init__(self, state):
        self.state = state


class _View:
    """A viewport stand-in carrying only what the pick geometry reads."""

    get_ray_from_mouse = QtGameView.get_ray_from_mouse
    _nearest_brush_along = QtGameView._nearest_brush_along
    get_object_at_3d = QtGameView.get_object_at_3d
    pick_actor_at = QtGameView.pick_actor_at
    _inspect_pick_radius = QtGameView._inspect_pick_radius
    _update_inspect_hover = QtGameView._update_inspect_hover
    _is_inspectable = staticmethod(QtGameView._is_inspectable)
    INSPECT_MIN_PICK_RADIUS = QtGameView.INSPECT_MIN_PICK_RADIUS

    def __init__(self, eye, look_at, things=(), brushes=()):
        self.editor = _Editor(_State(things, brushes))
        self.inspect_mode = True
        self.inspect_hover = None
        self.repaints = 0
        self._w, self._h = 800, 600
        self.view_matrix = glm.lookAt(glm.vec3(*eye), glm.vec3(*look_at),
                                      glm.vec3(0, 1, 0))
        self.projection_matrix = glm.perspective(glm.radians(70.0),
                                                 self._w / self._h, 0.1, 10000.0)
        # Deliberately parked far away: the old code took the ray origin from
        # here, which is exactly the bug.
        self.camera = mock.MagicMock()
        self.camera.pos = glm.vec3(9999, 9999, 9999)
        self.use_threading = True
        self.logic_thread = mock.MagicMock()
        self.logic_thread.get_editor_camera.return_value = self.camera

    def width(self):
        return self._w

    def height(self):
        return self._h

    def update(self):
        self.repaints += 1


def _centre(view):
    return view.width() // 2, view.height() // 2


# ------------------------------------------------------------------- the ray

def test_the_ray_starts_where_the_frame_was_drawn_from():
    """The regression: origin from the editor camera, direction from the play one."""
    eye = (100.0, 60.0, -200.0)
    view = _View(eye, (100.0, 60.0, 0.0))
    origin, direction = view.get_ray_from_mouse(*_centre(view))

    assert glm.length(origin - glm.vec3(*eye)) < 1e-3
    # And nowhere near the editor camera the old code used.
    assert glm.length(origin - view.camera.pos) > 1000.0
    # Down the centre of the screen is straight ahead.
    assert direction.z > 0.99


def test_the_ray_follows_the_camera_when_it_moves():
    a = _View((0.0, 0.0, 0.0), (0.0, 0.0, 100.0))
    b = _View((500.0, 0.0, 0.0), (500.0, 0.0, 100.0))
    assert glm.length(a.get_ray_from_mouse(*_centre(a))[0]
                      - b.get_ray_from_mouse(*_centre(b))[0]) > 400.0


# ---------------------------------------------------------------- pick radius

def test_the_pick_sphere_matches_the_sprite_the_renderer_drew():
    view = _View((0, 0, 0), (0, 0, 1))
    tall = _Thing((0, 0, 0), {"sprite_width": 128, "sprite_height": 192})
    assert view._inspect_pick_radius(tall) == 96.0        # half the tall side
    small = _Thing((0, 0, 0), {"sprite_width": 32, "sprite_height": 32})
    assert view._inspect_pick_radius(small) == view.INSPECT_MIN_PICK_RADIUS
    assert view._inspect_pick_radius(_Thing((0, 0, 0))) == 64.0   # 128 default


def test_aiming_at_the_head_of_a_tall_sprite_now_hits():
    """The old flat 32-unit sphere missed everything but the actor's midriff."""
    npc = _Thing((0.0, 0.0, 400.0), {"sprite_width": 128, "sprite_height": 192})
    # Look level, from a little below the top of the sprite: the ray passes
    # ~70 units above the actor's centre at that range — inside the drawn
    # billboard, outside the old 32-unit sphere.
    view = _View((0.0, 70.0, 0.0), (0.0, 70.0, 400.0), things=[npc])
    assert view.pick_actor_at(*_centre(view)) is npc
    assert glm.distance(glm.vec3(npc.pos), glm.vec3(0.0, 70.0, 400.0)) > 32.0


# --------------------------------------------------------------- what it picks

def test_only_actors_are_picked_never_the_floor_under_them():
    npc = _Thing((0.0, 0.0, 400.0))
    floor = {"pos": [0, -80, 400], "size": [4000, 32, 4000]}
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc], brushes=[floor])
    assert view.pick_actor_at(*_centre(view)) is npc


def test_an_actor_behind_a_wall_is_not_clickable():
    npc = _Thing((0.0, 0.0, 400.0))
    wall = {"pos": [0, 0, 200], "size": [400, 400, 32]}
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc], brushes=[wall])
    assert view.pick_actor_at(*_centre(view)) is None


def test_the_nearest_of_two_actors_wins():
    near = _Thing((0.0, 0.0, 300.0))
    far = _Thing((0.0, 0.0, 900.0))
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[far, near])
    assert view.pick_actor_at(*_centre(view)) is near


def test_a_hidden_actor_is_not_pickable():
    npc = _Thing((0.0, 0.0, 400.0), {"hidden": True})
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc])
    assert view.pick_actor_at(*_centre(view)) is None


def test_scenery_is_not_an_actor():
    lamp = _Thing((0.0, 0.0, 400.0), {"type": "light"})
    lamp.properties.pop("health", None)
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[lamp])
    assert view.pick_actor_at(*_centre(view)) is None
    assert view._is_inspectable(lamp) is False


def test_nothing_under_the_cursor_picks_nothing():
    npc = _Thing((5000.0, 0.0, 400.0))
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc])
    assert view.pick_actor_at(*_centre(view)) is None


# --------------------------------------------------------------------- hover

def test_hovering_marks_the_actor_and_repaints_once():
    npc = _Thing((0.0, 0.0, 400.0))
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc])
    view._update_inspect_hover(*_centre(view))
    assert view.inspect_hover is npc
    assert view.repaints == 1
    view._update_inspect_hover(*_centre(view))          # same actor, no churn
    assert view.repaints == 1


def test_looking_away_clears_the_hover():
    npc = _Thing((0.0, 0.0, 400.0))
    view = _View((0.0, 0.0, 0.0), (0.0, 0.0, 400.0), things=[npc])
    view._update_inspect_hover(*_centre(view))
    view._update_inspect_hover(0, 0)                    # top-left corner
    assert view.inspect_hover is None


def test_the_snapshot_carries_the_identity_the_highlight_matches_on():
    """The renderer draws from snapshots, so it needs the live Thing's id."""
    from editor.things import Monster

    monster = Monster([0, 0, 0])
    assert monster.get_render_snapshot()["id"] == id(monster)
