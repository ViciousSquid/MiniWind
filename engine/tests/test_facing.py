"""
Tests for the shared actor-heading module (:mod:`engine.facing`).

Every system that moves an actor writes its heading through here, because the
renderer reads exactly one property (``_facing``) to decide which way a head
billboard, an overhead ground sprite and an equipped weapon point. These tests
pin the convention (forward is ``(sin a, 0, cos a)``), the easing, the
hold-your-heading rule for a stationary actor, and — the bug that started this —
that the RPG runtime's NPC mover actually writes the property the renderer reads.

Run:  python -m pytest engine/tests/test_facing.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import facing


def test_heading_uses_the_engine_forward_convention():
    # Forward at heading 0 is +z; +x is a quarter turn.
    assert facing.heading_from(0.0, 1.0) == 0.0
    assert math.isclose(facing.heading_from(1.0, 0.0), math.pi / 2)
    assert math.isclose(facing.heading_from(0.0, -1.0), math.pi)
    assert math.isclose(facing.heading_from(-1.0, 0.0), -math.pi / 2)


def test_first_heading_is_set_outright():
    props = {}
    facing.face_heading(props, 1.0, 0.0)
    assert math.isclose(props[facing.FACING_KEY], math.pi / 2)


def test_a_turn_is_eased_over_time_not_snapped():
    props = {facing.FACING_KEY: 0.0}
    # Ask for most of a half turn (not exactly pi, where either way round is
    # equally short and the direction is arbitrary).
    facing.face_heading(props, -0.2, -1.0, delta=0.016)
    turned = props[facing.FACING_KEY]
    step = facing.ACTOR_TURN_RATE * 0.016
    assert 0.0 < abs(turned) <= step + 1e-9   # it moved, but only one step
    assert abs(turned) < math.pi * 0.9        # nowhere near there yet


def test_easing_takes_the_short_way_round():
    # From just below +pi to just above -pi is a small turn, not a full lap.
    props = {facing.FACING_KEY: math.pi - 0.05}
    facing.face_heading(props, -0.05, -1.0, delta=0.016)
    # Still near the far side of the circle, and it moved *up* toward +pi
    # (wrapping) rather than unwinding the long way through zero.
    assert abs(facing.wrap_angle(props[facing.FACING_KEY] - (math.pi - 0.05))) < 0.2


def test_arriving_snaps_exactly_when_within_one_step():
    props = {facing.FACING_KEY: 0.0}
    facing.face_heading(props, 0.001, 1.0, delta=1.0)
    assert math.isclose(props[facing.FACING_KEY], math.atan2(0.001, 1.0))


def test_a_stationary_actor_holds_its_heading():
    props = {facing.FACING_KEY: 1.25}
    facing.face_heading(props, 0.0, 0.0, delta=0.016)
    assert props[facing.FACING_KEY] == 1.25


def test_get_heading_falls_back_to_the_design_time_angle():
    assert facing.get_heading({'angle': 0.75}) == 0.75
    assert facing.get_heading({facing.FACING_KEY: 0.5, 'angle': 0.75}) == 0.5
    assert facing.get_heading({}) == 0.0
    assert facing.get_heading({facing.FACING_KEY: None, 'angle': None}) == 0.0


def test_runtime_npc_mover_writes_the_property_the_renderer_reads():
    """The regression: schedule-driven NPCs used to write a bare ``angle``.

    ``Monster.get_render_state`` snapshots ``_facing`` (and nothing else) as the
    angle the 3D head billboard rotates by, so an NPC walked by the RPG runtime
    slid around the world without ever turning.
    """
    from game.runtime import MiniwindSession

    class _NPC:
        def __init__(self):
            self.pos = [0.0, 0.0, 0.0]
            self.properties = {"_dest": [1000.0, 0.0, 0.0], "move_speed": 90.0}

    npc = _NPC()
    # Unbound call: _move touches nothing on the session itself.
    MiniwindSession._move(None, npc, 0.1)

    assert npc.pos[0] > 0.0                       # it walked
    assert facing.FACING_KEY in npc.properties    # and it turned
    assert math.isclose(npc.properties[facing.FACING_KEY], math.pi / 2, abs_tol=1e-6)


def test_a_fleeing_villager_moves_at_double_speed():
    """Fright doubles the step, and only for as long as the fright lasts.

    The FLEE state is re-decided every tick and dropped as soon as no hostile is
    in sight, so the multiplier is inherently temporary — this pins the factor
    and that a calm NPC is unaffected.
    """
    from game import runtime
    from game.rpg import schedule as sched

    def _walk(state):
        class _NPC:
            def __init__(self):
                self.pos = [0.0, 0.0, 0.0]
                self.properties = {"_dest": [100000.0, 0.0, 0.0],
                                   "move_speed": runtime.NPC_WALK_SPEED}
                if state:
                    self.properties["sched_state"] = state
        npc = _NPC()
        runtime.MiniwindSession._move(None, npc, 1.0)
        return npc.pos[0]

    calm = _walk(None)
    fleeing = _walk(sched.FLEE)
    assert math.isclose(calm, runtime.NPC_WALK_SPEED)
    assert math.isclose(fleeing, calm * runtime.FLEE_SPEED_MULTIPLIER)
    assert runtime.FLEE_SPEED_MULTIPLIER == 2.0
