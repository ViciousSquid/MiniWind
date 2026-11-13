"""The shipped world carries the first hour's authored fixes
(game/tools/first_hour_content.py), and the tool has nothing left to do."""

from __future__ import annotations

import json
import math
import os
import re

import pytest

from ..tools import first_hour_content as content

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="module")
def world():
    with open(os.path.join(ROOT, content.WORLD), encoding="utf-8") as fh:
        return json.load(fh)


def test_the_tool_has_nothing_left_to_change_on_the_shipped_world(world):
    assert content.apply(json.loads(json.dumps(world))) == []


def test_no_one_in_the_vale_is_called_by_a_counter_or_a_job(world):
    shown = [t["properties"].get("display_name", "") for t in world["things"]
             if t.get("type") == "npc"]
    assert not [n for n in shown if re.match(r"Folk\d+", str(n))]
    assert "Town Archer" not in shown


def test_bryns_pasture_has_wolves_and_the_old_mill_stays_cleared(world):
    by = {t["properties"].get("name"): t["properties"] for t in world["things"]}
    assert by["CreatureSpawn_1"]["creature_role"] == "wolf"
    assert "_spawned" not in by["CreatureSpawn_1"], "a spent spawner never spawns"
    fiends = [t for t in world["things"] if t["properties"].get("npc_role") == "monster"
              and t["properties"].get("name") in ("Creature_19", "Creature_20")]
    assert not fiends
    # The Old Mill's spawner (four anonymous bandits) is gone: Hal Corbin's
    # band is placed by name, and nobody in it comes back.
    assert "BanditSpawner" not in by
    band = [by[n] for n in ("Hal Corbin", "Wat Fenner", "Ned Crake", "Jory Spratt")]
    assert all(p["faction"] == "bandits" and p["respawn_lair"] is False for p in band)
    assert [p["npc_role"] for p in band].count("bandit_archer") == 1
    assert {s["id"] for s in by["Hal Corbin"]["inventory"]} >= {"corbin_ledger"}
    anonymous = [t for t in world["things"] if t["properties"].get("display_name") == "Bandit Archer"
                 and 8000 < t["pos"][0] < 9800 and -6400 < t["pos"][2] < -5000]
    assert not anonymous


def test_no_hostile_skeleton_stands_in_millbrooks_fields(world):
    import math
    near = [t["properties"].get("name") for t in world["things"]
            if t["properties"].get("npc_role") == "skeleton"
            and math.hypot(t["pos"][0], t["pos"][2]) < 7000]
    assert not near, near


def test_the_first_hour_has_locks_to_pick(world):
    """Only distant chests were locked: a new player never met lockpicking."""
    locks = {t["properties"]["name"]: t["properties"] for t in world["things"]
             if t.get("type") == "container" and t["properties"].get("locked")}
    for name in ("rusted_lockbox", "old_mill_strongbox", "aldric_toll_chest"):
        assert name in locks, name
    assert "owner" not in locks["rusted_lockbox"]
    assert locks["aldric_toll_chest"]["owner"] == "Aldric"
    # The Old Mill's strongbox holds the Cross's stolen tolls: Aldric's by
    # right, so taking them is theft from him unless they go back.
    box = locks["old_mill_strongbox"]
    assert box["owner"] == "Aldric" and [s["id"] for s in box["inventory"]] == ["toll_purse"]


def test_the_old_mill_has_a_mill_held_by_hal_corbin(world):
    by = {t["properties"].get("name"): t for t in world["things"]}
    mill = by["old_mill_windmill"]
    assert mill["properties"]["windmill"] and mill["properties"]["mill_held_by"] == "Hal Corbin"
    assert by["old_mill_sails"]["properties"]["mill_rotor_for"] == mill["properties"]["id"]
    brewer = [t["properties"] for t in world["things"]
              if t["properties"].get("display_name") == "Hollin Brewer"][0]
    assert brewer["flour_mill"] == mill["properties"]["id"]


def test_most_chests_are_locked_and_locks_vary(world):
    from collections import Counter
    chests = [t["properties"] for t in world["things"]
              if t.get("type") == "container" and t["properties"].get("container_kind") == "chest"]
    locked = [p for p in chests if p.get("locked")]
    assert len(locked) >= 0.85 * len(chests)
    tiers = Counter(p.get("lock_difficulty") for p in locked)
    assert len(tiers) >= 4, tiers
    for t in world["things"]:
        p = t["properties"]
        if t.get("type") == "container" and p.get("container_kind") in ("sack", "barrel", "urn"):
            assert not p.get("locked"), "a sack has nothing to lock: " + str(p.get("name"))


def test_a_greeting_that_names_a_neighbour_is_said_near_them(world):
    """populate_world copied Oakridge's farmhand, line and all, into 93
    cottagers, farmers and wayfarers: "If you're after work, Hobb's the one to
    ask" was said all over the Vale, nowhere near Hobb. Each countryside
    title now has lines of its own (populate_world.TITLE_LINES)."""
    from ..tools import populate_world
    npcs = [t for t in world["things"] if t["properties"].get("type") == "npc"]
    first = {}
    for t in npcs:
        name = str(t["properties"].get("display_name") or "").split(" ")[0]
        if len(name) > 2:
            first.setdefault(name, []).append(t["pos"])
    far = []
    for t in npcs:
        tree = t["properties"].get("dialogue") or {}
        start = (tree.get("nodes") or {}).get(tree.get("start")) or {}
        text = str(start.get("text") or "")
        own = str(t["properties"].get("display_name") or "").split(" ")[0]
        for name, places in first.items():
            if name == own or not re.search(rf"\b{re.escape(name)}\b", text):
                continue
            if min(math.hypot(t["pos"][0] - p[0], t["pos"][2] - p[2]) for p in places) > 3000:
                far.append((t["properties"].get("display_name"), name))
    assert not far
    assert populate_world.title_line("Wayfarer", "Tom the Wayfarer") in \
        populate_world.TITLE_LINES["Wayfarer"]
