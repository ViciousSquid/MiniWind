"""Bot parties use real character contexts, physics, quests and persistence."""

from types import SimpleNamespace

from game.multiplayer.bots import PartyBots, distance
from game.multiplayer.companion_behavior import CompanionMind
from game.multiplayer.model import InputFrame
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401 - shared runtime fixture


def companions(coop):
    players = list(coop.players.values())
    for player in players[1:]:
        player.bot = True
        player.mind = CompanionMind("bot-regressions", player.profile["name"])
        player.profile["device"] = "bot:" + player.player_id
        member = coop.lobby.lobby.member(player.player_id)
        member.bot, member.ready = True, True
        member.profile = dict(player.profile)
    coop.lobby.state = coop.lobby.lobby.snapshot()
    for actor in coop.root._actors:
        if not actor.properties.get("multiplayer_player"):
            actor.properties["disabled"] = True
    return players


def think_until(brain, predicate, seconds=3):
    """Wait for a human reaction while keeping the real action assertions."""
    for _ in range(round(seconds / 0.05)):
        brain.tick(0.05)
        if predicate():
            return
    assert predicate(), "Companion did not act within a bounded reaction window"


def test_three_bots_follow_without_consuming_human_input(coop_game):
    import glm

    coop = coop_game.logic.game_session.coop
    human, *bots = companions(coop)
    for index, bot in enumerate(bots):
        bot.physics.pos = human.physics.pos + glm.vec3(300, 0, index * 25)
    before = distance(human.physics.pos, bots[0].physics.pos)
    # Allow the initially bunched companions to spread into their formation.
    coop_game.step(120)
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
    think_until(brain, lambda: bot.session._attack_cooldown > 0)
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
    coop_game, monkeypatch,
):
    from game.rpg import equipment, inventory, magic
    from game.rpg.dialogue import DictStore
    from game.rpg.game_state import GameState

    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    mage = GameState.new_game(DictStore(), "Companion mage", "wyrfolk", "mage").character
    bot.session.game.character = mage
    mage.health = mage.max_health * 0.2
    mage.magicka = mage.max_magicka
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (True, {}))
    human_potions = inventory.quantity(
        human.session.game.character.inventory, "potion_heal_minor"
    )
    potions = inventory.quantity(mage.inventory, "potion_heal_minor")
    before = mage.health
    brain = PartyBots(coop)
    think_until(brain, lambda: mage.health > before)
    assert mage.health > before
    assert inventory.quantity(mage.inventory, "potion_heal_minor") == potions
    assert mage.magicka < mage.max_magicka
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
    coop_game.step(270)
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
    coop.respawn_at_village = True
    bot.returning = True
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
    assert controller.lobby.respawn_at_village
    assert controller.campaign_state["players"][bot.player_id]["returning"]
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


def test_companion_personality_and_choices_survive_save_and_live_restore(coop_game, tmp_path):
    from engine import savegame

    coop = coop_game.logic.game_session.coop
    _, bot, *_ = companions(coop)
    brain = coop._bots = PartyBots(coop)
    think_until(brain, lambda: bool(bot.task))
    before = bot.mind.to_dict()
    personality = bot.mind.personality
    path = tmp_path / "companion-habits.fiosave"
    savegame.write(str(path), savegame.build_snapshot(coop.logic))
    saved = savegame.read(str(path))["coop"]
    assert saved["players"][bot.player_id]["companion"] == before
    # New map sessions recreate contexts but must keep each mind's identity.
    member = next(p for p in coop.lobby.state["members"]
                  if p["player_id"] == bot.player_id)
    coop.lobby.travelling = True
    try:
        arrived = coop._create_player(member, saved=saved["players"][bot.player_id])
        assert arrived.mind.to_dict() == before
    finally:
        coop.players[bot.player_id] = bot
        coop.lobby.travelling = False
    expected = [bot.mind.uniform(0, 1) for _ in range(10)]
    coop.restore_campaign(saved)
    assert bot.mind.personality == personality
    assert [bot.mind.uniform(0, 1) for _ in range(10)] == expected
    assert coop._bots is not brain and not coop._bots.sightings
    assert bot.bot_target is None and bot.frame == InputFrame()
    # Existing saves do not need a format migration.
    saved["players"][bot.player_id].pop("companion")
    coop.restore_campaign(saved)
    assert bot.mind.to_dict() == CompanionMind(saved["campaign_id"], bot.player_id).to_dict()


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


def test_companion_uses_healing_effects_and_does_not_chug_every_think(coop_game, monkeypatch):
    from game.rpg import inventory, items

    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    potion = items.ItemDef(
        "field_elixir", "Field Elixir", items.POTION,
        effects=[{"kind": "restore_health", "magnitude": 75, "duration": 0}],
    )
    monkeypatch.setitem(items.ITEMS, potion.id, potion)
    c = bot.session.game.character
    c.inventory[:] = [potion.make_stack(2)]
    c.health = 1
    human_items = list(human.session.game.character.inventory)
    brain = PartyBots(coop)
    think_until(brain, lambda: c.health == 76)
    assert c.health == 76
    assert inventory.quantity(c.inventory, potion.id) == 1
    # Sustained damage must not consume a potion on every AI think.
    c.health = 1
    brain.tick(0.1)
    brain.tick(0.1)
    assert inventory.quantity(c.inventory, potion.id) == 1
    brain.clock = brain.next_heal[bot.player_id] + 0.1
    think_until(brain, lambda: c.health == 76)
    assert c.health == 76 and inventory.quantity(c.inventory, potion.id) == 0
    assert human.session.game.character.inventory == human_items
    c.inventory[:] = [items.make("potion_heal"), items.make("potion_heal_minor")]
    c.health = c.max_health - 20
    assert brain._healing_potion(c).id == "potion_heal_minor"


def test_companion_weapon_choice_tracks_range_visibility_and_real_resources(coop_game):
    import glm
    from game.rpg import equipment, items, magic

    coop = coop_game.logic.game_session.coop
    _, bot, *_ = companions(coop)
    c = bot.session.game.character
    c.inventory[:] = [items.make(i) for i in ("iron_longsword", "elven_bow", "iron_arrow")]
    threat = SimpleNamespace(pos=bot.physics.pos + glm.vec3(350, 0, 0))
    brain = PartyBots(coop)
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c).id == "elven_bow"
    threat.pos = bot.physics.pos + glm.vec3(90, 0, 0)
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c).id == "iron_longsword"
    threat.pos = bot.physics.pos + glm.vec3(350, 0, 0)
    brain._choose_weapon(bot, threat, clear=False)
    assert equipment.weapon(c).id == "iron_longsword"
    c.inventory[-1]["qty"] = 0
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c).id == "iron_longsword"

    c.inventory[:] = [items.make("apprentice_staff"), items.make("iron_dagger")]
    cost = magic.cast_cost(c, magic.get("flare")) * 0.5
    c.magicka = cost
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c).id == "apprentice_staff"
    c.magicka = cost - 0.1
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c).id == "iron_dagger"
    c.inventory[:] = [items.make("elven_bow"), items.make("iron_longsword", qty=0)]
    equipment.equip(c, "elven_bow")
    brain._choose_weapon(bot, threat)
    assert equipment.weapon(c) is None


def test_dead_companion_respawns_and_uses_roads_without_tethering_the_party(coop_game, monkeypatch):
    import glm
    import pytest
    from game.navigation import Navigator
    from game.road_nav import RoadGraph

    coop = coop_game.logic.game_session.coop
    human, bot, *others = companions(coop)
    spawn = glm.vec3(*coop._village_spawn)
    for player in (human, *others):
        player.physics.pos = spawn + glm.vec3(3000, 0, 0)
    bot.physics.pos = spawn + glm.vec3(2000, 0, 0)
    c = bot.session.game.character
    c.health = 0
    coop._sync_actor(bot)
    coop._death_flow(4)
    assert c.is_dead and not bot.returning  # opt-in only
    coop.respawn_at_village = True
    coop._death_flow(coop.BOT_RESPAWN_SECONDS - 0.1)
    assert c.is_dead
    coop._death_flow(0.2)
    assert c.health == c.max_health and bot.returning
    assert tuple(bot.physics.pos) == pytest.approx(tuple(spawn))
    assert not bot.actor.properties["dead"]
    assert not bot.session.logic.player_runtime.player_dead
    assert coop.snapshot()["players"][bot.player_id]["returning"]
    before = {p.player_id: tuple(p.physics.pos) for p in coop.players.values()}
    coop._camera(0, before)
    assert tuple(bot.physics.pos) == pytest.approx(tuple(spawn))
    assert coop.simulation_focus().x == pytest.approx(human.physics.pos.x)

    x, y, z = spawn
    graph = RoadGraph.build([
        ("ROAD_A", x, z, ("ROAD_B",), y),
        ("ROAD_B", x + 1000, z + 400, ("ROAD_C",), y),
        ("ROAD_C", x + 3000, z, (), y),
    ])
    coop.root._road_graph = graph
    monkeypatch.setattr(coop.root, "_refresh_roads", lambda: None)
    # The road supplies the long trip; the regular navigator still goes
    # around a wall on the way to its first junction.
    bot.session.nav = Navigator(
        lambda px, py, pz: x + 350 < px < x + 500 and z - 100 < pz < z + 300
    )
    brain = PartyBots(coop)
    frame, _ = brain.decide(bot, 0)
    plan = coop.root._road_plans[id(bot.actor)]
    assert plan["points"][plan["i"]] == graph.points[1]
    assert frame.move_z > 0.1 and bot.task == "Returning from village"

    saved = coop.campaign()
    bot.returning = False
    coop.restore_campaign(saved)
    assert bot.returning
    bot.physics.pos = human.physics.pos + glm.vec3(100, 0, 0)
    brain.decide(bot, 0)
    assert not bot.returning and bot.task.startswith("Following")

    from engine.spatial import TIER_NEAR, tier_of
    from plugins.bigworld.runtime import BigWorldSession

    bot.physics.pos = spawn
    bot.returning = True
    coop._sync_actor(bot)
    streaming = BigWorldSession(coop.logic, activation_radius=1024, deactivation_radius=1280)
    streaming.start()
    try:
        assert bot.actor in streaming.manager.persistent_things
        assert tier_of(bot.actor) == TIER_NEAR
        assert not bot.actor.properties.get("hidden")
    finally:
        streaming.stop()


def test_returning_companion_collides_with_parked_scenery():
    import glm
    from engine.physics import SpatialGrid
    from engine.player import Player
    from engine.spatial import PARKED_HIDDEN_KEY
    from game.multiplayer.world import CompanionCollisionGrid

    floor = {"pos": [0, -32, 0], "size": [4000, 64, 4000],
             "hidden": True, PARKED_HIDDEN_KEY: False}
    wall = {"pos": [180, 64, 0], "size": [32, 128, 1000],
            "hidden": True, PARKED_HIDDEN_KEY: False}
    grid = SpatialGrid()
    grid.populate([floor, wall])
    body = Player(0, 0)
    body.pos.y = body._half.y
    local_grid = CompanionCollisionGrid(grid)
    for _ in range(90):
        body.update(1 / 60, glm.vec3(1, 0, 0), False, False, [], [], [],
                    None, spatial_grid=local_grid, movement_angle=0)
    assert 50 < body.pos.x < 150
    assert abs(body.pos.y - body._half.y) < 1
    assert floor["hidden"] and wall["hidden"]
