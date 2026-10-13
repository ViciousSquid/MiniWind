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

from ..rpg import items
from ..rpg import equipment as eq
from ..rpg import schedule as sched
from ..rpg.character import Character
from .fio_logic import FioLogic


# --- item + equipment ------------------------------------------------------
def test_torch_is_a_light_source_in_the_light_slot():
    d = items.get("torch")
    assert d is not None
    assert d.category == items.LIGHT
    assert items.slot_of("torch") == items.SLOT_LIGHT
    assert items.is_light_source(d)
    assert items.is_equippable("torch")


def test_equipping_a_torch_fills_the_light_slot_beside_a_weapon():
    from ..rpg import inventory as inv
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


class _FakeLogic(FioLogic):
    def __init__(self, things, player):
        self.things = things
        self.player = player


def _session(things, player, hour):
    from ..runtime import MiniwindSession
    session = MiniwindSession(_FakeLogic(things, player),
                              cfg={"start_hour": hour, "minutes_per_day": 999999.0})
    session.clock.set_time(hour, 1)
    return session


def _torch_lights(things):
    return [t for t in things if getattr(t, "properties", {}).get("_torch")]


def test_player_torch_spawns_a_following_light_and_clears_on_unequip():
    from ..rpg import inventory as inv
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
    from .. import data
    kestrel = next(n for n in data.load("settlement")["npcs"] if n["name"] == "Kestrel")
    assert kestrel.get("torch") is True


# --- torches carried in the inventory, flicker, shadows --------------------
def _villager(pos=(0, 272, 0), **props):
    base = {"type": "npc", "name": "Wren", "npc_role": "villager",
            "faction": "villagers", "team": "villagers",
            "home": list(pos), "schedule": [], "sched_state": sched.IDLE,
            "autonomy": False}
    base.update(props)
    return _FakeThing(list(pos), base)


def test_a_torch_in_the_inventory_is_held_lit_after_dark_only():
    wren = _villager(inventory=[items.make("torch")])
    player = _FakePlayer([9000, 272, 9000])
    session = _session([wren], player, 23.0)
    session.tick(0.1)
    assert len(_torch_lights(session.logic.things)) == 1
    assert wren.properties["_torch_lit"] == "torch"
    # ... and drawn in the hand the weapon is not in.
    session._refresh_actor_cache()
    session.logic.player.pos = [0, 272, 0]
    held = [h for h in session.held.overhead() if h[2] == "torch"]
    assert held and held[0][3] == ("left" if wren.properties.get("handed", "right") == "right"
                                   else "right")
    session.clock.set_time(12.0, 1)
    session.tick(0.1)
    assert _torch_lights(session.logic.things) == []
    assert "_torch_lit" not in wren.properties


def test_without_a_torch_nobody_lights_one():
    wren = _villager(inventory=[items.make("bread")] if items.make("bread") else [])
    session = _session([wren], _FakePlayer([9000, 272, 9000]), 23.0)
    session.tick(0.1)
    assert _torch_lights(session.logic.things) == []


def test_the_flame_flickers_and_tells_the_renderer(monkeypatch):
    from .. import runtime
    touched = []
    monkeypatch.setattr(runtime, "_journal", lambda obj, *a: touched.append(obj))
    wren = _villager(inventory=[items.make("torch")])
    session = _session([wren], _FakePlayer([9000, 272, 9000]), 23.0)
    seen = set()
    for _ in range(12):
        session.tick(0.07)
        light = _torch_lights(session.logic.things)[0]
        seen.add(round(light.properties["intensity"], 3))
    assert len(seen) > 6                                   # it wavers
    base = light.properties["_torch_base_intensity"]
    assert all(abs(v - base) <= base * 0.2 for v in seen)  # around its base
    assert light in touched


def test_torch_shadows_follow_the_setting_and_the_near_tier():
    import configparser
    from .. import runtime
    from engine.spatial import TIER_ACTIVE, TIER_NEAR
    near = _villager(pos=(0, 272, 0), name="Near", inventory=[items.make("torch")])
    mid = _villager(pos=(50, 272, 0), name="Mid", inventory=[items.make("torch")])
    session = _session([near, mid], _FakePlayer([9000, 272, 9000]), 23.0)
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"torch_shadows": "False"}})
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    try:
        near.properties["_sim_tier"] = TIER_NEAR
        mid.properties["_sim_tier"] = TIER_ACTIVE
        session._update_torch_lights(0.1)
        lights = {k: l for k, l in session._torch_lights.items()}
        assert not any(l.properties["casts_shadows"] for l in lights.values())
        config.set("GAME", "torch_shadows", "True")
        session._update_torch_lights(0.1)
        assert session._torch_lights[id(near)].properties["casts_shadows"] is True
        assert session._torch_lights[id(mid)].properties["casts_shadows"] is False
    finally:
        runtime.set_editor_config(previous)
