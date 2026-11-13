"""The shipped world carries the first hour's authored fixes
(game/tools/first_hour_content.py), and the tool has nothing left to do."""

from __future__ import annotations

import json
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
    assert by["BanditSpawner"]["respawn"] is False
