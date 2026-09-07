"""
Drawing a weapon with the number keys.

1 draws the first weapon you carry, 2 the second, and so on — the same order the
loadout popup lists them in, so what is on screen and what the keys do can never
disagree. Pressing the slot you already hold sheathes it.

Run:  python -m pytest game/tests/test_weapon_slots.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import host
from game.runtime import MiniwindSession
from game.rpg import equipment as eq
from game.rpg import items as rpg_items


class _Character:
    def __init__(self, inventory):
        self.inventory = list(inventory)
        self.equipment = {}
        # equipment._refresh_weapon_kind reads both of these off a real Character.
        self.active_spell = None
        self.active_weapon_kind = "unarmed"



class _Game:
    def __init__(self, inventory):
        self.character = _Character(inventory)
        self.equipped = []

    def equip(self, item_id):
        self.equipped.append(item_id)
        eq.equip(self.character, item_id)


class _Session:
    weapon_slots = MiniwindSession.weapon_slots
    select_weapon_slot = MiniwindSession.select_weapon_slot

    def __init__(self, inventory):
        self.game = _Game(inventory)
        self.notices = []

    def notify(self, text, seconds=3.0):
        self.notices.append(text)


def _pack(*item_ids):
    return _Session([{"id": iid, "qty": 1} for iid in item_ids])


# -------------------------------------------------------------------- slots

def test_slots_are_the_weapons_you_carry_in_order():
    session = _pack("iron_shortsword", "bread", "hunting_bow")
    assert [s["id"] for s in session.weapon_slots()] == ["iron_shortsword",
                                                         "hunting_bow"]


def test_bread_takes_no_slot():
    assert _pack("bread", "potion_heal").weapon_slots() == []


def test_a_stack_of_daggers_is_one_slot():
    session = _Session([{"id": "iron_dagger", "qty": 3},
                        {"id": "iron_dagger", "qty": 1}])
    assert len(session.weapon_slots()) == 1


def test_an_empty_pack_has_no_slots():
    assert _pack().weapon_slots() == []


# ------------------------------------------------------------------ drawing

def test_pressing_one_draws_the_first_weapon():
    session = _pack("iron_shortsword", "hunting_bow")
    assert session.select_weapon_slot(1) is True
    assert eq.equipped_id(session.game.character, rpg_items.SLOT_WEAPON) == \
        "iron_shortsword"


def test_pressing_two_draws_the_second():
    session = _pack("iron_shortsword", "hunting_bow")
    session.select_weapon_slot(2)
    assert eq.equipped_id(session.game.character, rpg_items.SLOT_WEAPON) == \
        "hunting_bow"


def test_pressing_the_slot_you_already_hold_puts_it_away():
    session = _pack("iron_shortsword")
    session.select_weapon_slot(1)
    session.select_weapon_slot(1)
    assert eq.equipped_id(session.game.character, rpg_items.SLOT_WEAPON) is None
    assert session.notices[-1] == "Unarmed"


def test_an_empty_slot_says_so_and_changes_nothing():
    session = _pack("iron_shortsword")
    session.select_weapon_slot(1)
    assert session.select_weapon_slot(4) is False
    assert eq.equipped_id(session.game.character, rpg_items.SLOT_WEAPON) == \
        "iron_shortsword"
    assert "slot 4" in session.notices[-1]


def test_a_nonsense_slot_number_is_survivable():
    session = _pack("iron_shortsword")
    assert session.select_weapon_slot(0) is False
    assert session.select_weapon_slot(-1) is False


# ------------------------------------------------------------------ bindings

def test_the_number_keys_are_bound_and_leave_zero_free():
    assert host.WEAPON_SLOT_KEYS == tuple("123456789")


def test_the_slot_keys_do_not_clash_with_any_action_binding():
    actions = {value for name, value in vars(host).items()
               if name.startswith("K_") and isinstance(value, str)}
    assert not actions & set(host.WEAPON_SLOT_KEYS)


def test_the_loadout_popup_lists_the_same_order_the_keys_use():
    """One source of truth: row 1 is what pressing 1 draws."""
    from game.ui.loadout_window import LoadoutWindow

    session = _pack("iron_shortsword", "bread", "hunting_bow")
    listed = [row[0] for row in LoadoutWindow._weapons(
        type("W", (), {"session": session})())]
    assert listed == [s["id"] for s in session.weapon_slots()]
