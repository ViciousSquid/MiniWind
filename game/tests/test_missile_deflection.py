"""Luck ricochets preserve real projectiles, impacts and player-only dice."""

import random
from types import SimpleNamespace

import glm
import numpy as np
import pytest

from engine.logic_combat import ProjectileStore
from editor.things import Monster
from game.missile_deflection import deflect
from game.rpg import blocking, equipment, magic
from game.diceroll import DiceRoller
from game.tests.test_shield_blocks import Faces, fighter
from game.tests.test_multiplayer_bots import companions
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401
from tests.helpers.worlds import make_thing
from tests.monster_ai.test_projectile_batch import _logic


@pytest.mark.parametrize("luck,target,wins", [(59, None, 0), (60, 40, 1),
    (68, 39, 3), (76, 38, 6), (84, 37, 10), (92, 36, 15), (100, 35, 21)])
def test_luck_deflection_is_rare_and_scales_on_real_d20s(luck, target, wins):
    assert blocking.deflection_target(luck) == target
    assert sum(1 for a in range(1, 21) for b in range(1, 21)
               if target is not None and a + b >= target) == wins
    assert blocking.deflection_chance(luck) == wins / 400


@pytest.mark.parametrize("dense", [False, True])
@pytest.mark.parametrize("spell", [None, "flare"])
def test_npc_missile_ricochets_without_impact_then_can_hit_the_shooter(dense, spell):
    shooter = make_thing(Monster, "Shooter", (0, 0, 200), team="red")
    defender = make_thing(Monster, "Lucky guard", (0, 0, 0), team="blue")
    defender.properties.update(luck=100, offhand_weapon="iron_shield",
                               _shield_blocking=True, _facing=0)
    logic = _logic([shooter, defender], [])
    combat = logic.combat_runtime
    combat.PROJECTILE_DENSE_THRESHOLD = 0 if dense else 100
    impacts, burns, rolls = [], [], []
    game = fighter()
    game.dice = DiceRoller(rng=Faces(20, 20))
    game.dice.add_roll_listener(lambda result, source, context: rolls.append((result, context)))
    session = SimpleNamespace(logic=logic, game=game,
                               burning=SimpleNamespace(landed=lambda *a, **kw: burns.append(a)))
    combat.projectile_deflector = lambda store, row, target: deflect(session, store, row, target)
    metadata = ({"damage_kind": "fire", "spell": magic.get(spell)} if spell else None)
    combat.spawn_projectile(
        (0, 64, 25), (0, 0, -100), owner_id=id(shooter), damage=10, lifetime=5,
        max_dist=1000, on_impact=lambda *args: impacts.append(args), metadata=metadata,
    )
    store = combat._monster_projectiles
    original_tag = int(store.tag[0])
    health = defender.properties.get("health", 100)
    combat._update_monster_projectiles(0)
    assert defender.properties.get("health", 100) == health
    assert len(store) == 1 and int(store.tag[0]) == original_tag
    assert store.owner_id[0] == id(defender)
    np.testing.assert_allclose(store.vel[0], (0, 0, 100))
    assert store.lifetime[0] == 5 and store.distance[0] == 0
    assert not impacts and not burns
    assert rolls[0][0]["success"] and rolls[0][1]["quiet"] and rolls[0][1]["npc"]

    combat._update_monster_projectiles(1)
    assert shooter.properties["health"] == 90
    assert not store and not store.hooks and not store.metadata
    assert len(burns if spell else impacts) == 1


@pytest.mark.parametrize("dense", [False, True])
def test_solo_player_can_deflect_a_spell_before_damage_and_fire_effects(dense):
    shooter = make_thing(Monster, "Mage", (0, 0, 300), team="red")
    logic = _logic([shooter], [])
    player = SimpleNamespace(pos=glm.vec3(0, 64, 0), angle=0.0)
    logic.player_runtime.player = player
    game = fighter()
    game.character.attrs["luck"] = 100
    game.dice = DiceRoller(rng=Faces(20, 20))
    received, impacts = [], []
    logic.trigger_runtime._apply_player_damage = lambda *a, **kw: received.append((a, kw))
    session = SimpleNamespace(
        game=game, logic=logic, _blocking=True, add_floater=lambda *a, **kw: None,
        player_actor=SimpleNamespace(pos=player.pos, properties={"is_player": True}),
        burning=SimpleNamespace(landed=lambda *a, **kw: impacts.append(a)),
    )
    combat = logic.combat_runtime
    combat.PROJECTILE_DENSE_THRESHOLD = 0 if dense else 100
    combat.projectile_deflector = lambda store, row, target: deflect(session, store, row, target)
    combat.spawn_projectile((0, 64, 20), (0, 0, -100), owner_id=id(shooter), damage=30,
                            lifetime=3, on_impact=lambda *a: impacts.append(a),
                            metadata={"damage_kind": "fire", "spell": magic.get("flare")})
    combat._update_monster_projectiles(0)
    assert not received and not impacts
    assert len(combat._monster_projectiles) == 1
    assert combat._monster_projectiles.owner_id[0] == 0
    assert combat._monster_projectiles.vel[0, 2] > 0


@pytest.mark.parametrize("luck,blocking_now,facing,rolls", [
    (40, True, 0, ()), (100, False, 0, ()), (100, True, 3.14159265, ()),
    (100, True, 0, (1, 1)),
])
def test_ineligible_or_failed_deflection_leaves_the_missile_unchanged(luck, blocking_now, facing, rolls):
    logic = SimpleNamespace(player_runtime=SimpleNamespace(
        player=SimpleNamespace(pos=[0, 0, 0], angle=facing)))
    game = fighter()
    game.character.attrs["luck"] = luck
    game.dice = DiceRoller(rng=Faces(*rolls))
    session = SimpleNamespace(game=game, logic=logic, _blocking=blocking_now,
                               player_actor=SimpleNamespace(properties={}))
    store = ProjectileStore()
    store.add((0, 0, 20), (0, 0, -100), 123, 10, 3)
    assert not deflect(session, store, 0, None)
    np.testing.assert_allclose(store.vel[0], (0, 0, -100))
    assert store.owner_id[0] == 123 and store.tag[0] == 0


def test_companion_ricochet_uses_its_luck_and_only_the_rolling_log(coop_game):
    from game import fio
    from game.entities import NPC

    coop = coop_game.logic.game_session.coop
    human, bot, *others = companions(coop)
    for member in (human, *others):
        member.actor.properties["hidden"] = True
    c = bot.session.game.character
    c.attrs["luck"] = 100
    bot.session.game.dice.rng = Faces(20, 20)
    bot.session.toggle_block(True)
    bot.physics.angle = 0
    coop._sync_actor(bot)
    shooter = NPC(pos=[bot.actor.pos[0], bot.actor.pos[1], bot.actor.pos[2] + 300],
                  properties={"name": "Enemy mage", "team": "bandits", "health": 100})
    fio.things(coop.logic).append(shooter)
    fio.rebuild_entity_caches(coop.logic)
    before = c.health
    combat = coop.logic.combat_runtime
    combat.spawn_projectile(
        (bot.actor.pos[0], bot.actor.pos[1] + 64, bot.actor.pos[2] + 20), (0, 0, -100),
        owner_id=id(shooter), damage=30, lifetime=3,
        metadata={"damage_kind": "fire", "spell": magic.get("flare")},
    )
    combat._update_monster_projectiles(0)
    assert c.health == before and not coop.root.burning.burning(bot.actor)
    assert len(combat._monster_projectiles) == 1 and combat._monster_projectiles.vel[0, 2] > 0
    assert bot.session.dice_animation is None
    assert "lucky shield deflection" in human.session.roll_log[-1]["text"]


def test_player_arrow_has_a_real_damage_payload_even_after_its_last_ammo(coop_game):
    coop = coop_game.logic.game_session.coop
    human = coop.local_players[0]
    game = human.session.game
    c = game.character
    equipment.equip(c, "short_bow")
    for stack in c.inventory:
        if stack["id"] == "iron_arrow":
            stack["qty"] = 1
    assert game.fire_arrow()
    human.session._spawn_player_arrow_projectile()
    store = coop.logic.combat_runtime._monster_projectiles
    assert len(store) == 1 and store.damage[0] > 0


def test_failed_luck_save_allows_spell_damage_and_burning_without_a_physical_block(coop_game, monkeypatch):
    from game import fio
    from game.burning import PLAYER
    from game.entities import NPC

    coop = coop_game.logic.game_session.coop
    session = coop.root
    c = session.game.character
    c.attrs["luck"] = 100
    session.game.dice.rng = Faces(1, 1)
    session.toggle_block(True)
    player = fio.player(coop.logic)
    player.angle = 0
    shooter = NPC(pos=[player.pos.x, player.pos.y, player.pos.z + 300],
                  properties={"name": "Caster", "team": "bandits", "health": 100})
    fio.things(coop.logic).append(shooter)
    fio.rebuild_entity_caches(coop.logic)
    spell = magic.get("flare")
    before = c.health
    combat = coop.logic.combat_runtime
    combat.spawn_projectile(
        (player.pos.x, player.pos.y, player.pos.z + 20), (0, 0, -100),
        owner_id=id(shooter), damage=10, lifetime=3,
        metadata={"damage_kind": "fire", "spell": spell},
        on_impact=lambda pos, target: session.burning.landed(spell, pos, target, by=shooter),
    )
    with monkeypatch.context() as patch:
        patch.setattr(session, "coop", None)
        combat._update_monster_projectiles(0)
    assert c.health == before - 10
    assert session.burning.burning(PLAYER)
    assert session.game.dice.last_5_rolls[-1]["dice_notation"] == "2d20"
    assert not combat._monster_projectiles
