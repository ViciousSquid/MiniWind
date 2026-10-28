"""NPCs drink the potions they carry when they need them, heard and seen
where they stand; a magicka potion shimmers blue, the rest green."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import magic_fx, runtime
from ..rpg import items
from .test_combat_ai import _FakeLogic, _FakePlayer, _guard


def _session(*things):
    s = runtime.MiniwindSession(_FakeLogic(list(things), _FakePlayer([0, 0, 0])), cfg={})
    queued = []
    s.logic.game_state = SimpleNamespace(queue_sound=queued.append)
    s.magic_fx = magic_fx.MagicFX(player_pos=lambda: (0.0, 0.0, 0.0))
    return s, queued


def _npc(health, potions=("potion_heal_minor",), **extra):
    g = _guard([100.0, 0.0, 0.0])
    g.properties.update(name="Brann", health=health, max_health=100,
                        inventory=[items.make(iid, 1) for iid in potions], **extra)
    return g


def test_a_wounded_npc_drinks_a_healing_potion_from_its_pack(monkeypatch):
    monkeypatch.setattr(runtime, "sound_available", lambda name: True)
    npc = _npc(30)
    s, queued = _session(npc)
    assert s._npc_drink(npc)
    p = npc.properties
    assert p["health"] == 60                                     # +30
    assert p["inventory"] == []                                  # the potion is gone
    assert queued[0]["file"] == "drink.mp3" and queued[0]["position"] == [100.0, 0.0, 0.0]
    _sprites, lenses, _t = s.magic_fx.frame()
    assert lenses and lenses[0][6] == magic_fx._rgb(magic_fx.DRINK_COLOUR)   # green


def test_a_healthy_npc_or_one_without_potions_does_not_drink():
    healthy = _npc(90)
    s, _q = _session(healthy)
    assert not s._npc_drink(healthy)
    assert healthy.properties["inventory"]
    dry = _npc(10, potions=())
    s, _q = _session(dry)
    assert not s._npc_drink(dry)
    bread = _npc(10, potions=("bread",))                         # food is not a potion
    s, _q = _session(bread)
    assert not s._npc_drink(bread)


def test_it_drinks_the_potion_that_best_makes_good_the_loss_and_not_twice_at_once():
    npc = _npc(25, potions=("potion_heal", "potion_heal_minor"))
    s, _q = _session(npc)
    strength = {iid: items.get(iid).get("effects")[0]["magnitude"]
                for iid in ("potion_heal", "potion_heal_minor")}
    lost = 75
    enough = [iid for iid, amount in strength.items() if amount >= lost]
    drunk = (min(enough, key=strength.get) if enough else max(strength, key=strength.get))
    assert s._npc_drink(npc)
    left = [st["id"] for st in npc.properties["inventory"]]
    assert left == [iid for iid in ("potion_heal", "potion_heal_minor") if iid != drunk]
    npc.properties["health"] = 10
    assert not s._npc_drink(npc)                                 # a moment between drinks


def test_a_caster_low_on_magicka_drinks_a_magicka_potion_with_a_blue_shimmer():
    from .. import npc_magic
    npc = _npc(100, potions=("potion_magicka",), hand_spells={"main": "flare"},
               spells=["flare"], max_magicka=100, magicka=5)
    s, _q = _session(npc)
    assert npc_magic.casts(npc.properties)
    assert s._npc_drink(npc)
    assert npc_magic.magicka(npc.properties) > 5
    _sprites, lenses, _t = s.magic_fx.frame()
    assert lenses[0][6] == magic_fx._rgb(magic_fx.DRINK_MAGICKA_COLOUR)      # blue


def test_the_players_magicka_potion_shimmers_blue_and_a_healing_one_green():
    assert magic_fx.drink_colour(items.get("potion_magicka")) == magic_fx.DRINK_MAGICKA_COLOUR
    assert magic_fx.drink_colour(items.get("potion_heal")) == magic_fx.DRINK_COLOUR
