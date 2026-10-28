"""Resurrection grants one second life and a permanent, saved follower mark."""

from game import fio
from game.rpg import equipment as eq, magic
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic, _Thing


def _raised():
    corpse = _Thing("Fallen", (0, 0, 100), type="npc", npc_role="bandit",
                    faction="bandits", team="bandits", aggression="hostile",
                    dead=True, health=0, max_health=40)
    session = MiniwindSession(_Logic([corpse]), cfg={})
    session.game.character = Character.create("Caster", "imperial", "necromancer")
    session.needs_char_creation = False
    session.open_screen = None
    assert eq.equip_spell(session.game.character, "resurrection", "main")
    assert session.do_cast(target=corpse, hand="main")
    return session, corpse


def test_raised_npc_is_red_friendly_and_follows_the_caster():
    session, raised = _raised()
    p = raised.properties
    assert not p["dead"]
    assert p["health"] == p["max_health"] == 40
    assert p["resurrection_used"] and p["resurrected_by"] == "player"
    assert p["sprite_tint"] == [1.0, .30, .30]
    assert p["follow_player"] and p["combatant"]
    assert p["team"] == "player" and p["aggression"] == "defensive"
    fio.player(session.logic).pos = [1000., 0., 100.]
    session._decide(raised)
    assert p["sched_state"] == "FOLLOW"
    assert p["_dest"][0] > raised.pos[0]


def test_second_death_ends_following_and_body_can_never_be_raised_again():
    session, raised = _raised()
    raised.properties.update(dead=True, health=0)
    session._reap_dead()
    assert not raised.properties["follow_player"]
    assert raised.properties["resurrection_used"]
    assert raised.properties["sprite_tint"] == [1., .30, .30]
    session.clock.day += 1
    session.game.character.magicka = 100
    session._cast_cooldown = 0
    assert session._nearest_dead_actor(1000) is None
    assert not session.do_cast(target=raised, hand="main")
    assert raised.properties["dead"]
    assert session.game.character.magicka == 100


def test_resurrection_history_and_tint_are_in_saved_entity_properties():
    from engine.savegame import _thing_state
    session, raised = _raised()
    saved = _thing_state({"properties": dict(raised.properties)})["properties"]
    for key in ("resurrection_used", "resurrected_by", "sprite_tint", "follow_player"):
        assert saved[key] == raised.properties[key]
    # A restored corpse still carries its spent second life.
    raised.properties = dict(saved, dead=True, health=0)
    session.clock.day += 1
    session.game.character.magicka = 100
    assert not session._do_resurrect(magic.get("resurrection"), target=raised)


def test_raised_follower_defends_nearby_caster_and_breaks_off_distant_chases():
    from game.runtime import RAISED_DEFEND_RADIUS, RAISED_LEASH
    session, raised = _raised()
    raised.pos = [180., 0., 0.]
    enemy = _Thing("Enemy", (0., 0., 200.), type="npc", team="bandits",
                   faction="bandits", aggression="hostile", health=40)
    session.logic.things.append(enemy)
    session._actors = []
    session._guard_raised_follower(raised)
    assert raised.properties["_aggro_target"] == id(enemy)
    assert not raised.properties["triggered"]
    enemy.pos = [0., 0., RAISED_DEFEND_RADIUS + 100.]
    session._guard_raised_follower(raised)
    assert "_aggro_target" not in raised.properties
    assert raised.properties["triggered"]
    enemy.pos = [0., 0., 200.]
    raised.pos = [RAISED_LEASH + 100., 0., 0.]
    session._guard_raised_follower(raised)
    assert "_aggro_target" not in raised.properties
    assert raised.properties["_dest"][0] < raised.pos[0]


def test_follower_keeps_personal_space_and_ignores_far_player_targets():
    import math
    from game.runtime import RAISED_PERSONAL_SPACE
    session, raised = _raised()
    raised.pos = [0., 0., 0.]
    session._guard_raised_follower(raised)
    destination = raised.properties["_dest"]
    assert math.hypot(destination[0], destination[2]) > RAISED_PERSONAL_SPACE
    far = _Thing("Far Enemy", (2000., 0., 0.), type="npc", faction="bandits")
    session.logic.things.append(far)
    session._alert_followers(far)
    assert "_aggro_target" not in raised.properties


# ------------------------------------------- end to end, across a map change
def _bandit_from_the_map():
    """The bandit as the map file has it: alive, hostile, never raised."""
    return _Thing("Brigand", (0, 0, 100), type="npc", id="bandit-1", npc_role="bandit",
                  faction="bandits", team="bandits", aggression="hostile",
                  health=40, max_health=40, combatant=True)


def _enter(globals_store, thing):
    """Enter the map: a fresh session over *thing*, with what the map remembers."""
    from .test_sim import _FakeGlobals   # noqa: F401  (the store type)
    session = MiniwindSession(_Logic([thing]), cfg={}, globals_store=globals_store)
    session.game.character = Character.create("Caster", "imperial", "necromancer")
    session.needs_char_creation = False
    session.open_screen = None
    eq.equip_spell(session.game.character, "resurrection", "main")
    session.memory.load("testmap")
    session.memory.apply()
    return session


def test_a_raised_body_stays_raised_and_spent_across_leaving_the_map():
    from .test_sim import _FakeGlobals
    store = _FakeGlobals()
    # Killed, and the map notes the death.
    session = _enter(store, _bandit_from_the_map())
    bandit = session.logic.things[0]
    bandit.properties.update(dead=True, health=0)
    session.memory.update(10.0)
    # Raised: the map forgets the death and remembers the raising.
    assert session.do_cast(target=bandit, hand="main")
    assert "bandit-1" not in session.memory.record["dead"]
    session.memory.save()
    # Back in the map later: the follower is still the caster's.
    session = _enter(store, _bandit_from_the_map())
    p = session.logic.things[0].properties
    assert not p.get("dead") and p["follow_player"] and p["team"] == "player"
    assert p["resurrection_used"] and p["sprite_tint"] == [1.0, .30, .30]
    # Killed again; the map notes it, and it never comes back on its own.
    p.update(dead=True, health=0)
    session.memory.update(10.0)
    assert session.memory.record["dead"]["bandit-1"]["r"] is False
    session.memory.save()
    # Back once more: a spent corpse, which no necromancy raises.
    session = _enter(store, _bandit_from_the_map())
    corpse = session.logic.things[0]
    assert corpse.properties["dead"] and corpse.properties["resurrection_used"]
    assert not corpse.properties["follow_player"]
    session.clock.day += 1
    session.game.character.magicka = 100
    assert session._nearest_dead_actor(1000) is None
    assert not session.do_cast(target=corpse, hand="main")


def test_a_raised_lair_creature_is_not_reset_by_its_lair():
    from .test_sim import _FakeGlobals
    session = _enter(_FakeGlobals(), _Thing("Wolf", (0, 0, 100), type="creature", id="w1",
                                            npc_role="wolf", aggression="hostile",
                                            health=30, max_health=30))
    wolf = session.logic.things[0]
    wolf.properties["_respawns"] = True
    wolf.properties.update(dead=True, health=0)
    session.memory.update(10.0)
    assert session.do_cast(target=wolf, hand="main")
    assert wolf.properties["_respawns"] is False
    assert "w1" not in session.memory.record["dead"]


# ------------------------------------- what a raised body carries and knows
def _armed_bandit():
    from game.rpg import items
    return _Thing("Brigand", (0, 0, 100), type="npc", id="bandit-1", npc_role="bandit",
                  faction="bandits", team="bandits", aggression="hostile",
                  health=40, max_health=40, combatant=True,
                  equipped_weapon="iron_shortsword",
                  inventory=[items.make("iron_shortsword", 1),
                             items.make("potion_heal_minor", 3),
                             items.make("iron_dagger", 1)],
                  spells=[{"id": "firebolt"}, {"id": "sp_shield"}])


def _kill_and_loot(session, body, take=()):
    """The player kills *body* (its loot rolled onto it) and takes the stacks
    with ids in *take* from the corpse."""
    p = body.properties
    p.update(dead=True, health=0)
    session.game.stock_corpse(p)
    assert session.loot_corpse(body)
    for iid in take:
        i = next(n for n, s in enumerate(session.container_inventory()) if s["id"] == iid)
        assert session.take_from_container(i)
    session.close_container() if hasattr(session, "close_container") else None


def _ids(props):
    return sorted((s["id"], int(s.get("qty", 1))) for s in props["inventory"])


def test_a_raised_body_has_its_living_pack_less_what_was_looted():
    from .test_sim import _FakeGlobals
    session = _enter(_FakeGlobals(), _armed_bandit())
    bandit = session.logic.things[0]
    p = bandit.properties
    _kill_and_loot(session, bandit, take=("iron_shortsword", "potion_heal_minor"))
    assert session.do_cast(target=bandit, hand="main")
    # The loot table's potions were never its own; the looted ones are gone.
    assert _ids(p) == [("iron_dagger", 1)]
    assert "living_inventory" not in p
    # The sword it fought with was taken: its hand is empty now.
    assert "equipped_weapon" not in p and "_active_weapon" not in p
    # Its spells came back with it, readied in the hands the sword left free.
    assert [e["id"] for e in p["spells"]] == ["firebolt", "sp_shield"]
    from game import npc_magic
    assert npc_magic.hands(p) == {"main": "firebolt", "off": "sp_shield"}


def test_an_unlooted_raised_body_keeps_everything_it_carried_and_its_weapon():
    from .test_sim import _FakeGlobals
    session = _enter(_FakeGlobals(), _armed_bandit())
    bandit = session.logic.things[0]
    p = bandit.properties
    _kill_and_loot(session, bandit)
    assert session.do_cast(target=bandit, hand="main")
    assert _ids(p) == [("iron_dagger", 1), ("iron_shortsword", 1), ("potion_heal_minor", 3)]
    assert p["equipped_weapon"] == "iron_shortsword"


def test_a_looted_corpse_and_its_raised_body_keep_their_packs_across_the_map():
    from .test_sim import _FakeGlobals
    store = _FakeGlobals()
    session = _enter(store, _armed_bandit())
    bandit = session.logic.things[0]
    _kill_and_loot(session, bandit, take=("iron_dagger",))
    left = _ids(bandit.properties)
    session.memory.update(10.0)
    session.memory.save()
    # Back later: the corpse is not restocked from the map file.
    session = _enter(store, _armed_bandit())
    corpse = session.logic.things[0]
    assert corpse.properties["dead"]
    assert _ids(corpse.properties) == left
    # Raised there, it has its living pack less the dagger ...
    assert session.do_cast(target=corpse, hand="main")
    assert _ids(corpse.properties) == [("iron_shortsword", 1), ("potion_heal_minor", 3)]
    corpse.properties["inventory"].pop()   # (it drinks its potions, say)
    session.memory.save()
    # ... and it still has that, and its spells, the next time.
    session = _enter(store, _armed_bandit())
    p = session.logic.things[0].properties
    assert not p.get("dead") and p["follow_player"]
    assert _ids(p) == [("iron_shortsword", 1)]
    assert p["equipped_weapon"] == "iron_shortsword"
    assert [e["id"] for e in p["spells"]] == ["firebolt", "sp_shield"]
