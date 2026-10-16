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

pytestmark = pytest.mark.qt

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


# ------------------------------------------------------------ armour class

def test_unarmoured_is_armour_class_ten():
    s = _session()
    c = s.game.character
    c.attrs["agility"] = 40
    assert eq.armour_class(c) == eq.BASE_AC
    assert eq.deflect_chance(c) == 0.0


def test_plate_raises_armour_class_more_than_cloth():
    plate = _session("plate_armour").game.character
    cloth = _session("cloth_robe").game.character
    for c in (plate, cloth):
        c.attrs["agility"] = 40
    plate_char = plate
    eq.equip(plate_char, "plate_armour")
    eq.equip(cloth, "cloth_robe")
    assert eq.armour_class(plate_char) > eq.armour_class(cloth)


def test_heavy_armour_spends_your_agility_bonus():
    s = _session("plate_armour")
    c = s.game.character
    c.attrs["agility"] = 80                       # +4 out of armour
    nimble = eq.armour_class(c)
    eq.equip(c, "plate_armour")
    assert eq.armor_class_worn(c) == eq.HEAVY
    plate_only = eq.armour_class(c) - eq.BASE_AC
    assert plate_only == int(eq.armor_rating(c) // eq.RATING_PER_AC)
    assert nimble == eq.BASE_AC + 4


def test_medium_armour_lets_two_points_of_agility_through():
    s = _session("chain_shirt")
    c = s.game.character
    eq.equip(c, "chain_shirt")
    assert eq.armor_class_worn(c) == eq.MEDIUM
    c.attrs["agility"] = 40
    without_agility = eq.armour_class(c)
    c.attrs["agility"] = 90
    assert eq.armour_class(c) == without_agility + 2


def test_a_ring_of_protection_adds_to_armour_class():
    s = _session("ring_of_protection")
    c = s.game.character
    before = eq.armour_class(c)
    s.inventory_move(("pack", None, "ring_of_protection"), ("equip", "ring"),
                     "ring_of_protection")
    assert eq.armour_class(c) == before + 1


def test_a_deflected_blow_does_no_harm():
    import random
    from ..rpg import combat
    s = _session("plate_armour", "plate_helm", "tower_shield")
    c = s.game.character
    for iid in ("plate_armour", "plate_helm", "tower_shield"):
        eq.equip(c, iid)
    rng = random.Random(1)
    results = [combat.resolve_incoming(c, 20.0, rng=rng) for _ in range(200)]
    deflected = [r for r in results if r.get("deflected")]
    assert deflected and all(r["final"] == 0.0 for r in deflected)
    assert len(deflected) < len(results)


def test_dropping_a_weapon_on_the_main_hand_draws_it_and_slots_it():
    s = _session("iron_longsword")
    s.quick_weapon_slots()
    s.set_quick_weapon(0, None)
    assert s.inventory_move(("pack", None, "iron_longsword"), ("equip", "weapon"),
                            "iron_longsword")
    assert eq.equipped_id(s.game.character, "weapon") == "iron_longsword"
    assert any(e["id"] == "iron_longsword" for e in s.weapon_slots())
