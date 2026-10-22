"""
Schedule-driven NPCs must respect walls.

The RPG runtime walks villagers, guards and shopkeepers to their homes, posts
and beds. It used to do that by writing a position with no collision test at
all, so an NPC heading home cut straight through the house instead of round to
the door. The mover now takes the same slide-along-walls step the combat AI
does, against the same spatial grid.

Run:  python -m pytest game/tests/test_npc_movement.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import runtime
from ..runtime import MiniwindSession
from ..navigation import Navigator
from .fio_logic import FioLogic


class _NPC:
    def __init__(self, pos=(0.0, 0.0, 0.0), dest=(0.0, 0.0, 1000.0), **props):
        self.pos = list(pos)
        self.properties = {"_dest": list(dest), "move_speed": runtime.NPC_WALK_SPEED}
        self.properties.update(props)


class _AI:
    """Stands in for the engine's MonsterAI wall query.

    *walls* are axis-aligned (x_min, x_max, z_min, z_max) footprints; a body is
    blocked when its margin box overlaps one. That is the same question
    MonsterAI._monster_overlaps_wall answers off the spatial grid, without
    needing a live play session to build one.
    """

    def __init__(self, walls=()):
        self.walls = list(walls)
        self.queries = 0

    def _monster_overlaps_wall(self, x, y, z, margin):
        self.queries += 1
        for x0, x1, z0, z1 in self.walls:
            if (x + margin > x0 and x - margin < x1
                    and z + margin > z0 and z - margin < z1):
                return True
        return False


class _Logic(FioLogic):
    def __init__(self, walls=()):
        self.monster_ai = _AI(walls)


class _Walker:
    """The runtime's mover with a scene behind it, and nothing else."""

    _move = MiniwindSession._move
    _step_to = MiniwindSession._step_to
    _blocked_by_wall = MiniwindSession._blocked_by_wall

    def __init__(self, walls=()):
        self.logic = _Logic(walls)
        # Exercise the same wall-routing layer that MiniwindSession installs.
        self.nav = Navigator(self._blocked_by_wall)


#: A wall straight across the NPC's path north, with a gap nowhere near it.
_WALL_ACROSS_PATH = [(-400.0, 400.0, 200.0, 260.0)]


def test_an_npc_walks_when_nothing_is_in_the_way():
    npc = _NPC()
    _Walker()._move(npc, 1.0)
    assert npc.pos[2] > 0.0


def test_an_npc_routes_around_a_wall_without_clipping_through_it():
    """A directly blocked step must activate navigation and find the wall's end."""
    npc = _NPC()
    walker = _Walker(_WALL_ACROSS_PATH)
    margin = runtime.NPC_WALL_MARGIN
    for _ in range(300):
        walker._move(npc, 0.1)
        x, z = npc.pos[0], npc.pos[2]
        overlaps_x = x + margin > -400.0 and x - margin < 400.0
        overlaps_z = z + margin > 200.0 and z - margin < 260.0
        assert not (overlaps_x and overlaps_z), "the NPC clipped through the wall"
    assert npc.pos[2] > 260.0, "the NPC never made it around the wall"


def test_a_blocked_npc_slides_or_routes_along_the_wall_without_clipping():
    """An oblique approach may slide first, then pass the wall's end."""
    npc = _NPC(pos=(0.0, 0.0, 0.0), dest=(1000.0, 0.0, 1000.0))
    walker = _Walker(_WALL_ACROSS_PATH)
    margin = runtime.NPC_WALL_MARGIN
    for _ in range(100):
        walker._move(npc, 0.1)
        x, z = npc.pos[0], npc.pos[2]
        overlaps_x = x + margin > -400.0 and x - margin < 400.0
        overlaps_z = z + margin > 200.0 and z - margin < 260.0
        assert not (overlaps_x and overlaps_z), "the NPC clipped through the wall"
    assert npc.pos[0] > 100.0, "it should make progress along the wall"


def test_a_blocked_axis_fallback_does_not_count_a_no_op_as_movement():
    # The NPC is just outside the wall's collision margin. The next northward
    # step is blocked, while the attempted X-axis slide leaves X unchanged.
    npc = _NPC(pos=(0.0, 0.0, 170.0), dest=(0.0, 0.0, 1000.0))
    walker = _Walker(_WALL_ACROSS_PATH)
    assert walker._step_to(npc, 0.0, 179.0) is False
    assert npc.pos == [0.0, 0.0, 170.0]


def test_an_npc_finds_its_way_through_a_gap():
    walls = [(-2000.0, -100.0, 200.0, 260.0), (100.0, 2000.0, 200.0, 260.0)]
    npc = _NPC(pos=(-300.0, 0.0, 0.0), dest=(0.0, 0.0, 1000.0))
    walker = _Walker(walls)
    for _ in range(300):
        walker._move(npc, 0.1)
    assert npc.pos[2] > 260.0, "it never got through the doorway"


def test_an_npc_jammed_in_a_corner_gives_up_on_its_destination():
    """Better a new errand than grinding into a brush for the rest of the day."""
    # Enclose all four sides: an open corner can now be escaped by A*.
    box = [(-1000.0, 1000.0, 60.0, 400.0), (60.0, 1000.0, -1000.0, 1000.0),
           (-1000.0, 1000.0, -400.0, -60.0), (-1000.0, -60.0, -1000.0, 1000.0)]
    npc = _NPC(pos=(0.0, 0.0, 0.0), dest=(1000.0, 0.0, 1000.0))
    walker = _Walker(box)
    for _ in range(runtime.NPC_BLOCKED_GIVE_UP_TICKS + 5):
        walker._move(npc, 0.1)
    assert "_dest" not in npc.properties


def test_a_walking_npc_costs_one_wall_query_a_tick():
    """Per NPC, per tick, on the same grid the combat AI already uses."""
    npc = _NPC()
    walker = _Walker()
    for _ in range(50):
        walker._move(npc, 0.01)
    assert walker.logic.monster_ai.queries == 50


def test_an_npc_that_has_arrived_costs_nothing_at_all():
    npc = _NPC(pos=(0.0, 0.0, 0.0), dest=(0.0, 0.0, 0.0))
    walker = _Walker()
    for _ in range(50):
        walker._move(npc, 0.1)
    assert walker.logic.monster_ai.queries == 0


def test_the_npc_margin_lets_them_through_a_player_sized_door():
    """A villager must fit anywhere the player does, not need a monster's berth."""
    from engine.monster_constants import MONSTER_WALL_MARGIN

    assert runtime.NPC_WALL_MARGIN < MONSTER_WALL_MARGIN
    assert runtime.NPC_WALL_MARGIN >= 25.0        # the player's own half-width


def test_no_live_scene_means_nothing_is_solid():
    """The schedule stays testable, and playable, without a spatial grid."""
    class _Bare:
        _move = MiniwindSession._move
        _step_to = MiniwindSession._step_to
        _blocked_by_wall = MiniwindSession._blocked_by_wall
        logic = None

    npc = _NPC()
    _Bare()._move(npc, 1.0)
    assert npc.pos[2] > 0.0
