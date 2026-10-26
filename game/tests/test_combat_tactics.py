"""Casters and archers keep their distance, and can still be caught and cut down."""

import math

import pytest

from .. import combat_styles
from ..combat_tactics import (ADVANCE, COMMIT, COMMIT_RANGE, FIGHTER_SPEED, HOLD,
                              KEEP_BAND, RETREAT, CombatTactics)
from ..combat_loadout import MAGIC

combat_styles.register()

DT = 1.0 / 30.0


class _Actor:
    def __init__(self, **props):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = props


def _caster():
    return _Actor(attack_style="magic", equipped_weapon="apprentice_staff",
                  spells=[{"id": "flare"}], inventory=[{"id": "iron_dagger", "qty": 1}])


def _swordsman():
    return _Actor(attack_style="melee", equipped_weapon="iron_longsword", inventory=[])


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _step(tactics, actor, foe_x, clock):
    """One engine step: the caster moves at fighter pace toward its waypoint."""
    start = (actor.pos[0], 0.0, actor.pos[2])
    wp = tactics.waypoint(actor, start, (foe_x, 0.0, 0.0))
    goal = (foe_x, 0.0, 0.0) if wp is None else wp
    dx, dz = goal[0] - start[0], goal[2] - start[2]
    d = math.hypot(dx, dz)
    # Fio steps only fighters beyond its stop distance, toward the waypoint.
    if d > 1e-3 and math.hypot(foe_x - start[0], start[2]) > 85.0:
        actor.pos[0] += dx / d * FIGHTER_SPEED * DT
        actor.pos[2] += dz / d * FIGHTER_SPEED * DT
    clock.t += DT


def _chase(foe_speed, seconds=40.0):
    """A foe running at *foe_speed* straight at a kiting caster; the time it
    first gets within striking range, or None."""
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    foe_x = 700.0
    for _ in range(int(seconds / DT)):
        _step(tactics, caster, foe_x, clock)
        gap = math.hypot(foe_x - caster.pos[0], caster.pos[2])
        if gap <= COMMIT_RANGE:
            return clock.t, tactics
        foe_x -= math.copysign(foe_speed * DT, foe_x - caster.pos[0])
    return None, tactics


def test_a_ranged_caster_stands_in_its_band():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    near, far = KEEP_BAND[MAGIC]
    wp = tactics.waypoint(caster, (0.0, 0.0, 0.0), ((near + far) / 2, 0.0, 0.0))
    assert wp == (0.0, 0.0, 0.0)                       # stands: its own position


def test_too_far_it_advances_and_too_close_it_backs_away():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    assert tactics.waypoint(caster, (0.0, 0.0, 0.0), (2000.0, 0.0, 0.0)) is None
    wp = tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert wp[0] < 0.0                                  # away from the foe
    assert tactics.retreating(caster)


def test_a_swordsman_just_chases():
    tactics = CombatTactics(_Clock())
    assert tactics.waypoint(_swordsman(), (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None


def test_the_player_running_catches_a_caster_quickly():
    caught, _ = _chase(foe_speed=250.0)
    assert caught is not None and caught < 6.0


@pytest.mark.parametrize("speed", [FIGHTER_SPEED, 120.0])
def test_a_fighter_at_walking_pace_still_catches_a_caster(speed):
    caught, _ = _chase(foe_speed=speed)
    assert caught is not None


def test_once_caught_it_stands_and_fights_with_its_blade():
    caught, tactics = _chase(foe_speed=250.0)
    caster = next(iter(tactics._states))
    state = tactics._states[caster]
    # The next step inside striking range commits it to melee, for a while.
    actor = _caster()
    tactics._states[id(actor)] = state
    tactics.waypoint(actor, (0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
    assert state.mode == COMMIT
    assert tactics.waypoint(actor, (0.0, 0.0, 0.0), (250.0, 0.0, 0.0)) is None   # closes in


def test_a_wall_at_its_back_corners_it():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert tactics.retreating(caster)
    clock.t += 0.6                                      # it did not move at all
    tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert tactics._states[id(caster)].mode == COMMIT


def test_too_many_retreats_and_it_stops_running():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    state = None
    for i in range(4):
        x = -i * 200.0
        tactics.waypoint(caster, (x, 0.0, 0.0), (x + 200.0, 0.0, 0.0))
        state = tactics._states[id(caster)]
        if state.mode == COMMIT:
            break
        # It backs away properly, then stands its rest.
        clock.t += 0.5
        tactics.waypoint(caster, (x - 45.0, 0.0, 0.0), (x + 200.0, 0.0, 0.0))
        clock.t += 2.0
        tactics.waypoint(caster, (x - 45.0, 0.0, 0.0), (x + 400.0, 0.0, 0.0))
    assert state.mode == COMMIT


def test_distant_tiers_chase_straight_on():
    from engine.spatial import TIER_DISTANT
    tactics = CombatTactics(_Clock(), tier_of=lambda t: TIER_DISTANT)
    assert tactics.waypoint(_caster(), (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None


def test_an_archer_mid_draw_stands_still():
    tactics = CombatTactics(_Clock(), busy=lambda t: True)
    archer = _Actor(attack_style="bow", equipped_weapon="long_bow", inventory=[])
    assert tactics.waypoint(archer, (5.0, 0.0, 7.0), (300.0, 0.0, 0.0)) == (5.0, 0.0, 7.0)


def test_out_of_magicka_a_caster_closes_like_a_swordsman():
    tactics = CombatTactics(_Clock())
    caster = _caster()
    caster.properties["max_magicka"] = 0
    assert tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None
