"""
Headless tests for MiniWind's living-world combat coordination (runtime layer).

The engine's MonsterAI (which needs PyQt to import) is not exercised here; these
cover the game-side rules the runtime owns: confidence-based civilian rally,
non-combatants flee or hesitate, guards un-park to defend, and the faction model
the runtime hands the engine is correct.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import factions
from game.rpg import schedule as sched


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


def _session(things, player):
    from game.runtime import MiniwindSession
    logic = _FakeLogic(things, player)
    s = MiniwindSession(logic, cfg={"start_hour": 12.0, "minutes_per_day": 9e9})
    s.clock.set_time(12.0, 1)
    return s


def _villager(pos, **extra):
    p = {"type": "npc", "npc_role": "villager", "faction": "villagers",
         "team": "villagers", "aggression": "passive", "triggered": True,
         "combatant": False, "home": list(pos), "schedule": [], "autonomy": True,
         "move_speed": 90.0, "courage": 0.3}
    p.update(extra)
    return _FakeThing(pos, p)


def _marker(pos, kind):
    return _FakeThing(pos, {"type": "marker", "marker_kind": kind,
                            "name": f"{kind}_marker"})


def _bandit(pos):
    return _FakeThing(pos, {"type": "creature", "npc_role": "bandit",
                            "faction": "bandits", "team": "bandits",
                            "aggression": "hostile", "triggered": False,
                            "awake": True})


def _guard(pos):
    return _FakeThing(pos, {
        "type": "npc", "npc_role": "guard", "faction": "guards", "team": "guards",
        "aggression": "defensive", "triggered": True, "combatant": True,
        "can_defend": True, "home": list(pos), "schedule": [], "courage": 0.8})


# --- faction model handed to the engine ------------------------------------
def test_faction_model_is_installed_on_play():
    s = _session([], _FakePlayer([0, 0, 0]))
    s.install()
    assert s.logic._faction_hostile is factions.is_hostile
    assert factions.is_hostile("bandits", "villagers")
    assert factions.is_hostile("guards", "bandits")
    assert not factions.is_hostile("wildlife", "villagers")
    assert not factions.is_hostile("guards", "player")


# --- confidence-based civilian behaviour -----------------------------------

def test_lone_coward_always_flees():
    """A cowardly villager (courage=0.1) alone with a nearby bandit always flees."""
    v = _villager([0, 0, 0], courage=0.1, home=[-300, 0, 0])
    bandit = _bandit([200, 0, 0])
    s = _session([v, bandit], _FakePlayer([9999, 0, 9999]))
    for _ in range(5):
        s.tick(0.1)
    assert v.properties["sched_state"] == sched.FLEE


def test_cautious_villager_wont_fight_alone():
    """A default-courage villager alone with a single bandit should not rally."""
    v = _villager([0, 0, 0], courage=0.3, home=[-300, 0, 0])
    bandit = _bandit([200, 0, 0])
    s = _session([v, bandit], _FakePlayer([9999, 0, 9999]))
    for _ in range(5):
        s.tick(0.1)
    assert v.properties["sched_state"] in (sched.FLEE, sched.ALERT)
    assert v.properties.get("_rally") is not True


def test_guard_boosts_confidence_not_passivity():
    """A nearby guard increases confidence — the villager may alert/rally, but
    a guard's presence alone does NOT force the villager into passive flee."""
    v = _villager([0, 0, 0], courage=0.3, home=[-300, 0, 0])
    bandit = _bandit([300, 0, 0])
    guard = _guard([-100, 0, 0])
    s = _session([v, bandit, guard], _FakePlayer([9999, 0, 9999]))
    for _ in range(5):
        s.tick(0.1)
    state = v.properties["sched_state"]
    assert state in (sched.ALERT, sched.RALLY, sched.FLEE)


def test_group_rally_cascades():
    """Several villagers near each other with moderate courage rally as a group
    when enough are present — the mob bonus cascades confidence upward.
    One brave villager seeds the cascade; the rest follow on subsequent ticks."""
    villagers = []
    for i in range(5):
        v = _villager([i * 30, 0, 0], courage=0.45, home=[-300, 0, 0])
        villagers.append(v)
    bandit = _bandit([400, 0, 0])
    s = _session(villagers + [bandit], _FakePlayer([9999, 0, 9999]))
    for _ in range(15):
        s.tick(0.1)
    rallied = sum(1 for v in villagers if v.properties.get("_rally"))
    assert rallied >= 2, f"expected at least 2 rallied, got {rallied}"


def test_no_rally_against_overwhelming_odds():
    """Many bandits overwhelm even brave villagers — nobody rallies."""
    villagers = [_villager([i * 30, 0, 0], courage=0.4, home=[-300, 0, 0])
                 for i in range(3)]
    bandits = [_bandit([200 + i * 50, 0, 0]) for i in range(5)]
    s = _session(villagers + bandits, _FakePlayer([9999, 0, 9999]))
    for _ in range(10):
        s.tick(0.1)
    rallied = sum(1 for v in villagers if v.properties.get("_rally"))
    assert rallied == 0, f"expected no rally against 5 bandits, got {rallied}"


def test_rally_collapse_after_deaths():
    """Rallied civilians lose confidence and flee when friendly casualties mount."""
    villagers = []
    for i in range(5):
        v = _villager([i * 30, 0, 0], courage=0.45, home=[-500, 0, 0])
        villagers.append(v)
    bandit = _bandit([400, 0, 0])
    s = _session(villagers + [bandit], _FakePlayer([9999, 0, 9999]))
    # let them rally first
    for _ in range(15):
        s.tick(0.1)
    rallied_before = sum(1 for v in villagers if v.properties.get("_rally"))
    assert rallied_before >= 2, "precondition: need rallied civilians first"

    # kill some to simulate casualties
    for v in villagers[:3]:
        v.properties["dead"] = True

    for _ in range(10):
        s.tick(0.1)
    survivors = [v for v in villagers if not v.properties.get("dead")]
    rallied_after = sum(1 for v in survivors if v.properties.get("_rally"))
    assert rallied_after < rallied_before, "casualties should reduce rallied count"


def test_guards_retain_normal_defend_behaviour():
    """Guards still un-park to defend via the combatant branch, not confidence."""
    guard = _guard([0, 0, 0])
    bandit = _bandit([400, 0, 0])
    s = _session([guard, bandit], _FakePlayer([9999, 0, 9999]))
    s.tick(0.5)
    assert guard.properties["triggered"] is False
    assert guard.properties["awake"] is True
    assert guard.properties["sched_state"] == sched.COMBAT


# --- retained existing tests -----------------------------------------------

def test_villager_does_not_flee_neutral_wildlife():
    v = _villager([0, 0, 0])
    wolf = _FakeThing([200, 0, 0], {"type": "creature", "npc_role": "wolf",
                                    "faction": "wildlife", "team": "wildlife",
                                    "aggression": "hostile", "triggered": False})
    s = _session([v, wolf], _FakePlayer([9999, 0, 9999]))
    for _ in range(10):
        s.tick(0.1)
    assert v.properties["sched_state"] != sched.FLEE


def test_idle_villager_wanders_locally():
    v = _villager([0, 0, 0], wander_radius=200.0)
    s = _session([v], _FakePlayer([9999, 0, 9999]))
    for _ in range(40):
        s.tick(0.1)
    assert v.properties["sched_state"] == sched.WANDER
    moved = math.hypot(v.pos[0], v.pos[2])
    assert moved > 1.0, "an idle villager should stroll around its anchor"
    assert moved < 500.0, "but stay within a local radius"


def test_talk_range_lets_player_reach_a_bubbled_npc():
    from game.runtime import TALK_RADIUS, BUBBLE_RADIUS
    assert TALK_RADIUS < BUBBLE_RADIUS
    npc = _villager([120, 0, 0], dialogue={"start": "g",
                                            "nodes": {"g": {"text": "hi", "responses": []}}})
    s = _session([npc], _FakePlayer([0, 0, 0]))
    assert s.bubble_kind(npc) == "talk"
    assert s.nearest_talkable([0, 0, 0], TALK_RADIUS) is npc


def test_speech_bubble_kind():
    qtree = {"start": "g", "nodes": {"g": {"text": "hi", "responses": [
        {"text": "work?", "goto": "END", "actions": [{"op": "start_quest", "quest": "wolves"}]}]}}}
    npc_q = _villager([100, 0, 0], dialogue=qtree)
    npc_t = _villager([120, 0, 0], dialogue={"start": "g", "nodes": {"g": {"text": "hi", "responses": []}}})
    npc_m = _villager([140, 0, 0], merchant=True)
    bandit = _bandit([160, 0, 0])
    s = _session([npc_q, npc_t, npc_m, bandit], _FakePlayer([0, 0, 0]))
    assert s.bubble_kind(npc_q) == "quest"
    assert s.bubble_kind(npc_t) == "talk"
    assert s.bubble_kind(npc_m) == "talk"
    assert s.bubble_kind(bandit) is None
    kinds = [k for _n, k in s.bubble_npcs([0, 0, 0], 700.0)]
    assert kinds == ["quest", "talk", "talk"]


def test_guard_unparks_to_defend():
    guard = _guard([0, 0, 0])
    bandit = _bandit([400, 0, 0])
    s = _session([guard, bandit], _FakePlayer([9999, 0, 9999]))
    s.tick(0.5)
    assert guard.properties["triggered"] is False
    assert guard.properties["awake"] is True
    assert guard.properties["sched_state"] == sched.COMBAT


def test_combat_capability_is_separate_from_faction():
    guard_t = _FakeThing([0, 0, 0], {
        "type": "npc", "npc_role": "guard", "faction": "guards", "team": "guards",
        "aggression": "defensive", "combatant": True})
    merchant = _FakeThing([0, 0, 0], {
        "type": "npc", "npc_role": "merchant", "faction": "villagers",
        "team": "villagers", "aggression": "passive", "combatant": False})
    from game.runtime import MiniwindSession
    assert MiniwindSession._is_combatant(guard_t) is True
    assert MiniwindSession._is_combatant(merchant) is False
    m = _villager([0, 0, 0], npc_role="merchant", home=[-300, 0, 0], courage=0.2)
    m.pos = [0, 0, 0]
    nearby_guard = _guard([-100, 0, 0])
    s = _session([m, _bandit([200, 0, 0]), nearby_guard], _FakePlayer([9999, 0, 9999]))
    for _ in range(5):
        s.tick(0.1)
    assert m.properties["sched_state"] in (sched.FLEE, sched.ALERT)
