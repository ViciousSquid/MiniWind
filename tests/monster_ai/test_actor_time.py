"""Actors whose own clock is altered (engine/actor_time.py).

Under a slowed world (``LogicThread.time_scale`` 0.5) the logic thread and
the monster AI run half as many fixed ticks a real second. An actor given a
time rate of 2 -- MiniWind's Slow Time caster -- takes twice each tick's
delta, so over one real second it covers what it would at normal speed while
everyone else covers half: twice as fast as the world round it.
"""

import glm
import numpy as np
import pytest

from engine import actor_time
from engine.monster_constants import MONSTER_MOVE_SPEED

pytestmark = pytest.mark.qt

AI_TICK = 1.0 / 30.0


def _ticks(real_seconds, time_scale, tick):
    """How many fixed ticks a thread runs in *real_seconds* at *time_scale*
    (the accumulators of LogicThread._run_loop and MonsterAIThread.run)."""
    return int(real_seconds * time_scale / tick + 1e-9)


def test_rates_are_set_cleared_and_cost_nothing_when_none(ai_world):
    _ai, logic = ai_world()
    thing = object()
    assert actor_time.rate(logic, thing) == 1.0
    assert actor_time.row_deltas(logic, [thing], 0.1) == (None, None)
    actor_time.set_rate(logic, thing, 2.0)
    assert actor_time.rate(logic, thing) == 2.0
    rows, sit = actor_time.row_deltas(logic, [object(), thing], 0.1)
    assert rows.tolist() == pytest.approx([0.1, 0.2]) and not sit.any()
    actor_time.set_rate(logic, thing, 1.0)        # back in step: forgotten
    assert logic.actor_time_rates == {}
    actor_time.set_rate(logic, thing, 2.0)
    actor_time.clear(logic)
    assert actor_time.rate(logic, thing) == 1.0


def test_a_monster_with_its_own_clock_outruns_the_slowed_world(
        monster_factory, ai_world, flat_ground):
    """Over one real second at half speed, the caster's monster closes what it
    would at normal speed; the other, half of it."""
    caster = monster_factory("caster", (600, 96, 0))
    other = monster_factory("other", (-600, 96, 0))
    ai, logic = ai_world(brushes=flat_ground, things=[caster, other])
    logic.time_scale = 0.5
    actor_time.set_rate(logic, caster, 1.0 / logic.time_scale)
    for _ in range(_ticks(1.0, logic.time_scale, AI_TICK)):
        ai.update(AI_TICK)
    caster_run = 600.0 - caster.pos[0]
    other_run = other.pos[0] + 600.0
    assert caster_run == pytest.approx(MONSTER_MOVE_SPEED * 1.0, rel=0.02)
    assert other_run == pytest.approx(MONSTER_MOVE_SPEED * 0.5, rel=0.02)
    assert caster_run / other_run == pytest.approx(2.0, rel=0.02)


def test_the_per_monster_path_honours_the_clock_too(monster_factory, ai_world, flat_ground):
    caster = monster_factory("caster", (600, 96, 0))
    other = monster_factory("other", (-600, 96, 0))
    ai, logic = ai_world(brushes=flat_ground, things=[caster, other])
    ai.DENSE_UPDATE = False
    actor_time.set_rate(logic, caster, 2.0)
    for _ in range(6):
        ai.update(AI_TICK)
    assert (600.0 - caster.pos[0]) == pytest.approx(2.0 * (other.pos[0] + 600.0), rel=0.02)


def _walk(logic, real_seconds):
    """Hold W for *real_seconds* of real time; the distance walked."""
    from engine.logic_player import KEY_W
    tick = logic.TICK_DURATION
    player = logic.player_runtime.player
    start = glm.vec3(player.pos)
    for _ in range(_ticks(real_seconds, getattr(logic, "time_scale", 1.0), tick)):
        logic.player_runtime.update_primary(tick, {KEY_W}, 0.0, 0.0)
    end = player.pos
    return float(np.hypot(end.x - start.x, end.z - start.z))


@pytest.fixture
def walker(ai_world, flat_ground):
    def _make():
        _ai, logic = ai_world(brushes=flat_ground, player_pos=(0.0, 40.0, 0.0))
        logic.session_runtime.apply_play_mode(True)
        logic.session_runtime.stop_monster_ai()
        logic.player_runtime.update_primary(logic.TICK_DURATION, set(), 0.0, 0.0)
        for _ in range(30):                          # settle on the floor
            logic.player_runtime.update_primary(logic.TICK_DURATION, set(), 0.0, 0.0)
        return logic
    return _make


def test_the_player_with_its_own_clock_walks_at_normal_speed_in_a_slowed_world(walker):
    normal = walker()
    normal_run = _walk(normal, 1.0)
    slowed = walker()
    slowed.time_scale = 0.5
    slowed_run = _walk(slowed, 1.0)
    caster = walker()
    caster.time_scale = 0.5
    actor_time.set_rate(caster, caster.player_runtime.player, 2.0)
    caster_run = _walk(caster, 1.0)
    assert normal_run > 50.0
    assert caster_run == pytest.approx(normal_run, rel=0.06)
    assert caster_run / slowed_run == pytest.approx(2.0, rel=0.1)
