"""
The pack (the player's inventory) has 20 slots; a satchel adds 4. Things can
be dropped on the floor, and when the pack loses slots what no longer fits
falls there.

Run:  python -m pytest game/tests/test_pack_satchel.py -q
"""

from __future__ import annotations

import random

from .fio_logic import FioLogic


class _Thing:
    def __init__(self, name, pos=(0.0, 0.0, 0.0), **props):
        self.pos = list(pos)
        self.properties = {"name": name, "display_name": name, **props}


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = _Thing("You", is_player=True)


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s.game.character.inventory[:] = []
    s.game.character.equipment.clear()
    s.rng = random.Random(1)
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    return s


def _give(s, iid, qty=1):
    from ..rpg import items, inventory as inv
    inv.add_item(s.game.character.inventory, items.make(iid, qty))


#: Twenty-odd different things to fill a pack with.
FILL = ["potion_heal", "potion_heal_minor", "potion_magicka", "potion_stamina",
        "potion_cure", "lockpick", "torch", "book_marksman", "book_blade",
        "ingr_flax", "ingr_nightshade", "ingr_mushroom", "ingr_bonemeal",
        "ingr_wolf_pelt", "milk", "egg", "wool", "repair_hammer", "silver_amulet",
        "book_lore", "iron_dagger", "iron_mace", "club", "iron_longsword"]


def _dropped(s):
    return [t for t in s.logic.things if t.properties.get("_dropped")]


def test_the_pack_has_twenty_slots_and_a_satchel_adds_four():
    from ..runtime import PACK_SLOTS
    s = _session()
    assert PACK_SLOTS == 20 and s.pack_capacity() == 20
    _give(s, "satchel")
    assert s.pack_capacity() == 24
    _give(s, "satchel")                               # a second adds nothing
    assert s.pack_capacity() == 24


def test_a_weapon_takes_a_slot_per_copy_and_what_is_worn_takes_none():
    s = _session()
    _give(s, "iron_shortsword", 2)
    _give(s, "potion_heal", 3)
    assert s.pack_used() == 3                         # two blades, one stack
    s.ready_weapon("iron_shortsword")
    assert s.pack_used() == 2                         # one is in hand


def test_a_full_pack_refuses_what_it_has_no_slot_for():
    s = _session()
    for iid in FILL[:20]:
        _give(s, iid)
    assert s.pack_used() == 20
    assert not s.pack_has_room("iron_dagger")
    assert s.pack_has_room("potion_heal")             # joins its stack
    chest = _Thing("Chest", type="container", inventory=[])
    from ..rpg import items
    chest.properties["inventory"] = [items.make("iron_dagger", 1)]
    s.container_thing = chest
    assert not s.take_from_container(0)
    assert chest.properties["inventory"]              # still in the chest


def test_dropping_puts_it_on_the_floor_and_it_is_not_taken_straight_back():
    s = _session()
    _give(s, "iron_shortsword", 2)
    s.ready_weapon("iron_shortsword", 0)
    s.ready_weapon("iron_shortsword", 1)              # dual wielding the pair
    assert s.drop_item("iron_shortsword")             # one copy
    from ..rpg import inventory as inv, equipment as eq
    assert inv.quantity(s.game.character.inventory, "iron_shortsword") == 1
    assert not eq.dual_wielding(s.game.character)
    [item] = _dropped(s)
    assert item.properties["item_id"] == "iron_shortsword"
    s._tick_pickups()                                 # still standing by it
    assert not item.properties.get("dead")
    s._player_pos = lambda: [500.0, 0.0, 0.0]         # walk off ...
    s._tick_pickups()
    s._player_pos = lambda: list(item.pos)            # ... and back
    s._tick_pickups()
    assert item.properties.get("dead")
    assert inv.quantity(s.game.character.inventory, "iron_shortsword") == 2


def test_losing_the_satchel_drops_what_no_longer_fits():
    s = _session()
    _give(s, "satchel")
    for iid in FILL[:23]:
        _give(s, iid)
    s._check_pack()
    assert s.pack_used() == 24 and not _dropped(s)
    s.merchant_npc = _Thing("Elowen", merchant=True)
    assert s.sell("satchel")
    s._check_pack()
    assert s.pack_capacity() == 20 and s.pack_used() == 20
    # The satchel's own slot went with it: three things fall, not four.
    assert sorted(t.properties["item_id"] for t in _dropped(s)) == sorted(FILL[20:23])


def test_a_pack_over_full_from_an_old_save_is_kept_but_cannot_grow():
    s = _session()
    for iid in FILL[:22]:
        _give(s, iid)
    s._check_pack()
    assert s.pack_used() == 22 and not _dropped(s)
    _give(s, FILL[22])                                # a quest reward, say
    s._check_pack()
    assert s.pack_used() == 22
    assert [t.properties["item_id"] for t in _dropped(s)] == [FILL[22]]


def test_the_strip_is_always_nine_slots():
    s = _session()
    _give(s, "satchel")
    assert s.strip_size() == 9 and len(s.strip_slots()) == 9
