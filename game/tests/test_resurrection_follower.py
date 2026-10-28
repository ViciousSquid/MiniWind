"""Resurrection grants one second life and a permanent, saved follower mark."""

from types import SimpleNamespace

import pytest

from engine.spatial import (PARKED_DISABLED_KEY, PARKED_HIDDEN_KEY,
                            TIER_DISTANT, TIER_DORMANT, TIER_NEAR)
from game import fio
from game.rpg import equipment as eq, magic
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic, _Thing


def _raised(actor_type="npc"):
    corpse = _Thing("Fallen", (0, 0, 100), type=actor_type, npc_role="bandit",
                    faction="bandits", team="bandits", aggression="hostile",
                    dead=True, health=0, max_health=40)
    return _raise_actor(corpse)


def _raise_actor(corpse):
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


@pytest.mark.parametrize("actor_type", ["npc", "creature", "monster"])
def test_second_death_ends_following_and_body_can_never_be_raised_again(actor_type):
    session, raised = _raised(actor_type)
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


@pytest.mark.parametrize("actor_type", ["npc", "creature", "monster"])
@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("tier", [TIER_NEAR, TIER_DISTANT])
def test_raised_actors_walk_once_per_tick_toward_the_caster(actor_type, indexed,
                                                          tier, monkeypatch):
    """A follow flag must produce motion in both small and indexed worlds."""
    session, raised = _raised(actor_type)
    if indexed:
        from game import runtime
        session.logic.world_runtime = SimpleNamespace(monster_things=[raised])
        monkeypatch.setattr(runtime, "WORLD_INDEX_MIN_ACTORS", 1)
    raised.properties["move_speed"] = 120.0
    raised.properties["_sim_tier"] = tier
    fio.player(session.logic).pos = [1000., 0., 100.]
    for _ in range(5):
        session.tick(0.1)
    assert raised.properties["sched_state"] == "FOLLOW"
    assert raised.pos[0] == pytest.approx(60.0)
    assert raised.pos[2] == pytest.approx(100.0)


@pytest.mark.parametrize("actor_type", ["npc", "creature", "monster"])
@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("marker", [PARKED_HIDDEN_KEY, PARKED_DISABLED_KEY])
def test_parked_raised_actors_stay_stationary(actor_type, indexed, marker,
                                             monkeypatch):
    """A parking marker's presence matters even when its saved value is False."""
    session, raised = _raised(actor_type)
    if indexed:
        from game import runtime
        session.logic.world_runtime = SimpleNamespace(monster_things=[raised])
        monkeypatch.setattr(runtime, "WORLD_INDEX_MIN_ACTORS", 1)
    raised.properties.update(hidden=True, disabled=True, _sim_tier=TIER_DORMANT)
    raised.properties[marker] = False
    fio.player(session.logic).pos = [1000., 0., 100.]
    original_pos = list(raised.pos)
    for _ in range(5):
        session.tick(0.1)
    assert raised.pos == original_pos


@pytest.mark.parametrize("role", ["bandit", "wolf"])
def test_a_raised_creature_walks_in_the_normal_session_tick(role):
    """Humanoid creatures follow too, and roaming beasts stop wandering."""
    from game.entities import Creature
    corpse = Creature(pos=[0., 0., 100.], properties={
        "name": "Fallen", "npc_role": role, "dead": True,
        "health": 0, "max_health": 40, "move_speed": 120.0})
    corpse.properties["_roam_dest"] = [0., 1000.]
    session, raised = _raise_actor(corpse)
    assert raised.properties["type"] == "creature"
    fio.player(session.logic).pos = [1000., 0., 100.]
    session.tick(0.1)
    assert raised.properties["sched_state"] == "FOLLOW"
    assert raised.pos[0] == pytest.approx(12.0)
    assert raised.pos[2] == pytest.approx(100.0)


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
