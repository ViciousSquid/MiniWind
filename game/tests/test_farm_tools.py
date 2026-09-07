"""
The farm tools: scythe, pitchfork, shovel and bucket.

Four working tools that are also real items — carried, sold, bought and swung.
They go through no special path: they are ordinary weapon definitions in
``game/data/items.json``, so equipping, trading, damage and the overhead weapon
overlay all pick them up for free. Each has its own icon under
``assets/sprites/items/``, which is what the overlay resolves by id.

The scythe is also what the reaper carries (see test_reaper.py).

Run:  python -m pytest game/tests/test_farm_tools.py -q
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import equipment as eq
from game.rpg import inventory as inv
from game.rpg import items as rpg_items

TOOLS = ("scythe", "pitchfork", "shovel", "bucket")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_is_in_the_item_database(tool):
    assert rpg_items.get(tool) is not None


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_can_be_equipped(tool):
    """Equippable is what makes it a weapon an NPC or the player can hold."""
    assert rpg_items.is_equippable(tool)
    assert rpg_items.slot_of(tool) == rpg_items.SLOT_WEAPON


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_is_worth_something(tool):
    """A merchant needs a price to buy and sell at."""
    assert rpg_items.get(tool).value > 0


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_swings(tool):
    d = rpg_items.get(tool)
    assert d.get("kind") == rpg_items.KIND_MELEE
    assert d.get("damage", 0) > 0
    assert d.get("reach", 0) > 0
    assert d.get("skill") in ("blade", "blunt")


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_has_an_icon(tool):
    """The overhead weapon overlay resolves the icon straight off the item id."""
    path = os.path.join(ROOT, "assets", "sprites", "items", f"{tool}.png")
    assert os.path.isfile(path), f"missing {tool}.png"


@pytest.mark.parametrize("tool", TOOLS)
def test_the_tool_makes_a_tradeable_stack(tool):
    stack = rpg_items.make(tool, 2)
    assert stack["id"] == tool and stack["qty"] == 2
    assert stack["type"] == rpg_items.WEAPON
    assert stack["value"] > 0


def test_the_long_hafted_tools_are_two_handed():
    """A scythe is not something you swing alongside a shield."""
    for tool in ("scythe", "pitchfork", "shovel"):
        assert eq._is_two_handed(rpg_items.get(tool)), tool


def test_a_bucket_leaves_a_hand_free():
    assert not eq._is_two_handed(rpg_items.get("bucket"))


def test_the_scythe_is_the_heaviest_hitter_of_the_four():
    damage = {t: rpg_items.get(t).get("damage", 0) for t in TOOLS}
    assert max(damage, key=damage.get) == "scythe"
    assert damage["bucket"] == min(damage.values())


class _Character:
    def __init__(self):
        self.inventory = []
        self.equipment = {}
        self.active_spell = None
        self.active_weapon_kind = "unarmed"


@pytest.mark.parametrize("tool", TOOLS)
def test_picking_one_up_and_wielding_it(tool):
    c = _Character()
    inv.add_item(c.inventory, rpg_items.make(tool))
    assert eq.equip(c, tool)
    assert eq.equipped_id(c, rpg_items.SLOT_WEAPON) == tool
    assert c.active_weapon_kind == rpg_items.KIND_MELEE


def test_the_village_sells_them():
    """In stock somewhere, or nobody can buy one."""
    path = os.path.join(ROOT, "game", "data", "settlement.json")
    with open(path) as fh:
        settlement = json.load(fh)
    stocked = set()
    for npc in settlement.get("npcs", []):
        for stack in npc.get("inventory", []) or []:
            stocked.add(stack.get("id"))
    for tool in TOOLS:
        assert tool in stocked, f"nobody in the village carries a {tool}"
