"""
Tests for needs-driven schedules (:mod:`game.rpg.needs`).

Covers the pure need model (accrual by state, meals and sleep, per-NPC variation,
clamping) and the schedule bias (an exhausted NPC naps, a hungry one heads home),
then the runtime integration: a tired civilian on the settlement clock breaks off
its authored work to rest, while an on-duty guard is never pulled off post.

Run:  python -m pytest game/tests/test_needs.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import needs
from game.rpg import schedule as sched


# --- the pure need model ---------------------------------------------------
def test_working_builds_fatigue_sleeping_clears_it():
    p = {}
    needs.seed(p)
    needs.advance(p, 8.0, sched.WORKING)
    tired = p[needs.FATIGUE]
    assert tired > 0.4
    needs.advance(p, 8.0, sched.SLEEPING)
    assert p[needs.FATIGUE] < tired          # a night's sleep recovers it


def test_hunger_rises_through_the_day_and_a_meal_settles_it():
    p = {}
    needs.seed(p)
    needs.advance(p, 6.0, sched.WORKING)
    hungry = p[needs.HUNGER]
    assert hungry > 0.2
    needs.advance(p, 2.0, sched.IDLE)        # a meal at home
    assert p[needs.HUNGER] < hungry


def test_needs_are_clamped_to_unit_range():
    p = {}
    needs.seed(p)
    needs.advance(p, 100.0, sched.WORKING)   # an implausibly long shift
    assert p[needs.FATIGUE] == 1.0
    assert 0.0 <= p[needs.HUNGER] <= 1.0
    needs.advance(p, 100.0, sched.SLEEPING)
    assert p[needs.FATIGUE] == 0.0


def test_seed_gives_per_npc_variation_but_is_idempotent():
    import random
    rng = random.Random(1)
    a, b = {}, {}
    needs.seed(a, rng)
    needs.seed(b, rng)
    # two NPCs get their own appetite/stamina, so lives diverge
    assert (a[needs.APPETITE], a[needs.STAMINA]) != (b[needs.APPETITE], b[needs.STAMINA])
    before = a[needs.APPETITE]
    needs.seed(a, rng)                        # re-seeding never overwrites
    assert a[needs.APPETITE] == before


def test_seed_without_rng_is_deterministic():
    p = {}
    needs.seed(p)
    assert p[needs.APPETITE] == 1.0 and p[needs.STAMINA] == 1.0


# --- the schedule bias -----------------------------------------------------
def test_exhaustion_overrides_work_with_a_nap():
    p = {needs.FATIGUE: 0.95, needs.HUNGER: 0.0}
    state, reason = needs.apply(p, sched.WORKING)
    assert state == sched.SLEEPING and reason == "exhausted"


def test_hunger_overrides_work_with_a_meal_run():
    p = {needs.FATIGUE: 0.0, needs.HUNGER: 0.9}
    state, reason = needs.apply(p, sched.WORKING)
    assert state == sched.GOING_HOME and reason == "hungry"


def test_content_npc_keeps_its_authored_plan():
    p = {needs.FATIGUE: 0.2, needs.HUNGER: 0.2}
    state, reason = needs.apply(p, sched.WORKING)
    assert state == sched.WORKING and reason == ""


def test_a_sleeping_npc_is_left_to_sleep():
    p = {needs.FATIGUE: 0.95, needs.HUNGER: 0.95}
    state, reason = needs.apply(p, sched.SLEEPING)
    assert state == sched.SLEEPING and reason == ""


# --- runtime integration ---------------------------------------------------
class _FakeThing:
    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakePlayer:
    def __init__(self, pos):
        self.pos = list(pos)
        self.properties = {}


class _FakeLogic:
    def __init__(self, things, player):
        self.things = things
        self.player = player


def _villager(name, pos, home, schedule):
    return _FakeThing(pos, {
        "type": "npc", "name": name, "npc_role": "villager",
        "faction": "villagers", "team": "villagers",
        "home": list(home), "work_location": "",
        "schedule": schedule, "sched_state": sched.WORKING,
        "autonomy": False,
    })


def _session(things, hour):
    from game.runtime import MiniwindSession
    player = _FakePlayer([5000, 272, 5000])   # far away: no combat/flee interplay
    session = MiniwindSession(_FakeLogic(things, player),
                              cfg={"start_hour": hour, "minutes_per_day": 5.0})
    session.clock.set_time(hour, 1)
    return session


def test_exhausted_civilian_breaks_off_work_to_rest():
    # A villager whose schedule says WORK all day, but who is already exhausted.
    home = [0, 272, 0]
    work = [1200, 272, 0]
    schedule = [{"hour": 0, "state": sched.WORKING, "location": "home"}]
    v = _villager("Tam", list(work), home, schedule)
    v.properties[needs.FATIGUE] = 0.95        # dead on their feet
    things = [v]
    session = _session(things, 12.0)
    d0 = math.dist(v.pos, home)
    for _ in range(40):
        session.tick(0.1)
    assert v.properties["sched_state"] == sched.SLEEPING
    assert v.properties.get("_need_reason") == "exhausted"
    assert math.dist(v.pos, home) < d0        # they walked home to rest


def test_on_duty_guard_is_never_pulled_off_post_by_needs():
    guard = _FakeThing([0, 272, 0], {
        "type": "npc", "name": "Watch", "npc_role": "guard",
        "faction": "guards", "team": "guards", "combatant": True,
        "home": [0, 272, 0], "work_location": "",
        "schedule": [{"hour": 0, "state": sched.WORKING, "location": "work"}],
        "sched_state": sched.WORKING,
        needs.FATIGUE: 0.99, needs.HUNGER: 0.99,
    })
    session = _session([guard], 12.0)
    for _ in range(20):
        session.tick(0.1)
    # A combatant keeps working regardless of needs; no need ever overrode it.
    assert guard.properties["sched_state"] == sched.WORKING
    assert "_need_reason" not in guard.properties


def test_needs_accumulate_over_played_time_and_persist_on_props():
    home = [0, 272, 0]
    schedule = [{"hour": 0, "state": sched.WORKING, "location": "home"}]
    v = _villager("Nel", list(home), home, schedule)
    v.properties[needs.FATIGUE] = 0.0
    session = _session([v], 8.0)
    for _ in range(30):
        session.tick(0.2)                     # fast clock -> hours pass
    # Fatigue is a plain persistent property that grew as the day was played.
    assert v.properties[needs.FATIGUE] > 0.0
    assert needs.FATIGUE in v.properties      # round-trips through save/load
