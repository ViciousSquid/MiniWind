"""Companions cast through the real RPG session and give party members room."""

from types import SimpleNamespace

import glm
import pytest

pytest.importorskip("PyQt5")

from game import fio
from game.entities import NPC
from game.multiplayer.bots import PartyBots, distance
from game.multiplayer.model import InputFrame
from game.rpg import equipment, magic
from game.tests.test_multiplayer_bots import companions, think_until
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401


def enemy_near(coop, bot, offset=350, **extra):
    actor = NPC(pos=[bot.physics.pos.x + offset, bot.physics.pos.y + 64,
                     bot.physics.pos.z], properties={
        "id": "companion-defense-target", "name": "Attacker",
        "aggression": "hostile", "team": "bandits", "faction": "bandits",
        "triggered": True, "health": 500, "max_health": 500, **extra,
    })
    fio.things(coop.logic).append(actor)
    fio.rebuild_entity_caches(coop.logic)
    coop.root._rebuild_type_index(fio.things(coop.logic))
    return actor


def setup_mage(coop, monkeypatch):
    human, bot, *others = companions(coop)
    for i, member in enumerate((human, *others)):
        member.physics.pos = bot.physics.pos + glm.vec3(-300, 0, 200 * i)
        coop._sync_actor(member)
    bot.session.nav = None
    c = bot.session.game.character
    c.class_id = "mage"
    c.known_spells = ["flare", "heal_minor", "sp_shield"]
    c.magicka = c.max_magicka = 200
    c.health = c.max_health
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (True, {}))
    return human, bot, c


def test_companion_casts_ward_attack_and_healing_with_real_costs(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    _, bot, c = setup_mage(coop, monkeypatch)
    enemy = enemy_near(coop, bot)
    brain = PartyBots(coop)
    mana = c.magicka
    think_until(brain, lambda: c.effect_magnitude("shield") > 0)
    assert c.effect_magnitude("shield") > 0
    assert c.magicka == pytest.approx(mana - magic.cast_cost(c, magic.for_caster(c, "sp_shield")))
    assert bot.session._cast_cooldown > 0
    assert bot.bot_target is enemy

    # The existing ward is not cast again; the next cast fires a real bolt.
    bot.session._cast_cooldown = 0
    before = len(coop.logic.combat_runtime._monster_projectiles)
    brain.clock += 1
    think_until(brain, lambda: len(coop.logic.combat_runtime._monster_projectiles) > before)
    assert c.active_spell == "flare"
    assert equipment.spell_equipped(c, "flare")
    assert len(coop.logic.combat_runtime._monster_projectiles) == before + 1
    assert c.spell_practice["flare"] == 1
    assert c.magicka < mana
    # A cooldown cannot be bypassed by another think tick.
    after = c.magicka
    brain.clock += 0.2
    brain.tick(0.016)
    assert c.spell_practice["flare"] == 1
    assert c.magicka == after

    enemy.properties["dead"] = True
    bot.session._cast_cooldown = 0
    c.health = 10
    brain.clock += 1
    think_until(brain, lambda: c.health > 10)
    assert c.health > 10
    assert c.spell_practice["heal_minor"] == 1
    # No resources means no spell request; a warrior never casts either.
    c.magicka = 0
    bot.session._cast_cooldown = 0
    assert brain._spells(bot) == []
    c.magicka = 200
    c.class_id = "warrior"
    assert brain._spells(bot) == []


def test_spell_attacks_respect_walls_and_bystanders(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    _, bot, c = setup_mage(coop, monkeypatch)
    c.known_spells = ["flare"]
    enemy = enemy_near(coop, bot)
    brain = PartyBots(coop)
    bot.session.nav = SimpleNamespace(
        line_clear=lambda *a: False,
        steer_actor=lambda actor, start, goal: goal,
    )
    _, actions = brain.decide(bot, 0)
    assert not any(a in ("attack", "cast_at") for a, _ in actions)
    bot.session.nav = None
    bystander = enemy_near(coop, bot, 150, aggression="passive", team="villagers")
    bystander.properties["id"] = "companion-defense-bystander"
    _, actions = brain.decide(bot, 0)
    assert not any(a in ("attack", "cast_at") for a, _ in actions)
    assert c.magicka == 200


def test_actual_assaults_trigger_defense_and_distant_bots_defend_themselves(coop_game):
    coop = coop_game.logic.game_session.coop
    human, bot, *others = companions(coop)
    for i, member in enumerate((human, *others)):
        member.physics.pos = bot.physics.pos + glm.vec3(-1300, 0, 200 * i)
    bot.returning = True
    enemy = enemy_near(coop, bot, 85, aggression="defensive", team="villagers")
    brain = coop._bots = PartyBots(coop)
    assert brain._threat(bot, human) is None
    coop.damage(bot.player_id, 2, source=enemy)
    assert brain._threat(bot, human) is enemy
    think_until(brain, lambda: enemy.properties["health"] < 500)
    assert bot.bot_target is enemy and bot.task == "Defending the party"
    assert enemy.properties["health"] < 500
    assert bot.returning
    enemy.properties["dead"] = True
    assert brain._threat(bot, human) is None
    enemy.properties["dead"] = False
    # End its retaliation too: an ongoing fight remains a current threat.
    enemy.properties["aggression"] = "defensive"
    enemy.properties.pop("_aggro_target", None)
    brain.clock += 9
    assert brain._threat(bot, human) is None

    # A different conscious human is protected too, without relying on P1.
    human.physics.pos = bot.physics.pos + glm.vec3(-250, 0, 0)
    coop.damage(human.player_id, 2, source=enemy)
    assert brain._threat(bot, human) is enemy
    assert not human.session._attackable(bot.actor)
    enemy.properties["hidden"] = True
    assert brain._threat(bot, human) is None


def test_companions_step_out_of_overlap_and_settle_clear_of_player(coop_game):
    coop = coop_game.logic.game_session.coop
    human, *bots = companions(coop)
    for bot in bots:
        bot.physics.pos = glm.vec3(human.physics.pos)
    brain = coop._bots = PartyBots(coop)
    for bot in bots:
        frame, _ = brain.decide(bot, bots.index(bot))
        assert abs(frame.move_x) + abs(frame.move_z) > 0
    coop_game.step(240)
    for bot in bots:
        assert 150 < distance(bot.physics.pos, human.physics.pos) < 310
    assert all(distance(a.physics.pos, b.physics.pos) > 75
               for i, a in enumerate(bots) for b in bots[i + 1:])

    # A player walking into an idle companion makes it give way again.
    bot = bots[0]
    human.physics.pos = bot.physics.pos + glm.vec3(20, 0, 0)
    frame, _ = brain.decide(bot, 0)
    assert frame.move_x < 0
    assert human.frame == InputFrame()
