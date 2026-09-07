"""
Tests for NPC weapon and spell switching (:mod:`engine.combat_loadout`).

An actor's ``attack_style`` used to be one authored string for the whole fight.
Now an actor that carries more than one option switches: blade inside its reach,
spell or bow outside it — but only between things it genuinely has, and an actor
with a single option is untouched.

The other half of the contract is cost. There is no per-tick decision: the
loadout scan runs only when the target crosses the melee boundary, and the AI's
per-tick work is one comparison. The last tests here pin that, because it is the
part that would quietly regress.

Run:  python -m pytest engine/tests/test_combat_loadout.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import combat_loadout as cl


def _guard():
    """Sword in hand, bow in the pack — the actor with a real choice."""
    return {"attack_style": "melee", "equipped_weapon": "iron_shortsword",
            "inventory": [{"id": "hunting_bow", "qty": 1}, {"id": "bread", "qty": 2}]}


def _mage():
    return {"attack_style": "magic", "equipped_weapon": "apprentice_staff",
            "spells": [{"id": "flare"}],
            "inventory": [{"id": "iron_shortsword", "qty": 1}]}


def _archer():
    return {"attack_style": "bow", "equipped_weapon": "hunting_bow", "inventory": []}


def _wolf():
    return {"attack_style": "melee", "equipped_weapon": "", "inventory": []}


# ------------------------------------------------------------------- loadouts

def test_a_loadout_lists_only_what_the_actor_carries():
    loadout = cl.build_loadout(_guard())
    assert loadout[cl.MELEE] == "iron_shortsword"
    assert loadout[cl.BOW] == "hunting_bow"
    assert cl.MAGIC not in loadout          # no staff, no spells


def test_bread_is_not_a_weapon():
    loadout = cl.build_loadout(
        {"attack_style": "melee", "inventory": [{"id": "bread"}, {"id": "hunting_bow"}]})
    assert set(loadout) == {"default", cl.MELEE, cl.BOW}


def test_spells_make_magic_available_with_no_weapon_needed():
    loadout = cl.build_loadout(
        {"attack_style": "melee", "equipped_weapon": "iron_shortsword",
         "spells": [{"id": "flare"}]})
    assert cl.MAGIC in loadout
    assert cl.weapon_for(loadout, cl.MAGIC) == ""


def test_the_authored_style_is_always_available_even_with_no_weapon():
    """A wolf's claws and a hexer's curse are not items."""
    loadout = cl.build_loadout(_wolf())
    assert cl.MELEE in loadout
    assert loadout[cl.MELEE] is None


def test_an_actor_with_nothing_authored_still_gets_a_loadout():
    assert cl.build_loadout({})["default"] == cl.MELEE
    assert cl.build_loadout(None)["default"] == cl.MELEE


def test_a_bare_item_id_in_the_inventory_counts():
    loadout = cl.build_loadout({"attack_style": "melee", "inventory": ["hunting_bow"]})
    assert loadout[cl.BOW] == "hunting_bow"


# --------------------------------------------------------------------- choice

def test_a_guard_draws_a_blade_up_close_and_a_bow_at_range():
    loadout = cl.build_loadout(_guard())
    assert cl.choose_style(loadout, in_melee=True) == cl.MELEE
    assert cl.choose_style(loadout, in_melee=False) == cl.BOW


def test_a_mage_leads_with_the_spell_at_range_and_the_blade_up_close():
    loadout = cl.build_loadout(_mage())
    assert cl.choose_style(loadout, in_melee=False) == cl.MAGIC
    assert cl.choose_style(loadout, in_melee=True) == cl.MELEE


def test_magic_is_preferred_over_a_bow_when_both_are_carried():
    loadout = cl.build_loadout(
        {"attack_style": "bow", "equipped_weapon": "hunting_bow",
         "spells": [{"id": "flare"}]})
    assert cl.choose_style(loadout, in_melee=False) == cl.MAGIC


def test_an_actor_with_one_option_is_left_exactly_as_authored():
    """Nothing to switch to means nothing about its behaviour changes."""
    for props, style in ((_archer(), cl.BOW), (_wolf(), cl.MELEE)):
        loadout = cl.build_loadout(props)
        assert cl.has_choice(loadout) is False
        assert cl.choose_style(loadout, in_melee=True) == style
        assert cl.choose_style(loadout, in_melee=False) == style


def test_an_archer_shoved_to_point_blank_keeps_shooting():
    loadout = cl.build_loadout(_archer())
    assert cl.choose_style(loadout, in_melee=True) == cl.BOW


def test_a_swordsman_across_the_square_keeps_the_sword_and_closes():
    loadout = cl.build_loadout({"attack_style": "melee",
                                "equipped_weapon": "iron_shortsword"})
    assert cl.choose_style(loadout, in_melee=False) == cl.MELEE


def test_the_weapon_follows_the_style():
    loadout = cl.build_loadout(_guard())
    assert cl.weapon_for(loadout, cl.MELEE) == "iron_shortsword"
    assert cl.weapon_for(loadout, cl.BOW) == "hunting_bow"
    assert cl.weapon_for(loadout, cl.MAGIC) == ""      # not carried


def test_no_game_item_database_means_no_switching():
    """The engine runs maps with no MiniWind layer; those keep their style."""
    real = cl._item_style

    def _blind(_item_id):
        return None                     # as if game.rpg.items were unavailable

    cl._item_style = _blind
    try:
        loadout = cl.build_loadout(_guard())
        assert cl.has_choice(loadout) is False
        assert cl.choose_style(loadout, in_melee=False) == cl.MELEE
    finally:
        cl._item_style = real


# ----------------------------------------------------------------------- cost

def test_the_ai_only_rebuilds_a_loadout_when_the_range_band_flips():
    """The whole performance contract: no decision on an ordinary tick."""
    from engine.monster_ai import MonsterAI

    calls = []
    real_build = cl.build_loadout

    def _counting_build(props):
        calls.append(props)
        return real_build(props)

    class _Thing:
        properties = _guard()

    cl.build_loadout = _counting_build
    try:
        thing, state = _Thing(), {}
        # Closing in: one build on the first tick, nothing on the next hundred.
        assert MonsterAI._attack_style_for(thing, state, True) == cl.MELEE
        assert len(calls) == 1
        for _ in range(100):
            assert MonsterAI._attack_style_for(thing, state, True) == cl.MELEE
        assert len(calls) == 1

        # Target backs off: one more build, then quiet again.
        assert MonsterAI._attack_style_for(thing, state, False) == cl.BOW
        assert len(calls) == 2
        for _ in range(100):
            MonsterAI._attack_style_for(thing, state, False)
        assert len(calls) == 2
    finally:
        cl.build_loadout = real_build


def test_switching_style_also_switches_the_weapon_in_hand():
    from engine.monster_ai import MonsterAI

    class _Thing:
        def __init__(self):
            self.properties = _guard()

    thing, state = _Thing(), {}
    MonsterAI._attack_style_for(thing, state, True)
    assert thing.properties["_active_weapon"] == "iron_shortsword"
    MonsterAI._attack_style_for(thing, state, False)
    assert thing.properties["_active_weapon"] == "hunting_bow"
    # The authored weapon is never overwritten, so re-saving the map is safe.
    assert thing.properties["equipped_weapon"] == "iron_shortsword"


def test_an_actor_with_no_choice_never_gets_a_live_weapon_written():
    from engine.monster_ai import MonsterAI

    class _Thing:
        def __init__(self):
            self.properties = _archer()

    thing, state = _Thing(), {}
    MonsterAI._attack_style_for(thing, state, False)
    MonsterAI._attack_style_for(thing, state, True)
    assert "_active_weapon" not in thing.properties


def test_the_renderer_shows_whatever_is_actually_in_hand():
    from editor.things import Monster

    monster = Monster([0, 0, 0])
    monster.properties.update(_guard())
    assert monster.get_render_snapshot()["weapon_id"] == "iron_shortsword"
    monster.properties["_active_weapon"] = "hunting_bow"
    assert monster.get_render_snapshot()["weapon_id"] == "hunting_bow"
