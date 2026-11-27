"""
An NPC whose way is blocked strafes round the obstacle, still facing its goal.

The worlds here are real brushes in the engine's own spatial grid -- the very
collision test the runtime's mover and Fio's combat chase step against --
with a crate, a pillar or a corridor dropped across an NPC's path.

Run:  python -m pytest game/tests/test_strafe.py -q
"""

from __future__ import annotations

import math

import pytest

from engine import monster_facing
from engine.spatial_grid import SpatialGrid
from tests.helpers.worlds import box_brush

from .. import runtime, strafe
from ..combat_tactics import CombatTactics
from ..navigation import Navigator
from ..runtime import MiniwindSession
from .fio_logic import FioLogic

DT = 1.0 / 30.0
GROUND = box_brush("ground", (0, -16, 0), (8192, 32, 8192))


class _GridAI:
    """MonsterAI's wall query, answered off a real spatial grid of brushes."""

    def __init__(self, brushes):
        self._grid = SpatialGrid()
        self._grid.populate([GROUND, *brushes])

    def _monster_overlaps_wall(self, x, y, z, margin):
        return self._grid.overlaps_wall(x, y, z, margin)


class _Logic(FioLogic):
    def __init__(self, brushes):
        self.monster_ai = _GridAI(brushes)


class _Walker:
    """The runtime's mover (and its wall routing) over a real small world."""

    _move = MiniwindSession._move
    _step_to = MiniwindSession._step_to
    _slide_to = MiniwindSession._slide_to
    _glance_or_strafe = MiniwindSession._glance_or_strafe
    _strafe_tick = MiniwindSession._strafe_tick
    _blocked_by_wall = MiniwindSession._blocked_by_wall

    def __init__(self, brushes):
        self.logic = _Logic(brushes)
        self.nav_clock = [0.0]
        self.nav = Navigator(self._blocked_by_wall, clock=lambda: self.nav_clock[0])

    def inside(self, npc, margin=runtime.NPC_WALL_MARGIN):
        return self.logic.monster_ai._monster_overlaps_wall(
            npc.pos[0], npc.pos[1], npc.pos[2], margin)


class _NPC:
    def __init__(self, pos=(0.0, 0.0, 0.0), dest=(0.0, 0.0, 1200.0), **props):
        self.pos = list(pos)
        self.properties = {"_dest": list(dest), "move_speed": runtime.NPC_WALK_SPEED,
                           "angle": 0.0}
        self.properties.update(props)


def _crate(x=0.0, z=200.0, w=64.0, d=64.0, name="crate"):
    return box_brush(name, (x, 32, z), (w, 64, d))


def _off_goal_degrees(npc, goal):
    """How far (degrees) *npc*'s facing is from looking straight at *goal*."""
    want = math.atan2(goal[0] - npc.pos[0], goal[2] - npc.pos[2])
    return abs(math.degrees(monster_facing.wrap(monster_facing.heading(npc) - want)))


def _walk(walker, npc, ticks):
    """Walk *ticks* ticks; the per-tick (x, z, strafing, off-goal facing)."""
    goal = npc.properties["_dest"]
    out = []
    for _ in range(ticks):
        # The planner's work budget and route refreshes run on a 60 Hz clock.
        # Advance it with the simulated 30 Hz walk; wall time makes this test
        # depend on how quickly the CI runner executes its 400 ticks.
        walker.nav_clock[0] += DT
        walker._move(npc, DT)
        assert not walker.inside(npc), "the NPC walked into the obstacle"
        out.append((npc.pos[0], npc.pos[2], strafe.strafing(npc.properties),
                    _off_goal_degrees(npc, goal)))
    return out


# ------------------------------------------------------------------ walking

def test_an_npc_walking_at_a_crate_strafes_round_it_still_facing_its_goal():
    walker = _Walker([_crate()])
    npc = _NPC()
    trace = _walk(walker, npc, 600)
    strafing = [t for t in trace if t[2]]
    assert strafing, "it never strafed"
    # Sideways: its lateral displacement grows tick on tick while it strafes,
    # and its forward position holds (it does not slide forward along the face).
    xs = [abs(x) for x, _z, _s, _f in strafing]
    assert all(b > a for a, b in zip(xs, xs[1:]))
    assert xs[-1] >= 32.0 + runtime.NPC_WALL_MARGIN
    zs = [z for _x, z, _s, _f in strafing]
    assert max(zs) - min(zs) < 1.0
    # And it keeps looking where it is going, not where it steps.
    assert max(f for *_rest, f in strafing) < 10.0
    # It got past, by stepping round rather than by a route.
    assert npc.pos[2] > 232.0 + runtime.NPC_WALL_MARGIN
    assert not walker.nav.has_route(id(npc))
    assert npc.properties.get("_blocked_ticks", 0) == 0


def test_it_strafes_toward_the_side_with_the_nearer_way_round():
    # The crate sits mostly to the right (+X) of the NPC's line: left is shorter.
    walker = _Walker([_crate(x=24.0)])
    npc = _NPC()
    trace = _walk(walker, npc, 600)
    strafing = [t for t in trace if t[2]]
    assert strafing and all(x < 0.0 for x, *_rest in strafing)
    assert npc.properties[strafe.SIDE] == -1
    assert npc.pos[2] > 300.0


def test_a_tie_goes_to_the_side_last_strafed():
    walker = _Walker([_crate()])
    npc = _NPC()
    npc.properties[strafe.SIDE] = -1
    trace = _walk(walker, npc, 600)
    assert all(x < 0.0 for x, _z, s, _f in trace if s)
    assert npc.pos[2] > 300.0


def test_a_strafe_commits_to_its_side_without_dithering():
    walker = _Walker([_crate(), _crate(x=-150.0, z=420.0, name="crate2")])
    npc = _NPC()
    trace = _walk(walker, npc, 900)
    # Each strafe keeps one side from its first sidestep to its last.
    runs, current = [], []
    for x, z, s, _f in trace:
        if s:
            current.append((x, z))
        elif current:
            runs.append(current)
            current = []
    assert runs
    for run in runs:
        steps = [b[0] - a[0] for a, b in zip(run, run[1:])]
        assert all(st > 0 for st in steps) or all(st < 0 for st in steps)
        assert len(run) * DT >= strafe.STRAFE_MIN_SECONDS - DT
    assert npc.pos[2] > 500.0


def test_an_npc_with_a_clear_path_does_not_strafe():
    walker = _Walker([_crate(x=400.0)])           # off to the side, not in the way
    npc = _NPC()
    trace = _walk(walker, npc, 200)
    assert not any(s for _x, _z, s, _f in trace)
    assert all(x == 0.0 for x, *_rest in trace)
    assert strafe.REST not in npc.properties
    assert npc.pos[2] > 500.0


def test_a_glancing_contact_with_a_long_wall_still_slides_along_it():
    wall = box_brush("wall", (0, 64, 400), (1600, 128, 32))
    walker = _Walker([wall])
    npc = _NPC(dest=(1200.0, 0.0, 1200.0))
    trace = _walk(walker, npc, 300)
    assert not any(s for _x, _z, s, _f in trace)
    # It reached the wall, and slid on along it toward the goal.
    assert any(z >= 384.0 - runtime.NPC_WALL_MARGIN - 5.0 for _x, z, _s, _f in trace)
    assert npc.pos[0] > 500.0


def test_shut_in_on_both_sides_it_falls_back_on_a_route_without_crashing():
    # A corridor just wider than a body, with a crate across it: no sidestep
    # is open either way.
    walls = [box_brush("left", (-50, 64, 0), (20, 128, 800)),
             box_brush("right", (50, 64, 0), (20, 128, 800)),
             _crate(w=80.0)]
    walker = _Walker(walls)
    npc = _NPC(pos=(0.0, 0.0, -300.0))
    rested = blocked = routed = False
    for _ in range(400):
        (_x, _z, s, _f), = _walk(walker, npc, 1)       # (and never clips a wall)
        assert not s, "there was nowhere to strafe to"
        rested = rested or bool(npc.properties.get(strafe.REST))
        blocked = blocked or bool(npc.properties.get("_blocked_ticks"))
        routed = routed or walker.nav.has_route(id(npc))
    # It fell back: a rest before probing again, a blocked step, and the
    # route machinery taking over from there.
    assert rested and blocked and routed


def test_a_long_wall_is_not_strafed_along_it_is_routed_round():
    wall = box_brush("wall", (0, 64, 300), (900, 128, 40))
    walker = _Walker([wall])
    npc = _NPC()
    routed = False
    for _ in range(400):
        (_x, _z, s, _f), = _walk(walker, npc, 1)
        assert not s
        routed = routed or walker.nav.has_route(id(npc))
    assert routed
    assert npc.pos[2] > 320.0 + runtime.NPC_WALL_MARGIN


def test_a_fleeing_npc_strafes_too():
    from ..rpg import schedule as sched
    walker = _Walker([_crate()])
    npc = _NPC(sched_state=sched.FLEE, _flee=True)
    trace = _walk(walker, npc, 400)
    assert any(s for _x, _z, s, _f in trace)
    assert npc.pos[2] > 300.0


def test_the_strafe_side_is_a_quarter_turn_off_the_heading():
    # Heading +Z: side +1 is +X (the heading's +90 degrees), -1 is -X.
    assert strafe.side_vector(0.0, 1.0, 1) == (1.0, -0.0)
    assert strafe.side_vector(0.0, 1.0, -1) == (-1.0, 0.0)


# ------------------------------------------------------------ combat chase

def _chase_world(dense, crate=True):
    """Fio's own MonsterAI over a real grid: one hunter, the player beyond."""
    import glm
    import numpy as np
    from editor.editor_state import EditorState
    from editor.things import Monster
    from engine.hostility import HostilityModel
    from engine.logic_thread import LogicThread
    from engine.monster_ai import MonsterAI
    from engine.player import Player
    from engine.threaded_game_state import ThreadedGameState
    from tests.helpers.worlds import make_thing

    brushes = [GROUND]
    if crate:
        brushes.append(box_brush("crate", (0, 100, 300), (64, 200, 64)))
    hunter = make_thing(Monster, "hunter", (0, 96, 0), monster_type="human", team="red",
                        awake=True, wake_on_sight=True, health=60, damage=0)
    state = EditorState()
    state.brushes = brushes
    state.things = [hunter]
    logic = LogicThread(ThreadedGameState(), state)
    logic.player_runtime.player = Player(0.0, 0.0)
    logic.player_runtime.player.pos = glm.vec3(0.0, 0.0, 900.0)
    logic.player_runtime.player_health = 10 ** 9
    logic.player_runtime.player_max_health = 10 ** 9
    logic.world_runtime.build_entity_caches()
    ai = MonsterAI(logic)
    logic.monster_ai = ai
    ai.DENSE_UPDATE = dense
    grid = SpatialGrid()
    grid.populate(brushes)
    ai.set_spatial_grid(grid)
    logic.session_runtime.spatial_grid = grid
    ai.set_hostility(HostilityModel(["red"], np.zeros((1, 1), bool), [True]))
    return ai, hunter


def _chase(dense, crate=True, ticks=300):
    """Run the chase with CombatTactics as the steer hook (as MiniWind installs
    it); per tick (x, z, strafing, off-target facing)."""
    from engine.monster_ai import MonsterAI
    from engine.monster_constants import MONSTER_WALL_MARGIN
    ai, hunter = _chase_world(dense, crate)
    clock = [0.0]
    tactics = CombatTactics(lambda: clock[0], blocked=lambda x, y, z: ai._monster_overlaps_wall(
        x, y, z, MONSTER_WALL_MARGIN))
    player = (0.0, 0.0, 900.0)
    trace = []
    MonsterAI.install_steer_hook(tactics.steer_many)
    try:
        for _ in range(ticks):
            ai.update(DT)
            clock[0] += DT
            assert not ai._monster_overlaps_wall(*hunter.pos, MONSTER_WALL_MARGIN)
            trace.append((hunter.pos[0], hunter.pos[2], strafe.strafing(hunter.properties),
                          _off_goal_degrees(hunter, player)))
    finally:
        MonsterAI.clear_steer_hook(tactics.steer_many)
    return trace


@pytest.mark.qt
@pytest.mark.parametrize("dense", [True, False])
def test_a_chaser_blocked_by_a_crate_strafes_round_it_facing_its_foe(dense):
    from engine.monster_constants import MONSTER_WALL_MARGIN
    trace = _chase(dense)
    strafing = [t for t in trace if t[2]]
    assert strafing, "the chaser never strafed"
    xs = [abs(x) for x, *_rest in strafing]
    assert all(b >= a for a, b in zip(xs, xs[1:]))
    assert xs[-1] >= 32.0 + MONSTER_WALL_MARGIN
    # Fio keeps a chaser facing its target, and a strafe waypoint changes that
    # not at all.
    assert max(f for *_rest, f in strafing) < 5.0
    assert trace[-1][1] > 332.0 + MONSTER_WALL_MARGIN, "it never got past the crate"


@pytest.mark.qt
def test_a_chaser_in_the_open_is_left_alone():
    trace = _chase(True, crate=False, ticks=120)
    assert not any(s for _x, _z, s, _f in trace)
    assert all(abs(x) < 1e-6 for x, *_rest in trace)
