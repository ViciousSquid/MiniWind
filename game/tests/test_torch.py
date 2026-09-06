"""
Tests for the carried torch light (item + equip + runtime light management).

Covers the item definition and off-hand light slot, equipping through the game
state, and the live runtime behaviour: a torch equipped by the player floats a
dynamic light that follows them and vanishes when unequipped, an NPC flagged
``torch`` lights one after dark and douses it by day, and ``torch_always`` burns
around the clock.

Run:  python -m pytest game/tests/test_torch.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import items
from game.rpg import equipment as eq
from game.rpg import schedule as sched
from game.rpg.character import Character


# --- item + equipment ------------------------------------------------------
def test_torch_is_a_light_source_in_the_light_slot():
    d = items.get("torch")
    assert d is not None
    assert d.category == items.LIGHT
    assert items.slot_of("torch") == items.SLOT_LIGHT
    assert items.is_light_source(d)
    assert items.is_equippable("torch")


def test_equipping_a_torch_fills_the_light_slot_beside_a_weapon():
    from game.rpg import inventory as inv
    c = Character()
    inv.add_item(c.inventory, items.make("iron_shortsword"))
    inv.add_item(c.inventory, items.make("torch"))
    assert eq.equip(c, "iron_shortsword")
    assert eq.equip(c, "torch")
    # a torch is off-hand: it does not displace the weapon
    assert eq.equipped_id(c, items.SLOT_WEAPON) == "iron_shortsword"
    assert eq.equipped_id(c, items.SLOT_LIGHT) == "torch"
    assert eq.light_source(c) is items.get("torch")


def test_no_light_source_when_none_equipped():
    assert eq.light_source(Character()) is None


# --- runtime light management ----------------------------------------------
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


def _session(things, player, hour):
    from game.runtime import MiniwindSession
    session = MiniwindSession(_FakeLogic(things, player),
                              cfg={"start_hour": hour, "minutes_per_day": 999999.0})
    session.clock.set_time(hour, 1)
    return session


def _torch_lights(things):
    return [t for t in things if getattr(t, "properties", {}).get("_torch")]


def test_player_torch_spawns_a_following_light_and_clears_on_unequip():
    from game.rpg import inventory as inv
    player = _FakePlayer([100, 272, 100])
    things = []
    session = _session(things, player, 12.0)
    c = session.game.character
    inv.add_item(c.inventory, items.make("torch"))
    assert eq.equip(c, "torch")

    session.tick(0.1)
    lights = _torch_lights(things)
    assert len(lights) == 1
    light = lights[0]
    # the light sits on the player (a little above their feet)
    assert abs(light.pos[0] - player.pos[0]) < 1e-6
    assert abs(light.pos[2] - player.pos[2]) < 1e-6
    assert light.pos[1] > player.pos[1]

    # it follows the player as they move
    player.pos[0] += 500
    session.tick(0.1)
    assert abs(light.pos[0] - player.pos[0]) < 1e-6

    # unequipping douses it
    eq.unequip(c, items.SLOT_LIGHT)
    session.tick(0.1)
    assert _torch_lights(things) == []


def test_npc_torch_lights_at_night_and_douses_by_day():
    guard = _FakeThing([0, 272, 0], {
        "type": "npc", "name": "Watch", "npc_role": "guard",
        "faction": "guards", "team": "guards", "torch": True,
        "home": [0, 272, 0], "schedule": [], "sched_state": sched.WORKING,
    })
    player = _FakePlayer([9000, 272, 9000])   # far away, unlit
    # Night: the torch is lit.
    session = _session([guard], player, 22.0)
    session.tick(0.1)
    assert len(_torch_lights(session.logic.things)) == 1

    # Advance to daytime: the same NPC douses the torch.
    session.clock.set_time(12.0, 1)
    session.tick(0.1)
    assert _torch_lights(session.logic.things) == []


def test_torch_always_burns_by_day():
    sconce = _FakeThing([0, 272, 0], {
        "type": "npc", "name": "Keeper", "npc_role": "villager",
        "faction": "villagers", "team": "villagers", "torch_always": True,
        "home": [0, 272, 0], "schedule": [], "sched_state": sched.IDLE,
        "autonomy": False,
    })
    player = _FakePlayer([9000, 272, 9000])
    session = _session([sconce], player, 12.0)   # broad daylight
    session.tick(0.1)
    assert len(_torch_lights(session.logic.things)) == 1


def test_settlement_night_guard_carries_a_torch():
    # The authored settlement wires Kestrel with a torch flag.
    from game import data
    kestrel = next(n for n in data.load("settlement")["npcs"] if n["name"] == "Kestrel")
    assert kestrel.get("torch") is True
