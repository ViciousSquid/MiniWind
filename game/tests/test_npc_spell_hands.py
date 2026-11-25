"""
NPCs hold their spells in their hands, as the player does, and cast what they
hold: an attack at whoever they fight, a ward or a heal to defend themselves.

Run:  python -m pytest game/tests/test_npc_spell_hands.py -q
"""

from __future__ import annotations

from .. import npc_magic
from .test_cast_controls import _Logic, _Thing


def _caster(**props):
    base = {"type": "npc", "combatant": True, "health": 40, "max_health": 40,
            "spells": [{"id": "firebolt"}, {"id": "sp_shield"}],
            "magic_skill": 100}     # a master: these tests are not about fizzles
    base.update(props)
    return {k: v for k, v in base.items() if v is not None}


def test_a_caster_with_its_hands_free_leads_with_an_attack_and_guards_with_the_other():
    p = _caster()
    assert npc_magic.ready_hands(p) == {"main": "firebolt", "off": "sp_shield"}
    assert [s.id for s, *_ in npc_magic.attacks(p)] == ["firebolt"]
    assert [w[0].id for w in npc_magic.wards(p)] == ["sp_shield"]


def test_an_armed_fighter_keeps_its_blade_and_holds_one_spell():
    blade = _caster(equipped_weapon="iron_shortsword")
    assert npc_magic.ready_hands(blade) == {"off": "firebolt"}       # its range option
    archer = _caster(equipped_weapon="short_bow")
    assert npc_magic.ready_hands(archer) == {"off": "sp_shield"}     # already has range


def test_a_caster_casts_any_spell_it_knows_not_only_what_is_in_hand():
    blade = _caster(equipped_weapon="iron_shortsword")
    npc_magic.ready_hands(blade)
    assert [s.id for s, *_ in npc_magic.wards(blade)] == ["sp_shield"]   # known, not in hand
    archer = _caster(equipped_weapon="short_bow")
    npc_magic.ready_hands(archer)
    assert [s.id for s, *_ in npc_magic.attacks(archer)] == ["firebolt"]


def test_casting_a_spell_readies_it_in_a_hand():
    blade = _caster(equipped_weapon="iron_shortsword")
    npc_magic.ready_hands(blade)                       # {"off": "firebolt"}
    assert npc_magic.ready_spell(blade, "sp_shield") == "off"
    assert npc_magic.hands(blade) == {"off": "sp_shield"}
    mage = _caster(hand_spells={})
    assert npc_magic.ready_spell(mage, "firebolt") == "main"
    shielded = _caster(equipped_weapon="iron_shortsword", offhand_weapon="iron_shield",
                       hand_spells={})
    assert npc_magic.ready_spell(shielded, "firebolt") == ""        # no hand free: cast anyway


def test_the_editors_hands_win_and_every_known_spell_can_be_cast():
    p = _caster(hand_spell_main="frostbite", spells=[{"id": "firebolt"}])
    assert npc_magic.hands(p) == {"main": "frostbite"}
    assert {s.id for s, *_ in npc_magic.attacks(p)} == {"firebolt", "frostbite"}


def test_only_an_actor_with_no_spells_casts_nothing():
    p = _caster(hand_spells={}, spells=[])
    assert npc_magic.attacks(p) == [] and npc_magic.wards(p) == []
    assert not npc_magic.can_attack_with_magic(p)
    q = _caster(hand_spells={})                        # knows spells: still casts
    assert npc_magic.attacks(q) and npc_magic.can_attack_with_magic(q)


def test_a_spell_glows_in_the_hand_only_while_fighting():
    p = _caster()
    assert npc_magic.hand_glows(p) == []
    p["_aggro_target"] = 1
    assert [(h, s.id) for h, s in npc_magic.hand_glows(p)] == [
        ("main", "firebolt"), ("off", "sp_shield")]
    p["_active_weapon"] = "iron_dagger"                   # closed in: blade drawn
    assert [h for h, _s in npc_magic.hand_glows(p)] == ["off"]


def test_an_npc_defends_itself_with_its_ward_and_attacks_with_its_bolt():
    from ..runtime import MiniwindSession
    caster = _Thing("Hedge Mage", (0, 0, 0), **_caster())
    enemy = _Thing("Brigand", (0, 0, 300), type="npc", health=40)
    s = MiniwindSession(_Logic([caster, enemy]), cfg={})
    assert s.npc_magic.try_ward(caster)
    assert npc_magic.warded(caster.properties) is not None
    fired = []
    s.npc_magic._loose = lambda thing, target, *_a: fired.append(target)
    s.archery._target_pos = lambda target: list(target.pos)
    assert s.npc_magic.cast_attack(caster, enemy)
    assert fired == [enemy]


def test_raised_followers_keep_their_spells_in_hand():
    from ..runtime import MiniwindSession
    raised = _Thing("Risen Cultist", (0, 0, 0), **_caster(dead=True))
    s = MiniwindSession(_Logic([raised]), cfg={})
    s._bind_raised(raised.properties)
    assert npc_magic.hands(raised.properties)["main"] == "firebolt"
