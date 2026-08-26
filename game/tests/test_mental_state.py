"""
Headless tests for the debug inspector's mental-state snapshot builder.

These exercise the pure-Python derivation the click-to-inspect popup renders:
identity/vitals/AI sections and the prioritised task list. No Qt, no engine.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import mental_state as ms


class _Thing:
    def __init__(self, properties):
        self.properties = dict(properties)


def _labels(section_pairs):
    return {k: v for k, v in section_pairs}


def test_snapshot_basic_identity_and_sections():
    t = _Thing({"npc_role": "guard", "display_name": "Bram", "faction": "guards",
                "aggression": "defensive", "health": 80, "courage": 0.8})
    snap = ms.snapshot(t)
    assert snap["title"] == "Bram  (guards)"
    assert "guard" in snap["subtitle"] and "defensive" in snap["subtitle"]
    headings = [h for h, _ in snap["sections"]]
    assert "Identity" in headings and "AI State" in headings
    ident = _labels(dict(snap["sections"])["Identity"])
    assert ident["Role"] == "guard"
    assert ident["Faction"] == "guards"


def test_tasks_are_priority_sorted_with_one_active():
    t = _Thing({"npc_role": "farmer", "faction": "villagers", "sched_state": "WORKING",
                "autonomy": True, "wander_radius": 200})
    tasks = ms.snapshot(t)["tasks"]
    prios = [p for p, _l, _a in tasks]
    assert prios == sorted(prios, reverse=True)          # highest first
    assert sum(1 for _p, _l, a in tasks if a) == 1       # exactly one active
    # the highest-priority task is the active one
    assert tasks[0][2] is True


def test_combat_target_outranks_schedule():
    t = _Thing({"npc_role": "guard", "faction": "guards", "aggression": "defensive",
                "combatant": True, "target_name": "Bandit", "sched_state": "WORKING"})
    tasks = ms.snapshot(t)["tasks"]
    top_pri, top_label, top_active = tasks[0]
    assert top_active is True
    assert "Attack Bandit" in top_label
    assert top_pri == ms.PRI_COMBAT


def test_flee_state_produces_flee_task():
    t = _Thing({"npc_role": "villager", "faction": "villagers", "sched_state": "FLEE",
                "_flee": True})
    labels = [l for _p, l, _a in ms.snapshot(t)["tasks"]]
    assert any("Flee" in l for l in labels)


def test_rally_state_produces_rally_task():
    t = _Thing({"npc_role": "villager", "faction": "villagers", "sched_state": "RALLY",
                "_rally": True})
    tasks = ms.snapshot(t)["tasks"]
    assert tasks[0][2] is True
    assert any("Rally" in l for _p, l, _a in tasks)


def test_dead_actor_has_no_active_tasks():
    t = _Thing({"npc_role": "wolf", "faction": "wildlife", "dead": True})
    tasks = ms.snapshot(t)["tasks"]
    assert len(tasks) == 1
    assert "Dead" in tasks[0][1]


def test_monster_state_reports_in_sight():
    t = _Thing({"npc_role": "bandit", "faction": "bandits", "aggression": "hostile"})
    snap = ms.snapshot(t, monster_state={"in_sight": True})
    ai = dict(snap["sections"])["AI State"]
    assert ("Player in sight", "yes") in ai


def test_handles_missing_properties_gracefully():
    snap = ms.snapshot(_Thing({}))
    assert snap["title"]              # non-empty
    assert snap["tasks"]             # always at least one task
