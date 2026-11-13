"""
Tests for MiniWind's actor heading (:mod:`game.facing`).

An actor has one heading, its ``angle`` (degrees), written only through
:mod:`engine.monster_facing`; the head billboard, the overhead weapon and the
2D map all read it. These tests pin the convention (forward is
``(sin a, 0, cos a)``), the easing, the hold-your-heading rule for a
stationary actor, and that the RPG runtime's NPC mover turns its NPC.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from .. import facing


def actor(angle=None):
    return SimpleNamespace(pos=[0.0, 0.0, 0.0],
                           properties={} if angle is None else {"angle": angle})


def test_heading_uses_the_engine_forward_convention():
    # Forward at heading 0 is +z; +x is a quarter turn.
    assert facing.heading_from(0.0, 1.0) == 0.0
    assert math.isclose(facing.heading_from(1.0, 0.0), math.pi / 2)
    assert math.isclose(facing.heading_from(0.0, -1.0), math.pi)
    assert math.isclose(facing.heading_from(-1.0, 0.0), -math.pi / 2)


def test_without_a_delta_the_heading_is_set_outright():
    a = actor()
    facing.face_heading(a, 1.0, 0.0)
    assert math.isclose(a.properties["angle"], 90.0)
    assert math.isclose(facing.heading(a), math.pi / 2)


def test_a_turn_is_eased_over_time_not_snapped():
    a = actor(0.0)
    # Ask for most of a half turn (not exactly pi, where either way round is
    # equally short and the direction is arbitrary).
    facing.face_heading(a, -0.2, -1.0, delta=0.016)
    turned = facing.wrap_angle(facing.heading(a))
    step = facing.ACTOR_TURN_RATE * 0.016
    assert 0.0 < abs(turned) <= step + 1e-9   # it moved, but only one step
    assert abs(turned) < math.pi * 0.9        # nowhere near there yet


def test_easing_takes_the_short_way_round():
    a = actor(math.degrees(math.pi - 0.05))
    facing.face_heading(a, -0.05, -1.0, delta=0.016)
    assert abs(facing.wrap_angle(facing.heading(a) - (math.pi - 0.05))) < 0.2


def test_arriving_snaps_exactly_when_within_one_step():
    a = actor(0.0)
    facing.face_heading(a, 0.001, 1.0, delta=1.0)
    assert math.isclose(facing.heading(a), math.atan2(0.001, 1.0))


def test_a_stationary_actor_holds_its_heading():
    a = actor(71.6)
    facing.face_heading(a, 0.0, 0.0, delta=0.016)
    assert a.properties["angle"] == 71.6


def test_the_heading_is_the_design_time_angle_until_play_turns_it():
    assert math.isclose(facing.heading(actor(90.0)), math.pi / 2)
    assert facing.heading(actor()) == 0.0
    assert facing.heading(actor(None)) == 0.0


def test_install_makes_the_engine_ease_its_own_turns(monkeypatch):
    from engine import monster_facing
    monkeypatch.setattr(monster_facing, "TURN_RATE", None)
    facing.install()
    a = actor(0.0)
    monster_facing.face_direction(a, (-0.2, 0.0, -1.0), 0.016)
    assert abs(facing.wrap_angle(facing.heading(a))) <= facing.ACTOR_TURN_RATE * 0.016 + 1e-9


class _NPC:
    def __init__(self, dest=(1000.0, 0.0, 0.0), **props):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = {"_dest": list(dest), "move_speed": 90.0}
        self.properties.update(props)


class _Walker:
    """Just the RPG runtime's mover, with no live scene behind it.

    ``logic`` is None, so the wall test finds no spatial grid and nothing is
    solid — which is what isolates these tests to the movement and turning
    rules. Wall collision has its own tests in game/tests/test_npc_movement.py.
    """

    from ..runtime import MiniwindSession as _S
    _move = _S._move
    _step_to = _S._step_to
    _blocked_by_wall = _S._blocked_by_wall
    logic = None


def test_runtime_npc_mover_turns_the_npc_it_walks():
    """The regression: schedule-driven NPCs slid around without turning."""
    npc = _NPC()
    _Walker()._move(npc, 0.1)

    assert npc.pos[0] > 0.0                       # it walked
    # ...and swung one eased step from its authored heading (0) toward +X.
    assert math.isclose(facing.heading(npc), facing.ACTOR_TURN_RATE * 0.1, abs_tol=1e-6)
    for _ in range(5):
        _Walker()._move(npc, 0.1)
    assert math.isclose(facing.heading(npc), math.pi / 2, abs_tol=1e-6)


def test_a_fleeing_villager_runs_while_its_stamina_lasts():
    """Fright makes a villager run, paid for in stamina; winded, it walks.

    The FLEE state is re-decided every tick and dropped as soon as no hostile is
    in sight, so the run is inherently temporary -- this pins the pace, that a
    calm NPC is unaffected, and that a winded one is back to a walk.
    """
    from .. import npc_stamina, runtime
    from ..rpg import schedule as sched

    def _walk(state, **extra):
        props = {"move_speed": runtime.NPC_WALK_SPEED, **extra}
        if state:
            props["sched_state"] = state
        npc = _NPC(dest=(100000.0, 0.0, 0.0), **props)
        _Walker()._move(npc, 1.0)
        return npc.pos[0]

    calm = _walk(None)
    fleeing = _walk(sched.FLEE)
    assert math.isclose(calm, runtime.NPC_WALK_SPEED)
    assert math.isclose(fleeing, calm * npc_stamina.RUN_SCALE)
    assert math.isclose(_walk(sched.FLEE, _stamina=0.0, _stamina_at=0.0), calm)
