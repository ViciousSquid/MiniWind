"""Spells occupy a real hand, replace gear safely and survive saved games."""

from types import SimpleNamespace

import pytest

from game import host, keybinds
from game.rpg import equipment as eq, items
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic


def _caster():
    c = Character.create("Mage", "imperial", "mage")
    c.known_spells = ["flare", "heal_minor"]
    c.inventory = [items.make(iid) for iid in
                   ("iron_shortsword", "iron_shield", "short_bow", "torch")]
    c.equipment = {}
    return c


@pytest.mark.parametrize("handed", ["left", "right"])
def test_spells_replace_only_their_own_hand_and_keep_displaced_items(handed):
    c = _caster()
    c.handed = handed
    eq.equip(c, "iron_shortsword")
    eq.equip(c, "iron_shield")
    before = list(c.inventory)
    other = "left" if handed == "right" else "right"
    assert eq.equip_spell(c, "flare", other)
    assert eq.weapon(c).id == "iron_shortsword"
    assert eq.shield(c) is None
    assert eq.hand_spell(c, other).id == "flare"
    assert c.inventory == before
    assert eq.equip_spell(c, "heal_minor", handed)
    assert eq.weapon(c) is None
    assert eq.hand_spell(c, "main").id == "heal_minor"
    assert eq.hand_spell(c, "off").id == "flare"


def test_items_replace_hand_spells_and_two_handers_clear_both_hands():
    c = _caster()
    eq.equip_spell(c, "flare", "main")
    eq.equip_spell(c, "heal_minor", "off")
    eq.equip(c, "iron_shortsword")
    assert eq.hand_spell(c, "main") is None
    assert eq.hand_spell(c, "off").id == "heal_minor"
    assert c.active_weapon_kind == "melee"
    eq.equip(c, "short_bow")
    assert not c.hand_spells
    assert eq.weapon(c).id == "short_bow"
    eq.equip_spell(c, "flare", "off")
    assert eq.weapon(c) is None  # a bow cannot share either hand


def test_hand_equipment_survives_save_load_without_equipping_legacy_selection():
    c = _caster()
    eq.equip(c, "iron_shortsword")
    eq.equip_spell(c, "flare", "off")
    saved = c.to_dict()
    loaded = Character.from_dict(saved)
    assert loaded.hand_spells == {"off": "flare"}
    assert eq.weapon(loaded).id == "iron_shortsword"
    assert eq.hand_spell(loaded, "off").id == "flare"
    saved.pop("hand_spells")
    loaded = Character.from_dict(saved)
    assert not loaded.hand_spells
    assert not eq.spell_equipped(loaded, "flare")


def _session():
    s = MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    s.game.character = _caster()
    return s


def test_each_mouse_button_uses_its_own_equipped_spell_or_weapon():
    s = _session()
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    eq.equip_spell(c, "flare", "off")
    calls = []
    s.do_attack = lambda hand="main": calls.append(("weapon", hand))
    s.do_cast = lambda **kw: calls.append(("spell", kw["hand"]))
    s.fire_player_weapon(s.logic, "primary")
    s.fire_player_weapon(s.logic, "secondary")
    assert calls == [("weapon", "main"), ("spell", "off")]
    eq.equip_spell(c, "heal_minor", "main")
    eq.equip(c, "iron_shortsword", "shield")
    calls.clear()
    s.fire_player_weapon(s.logic, "primary")
    s.fire_player_weapon(s.logic, "secondary")
    assert calls == [("spell", "main"), ("weapon", "off")]


def test_selected_but_unequipped_spell_cannot_cast_or_spend_magicka():
    s = _session()
    c = s.game.character
    c.active_spell = "flare"
    before = c.magicka
    assert not s.do_cast(aim="facing")
    assert not s.game.cast_active_spell().cast
    assert c.magicka == before
    assert s._cast_cooldown == 0


def test_obsolete_k_binding_is_absent_and_pressing_k_does_not_cast():
    s = _session()
    eq.equip_spell(s.game.character, "flare", "main")
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    s.cast_key = lambda: pytest.fail("K must not cast")
    s.do_cast = lambda **kw: pytest.fail("K must not cast")
    game._handle_gameplay_input(s, {"k"}, SimpleNamespace(key_down=lambda key: False))
    assert "cast" not in keybinds.defaults()
    assert not hasattr(host, "K_CAST")


def test_replacing_items_with_a_spell_is_atomic_when_pack_is_full(monkeypatch):
    s = _session()
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    original = dict(c.equipment)
    monkeypatch.setattr(s, "pack_capacity", lambda: s.pack_used() - (0 if c.equipment == original else 1))
    assert not s.equip_hand_spell("flare", "main")
    assert c.equipment == original
    assert not c.hand_spells


def test_dragging_a_spell_between_hands_moves_it_and_dragging_back_unequips():
    s = _session()
    c = s.game.character
    assert s.item_drop(("spell", None, "flare"), ("hand", "right"))
    assert eq.hand_spell(c, "main").id == "flare"
    assert s.item_drop(("spell_hand", "main", "flare"), ("hand", "left"))
    assert eq.hand_spell(c, "main") is None
    assert eq.hand_spell(c, "off").id == "flare"
    assert s.item_drop(("spell_hand", "off", "flare"), ("spells", None))
    assert not c.hand_spells


def test_equipped_spells_glow_in_their_own_hands_and_stop_when_replaced():
    import math
    import numpy as np
    from game import magic_fx
    s = _session()
    c = s.game.character
    s.logic.camera_mode = "overhead"
    eq.equip_spell(c, "flare", "right")
    eq.equip_spell(c, "heal_minor", "left")
    hands = s._magic_hands()
    assert len(hands) == 2
    assert hands[0][0][0] > 0 and hands[1][0][0] < 0
    sprites = s.magic_fx.frame(now=10.)[0]
    orbs = sprites[sprites[:, 8] == magic_fx.ORB]
    assert len(orbs) == 2
    np.testing.assert_allclose(orbs[0, 4:7], hands[0][1]["colour"])
    assert hands[0][1]["colour"] != hands[1][1]["colour"]
    s.logic.player.angle = math.pi / 2
    assert s._magic_hands()[0][0][2] < 0  # the right hand follows heading
    eq.equip(c, "iron_shortsword")
    assert len(s._magic_hands()) == 1
    eq.unequip_spell(c, "off")
    assert s._magic_hands() == []
    assert len(s.magic_fx.frame(now=10.)[0]) == 0
