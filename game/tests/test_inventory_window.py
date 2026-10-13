"""
The inventory window's rules: what may be dropped where, and what a drop does.

The window itself is Qt; the rules it applies (``fits``) and the verbs the game
tick carries out (``MiniwindSession.inventory_move`` / ``inventory_use`` /
``inventory_assign_quick``) are plain Python and tested here.

Run:  python -m pytest game/tests/test_inventory_window.py -q
"""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5")

from ..rpg import items
from ..rpg import equipment as eq
from ..rpg.game_state import GameState
from ..runtime import MiniwindSession
from ..ui import inventory_window as iw


class _Store:
    def get(self, *_a, **_k):
        return "false"

    def set(self, *_a):
        pass

    def all(self):
        return {}


def _session(*ids):
    s = MiniwindSession.__new__(MiniwindSession)
    s.game = GameState.new_game(_Store(), "Tester", "imperial", "warrior")
    c = s.game.character
    c.inventory.clear()
    c.equipment.clear()
    c.quick_weapons = [None] * 4
    c._quick_seen = set()
    for iid in ids:
        c.inventory.append(items.make(iid, 1))
    s.notifications = []
    s._bow_input = []
    s.bow_charge = None
    return s


def test_only_weapons_fit_a_quick_slot():
    assert iw.fits(("quick", 0), items.get("iron_longsword"))
    assert not iw.fits(("quick", 0), items.get("iron_helmet"))
    assert not iw.fits(("quick", 0), items.get("potion_heal"))


def test_armour_fits_only_its_own_slot():
    helmet = items.get("iron_helmet")
    assert iw.fits(("equip", "head"), helmet)
    assert not iw.fits(("equip", "chest"), helmet)
    assert not iw.fits(("equip", "ring"), items.get("iron_longsword"))


def test_arrows_go_in_the_quiver_and_a_torch_in_the_torch_hand():
    assert iw.fits(("equip", "ammo"), items.get("iron_arrow"))
    assert iw.fits(("equip", "light"), items.get("torch"))
    assert not iw.fits(("equip", "ammo"), items.get("torch"))


def test_anything_goes_back_to_the_pack():
    assert iw.fits(("pack", None), items.get("bread"))


def test_dropping_a_helmet_on_the_head_wears_it():
    s = _session("iron_helmet")
    assert s.inventory_move(("pack", None, "iron_helmet"), ("equip", "head"), "iron_helmet")
    assert eq.equipped_id(s.game.character, "head") == "iron_helmet"


def test_a_misplaced_drop_changes_nothing_and_says_why():
    s = _session("iron_helmet")
    assert not s.inventory_move(("pack", None, "iron_helmet"), ("equip", "feet"),
                                "iron_helmet")
    assert eq.equipped_id(s.game.character, "feet") is None
    assert "doesn't go" in s.notifications[-1]["text"]


def test_dragging_worn_armour_to_the_pack_takes_it_off():
    s = _session("iron_helmet")
    s.game.equip("iron_helmet")
    s.inventory_move(("equip", "head", "iron_helmet"), ("pack", None), "iron_helmet")
    assert eq.equipped_id(s.game.character, "head") is None


def test_dragging_a_weapon_out_of_its_quick_slot_empties_it_and_sheathes_it():
    s = _session("iron_longsword")
    s.select_weapon_slot(1)
    s.inventory_move(("quick", 0, "iron_longsword"), ("pack", None), "iron_longsword")
    assert s.weapon_slots() == []
    assert eq.equipped_id(s.game.character, "weapon") is None


def test_double_click_on_a_weapon_draws_it():
    s = _session("hunting_bow")
    s.inventory_use("hunting_bow")
    assert eq.equipped_id(s.game.character, "weapon") == "hunting_bow"


def test_assign_fills_the_first_free_quick_slot():
    s = _session("iron_longsword", "hunting_bow")
    s.quick_weapon_slots()
    s.set_quick_weapon(0, None)
    assert s.inventory_assign_quick("iron_longsword")
    assert s.quick_weapon_slots()[0]["id"] == "iron_longsword"
