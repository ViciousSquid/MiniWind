"""Metal interferes with magic: anyone wearing a piece of metal armour cannot
cast. Leather, studded leather, cloth, hide, fur, wood and elven work are fine.
"""

from __future__ import annotations

import random

import pytest

from ..rpg import equipment as eq, inventory as inv, items, magic
from ..rpg.game_state import GameState

METAL = ["iron_helmet", "iron_cuirass", "steel_shield", "chain_shirt", "scale_mail",
         "plate_gauntlets", "mithril_mail", "kite_shield", "tower_shield"]
NOT_METAL = ["leather_cuirass", "studded_leather", "studded_bracers", "cloth_robe",
             "hide_armour", "fur_cuirass", "elven_cuirass", "buckler", "round_shield"]


class _Store(dict):
    def set(self, key, value):
        self[key] = value


def _caster(class_id="mage", wearing=()):
    gs = GameState.new_game(_Store(), "T", "nord", class_id, "none", rng=random.Random(3))
    c = gs.character
    for iid in wearing:
        inv.add_item(c.inventory, items.make(iid))
        assert eq.equip(c, iid), iid
    c.known_spells = ["heal_minor"]
    c.active_spell = "heal_minor"
    eq.equip_spell(c, "heal_minor", "main")
    c.magicka = c.max_magicka
    return gs, c


@pytest.mark.parametrize("iid", METAL)
def test_metal_pieces_are_metal(iid):
    assert eq.is_metal(items.get(iid))


@pytest.mark.parametrize("iid", NOT_METAL)
def test_leather_and_the_rest_are_not(iid):
    assert not eq.is_metal(items.get(iid))


def test_jewellery_and_weapons_never_count():
    assert not eq.is_metal(items.get("copper_ring"))
    assert not eq.is_metal(items.get("iron_longsword"))


@pytest.mark.parametrize("class_id", ["mage", "sorcerer", "knight", "thief"])
def test_one_metal_piece_stops_anyone_casting_and_costs_nothing(class_id):
    gs, c = _caster(class_id, wearing=["iron_helmet"])
    before = c.magicka
    res = gs.cast_active_spell()
    assert not res.cast and res.reason == "metal"
    assert c.magicka == before
    assert gs.log[-1] == magic.METAL_INTERFERES == "The metal interferes..."


def test_leather_armour_casts_as_normal():
    gs, c = _caster("mage", wearing=["leather_cuirass", "leather_helmet", "studded_bracers"])
    res = magic.try_cast(c, "heal_minor", rng=random.Random(0))
    assert res.reason != "metal"
    assert c.magicka < c.max_magicka                 # it was paid for


def test_taking_the_metal_off_lets_the_spell_through():
    gs, c = _caster("mage", wearing=["chain_shirt"])
    assert magic.metal_blocks(c)
    eq.unequip(c, items.SLOT_CHEST)
    assert not magic.metal_blocks(c)


def test_an_explicit_metal_flag_overrides_the_material():
    d = items.get("leather_cuirass")
    d.extra["metal"] = True
    try:
        assert eq.is_metal(d)
    finally:
        del d.extra["metal"]


def test_the_session_says_why_and_never_casts(monkeypatch):
    """The cast key path (do_cast) and a staff both stop at worn metal."""
    from types import SimpleNamespace
    from ..runtime import MiniwindSession
    from .test_cast_controls import _Logic

    s = MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    c = s.game.character
    c.class_id = "mage"
    c.known_spells = ["heal_minor"]
    c.active_spell = "heal_minor"
    eq.equip_spell(c, "heal_minor", "main")
    inv.add_item(c.inventory, items.make("plate_armour"))
    eq.equip(c, "plate_armour")
    c.magicka = c.max_magicka = 100.0
    notes = []
    s.notify = lambda text, *a, **k: notes.append(text)
    called = []
    s.game.cast_active_spell = lambda: called.append(1) or SimpleNamespace(cast=True)
    assert s.do_cast() is False
    assert not called and notes[-1] == magic.METAL_INTERFERES
    assert s._staff_attack({"staff_spell": "flare"}) is False
    assert notes[-1] == magic.METAL_INTERFERES and c.magicka == 100.0
