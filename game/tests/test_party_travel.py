"""Raised followers travel with the player from map to map, as themselves."""

from game import fio, party
from game.rpg import equipment as eq
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic, _Thing
from .test_resurrection_follower import _armed_bandit


def _enter(store, map_key, things):
    session = MiniwindSession(_Logic(list(things)), cfg={}, globals_store=store)
    session.game.character = Character.create("Caster", "imperial", "necromancer")
    session.needs_char_creation = False
    session.open_screen = None
    eq.equip_spell(session.game.character, "resurrection", "main")
    session.memory.load(map_key)
    session.memory.apply()
    party.arrive(session)
    return session


def _leave(session):
    session.leave_map()
    session.memory.save()


def _actors(session):
    return [t for t in fio.things(session.logic)
            if str(t.properties.get("type")) in ("npc", "creature")]


def _villager():
    return _Thing("Mira", (900, 0, 900), type="npc", id="mira-1", npc_role="villager")


def test_a_raised_follower_goes_to_the_next_map_and_back_as_itself():
    from .test_sim import _FakeGlobals
    store = _FakeGlobals()
    a = _enter(store, "mapA", [_armed_bandit()])
    bandit = a.logic.things[0]
    bandit.properties.update(dead=True, health=0)
    assert a.do_cast(target=bandit, hand="main")
    spells = [e["id"] for e in bandit.properties["spells"]]
    pack = sorted(s["id"] for s in bandit.properties["inventory"])
    _leave(a)
    # Into the next map: it arrives beside the player, the same actor.
    b = _enter(store, "mapB", [_villager()])
    follower = next(t for t in _actors(b) if t.properties["id"] == "bandit-1")
    p = follower.properties
    assert p["follow_player"] and p["team"] == "player" and p["resurrection_used"]
    assert p["sprite_tint"] == [1.0, .30, .30] and not p.get("dead")
    assert [e["id"] for e in p["spells"]] == spells
    assert sorted(s["id"] for s in p["inventory"]) == pack
    ppos = fio.player(b.logic).pos
    assert abs(follower.pos[0] - ppos[0]) + abs(follower.pos[2] - ppos[2]) < 400
    _leave(b)
    # Home again: not standing there twice, and still following.
    a = _enter(store, "mapA", [_armed_bandit()])
    bandits = [t for t in _actors(a) if t.properties["id"] == "bandit-1"]
    assert len(bandits) == 1 and bandits[0].properties["follow_player"]
    # The map it was left behind in does not keep a copy of it either.
    _leave(a)
    b = _enter(store, "mapB", [_villager()])
    assert len([t for t in _actors(b) if t.properties["id"] == "bandit-1"]) == 1


def test_a_follower_already_in_the_map_from_a_saved_game_is_not_doubled():
    from .test_sim import _FakeGlobals
    store = _FakeGlobals()
    a = _enter(store, "mapA", [_armed_bandit()])
    bandit = a.logic.things[0]
    bandit.properties.update(dead=True, health=0)
    assert a.do_cast(target=bandit, hand="main")
    _leave(a)
    b = _enter(store, "mapB", [])
    saved = next(t for t in _actors(b) if t.properties["id"] == "bandit-1")
    again = _Thing("Brigand", tuple(saved.pos), **{k: v for k, v in saved.properties.items()
                                                  if k != "name"})
    b = _enter(store, "mapB", [again])
    assert len([t for t in _actors(b) if t.properties["id"] == "bandit-1"]) == 1


def test_a_follower_dead_when_the_player_leaves_stays_behind():
    from .test_sim import _FakeGlobals
    store = _FakeGlobals()
    a = _enter(store, "mapA", [_armed_bandit()])
    bandit = a.logic.things[0]
    bandit.properties.update(dead=True, health=0)
    assert a.do_cast(target=bandit, hand="main")
    bandit.properties.update(dead=True, health=0)
    _leave(a)
    assert party.members(a) == []
    b = _enter(store, "mapB", [])
    assert not [t for t in _actors(b) if t.properties["id"] == "bandit-1"]


def test_spawned_actors_keep_the_same_uuid_every_time_their_map_is_entered():
    def spawned():
        spawner = _Thing("Den", (0, 0, 0), type="creaturespawn", id="den-1",
                         creature_role="wolf", count=3, spawn_radius=50.0)
        s = MiniwindSession(_Logic([spawner]), cfg={})
        s.spawn_creature_points()
        return [t.properties["id"] for t in _actors(s)]
    first = spawned()
    assert len(first) == len(set(first)) == 3
    assert spawned() == first
