"""
Headless tests for the placeable world entities: item pickups, quest triggers
and creature spawn points. These are data-driven Things the MiniWind runtime
interprets; the engine is not needed to exercise the game-layer behaviour.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import entities
from game.rpg import inventory as inv


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
        self.rebuilt = 0

    def _build_entity_caches(self):
        self.rebuilt += 1


class _G:
    """A minimal GlobalStore-like backing so StateStore actually persists."""
    def __init__(self):
        self.d = {}

    def get(self, k, default=None, store="plugins"):
        return self.d.get((store, k), default)

    def set(self, k, v, store="plugins"):
        self.d[(store, k)] = str(v)

    def all(self, store="plugins"):
        return {k[1]: v for k, v in self.d.items() if k[0] == store}


def _session(things, player):
    from game.runtime import MiniwindSession, StateStore
    s = MiniwindSession(_FakeLogic(things, player), cfg={})
    store = StateStore(_G(), "miniwind")
    s.store = store
    s.game.store = store
    return s


def test_markers_use_per_kind_sprites():
    import os
    from game.entities import Marker, marker_sprite, MARKER_KINDS
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    seen = set()
    for kind in MARKER_KINDS:
        m = Marker(pos=[0, 0, 0], properties={"marker_kind": kind})
        sp = m.properties["custom_idle"]
        assert sp.endswith(f"marker_{kind}.png"), f"{kind} sprite wrong: {sp}"
        assert os.path.isfile(os.path.join(root, sp)), f"missing marker sprite {sp}"
        seen.add(sp)
    assert len(seen) == len(MARKER_KINDS)          # every kind is distinct
    # unknown kind falls back to the generic marker, not the logic-command icon
    assert marker_sprite("nonesuch").endswith("/marker.png")


def test_entities_construct_with_correct_types():
    assert entities.ItemPickup(pos=[0, 0, 0]).properties["type"] == "itempickup"
    assert entities.CreatureSpawn(pos=[0, 0, 0]).properties["type"] == "creaturespawn"
    assert entities.MiniwindTrigger(pos=[0, 0, 0]).properties["type"] == "miniwindtrigger"
    # class names match their types so map from_dict can find them
    assert entities.ItemPickup.__name__ == "ItemPickup"
    assert entities.MiniwindTrigger.__name__ == "MiniwindTrigger"


def test_item_pickup_adds_to_player_inventory():
    it = _FakeThing([0, 0, 0], {"type": "itempickup", "item_id": "iron_dagger",
                                "quantity": 2, "pickup_radius": 60.0})
    s = _session([it], _FakePlayer([30, 0, 0]))   # within radius
    s.tick(0.1)
    assert inv.has_item(s.game.character.inventory, "iron_dagger")
    assert it.properties.get("dead") is True       # consumed
    # out of range does nothing to a second pickup
    far = _FakeThing([9999, 0, 9999], {"type": "itempickup", "item_id": "gold"})
    s2 = _session([far], _FakePlayer([0, 0, 0]))
    s2.tick(0.1)
    assert far.properties.get("dead") is not True


def test_quest_trigger_sets_flag_once():
    tr = _FakeThing([0, 0, 0], {"type": "miniwindtrigger", "trigger_radius": 100.0,
                                "once": True, "set_flag": "met_bram=true"})
    s = _session([tr], _FakePlayer([10, 0, 0]))
    s.tick(0.1)
    assert s.store.get("met_bram") == "true"
    assert tr.properties.get("_fired") is True


def test_creature_spawn_point_materialises_creatures():
    sp = _FakeThing([100, 0, 100], {"type": "creaturespawn", "creature_role": "wolf",
                                    "count": 3, "spawn_radius": 50.0})
    logic_things = [sp]
    s = _session(logic_things, _FakePlayer([0, 0, 0]))
    made = s.spawn_creature_points()
    assert made == 3
    creatures = [t for t in s.logic.things
                 if str(t.properties.get("type")) == "creature"]
    assert len(creatures) == 3
    assert all(c.properties.get("npc_role") == "wolf" for c in creatures)
    assert s.logic.rebuilt == 1          # engine monster cache refreshed
    # idempotent: a second call spawns nothing more
    assert s.spawn_creature_points() == 0


def test_spawn_point_can_make_npc_group_same_faction():
    """A spawn point can materialise a same-faction GROUP of NPCs (not just
    creatures), with full control over role/appearance and shared faction."""
    sp = _FakeThing([0, 0, 0], {"type": "creaturespawn", "spawn_kind": "npc",
                                "creature_role": "guard", "count": 4,
                                "faction": "guards", "spawn_radius": 20.0})
    s = _session([sp], _FakePlayer([9999, 0, 0]))
    made = s.spawn_creature_points()
    assert made == 4
    npcs = [t for t in s.logic.things
            if str(t.properties.get("type")) == "npc"]
    assert len(npcs) == 4
    assert all(n.properties.get("npc_role") == "guard" for n in npcs)
    # the whole group shares the forced faction / team
    assert all(n.properties.get("faction") == "guards" for n in npcs)
    assert all(n.properties.get("team") == "guards" for n in npcs)


def test_spawn_point_grants_inventory_to_each_member():
    """Each spawned member receives its own copy of the authored inventory."""
    sp = _FakeThing([0, 0, 0], {"type": "creaturespawn", "spawn_kind": "npc",
                                "creature_role": "farmer", "count": 3,
                                "inventory": "gold:50, bread:2"})
    s = _session([sp], _FakePlayer([9999, 0, 0]))
    assert s.spawn_creature_points() == 3
    npcs = [t for t in s.logic.things
            if str(t.properties.get("type")) == "npc"]
    assert len(npcs) == 3
    for n in npcs:
        ids = {it.get("id"): it.get("qty") for it in n.properties.get("inventory", [])}
        assert ids.get("gold") == 50
        assert ids.get("bread") == 2
    # each member's inventory is a distinct list, not a shared reference
    assert npcs[0].properties["inventory"] is not npcs[1].properties["inventory"]


def test_spawn_point_defaults_to_creatures_unchanged():
    """With no spawn_kind the point still makes Creatures (backwards compatible)."""
    sp = _FakeThing([0, 0, 0], {"type": "creaturespawn", "creature_role": "wolf",
                                "count": 2})
    s = _session([sp], _FakePlayer([9999, 0, 0]))
    assert s.spawn_creature_points() == 2
    kinds = {str(t.properties.get("type")) for t in s.logic.things
             if t.properties.get("npc_role") == "wolf"}
    assert kinds == {"creature"}


def test_spawn_inventory_parses_string_and_list_forms():
    """The inventory helper accepts a compact string or an authored list, and
    silently drops unknown ids."""
    from game.runtime import MiniwindSession
    fn = MiniwindSession._spawn_inventory
    assert fn("") == []
    # plain id defaults to qty 1; unknown ids are skipped
    by_id = {it["id"]: it["qty"] for it in fn("gold, bread:3, made_up_item:9")}
    assert by_id == {"gold": 1, "bread": 3}
    # list of {id, qty} shorthand
    by_id2 = {it["id"]: it["qty"] for it in fn([{"id": "gold", "qty": 7}])}
    assert by_id2 == {"gold": 7}
