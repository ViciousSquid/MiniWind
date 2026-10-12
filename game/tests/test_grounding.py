"""
Actors stand on the ground.

The engine's AI finds the ground through brushes only, and the game's own
mover never changed an actor's height, so on terrain an actor kept the height
it was placed at: one that walked downhill, or stood where the ground was
sculpted after it was placed, floated (or sank). ``MiniwindSession`` now puts
every walking actor's feet on :func:`game.fio.ground_height` whenever it has
moved -- the terrain, or a floor standing on it, never a roof over it.

Run:  python -m pytest game/tests/test_grounding.py -q
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import fio
from .fio_logic import FioLogic


class _Terrain:
    """A slope: the ground rises one unit per unit of x."""
    enabled = True

    def get_height_at_safe(self, x, z):
        return float(x)


class _Grid:
    """Solid brush tops, as (x0, x1, top): a floor and a roof."""

    def __init__(self, tops):
        self.tops = tops

    def raycast_down(self, x, z, start_y=10000.0):
        best = None
        for x0, x1, top in self.tops:
            if x0 <= x <= x1 and top <= start_y and (best is None or top > best):
                best = top
        return best


class _Actor:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = {"type": "creature", "sprite_height": 128, **props}


class _FakeLogic(FioLogic):
    def __init__(self, actors, tops=()):
        self.things = actors
        self.player = None
        self.world_runtime = SimpleNamespace(terrain=_Terrain(), monster_things=actors)
        self.session_runtime = SimpleNamespace(spatial_grid=_Grid(list(tops)),
                                               monster_lock=None)


def _session(actors, tops=()):
    from ..runtime import MiniwindSession
    return MiniwindSession(_FakeLogic(actors, tops),
                           cfg={"start_hour": 12.0, "minutes_per_day": 999999.0})


def test_ground_height_is_the_terrain_or_a_floor_on_it_never_a_roof():
    logic = _FakeLogic([], tops=[(0, 100, 60.0), (200, 300, 900.0)])
    assert fio.ground_height(logic, 50, 0, below=80) == 60.0        # the floor
    assert fio.ground_height(logic, 150, 0, below=200) == 150.0     # the terrain
    assert fio.ground_height(logic, 250, 0, below=400) == 250.0     # not the roof


def test_floating_and_sunk_actors_are_stood_on_the_ground():
    floating = _Actor([100, 500, 0])
    sunk = _Actor([300, 100, 0])
    s = _session([floating, sunk])
    s._ground_actors()
    assert floating.pos[1] == 100 + 64
    assert sunk.pos[1] == 300 + 64


def test_an_actor_follows_the_ground_as_it_walks():
    walker = _Actor([0, 64, 0])
    s = _session([walker])
    s._ground_actors()
    walker.pos = [200.0, walker.pos[1], 0.0]          # walked uphill
    s._ground_actors()
    assert walker.pos[1] == 200 + 64


def test_flyers_stay_in_the_air():
    bat = _Actor([100, 900, 0], monster_type="flying")
    s = _session([bat])
    s._ground_actors()
    assert bat.pos[1] == 900


def test_an_actor_does_not_climb_onto_a_wall_or_fence():
    # A fence 35 units above the ground the cow stands on is too tall to
    # step onto; a 4-unit floor is not.
    cow = _Actor([50, 64, 0])
    s = _session([cow], tops=[(0, 100, 35.0)])
    cow.pos[0] = 0.0                                  # x=0: ground 0
    s._ground_actors()
    assert cow.pos[1] == 0 + 64
    floor = _Actor([500, 564, 0])
    s = _session([floor], tops=[(450, 550, 504.0)])
    s._ground_actors()
    assert floor.pos[1] == 504 + 64


# --- no jumping ------------------------------------------------------------
class _PlayerRuntime:
    def __init__(self, in_water=False):
        self.player = SimpleNamespace(in_water=in_water)
        self.seen = []

    def update_primary(self, delta, keys, mouse_dx, mouse_dy):
        self.seen.append(set(keys))


def test_the_jump_key_is_dropped_on_land_but_still_swims_in_water():
    runtime = _PlayerRuntime()
    logic = SimpleNamespace(player_runtime=runtime)
    fio.set_jump_enabled(logic, False)
    fio.set_jump_enabled(logic, False)          # installing twice is once
    runtime.update_primary(0.016, {0x20, ord("W")}, 0, 0)
    assert runtime.seen[-1] == {ord("W")}
    runtime.player.in_water = True
    runtime.update_primary(0.016, {0x20}, 0, 0)
    assert runtime.seen[-1] == {0x20}
    fio.set_jump_enabled(logic, True)
    runtime.player.in_water = False
    runtime.update_primary(0.016, {0x20}, 0, 0)
    assert runtime.seen[-1] == {0x20}
