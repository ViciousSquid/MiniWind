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


def test_marras_is_the_only_windmill(world):
    """Mara's windmill, by Millbrook, is the only one in the Vale; the Old
    Mill camp stands on the ground (no invisible slab walls it off)."""
    mills = [t["properties"] for t in world["things"] if t["properties"].get("windmill")]
    assert [p["name"] for p in mills] == ["windmill"]
    assert not any(t["properties"].get("flour_mill") for t in world["things"])
    slab = [b for b in world["brushes"] if b.get("id") == "b74c0988-958e-4b46-9da5-56f91533f829"]
    assert slab and slab[0]["hidden"] is True


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


def _solid_boxes(world):
    import copy
    from engine.brush_placement import world_bounds
    from engine.constants import is_solid_world_brush
    return [world_bounds(b) for b in copy.deepcopy(world["brushes"]) if is_solid_world_brush(b)]


def test_no_one_starts_or_lives_inside_a_wall(world):
    """populate_world put each hamlet home a fixed 170 units from its house's
    centre, inside the larger houses (which are solid), and the folk standing
    on it with it: ten farmers, from Ashby to Wyndham Cross, could never take
    a step, nor could hens, sheep, skeletons and bandits caught the same way;
    and the two innkeepers' homes were the middle of their inns."""
    from ..tools import populate_world
    boxes = _solid_boxes(world)

    def inside(x, y, z):
        return any(x + 1 > b[0] and x - 1 < b[3] and y + 128 > b[1] and y < b[4]
                   and z + 1 > b[2] and z - 1 < b[5] for b in boxes
                   if b[0] - 1 < x < b[3] + 1 and b[2] - 1 < z < b[5] + 1)
    walled = []
    for t in world["things"]:
        p = t["properties"]
        if p.get("type") not in ("npc", "creature"):
            continue
        x, y, z = t["pos"]
        if inside(x, y, z):
            walled.append((p.get("display_name"), "stands"))
        home = p.get("home")
        if isinstance(home, list) and len(home) == 3:
            # Millbrook's homes are stored under its floor: test them standing.
            hy = y if home[1] < y - 100 else home[1]
            if inside(home[0], hy, home[2]):
                walled.append((p.get("display_name"), "home"))
    assert not walled
    # The tool's homes clear the wall on the door side, whatever the house.
    for _tex, w, d in populate_world.HOUSES:
        for k in range(16):
            a = 2 * math.pi * k / 16
            out = populate_world.door_reach(w, d, math.cos(a), math.sin(a))
            x, z = -math.cos(a) * out, -math.sin(a) * out
            assert abs(x) > w / 2 + 25 or abs(z) > d / 2 + 25
