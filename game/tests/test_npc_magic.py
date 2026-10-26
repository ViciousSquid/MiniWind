"""NPC casters fight with their spells, and every fighter uses its best weapon.

* At range a caster looses its attack spell as a real bolt and pays magicka;
  up close, or out of magicka, it switches to its blade (or bow).
* Badly hurt, a caster that knows a healing spell heals itself first.
* Of two weapons of a kind, the harder-hitting one is used.
* A caster with no blade is given a dagger for when the enemy closes.
"""

import random
from types import SimpleNamespace

import pytest

from .. import combat_loadout as cl
from .. import combat_styles, npc_magic
from ..held_weapons import arm_fighters
from ..npc_archery import MELEE_BAND, NpcArchery
from ..rpg import items

combat_styles.register()

FAR = MELEE_BAND * 3
NEAR = MELEE_BAND * 0.5


class _Actor:
    def __init__(self, **props):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = props


def _cultist(**extra):
    props = {"type": "creature", "npc_role": "cultist", "combatant": True,
             "attack_style": "magic", "equipped_weapon": "apprentice_staff",
             "spells": [{"id": "flare", "damage": 12, "speed": 900.0}],
             "inventory": [{"id": "iron_dagger", "qty": 1}],
             "health": 50, "max_health": 50, "creature_level": 1}
    props.update(extra)
    return _Actor(**props)


class _Combat:
    def __init__(self):
        self.shots = []

    def spawn_projectile(self, pos, vel, **kwargs):
        self.shots.append((pos, vel, kwargs))
        return len(self.shots) - 1


class _Session(SimpleNamespace):
    """A session stand-in (a subclass, so the magic clock can refer to it weakly)."""


def _session():
    combat = _Combat()
    logic = SimpleNamespace(combat_runtime=combat, monster_ai=None,
                            player_runtime=SimpleNamespace(player=None))
    session = _Session(logic=logic, rng=random.Random(1), _archery_clock=0.0,
                       _player_pos=lambda: [FAR, 0.0, 0.0])
    session.archery = NpcArchery(session)
    session.npc_magic = npc_magic.NpcMagic(session)
    return session, combat


def _shot(session, actor, distance):
    session._player_pos = lambda: [distance, 0.0, 0.0]
    return session.archery.shot_hook(actor, [distance, 0.0, 0.0], None, distance ** 2)


# ------------------------------------------------------------ casting

def test_a_caster_at_range_looses_its_spell_as_a_bolt_and_pays_magicka():
    session, combat = _session()
    cultist = _cultist()
    before = npc_magic.magicka(cultist.properties)

    assert _shot(session, cultist, FAR) is True

    (start, vel, kwargs), = combat.shots
    assert kwargs["damage"] == 12
    assert kwargs["owner_id"] == id(cultist)
    assert vel[0] == pytest.approx(900.0, rel=0.05)      # toward the player
    assert npc_magic.magicka(cultist.properties) == pytest.approx(before - 12)


def test_up_close_a_caster_draws_its_dagger_instead():
    session, combat = _session()
    cultist = _cultist()

    # False leaves the blow to the engine: a melee strike, not a spell.
    assert _shot(session, cultist, NEAR) is False
    assert combat.shots == []
    assert cultist.properties["_active_weapon"] == "iron_dagger"


def test_out_of_magicka_a_caster_closes_with_its_blade_until_it_refills():
    session, combat = _session()
    cultist = _cultist(max_magicka=20)
    assert _shot(session, cultist, FAR) is True
    assert len(combat.shots) == 1
    # 8 magicka left, Flare costs 12: magic is no longer a way to fight.
    assert cl.choose_style(cl.build_loadout(cultist.properties), False) == cl.MELEE
    assert _shot(session, cultist, FAR) is True            # closes in
    assert len(combat.shots) == 1
    assert cultist.properties["_active_weapon"] == "iron_dagger"

    session._archery_clock += 4.0 / npc_magic.MAGICKA_REGEN + 0.1
    assert cl.choose_style(cl.build_loadout(cultist.properties), False) == cl.MAGIC
    assert _shot(session, cultist, FAR) is True
    assert len(combat.shots) == 2


def test_out_of_magicka_a_caster_with_a_bow_shoots_instead():
    session, _combat = _session()
    caster = _cultist(max_magicka=0, inventory=[{"id": "hunting_bow", "qty": 1}])
    assert cl.choose_style(cl.build_loadout(caster.properties), False) == cl.BOW


def test_a_staff_alone_casts_its_bound_spell():
    session, combat = _session()
    adept = _cultist(spells=[], inventory=[])
    assert _shot(session, adept, FAR) is True
    assert combat.shots[0][2]["damage"] == 14              # the staff's Flare


def test_the_strongest_affordable_spell_is_cast():
    found = npc_magic.attacks(_cultist(spells=[{"id": "flare"}, {"id": "firebolt"}]).properties)
    assert [f[0].id for f in found][:2] == ["firebolt", "flare"]


def test_healing_spells_alone_are_not_a_way_to_fight():
    healer = {"attack_style": "melee", "equipped_weapon": "iron_mace",
              "spells": [{"id": "heal_minor"}]}
    assert cl.MAGIC not in cl.build_loadout(healer)


def test_a_badly_hurt_caster_heals_itself_before_fighting_on():
    session, combat = _session()
    cultist = _cultist(health=10, spells=[{"id": "flare"}, {"id": "heal_minor"}])

    assert _shot(session, cultist, FAR) is True
    assert cultist.properties["health"] == 40             # Minor Healing: +30
    assert combat.shots == []
    # Healthy enough now: the next shot is a spell.
    assert _shot(session, cultist, FAR) is True
    assert len(combat.shots) == 1


# ------------------------------------------------------------ weapons

def test_the_harder_hitting_of_two_blades_is_used_whichever_is_equipped():
    props = {"attack_style": "melee", "equipped_weapon": "iron_dagger",
             "inventory": [{"id": "steel_longsword", "qty": 1}, {"id": "club", "qty": 1}]}
    assert cl.weapon_for(cl.build_loadout(props), cl.MELEE) == "steel_longsword"


def test_the_better_bow_is_used_at_range():
    props = {"attack_style": "melee", "equipped_weapon": "iron_shortsword",
             "inventory": ["short_bow", "long_bow"]}
    loadout = cl.build_loadout(props)
    assert cl.choose_style(loadout, False) == cl.BOW
    assert cl.weapon_for(loadout, cl.BOW) == "long_bow"
    assert cl.choose_style(loadout, True) == cl.MELEE


def test_a_spell_caster_holding_a_sword_does_not_cast_with_the_sword():
    skeleton = {"attack_style": "magic", "equipped_weapon": "iron_shortsword",
                "spells": [{"id": "frostbite"}]}
    loadout = cl.build_loadout(skeleton)
    assert cl.weapon_for(loadout, cl.MAGIC) == ""
    assert cl.weapon_for(loadout, cl.MELEE) == "iron_shortsword"
    assert cl.choose_style(loadout, False) == cl.MAGIC
    assert cl.choose_style(loadout, True) == cl.MELEE


def test_weapon_rating_is_damage_over_time():
    assert combat_styles.weapon_rating("iron_dagger") == pytest.approx(6 * 1.4)
    assert combat_styles.weapon_rating("bread") == 0.0


# ------------------------------------------------------------ arming

def _make_stack(item_id):
    return items.make(item_id, 1)


def test_a_caster_without_a_blade_is_given_a_dagger_once():
    cultist = _cultist(inventory=[])
    arm_fighters([cultist], random.Random(3), _make_stack)
    carried = [s["id"] for s in cultist.properties["inventory"]]
    assert carried == ["iron_dagger"]
    arm_fighters([cultist], random.Random(3), _make_stack)
    assert [s["id"] for s in cultist.properties["inventory"]] == carried


@pytest.mark.parametrize("props", [
    {"npc_role": "monster"},                                   # not a person
    {"inventory": [{"id": "iron_mace", "qty": 1}]},            # has a blade
    {"spells": [], "equipped_weapon": ""},                      # casts nothing
    {"combatant": False},
])
def test_only_bladeless_fighting_casters_who_are_people_get_one(props):
    actor = _cultist(**{"inventory": [], **props})
    before = [s["id"] for s in actor.properties["inventory"]]
    arm_fighters([actor], random.Random(3), _make_stack)
    assert [s["id"] for s in actor.properties["inventory"]] == before
