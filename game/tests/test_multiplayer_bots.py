"""Bot parties use real character contexts, physics, quests and persistence."""

from types import SimpleNamespace

from game.multiplayer.bots import PartyBots, distance
from game.multiplayer.model import InputFrame
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401 - shared runtime fixture


def companions(coop):
    players = list(coop.players.values())
    for player in players[1:]:
        player.bot = True
        player.profile["device"] = "bot:" + player.player_id
        member = coop.lobby.lobby.member(player.player_id)
        member.bot, member.ready = True, True
        member.profile = dict(player.profile)
    coop.lobby.state = coop.lobby.lobby.snapshot()
    for actor in coop.root._actors:
        if not actor.properties.get("multiplayer_player"):
            actor.properties["disabled"] = True
    return players


def test_three_bots_follow_without_consuming_human_input(coop_game):
    import glm

    coop = coop_game.logic.game_session.coop
    human, *bots = companions(coop)
    for index, bot in enumerate(bots):
        bot.physics.pos = human.physics.pos + glm.vec3(300, 0, index * 25)
    before = distance(human.physics.pos, bots[0].physics.pos)
    coop_game.step(25)
    assert distance(human.physics.pos, bots[0].physics.pos) < before
    assert coop.local_players == [human]
    assert all(bot.task.startswith("Following") for bot in bots)
    # A stale controller packet must never take control of a bot.
    expected = bots[0].frame
    coop.local_input(bots[0].player_id, InputFrame(-1, 0))
    coop._drain_inputs()
    assert bots[0].frame == expected


def test_bot_defends_party_with_own_weapon_and_ignores_innocent_npcs(coop_game):
    import glm
    from game import fio
    from game.entities import NPC

    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    bot.physics.pos = human.physics.pos + glm.vec3(80, 0, 0)
    enemy = NPC(
        pos=[bot.physics.pos.x + 85, bot.physics.pos.y + 64, bot.physics.pos.z],
        properties={
            "id": "bot-target",
            "name": "Raider",
            "aggression": "hostile",
            "team": "bandits",
            "faction": "bandits",
            "combatant": True,
            "triggered": True,
            "health": 500,
            "max_health": 500,
        },
    )
    innocent = NPC(
        pos=[bot.physics.pos.x + 30, bot.physics.pos.y + 64, bot.physics.pos.z + 90],
        properties={
            "id": "bot-bystander",
            "name": "Villager",
            "aggression": "passive",
            "team": "town",
            "health": 50,
        },
    )
    fio.things(coop.logic).extend([enemy, innocent])
    fio.rebuild_entity_caches(coop.logic)
    coop.root._rebuild_type_index(fio.things(coop.logic))
    brain = PartyBots(coop)
    assert brain._threat(bot, human) is enemy
    stamina = bot.session.game.character.stamina
    brain.tick(0.016)
    assert bot.task == "Defending the party"
    assert bot.session._attack_cooldown > 0
    assert bot.session.game.character.stamina < stamina
    assert enemy.properties["health"] < 500
    assert not bot.session._attackable(innocent)
    assert innocent.properties["health"] == 50
    innocent.pos[2] = bot.physics.pos.z
    assert not brain._clear_shot(bot, enemy)
    frame, actions = brain.decide(bot, 0)
    assert not any(action == "attack" for action, _ in actions)
    assert frame.move_x or frame.move_z
    innocent.properties["disabled"] = True
    bot.session._attack_cooldown = 0
    original = bot.session.nav
    bot.session.nav = SimpleNamespace(
        line_clear=lambda *args: False,
        steer_actor=lambda actor, start, goal: (start[0], start[1], start[2] + 100),
    )
    try:
        frame, actions = brain.decide(bot, 0)
        assert not any(action == "attack" for action, _ in actions), (
            "A wall must block the bot's attack"
        )
        assert frame.move_z > 0.9
    finally:
        bot.session.nav = original


def test_companion_opens_an_unlocked_door_ahead_but_keeps_locks(coop_game):
    coop = coop_game.logic.game_session.coop
    _, bot, *_ = companions(coop)
    pos = bot.physics.pos
    door = {
        "pos": [pos[0] + 40, pos[1], pos[2]],
        "size": [32, 128, 96],
        "door_locked": True,
    }
    opened = []
    movers = SimpleNamespace(
        doors=[(0, door)],
        door_states={0: {"state": "closed"}},
        _trigger_door_open=lambda index, brush: opened.append(index),
    )
    original = bot.session.logic
    bot.session.logic = SimpleNamespace(
        mover_runtime=movers, player_runtime=SimpleNamespace(collected_keys=set())
    )
    try:
        goal = [pos[0] + 150, pos[1], pos[2]]
        PartyBots._open_door_ahead(bot, goal)
        assert not opened
        door["door_locked"] = False
        PartyBots._open_door_ahead(bot, goal)
        assert opened == [0]
    finally:
        bot.session.logic = original


def test_mage_companion_heals_itself_and_changes_weapon_when_magicka_runs_out(
    coop_game,
):
    from game.rpg import equipment, inventory
    from game.rpg.dialogue import DictStore
    from game.rpg.game_state import GameState

    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    mage = GameState.new_game(DictStore(), "Companion mage", "breton", "mage").character
    bot.session.game.character = mage
    mage.health = mage.max_health * 0.2
    mage.magicka = mage.max_magicka
    human_potions = inventory.quantity(
        human.session.game.character.inventory, "potion_heal_minor"
    )
    potions = inventory.quantity(mage.inventory, "potion_heal_minor")
    before = mage.health
    brain = PartyBots(coop)
    brain.tick(0.016)
    assert mage.health > before
    assert inventory.quantity(mage.inventory, "potion_heal_minor") == potions - 1
    assert (
        inventory.quantity(human.session.game.character.inventory, "potion_heal_minor")
        == human_potions
    )
    brain._choose_weapon(bot)
    assert equipment.equipped_id(mage, "weapon") == "apprentice_staff"
    mage.magicka = 0
    brain._choose_weapon(bot)
    assert equipment.equipped_id(mage, "weapon") == "iron_dagger"


def test_bots_revive_the_only_human_instead_of_freezing_when_player_one_falls(
    coop_game,
):
    import glm

    coop = coop_game.logic.game_session.coop
    human, *bots = companions(coop)
    for index, bot in enumerate(bots):
        bot.physics.pos = human.physics.pos + glm.vec3(40 + index * 20, 0, 0)
    human.session.game.character.health = 0
    coop._sync_actor(human)
    coop_game.step(195)
    assert not human.session.game.character.is_dead
    assert human.session.game.character.health > 0
    assert not coop.logic.player_runtime.player_dead


def test_bot_participation_and_identity_survive_a_real_campaign_save(
    coop_game, tmp_path
):
    from pathlib import Path
    from engine import savegame
    from game.multiplayer.lobby import LobbyController
    from game.tests.test_multiplayer import register_quest
    from game.tests.test_multiplayer_integration import OfflineNetwork

    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    quest = register_quest()
    gold = bot.session.game.character.gold
    coop.party_quests.start(quest.id, human.player_id)
    coop.party_quests.complete(quest.id, human.player_id)
    assert bot.session.game.character.gold == gold + 10
    path = tmp_path / "bot-party.fiosave"
    savegame.write(
        str(path),
        savegame.build_snapshot(coop.logic, map_name=Path(coop.map_name).name),
    )
    controller = LobbyController(
        coop.lobby.root, coop.map_name, network=OfflineNetwork()
    )
    controller.opened = True
    controller.host(local_only=True)
    controller.resume_campaign(path)
    assert sum(p.bot for p in controller.lobby.members) == 3
    saved = controller.lobby.member(bot.player_id)
    assert saved.profile["head"] == bot.profile["head"]
    assert saved.character["gold"] == gold + 10
    assert saved.ready and saved.connected
    controller.lobby.ready("host", True)
    assert controller.lobby.can_start


def test_bots_use_navigation_and_only_run_on_the_host(coop_game):
    coop = coop_game.logic.game_session.coop
    _, bot, *_ = companions(coop)
    used = []
    original = bot.session.nav
    bot.session.nav = SimpleNamespace(
        steer_actor=lambda actor, start, goal: (
            used.append(actor) or (start[0], start[1], start[2] + 150)
        )
    )
    brain = PartyBots(coop)
    try:
        frame = brain._walk(
            bot, (bot.physics.pos[0] + 300, bot.physics.pos[1], bot.physics.pos[2])
        )
        assert used == [bot.actor] and frame.move_z > 0.9
        coop.authority = False
        bot.frame = InputFrame()
        brain.tick(1)
        assert bot.frame == InputFrame()
    finally:
        coop.authority = True
        bot.session.nav = original


def test_bots_automatically_accept_party_travel(coop_game):
    from pathlib import Path

    coop = coop_game.logic.game_session.coop
    human, *_ = companions(coop)
    destination = next(
        p
        for p in (coop.lobby.root / "maps").glob("*.json")
        if p.name != Path(coop.map_name).name
    )
    coop.travel = {
        "active": True,
        "target_map": destination.name,
        "ready": [human.player_id],
    }
    coop.tick(
        SimpleNamespace(delta=0.016, keys=frozenset(), key_down=lambda key: False)
    )
    assert coop.travel is None
    assert coop.lobby.travelling
    assert coop.lobby.map_name == "maps/" + destination.name
    coop.lobby.travelling = False
