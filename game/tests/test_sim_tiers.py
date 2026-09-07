"""
Simulation tiers, from the gameplay layer's side.

The engine's world index sorts actors by how near the player they are; this is
what the settlement runtime *does* with that. The rule being pinned down: a
distant townsperson is still living their day — the clock still moves them
through their schedule and their needs still build — they simply stop looking
around, because nothing they could notice is anything the player is in a
position to observe.

The counterpart matters just as much: everything the player can see must behave
exactly as it did before tiers existed.

Run:  python -m pytest game/tests/test_sim_tiers.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.world_index import TIER_ACTIVE, TIER_DISTANT, TIER_NEAR
from game import runtime
from game.rpg import schedule as sched
from game.runtime import MiniwindSession


class _Clock:
    def __init__(self, hour=9.0):
        self.hour = hour
        self.day = 1
        self.is_daytime = True


class _NPC:
    def __init__(self, name="Bram", pos=(0.0, 0.0, 0.0), tier=TIER_NEAR, **props):
        self.pos = list(pos)
        self.properties = {"type": "npc", "name": name, "team": "villagers",
                           "npc_role": "villager", "_sim_tier": tier,
                           "combatant": False}
        self.properties.update(props)


class _Session:
    """The decision pass, with just the scene plumbing it reaches for."""

    _decide = MiniwindSession._decide
    _decide_distant = MiniwindSession._decide_distant
    _schedule_entry = MiniwindSession._schedule_entry
    _tier_of = staticmethod(MiniwindSession._tier_of)
    _is_combatant = staticmethod(MiniwindSession._is_combatant)
    _resolve_location = MiniwindSession._resolve_location
    _advance_needs = MiniwindSession._advance_needs
    _patrol = MiniwindSession._patrol
    _patrol_points = MiniwindSession._patrol_points
    _idle_or_wander = MiniwindSession._idle_or_wander
    _nearest_hostile = MiniwindSession._nearest_hostile
    _world_index = MiniwindSession._world_index
    _dist2d = staticmethod(MiniwindSession._dist2d)
    _find_named = MiniwindSession._find_named

    def __init__(self, things=()):
        self.clock = _Clock()
        self.things = list(things)
        self._actors = list(things)
        self._dead_actors = []
        self._fights = []
        self._guards = []
        self._wi_cache = None
        self.rng = __import__("random").Random(1)
        self.perception_calls = 0

    # scene plumbing
    class _Logic:
        def __init__(self, things):
            self.things = things
    @property
    def logic(self):
        return _Session._Logic(self.things)

    def _apply_sim_intent(self, npc):
        self.perception_calls += 1
        return False

    def _civilian_confidence(self, npc, threat):
        self.perception_calls += 1
        return 1.0

    def _fight_to_break_up(self, npc, radius):
        self.perception_calls += 1
        return None


_WORK_SCHEDULE = [
    {"hour": 8, "state": sched.WORKING, "location": "work"},
    {"hour": 18, "state": sched.SLEEPING, "location": "home"},
]


def _worker(tier, hour=9.0):
    npc = _NPC(tier=tier, schedule=list(_WORK_SCHEDULE),
               work_location=[500.0, 0.0, 500.0], home=[0.0, 0.0, 0.0])
    s = _Session([npc])
    s.clock.hour = hour
    return s, npc


# --- the schedule still runs at every live tier ----------------------------

def test_a_distant_townsperson_still_goes_to_work():
    """Coarse is not frozen: the clock still moves them through their day."""
    s, npc = _worker(TIER_DISTANT)
    s._decide_distant(npc)
    assert npc.properties["sched_state"] == sched.WORKING
    assert npc.properties["_dest"] == [500.0, 0.0, 500.0]


def test_a_distant_townsperson_goes_to_bed_when_the_hour_comes():
    s, npc = _worker(TIER_DISTANT, hour=9.0)
    s._decide_distant(npc)
    assert npc.properties["sched_state"] == sched.WORKING
    s.clock.hour = 20.0
    s._decide_distant(npc)
    assert npc.properties["sched_state"] == sched.SLEEPING
    assert npc.properties["_dest"] == [0.0, 0.0, 0.0]


def test_the_near_and_distant_paths_agree_on_where_the_day_puts_someone():
    """The state a distant actor reaches is the same state — only reached more
    coarsely — so walking up to them never reveals a different person."""
    near_s, near = _worker(TIER_NEAR)
    far_s, far = _worker(TIER_DISTANT)
    near_s._decide(near)
    far_s._decide_distant(far)
    assert near.properties["sched_state"] == far.properties["sched_state"]
    assert near.properties["_dest"] == far.properties["_dest"]


# --- but the looking-around stops ------------------------------------------

def test_a_distant_actor_does_no_perception_at_all():
    s, npc = _worker(TIER_DISTANT)
    s._decide_distant(npc)
    assert s.perception_calls == 0


def test_a_near_actor_still_perceives_normally():
    s, npc = _worker(TIER_NEAR)
    s._decide(npc)
    assert s.perception_calls > 0, "the player's vicinity stays fully reactive"


def test_an_arrest_in_progress_is_never_downgraded():
    """The arrest flow owns its guard wherever he is; a coarse pass must not
    quietly drop him mid-escort."""
    s, npc = _worker(TIER_DISTANT)
    npc.properties["_arrest_state"] = "ready"
    s._decide_distant(npc)
    assert npc.properties["sched_state"] == "ARREST_READY"


# --- schedules transition on timestamps, not on every pass ------------------

def test_the_schedule_is_not_recomputed_while_its_window_holds():
    s, npc = _worker(TIER_NEAR)
    calls = []
    real = sched.evaluate_window

    def counting(schedule, hour):
        calls.append(hour)
        return real(schedule, hour)

    sched.evaluate_window = counting
    try:
        for _ in range(50):
            s._schedule_entry(npc)
        assert len(calls) == 1, "one lookup covers the whole window"
        s.clock.hour = 19.0                      # past the next entry's hour
        s._schedule_entry(npc)
        assert len(calls) == 2, "crossing the timestamp re-asks, exactly once"
    finally:
        sched.evaluate_window = real


def test_a_schedule_window_wraps_around_midnight():
    assert sched.window_holds(23.5, 18.0, 8.0)
    assert sched.window_holds(2.0, 18.0, 8.0)
    assert not sched.window_holds(12.0, 18.0, 8.0)
    assert sched.window_holds(9.0, 8.0, 18.0)
    assert not sched.window_holds(19.0, 8.0, 18.0)


def test_evaluate_still_answers_what_it_always_did():
    """The windowed planner is the same planner: the old entry point is a
    wrapper over it, so authored schedules behave identically."""
    for hour, expected in ((7.0, sched.SLEEPING), (8.0, sched.WORKING),
                           (17.9, sched.WORKING), (18.0, sched.SLEEPING),
                           (23.0, sched.SLEEPING), (0.5, sched.SLEEPING)):
        assert sched.evaluate(_WORK_SCHEDULE, hour)["state"] == expected, hour
