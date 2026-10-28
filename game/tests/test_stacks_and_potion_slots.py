"""Same things stack -- at most five to a slot, in the pack and on the strip
-- and a potion in a strip slot is drunk by pressing that slot's number, to
the sound of drink.mp3.

Run:  python -m pytest game/tests/test_stacks_and_potion_slots.py -q
"""

from __future__ import annotations

from ..rpg import inventory as inv, items
from .test_inventory_strip import _session


def _give(s, iid, qty):
    inv.add_item(s.game.character.inventory, items.make(iid, qty))


def _sounds(s, monkeypatch, *present):
    """Capture queued sounds, with only *present* shipped: no loose file in
    assets/sounds counts (they are looked for first), only the pinned set."""
    from .. import runtime
    queued = []
    s.logic.game_state = type("GS", (), {"queue_sound": staticmethod(queued.append)})()
    monkeypatch.setattr(runtime, "SOUND_DIR", "/nonexistent/sounds")
    monkeypatch.setattr(runtime, "_ARCHIVED_SOUNDS", set(present))
    return queued


def test_five_to_a_slot():
    assert inv.MAX_STACK == 5
    assert inv.slot_sizes("potion_heal", 12) == [5, 5, 2]
    assert inv.slot_sizes("potion_heal", 5) == [5]
    assert inv.slot_sizes("potion_heal", 0) == []
    assert inv.slot_sizes("iron_shortsword", 2) == [1, 1]   # a slot per blade
    assert inv.slot_sizes("iron_arrow", 20) == [20]         # a quiver is one slot


def test_the_pack_holds_five_to_a_slot_but_one_record_of_them():
    s = _session()
    _give(s, "potion_heal", 12)
    c = s.game.character
    assert [st["qty"] for st in s.pack_stacks() if st["id"] == "potion_heal"] == [5, 5, 2]
    assert inv.quantity(c.inventory, "potion_heal") == 12
    assert len([st for st in c.inventory if st["id"] == "potion_heal"]) == 1
    used = s.pack_used()
    # Three more top up the last stack; a fourth needs a new slot.
    assert s.pack_has_room("potion_heal", 3)
    _give(s, "potion_heal", 3)
    assert s.pack_used() == used
    _give(s, "potion_heal", 1)
    assert s.pack_used() == used + 1


def test_a_full_pack_takes_no_more_than_five_a_slot():
    s = _session()
    _give(s, "potion_heal", 5 * s.pack_capacity() - 1)
    assert s.pack_used() == s.pack_capacity()
    assert s.pack_has_room("potion_heal", 1)          # tops up the last stack
    assert not s.pack_has_room("potion_heal", 2)      # would start another


def test_the_strip_shows_stacks_of_five():
    s = _session()
    _give(s, "potion_heal", 7)
    slots = [(e["id"], e["qty"]) for e in s.strip_slots() if e]
    assert slots == [("potion_heal", 5), ("potion_heal", 2)]


def test_pressing_a_potions_number_drinks_it_with_a_sound(monkeypatch):
    s = _session()
    queued = _sounds(s, monkeypatch, "drink.mp3")
    _give(s, "potion_heal", 3)
    c = s.game.character
    c.health = 10
    index = next(i for i, e in enumerate(s.strip_slots()) if e and e["id"] == "potion_heal")
    assert s.select_strip_slot(index)               # the number key
    assert inv.quantity(c.inventory, "potion_heal") == 2
    assert c.health > 10
    assert [q["file"] for q in queued] == ["drink.mp3"]
    # The heal key drinks with the same sound.
    assert s.use_health_potion()
    assert [q["file"] for q in queued] == ["drink.mp3", "drink.mp3"]


def test_the_last_one_drunk_empties_its_slot(monkeypatch):
    s = _session()
    _sounds(s, monkeypatch)
    _give(s, "potion_heal", 1)
    index = next(i for i, e in enumerate(s.strip_slots()) if e)
    s.select_strip_slot(index)
    assert s.strip_slots()[index] is None


def test_no_drink_sound_is_no_error(monkeypatch):
    s = _session()
    queued = _sounds(s, monkeypatch)                # drink.mp3 not shipped
    _give(s, "potion_heal", 1)
    assert s.use_health_potion()
    assert queued == []


def test_every_potion_drunk_by_every_route_plays_drink(monkeypatch):
    from ..rpg import items
    s = _session()
    queued = _sounds(s, monkeypatch, "drink.mp3")
    potions = [iid for iid in ("potion_heal_minor", "potion_heal", "potion_magicka")
               if items.get(iid) is not None and items.get(iid).category == items.POTION]
    assert len(potions) == 3
    for iid in potions:
        _give(s, iid, 3)
    assert s.use_health_potion()                                 # the heal key
    index = next(i for i, e in enumerate(s.strip_slots())
                 if e and e["id"] == "potion_magicka")
    s.select_strip_slot(index)                                   # its number key / a click
    assert s.inventory_use("potion_magicka")                     # the pack, a double-click
    assert [q["file"] for q in queued] == ["drink.mp3"] * 3
