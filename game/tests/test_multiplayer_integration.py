"""Exercise the actual editor -> Fio runtime -> MiniWind co-op handoff."""

from __future__ import annotations

from pathlib import Path

import random

import pytest

from game.multiplayer import lobby as launch_state
from game.multiplayer.lobby import LobbyController
from game.multiplayer.model import InputFrame, Lobby
from game.tests.test_multiplayer import profile


class OfflineNetwork:
    def __init__(self):
        self.advertisement = None
        self.sent = []

    def broadcast(self, message, **kwargs):
        self.sent.append(message)

    def poll(self):
        return []

    def stop_browser(self):
        pass

    def close(self):
        pass


@pytest.fixture
def coop_game(qt_app, monkeypatch, tmp_path):
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    import game
    from plugins.manager import get_manager

    get_manager().register_builtin_game(game.GAME)
    from tests.helpers import scenes
    from game import music
    from game.ui import hud_layout

    music_config = (music.PLAYER._config, music.PLAYER._save)
    hud_config = (hud_layout._config, hud_layout._save_config)
    from tests.helpers.session import FioTestSession

    root = Path(__file__).resolve().parents[2]
    controller = LobbyController(
        root, "maps/miniwind_world.json", network=OfflineNetwork(), identity="a" * 64
    )
    controller.opened = True
    controller.signature = "test"
    controller.lobby = Lobby(signature="test", map_name="maps/miniwind_world.json")
    for i in range(4):
        controller.lobby.add("host", profile(i))
    controller.lobby.ready("host", True)
    controller.lobby.start("host")
    controller.state = controller.lobby.snapshot()
    controller.started = True
    launch_state.prepare(controller)
    scene = scenes.showcase()
    session = FioTestSession(qt_app, scene)
    try:
        session.start_play()
        yield session
    finally:
        try:
            # Keep the real project root for maps/content during the test, but
            # put the exit checkpoint in pytest's temporary directory.
            controller.root = tmp_path
            session.stop_play()
            # Editor integration binds these process-wide services to this
            # window's save callback. Restore them before checking Qt teardown.
            music.PLAYER.configure(*music_config)
            hud_layout.configure(*hud_config)
            session.close()
        finally:
            launch_state.finish()


def test_four_lobby_characters_enter_without_character_creation(coop_game):
    s = coop_game.logic.game_session
    assert hasattr(s, "coop"), "Multiplayer launcher handoff was not attached"
    assert len(s.coop.players) == 4
    assert not s.needs_char_creation
    assert not s.logic.session_runtime.world_paused
    assert [p.session.game.character.head for p in s.coop.players.values()] == [
        profile(i)["head"] for i in range(4)
    ]
    assert (
        len(
            [
                t
                for t in coop_game.state.things
                if t.properties.get("multiplayer_player")
            ]
        )
        == 4
    )
    coop_game.step(3)


def _draw_overhead_weapons(game, monkeypatch, *, publish=True):
    from types import SimpleNamespace

    weapons, heads = [], []

    def draw_weapon(projection, view, pos, facing, path, now, **kwargs):
        weapons.append(dict(pos=tuple(pos), facing=facing, item=Path(path).stem, **kwargs))

    view = game.view
    with monkeypatch.context() as patch:
        patch.setattr(view, "overhead_sprite_enabled", True)
        patch.setattr(view, "_overhead_head",
                      getattr(game.logic, "player_head_sprite", None), raising=False)
        patch.setattr(view, "_overhead_sprite_renderer", SimpleNamespace(
            draw=lambda *args, **kwargs: heads.append(args), draw_weapon=draw_weapon,
        ))
        if publish:
            game.publish()
        with game.render_state() as frame:
            view._draw_overhead_sprite(frame)
    return weapons, heads


def test_party_starter_weapons_are_drawn_for_human_and_companions(coop_game, monkeypatch):
    from game.rpg import equipment

    coop = coop_game.logic.game_session.coop
    for index, player in enumerate(coop.players.values()):
        player.bot = index > 0
        c = player.session.game.character
        assert equipment.equipped_id(c, "weapon") == "iron_longsword"
        assert equipment.equipped_id(c, "shield") == "iron_shield"
    weapons, heads = _draw_overhead_weapons(coop_game, monkeypatch)
    assert not heads, "Co-op heads are already published as actor sprites"
    for player in coop.players.values():
        held = [w for w in weapons if w["pos"] == tuple(player.actor.pos)]
        assert [(w["item"], w["handed"]) for w in held] == [
            ("iron_longsword", "right"), ("iron_shield", "left"),
        ]


def test_party_weapons_follow_equipment_hands_and_replica_state(coop_game, monkeypatch):
    import json
    import time

    coop = coop_game.logic.game_session.coop
    coop_game.publish()
    shield, dual, bow, mage = list(coop.players.values())
    shield.session.game.character.handed = "left"
    shield.session._blocking = True
    shield.session._block_at = time.perf_counter() - 1
    for item in ("iron_mace", "iron_dagger"):
        dual.session.game.pick_up(item)
    dual.session.game.equip("iron_mace")
    dual.session.game.equip("iron_dagger", "shield")
    dual.session._attack_anim_time = 0.18
    dual.session._offhand_anim_time = 0.12
    bow.session.game.equip("short_bow")
    mage.session.game.pick_up("apprentice_staff")
    mage.session.game.equip("apprentice_staff")
    mage.session._cast_cooldown = 0.65
    for player in coop.players.values():
        coop._sync_actor(player)

    def check_draws():
        weapons, heads = _draw_overhead_weapons(coop_game, monkeypatch, publish=False)
        assert not heads
        held = {
            p.player_id: [w for w in weapons if w["pos"] == tuple(p.actor.pos)]
            for p in coop.players.values()
        }
        assert [(w["item"], w["handed"]) for w in held[shield.player_id]] == [
            ("iron_longsword", "left"), ("iron_shield", "right"),
        ]
        assert held[shield.player_id][1]["block"] == 1
        assert [w["item"] for w in held[dual.player_id]] == ["iron_mace", "iron_dagger"]
        assert all(w["attacking"] for w in held[dual.player_id])
        assert [w["item"] for w in held[bow.player_id]] == ["short_bow"]
        assert held[bow.player_id][0]["weapon_kind"] == "bow"
        assert [w["item"] for w in held[mage.player_id]] == ["apprentice_staff", "iron_shield"]
        assert held[mage.player_id][0]["weapon_kind"] == "staff"
        assert held[mage.player_id][0]["attacking"]

    check_draws()
    snapshot = json.loads(json.dumps(coop.snapshot()))
    for player in coop.players.values():
        player.session._attack_anim_time = 0
        player.session._offhand_anim_time = 0
        player.session._cast_cooldown = 0
    coop.authority = False
    try:
        coop.apply_snapshot(snapshot)
        check_draws()
        shield.session.game.character.health = 0
        dual.connected = False
        bow.actor.properties["hidden"] = True
        weapons, _ = _draw_overhead_weapons(coop_game, monkeypatch, publish=False)
        absent = {tuple(p.actor.pos) for p in (shield, dual, bow)}
        assert not any(w["pos"] in absent for w in weapons)
    finally:
        coop.authority = True


def test_solo_weapon_overlay_still_draws_the_player_once(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    coop_game.publish()
    with monkeypatch.context() as patch:
        patch.setattr(coop.root, "coop", None)
        weapons, heads = _draw_overhead_weapons(coop_game, monkeypatch, publish=False)
    assert len(heads) == 1
    held = [w for w in weapons if w["pos"] == tuple(coop.root.logic.player_runtime.player.pos)]
    assert [w["item"] for w in held] == ["iron_longsword", "iron_shield"]


def test_two_assigned_players_move_independently_and_menus_do_not_pause(coop_game):
    coop = coop_game.logic.game_session.coop
    players = list(coop.players.values())
    before = [list(p.physics.pos) for p in players]
    coop.local_input(players[1].player_id, InputFrame(1, 0))
    coop.local_input(players[2].player_id, InputFrame(0, 1))
    coop_game.step(10)
    assert players[1].physics.pos.x != pytest.approx(before[1][0])
    assert players[2].physics.pos.z != pytest.approx(before[2][2])
    assert players[3].physics.pos.x == pytest.approx(before[3][0])
    coop.action(players[0], "inventory", [])
    hour = coop.root.clock.hour
    coop_game.step(3)
    assert not coop.logic.session_runtime.world_paused
    assert coop.root.clock.hour > hour


def test_keyboard_turns_from_north_to_east_before_wasd_movement(coop_game):
    import math

    from PyQt5.QtCore import Qt

    coop = coop_game.logic.game_session.coop
    player = coop.local_players[0]
    body = player.physics
    # Exercise the live input queue and movement runtime without momentum
    # from the previous direction affecting the next key's displacement.
    body.physics_enabled = False
    coop_game.game_state.set_aim(yaw=math.pi)  # north: negative world Z
    coop_game.step(2)
    assert body.angle == pytest.approx(math.pi)
    coop_game.game_state.set_aim(yaw=math.pi / 2)  # turn clockwise to east
    coop_game.step(2)
    assert body.angle == pytest.approx(math.pi / 2)
    assert coop.heading == pytest.approx(math.pi)  # camera still north-up

    for key, axis, sign in (
        (Qt.Key_W, 0, 1),   # forward: east
        (Qt.Key_S, 0, -1),  # backward: west
        (Qt.Key_A, 2, -1),  # strafe left: north
        (Qt.Key_D, 2, 1),   # strafe right: south
    ):
        coop_game.step(2)
        before = tuple(body.pos)
        coop_game.step(10, keys={key})
        assert (body.pos[axis] - before[axis]) * sign > 1
        cross_axis = 2 if axis == 0 else 0
        assert body.pos[cross_axis] == pytest.approx(before[cross_axis], abs=0.001)
        assert body.angle == pytest.approx(math.pi / 2)


def test_hand_attacks_use_each_characters_own_weapon_and_cooldown(coop_game):
    coop = coop_game.logic.game_session.coop
    first, second, third, _ = list(coop.players.values())
    before = second.session.game.character.stamina
    coop.local_input(second.player_id, InputFrame(held=frozenset({"right_hand"})))
    coop_game.step(3)
    assert second.session._attack_cooldown > 0
    assert second.session.game.character.stamina < before
    assert first.session._attack_cooldown == third.session._attack_cooldown == 0


def test_enemy_damage_targets_one_character_and_allied_damage_is_ignored(coop_game):
    from game.entities import NPC

    coop = coop_game.logic.game_session.coop
    first, second = list(coop.players.values())[:2]
    before = first.session.game.character.health
    target_health = second.session.game.character.health
    # This checks ownership of a landed hit, independently of the random
    # Armour Class deflection covered by the RPG combat tests.
    from game.rpg import attributes

    second.session.game.character.equipment.clear()
    second.session.game.character.attrs[attributes.ENDURANCE] = 40

    class Lands(random.Random):
        def randint(self, low, high):
            return high                       # the to-hit die always a 20

    second.session.game.dice.rng = Lands(0)
    coop.logic.monster_ai._apply_monster_damage(
        second.actor, 10000, attacker=NPC(pos=[0, 0, 0], properties={"name": "Enemy"})
    )
    assert second.session.game.character.health < target_health
    assert first.session.game.character.health == before
    coop.damage(first.player_id, 10000, source=second.actor)
    assert first.session.game.character.health == before


def test_local_game_menu_is_live_and_host_pause_is_explicit(coop_game):
    from game.ui.pause_menu import PauseMenu

    coop = coop_game.logic.game_session.coop
    menu = PauseMenu(coop_game.view)
    menu._grab_blurred_frame = lambda: None
    menu.open()
    try:
        hour = coop.root.clock.hour
        coop_game.step(2)
        assert not coop.logic.session_runtime.world_paused
        assert coop.root.clock.hour > hour
        host = next(iter(coop.players.values()))
        coop.action(host, "pause", [])
        assert coop.logic.session_runtime.world_paused
        coop.action(host, "inventory", [])
        assert host.session.open_screen == "inventory"
        assert coop.logic.session_runtime.world_paused
        coop.action(host, "pause", [])
        assert not coop.logic.session_runtime.world_paused
    finally:
        menu.close()


def test_resurrecting_companion_keeps_them_a_player(coop_game):
    from game.rpg import magic

    coop = coop_game.logic.game_session.coop
    first, second = list(coop.players.values())[:2]
    second.session.game.character.health = 0
    coop._sync_actor(second)
    first.session.game.character.magicka = 100
    assert first.session._do_resurrect(magic.get("resurrection"), target=second.actor)
    assert not second.session.game.character.is_dead
    assert not second.actor.properties.get("follow_player")
    assert not second.actor.properties.get("resurrected_by")


def test_player_one_can_fall_without_freezing_the_rest_and_save_keeps_all_four(
    coop_game,
):
    from engine import savegame

    coop = coop_game.logic.game_session.coop
    players = list(coop.players.values())
    players[0].session.game.character.health = 0
    coop.local_input(players[1].player_id, InputFrame(1, 0))
    before = players[1].physics.pos.x
    coop_game.step(4)
    assert players[1].physics.pos.x != pytest.approx(before)
    data = savegame.build_snapshot(coop.logic)
    assert data["save_version"] == 4
    assert len(data["coop"]["players"]) == 4
    assert len(data["coop"]["members"]) == 4


def test_authoritative_frames_recreate_missing_actors_and_preserve_inventory(coop_game):
    from game.multiplayer.replication import apply, capture

    coop = coop_game.logic.game_session.coop
    frame = capture(coop)
    assert len(frame["players"]) == 4
    player = list(coop.players.values())[2]
    original_head = player.profile["head"]
    coop_game.state.things.remove(player.actor)
    apply(coop, frame)
    assert player.actor in coop_game.state.things
    assert player.actor.properties["head"] == original_head


def test_checkpoint_rolls_back_every_character_and_completed_quest(coop_game):
    from game.tests.test_multiplayer import register_quest

    coop = coop_game.logic.game_session.coop
    q = register_quest()
    player = next(iter(coop.players.values()))
    before = player.session.game.character.gold
    coop.checkpoint()
    coop.party_quests.start(q.id, player.player_id)
    coop.party_quests.complete(q.id, player.player_id)
    assert player.session.game.character.gold > before
    coop.restore_checkpoint()
    assert player.session.game.character.gold == before
    assert not player.session.game.quests.state_of(q.id)


def test_shared_quest_values_are_visible_to_existing_map_logic(coop_game):
    from game.tests.test_multiplayer import register_quest

    coop = coop_game.logic.game_session.coop
    q = register_quest()
    pid = next(iter(coop.players))
    coop.party_quests.start(q.id, pid)
    assert (
        coop.logic.io_manager.query_keyvalue("miniwind", f"quest.{q.id}.state")
        == "active"
    )
    assert coop.logic.io_manager.set_keyvalue("miniwind", f"quest.{q.id}.stage", 10)
    assert coop.players[pid].session.game.quests.stage_of(q.id) == 10


def test_camera_boundary_stops_outward_steps_and_respects_zoom_ceiling(coop_game):
    import glm

    coop = coop_game.logic.game_session.coop
    players = list(coop.players.values())
    for index, player in enumerate(players):
        player.physics.pos = glm.vec3(index * 12, 80, 0)
    before = {p.player_id: tuple(p.physics.pos) for p in players}
    players[0].physics.pos.x = -500
    cam = coop.logic.camera
    cam.overhead_height_limit = 400
    cam.frustum_aspect = 0.5
    coop._camera(1 / 60, before)
    assert players[0].physics.pos.x == before[players[0].player_id][0]
    assert cam.overhead_height <= 400
    assert coop._party_radius < coop.MAX_SEPARATION


def test_client_replays_only_unacknowledged_movement_with_collisions(
    coop_game, monkeypatch
):
    coop = coop_game.logic.game_session.coop
    player = list(coop.players.values())[1]
    frame = InputFrame(1, 0)
    player.prediction.extend(
        [(10, 0.016, frame), (11, 0.016, frame), (12, 0.016, frame)]
    )
    steps = []
    original = coop._move_player

    def move(context, value, delta):
        steps.append((context, value, delta))
        original(context, value, delta)

    monkeypatch.setattr(coop, "_move_player", move)
    coop.reconcile(
        player,
        {
            "pos": list(player.physics.pos),
            "velocity": [0, 0, 0],
            "angle": 0,
            "movement_ack": 11,
        },
    )
    assert len(steps) == 1 and steps[0][0] is player
    assert [item[0] for item in player.prediction] == [12]


def test_client_keeps_receiving_world_when_primary_character_is_down(
    coop_game, monkeypatch
):
    coop = coop_game.logic.game_session.coop
    player = list(coop.players.values())[2]
    frame = coop.snapshot()
    frame["players"][player.player_id]["character"]["gold"] += 37
    coop.root.game.character.health = 0
    coop.root._sync_engine_health()
    monkeypatch.setattr(coop.lobby.network, "poll", lambda: [("host", frame)])
    coop.authority = False
    try:
        coop_game.step(1)
        assert coop._received_sequence == frame["sequence"]
        assert (
            player.session.game.character.gold
            == frame["players"][player.player_id]["character"]["gold"]
        )
    finally:
        coop.authority = True


def test_click_stays_bound_to_character_whose_panel_was_painted(coop_game):
    from PyQt5.QtCore import QRect
    from game.ui import hits

    coop = coop_game.logic.game_session.coop
    first, second = list(coop.players.values())[:2]
    received = []
    hits.begin(first.session)
    hits.add(QRect(0, 0, 20, 20), lambda session: received.append(session.player_id))
    hits.end()
    assert hits.click(5, 5)
    coop.focus(second)
    hits.run_clicks(second.session)
    assert received == [first.player_id]


def test_sound_and_moving_door_are_replicated_without_client_simulation(coop_game):
    import copy
    from game.multiplayer.replication import apply

    coop = coop_game.logic.game_session.coop
    door = {
        "id": "coop-test-door",
        "is_door": True,
        "pos": [0, 80, 0],
        "size": [48, 128, 16],
        "start_on": False,
    }
    coop.logic.editor_state.brushes.append(door)
    # A door is a row of the engine's mover table from the start of play;
    # this one arrives late, so have the doors gathered again.
    coop.logic.mover_runtime._init_doors()
    frame = coop.snapshot()
    frame["moving_brushes"]["coop-test-door"]["pos"] = [72, 80, 0]
    apply(coop, frame)
    # Fio 3.5: a door's ``pos`` is where it was authored; where it is now is
    # its live placement, which the replicated frame moved.
    from engine import brush_placement

    assert list(door["pos"]) == [0, 80, 0]
    assert list(brush_placement.placement(door).centre) == [72, 80, 0]
    sound = {"file": "fire.wav", "position": [0, 0, 0]}
    coop.logic.game_state.queue_sound(copy.deepcopy(sound))
    assert coop._sounds[-1] == sound


def test_real_peer_commands_are_owned_and_world_frames_round_trip(coop_game):
    import hashlib
    import time
    from game.multiplayer.transport import NetworkService
    from game.tests.test_multiplayer_network import guest

    coop = coop_game.logic.game_session.coop
    controller = coop.lobby
    original_network = controller.network
    controller.network = NetworkService()
    controller.network.host(port=0, address="127.0.0.1")
    owner = hashlib.sha256(("b" * 64).encode()).hexdigest()
    players = list(coop.players.values())
    for player, member in zip(players[2:], controller.lobby.members[2:]):
        player.owner = member.owner = owner
    controller.state = controller.lobby.snapshot()
    client = guest(controller)
    client.signature = controller.signature

    def pump(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            coop._network()
            client.poll()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError(str(controller.errors + client.errors))

    try:
        pump(lambda: client.started)
        client.network.send(
            "host",
            {
                "type": "input",
                "player_id": players[2].player_id,
                "sequence": 10,
                "frame": InputFrame(1, 0).to_dict(),
            },
        )
        pump(lambda: players[2].sequence == 10)
        before = players[2].physics.pos.x
        coop.move_all(0.016)
        assert players[2].physics.pos.x > before
        client.network.send(
            "host",
            {
                "type": "action",
                "player_id": players[0].player_id,
                "sequence": 11,
                "action": "inventory",
                "args": [],
            },
        )
        pump(lambda: bool(client.errors))
        assert "belong" in client.errors[0]
        assert players[0].session.open_screen is None
        client.errors.clear()
        client.network.send(
            "host",
            {
                "type": "action",
                "player_id": players[2].player_id,
                "sequence": 12,
                "action": "inventory",
                "args": [],
            },
        )
        pump(lambda: players[2].session.open_screen == "inventory")
        frame = coop.snapshot()
        controller.network.broadcast(frame, peers=controller.peers, replace=True)
        received = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not received:
            received = [m for _, m in client.network.poll() if m["type"] == "world"]
            time.sleep(0.01)
        assert (
            received
            and received[0]["players"][players[2].player_id]["screen"] == "inventory"
        )
        assert len(received[0]["players"]) == 4
        client.close()
        pump(lambda: owner not in controller.peers.values())
        assert not any(member.connected for member in controller.lobby.owned(owner))
    finally:
        client.close()
        controller.network.close()
        controller.network = original_network


def test_host_slot_load_restores_party_without_closing_connection(
    coop_game, tmp_path, monkeypatch
):
    from engine import savegame
    from game.ui.pause_actions import PauseActions

    coop = coop_game.logic.game_session.coop
    saved = savegame.build_snapshot(coop.logic, map_name=Path(coop.map_name).name)
    path = tmp_path / "slot.fiosave"
    savegame.write(str(path), saved)
    action = PauseActions(coop_game.view)
    player = list(coop.players.values())[2]
    before = player.session.game.character.gold
    player.session.game.character.gold += 50
    with monkeypatch.context() as patch:
        patch.setattr(action._console(), "_resolve_save_path", lambda _: str(path))
        assert action.load_named("slot.fiosave", "test slot")
    assert player.session.game.character.gold == before
    assert launch_state.active() is coop.lobby
    assert coop_game.playing


def test_campaign_save_resume_preserves_offline_character_and_lobby_appearance(
    coop_game, tmp_path
):
    from engine import savegame
    from game.rpg import heads

    coop = coop_game.logic.game_session.coop
    player = list(coop.players.values())[2]
    player.owner = coop.lobby.lobby.members[2].owner = "offline-owner"
    coop.lobby.state = coop.lobby.lobby.snapshot()
    player.session.game.character.gold += 81
    path = tmp_path / "campaign.fiosave"
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
    restored = controller.lobby.member(player.player_id)
    assert not restored.connected
    assert restored.character["gold"] == player.session.game.character.gold
    host = controller.lobby.owned("host")[0]
    chosen = dict(host.profile, head=heads.HEAD_IDS[8])
    controller.lobby.update("host", host.player_id, chosen)
    controller.lobby.ready("host", True)
    assert controller.lobby.can_start


def test_copy_solo_save_preserves_build_progress_and_original_file(coop_game, tmp_path):
    import json
    from engine import savegame
    from game.rpg.character import Character
    from game.multiplayer.quests import PlayerStore

    coop = coop_game.logic.game_session.coop
    character = Character.create("Original mage", "wyrfolk", "mage", "apprentice")
    data = savegame.build_snapshot(coop.logic, map_name=Path(coop.map_name).name)
    data.pop("coop")
    data["save_version"] = 3
    values = {
        "_character": json.dumps(character.to_dict()),
        "quest.fighters_join.state": "active",
        "quest.fighters_join.stage": "0",
        "kills.wolf": "1",
    }
    data["miniwind"] = {"store": "miniwind", "values": values}
    path = tmp_path / "solo.fiosave"
    savegame.write(str(path), data)
    original = path.read_bytes()
    controller = LobbyController(
        coop.lobby.root, coop.map_name, network=OfflineNetwork()
    )
    controller.opened = True
    controller.host(local_only=True)
    controller.resume_campaign(path)
    member = controller.lobby.members[0]
    assert member.profile["race"] == "wyrfolk" and member.profile["class"] == "mage"
    assert member.profile["birthsign"] == "apprentice"
    assert controller.lobby.campaign_id != coop.lobby.lobby.campaign_id
    scoped = PlayerStore(None, member.player_id)
    assert (
        controller.campaign_state["world"][scoped.key("quest.fighters_join.state")]
        == "active"
    )
    assert path.read_bytes() == original


def test_group_travel_updates_reconnect_map_and_preserves_current_save_identity(
    coop_game,
):
    coop = coop_game.logic.game_session.coop
    current = coop.map_name
    coop.travel = {
        "active": True,
        "target_map": "miniwind_whisperdeep.json",
        "ready": [],
    }
    # Choose an installed destination, using a file rather than a guessed name.
    destination = next(
        p
        for p in (coop.lobby.root / "maps").glob("*.json")
        if p.name != Path(current).name
    )
    coop.travel["target_map"] = destination.name
    for player in coop.players.values():
        coop.ready_to_travel(player)
    assert coop.lobby.lobby.map_name == "maps/" + destination.name
    assert coop.lobby.lobby.map_hash
    assert coop.map_name == current
    assert coop.lobby.travelling
    # This test stops before the editor performs the actual map load.
    coop.lobby.travelling = False


def _pending_trip(coop, ready):
    coop.travel = {"active": True, "target_map": "cave01.json", "ready": list(ready)}


def test_interact_joins_a_pending_trip_when_nothing_else_is_in_reach(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    first, second = list(coop.players.values())[:2]
    _pending_trip(coop, [second.player_id])
    session = first.session
    for name in ("nearest_talkable", "nearest_corpse", "nearest_container"):
        monkeypatch.setattr(session, name, lambda *a, **k: None)
    monkeypatch.setattr(coop, "_revive_near", lambda *a, **k: False)
    readied = []
    monkeypatch.setattr(coop, "ready_to_travel", lambda ctx: readied.append(ctx.player_id))
    coop.interact(first)
    assert readied == [first.player_id]
    coop.travel = None


def test_a_pending_trip_does_not_stop_a_player_talking(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    first, second = list(coop.players.values())[:2]
    _pending_trip(coop, [second.player_id])
    session = first.session
    villager = object()
    monkeypatch.setattr(session, "nearest_talkable", lambda *a, **k: villager)
    talked = []
    monkeypatch.setattr(session, "start_dialogue", lambda npc, *a: talked.append(npc))
    readied = []
    monkeypatch.setattr(coop, "ready_to_travel", lambda ctx: readied.append(ctx.player_id))
    coop.interact(first)
    assert talked == [villager] and readied == []
    assert coop.travel is not None, "the trip is still waiting for this player"
    coop.travel = None


def test_every_client_sees_the_same_dice(coop_game, monkeypatch):
    """The host rolls; the world frame carries that very roll to clients --
    the same numbers, throw and finishes -- for a player's own roll and for a
    roll box over anyone near them."""
    import json
    from game import fio
    from game.multiplayer.replication import apply, capture
    from game.ui import hud

    coop = coop_game.logic.game_session.coop
    player = list(coop.players.values())[0]
    s = player.session
    monkeypatch.setattr(s, "_visualise_dice_rolls_enabled", lambda: True)
    s.dice_animation = None
    s._on_dice_roll({"label": "Attack", "total": 15, "target": 10, "success": True,
                     "components": [{"notation": "1d20", "roll_details": [15]}]},
                    "test", {"against_name": "Wolf"})
    assert s.dice_animation is not None and "seed" in s.dice_animation
    npc = next(t for t in fio.things(coop.logic)
               if t.properties.get("id") and getattr(t, "pos", None) is not None
               and not t.properties.get("multiplayer_player"))
    npc.properties["_sim_tier"] = 0
    monkeypatch.setattr(s, "_player_pos", lambda: list(npc.pos))
    box = s.show_roll_box(npc, {"label": "Roll to hit", "total": 4, "target": 12,
                                "success": False,
                                "components": [{"notation": "1d20", "roll_details": [4]}]})
    assert box is not None

    def seen(b):
        return [(v["sides"], v["value"], v["shade"], v["motion"])
                for v in hud._prepare_dice_animation(dict(b), b["result"])]

    host_own, host_box = seen(s.dice_animation), seen(box)
    frame = json.loads(json.dumps(capture(coop)))      # over the wire
    s.dice_animation = None
    s.__dict__["roll_boxes"] = {}
    apply(coop, frame)
    assert s.dice_animation["result"]["components"][0]["roll_details"] == [15]
    assert s.dice_animation["actor"] is player.actor
    assert seen(s.dice_animation) == host_own
    (client_box,) = s.__dict__["roll_boxes"].values()
    assert client_box["actor"] is npc and client_box["result"]["total"] == 4
    assert seen(client_box) == host_box
