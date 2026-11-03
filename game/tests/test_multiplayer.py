"""Co-op rules, framing, ownership and lazy launcher lifecycle regressions."""

from __future__ import annotations

import copy
import socket
import struct

import pytest

from game.multiplayer.model import InputFrame, Lobby, LobbyError, validate_profile
from game.multiplayer.quests import CoopGameState, PartyQuests, QuestError
from game.multiplayer.transport import Decoder, NetworkService, encode
from game.rpg import heads, inventory, quests
from game.rpg.dialogue import DictStore


def profile(index=0, device=None):
    return dict(
        name=f"Player {index + 1}",
        head=heads.HEAD_IDS[index],
        race="imperial",
        **{"class": "warrior"},
        birthsign="none",
        gender="male",
        handed="right",
        device=device or ("keyboard" if index == 0 else f"pad:{index}"),
    )


def party(count=4):
    service = PartyQuests(DictStore())
    for i in range(count):
        game = CoopGameState(service, str(i))
        game.character.gold = 0
        service.attach(str(i), game)
    return service


def register_quest(qid="coop_test", kind="kill", count=2, scope="party"):
    return quests.register(
        quests.Quest(
            qid,
            "Shared work",
            [
                quests.Stage(
                    0,
                    "Do the work",
                    condition={"kind": kind, "target": "wolf", "count": count},
                ),
                quests.Stage(10, "Return", condition=None),
                quests.Stage(20, "Finished", finishes=True),
            ],
            rewards={"gold": 10},
            xp=5,
            coop_scope=scope,
        )
    )


def test_four_characters_are_counted_across_connections_and_devices():
    lobby = Lobby()
    a = lobby.add("host", profile())
    lobby.add("host", profile(1))
    lobby.add("guest", profile(2, "keyboard"))
    lobby.add("guest", profile(3, "pad:8"))
    with pytest.raises(LobbyError, match="full"):
        lobby.add("third", profile())
    with pytest.raises(LobbyError, match="belong"):
        lobby.update("guest", a.player_id, profile())
    lobby.ready("host", True)
    lobby.ready("guest", True)
    with pytest.raises(LobbyError):
        lobby.start("guest")
    lobby.start("host")
    assert lobby.started


def test_appearance_and_device_claims_are_unique_and_changes_reset_readiness():
    lobby = Lobby()
    a = lobby.add("host", profile())
    lobby.ready("host", True)
    with pytest.raises(LobbyError, match="head"):
        lobby.add("guest", profile())
    with pytest.raises(LobbyError, match="device"):
        lobby.add("host", profile(1, "keyboard"))
    lobby.update("host", a.player_id, profile(2, "keyboard"))
    assert not a.ready
    lobby.ready("host", True)
    lobby.start("host")
    with pytest.raises(LobbyError, match="Appearance"):
        lobby.update("host", a.player_id, profile())


def test_campaign_can_start_with_offline_friends_kept_in_the_roster():
    lobby = Lobby()
    lobby.add("host", profile())
    absent = lobby.add("guest", profile(1, "keyboard"))
    absent.connected = False
    lobby.ready("host", True)
    assert lobby.can_start
    lobby.start("host")
    assert len(lobby.members) == 2 and not absent.connected


def test_imported_solo_objective_retains_partial_personal_counter():
    service = party(1)
    q = register_quest()
    service.players["0"].quests.start(q.id)
    service.players["0"].store.set("kills.wolf", "1")
    service.import_legacy_progress()
    service.record("kill", ["wolf"], "new-wolf", "0")
    service.tick()
    assert service.players["0"].quests.stage_of(q.id) == 10


def test_saved_character_can_choose_new_lobby_head_without_changing_build():
    lobby = Lobby()
    saved = lobby.add("host", profile(), character={"level": 8})
    changed = dict(profile(), head=heads.HEAD_IDS[3], name="New appearance")
    lobby.update("host", saved.player_id, changed)
    assert saved.profile["head"] == heads.HEAD_IDS[3]
    changed["class"] = "mage"
    with pytest.raises(LobbyError, match="saved character"):
        lobby.update("host", saved.player_id, changed)


def test_human_host_can_start_with_three_automatically_ready_bots():
    lobby = Lobby()
    lobby.add("host", profile())
    for i in range(1, 4):
        bot = lobby.add("host", profile(i), bot=True)
        assert bot.bot and bot.ready and bot.profile["device"].startswith("bot:")
    assert not lobby.can_start
    lobby.ready("host", True)
    assert lobby.can_start
    lobby.start("host")
    assert sum(m["bot"] for m in lobby.snapshot()["members"]) == 3


def test_bots_use_party_slots_and_cannot_impersonate_human_devices_or_host():
    lobby = Lobby()
    with pytest.raises(LobbyError, match="host"):
        lobby.add("guest", profile(), bot=True)
    forged = dict(profile(), device="bot:spoof")
    with pytest.raises(LobbyError, match="keyboard"):
        lobby.add("guest", forged)
    for i in range(4):
        lobby.add("host", profile(i), bot=True)
    assert not lobby.can_start
    with pytest.raises(LobbyError, match="local character"):
        lobby.ready("host", True)
    with pytest.raises(LobbyError, match="full"):
        lobby.add("host", profile())


def test_imported_campaign_identity_cannot_escape_its_save_folder(monkeypatch):
    from pathlib import Path
    from engine import savegame
    from game.multiplayer.lobby import LobbyController

    root = Path(__file__).resolve().parents[2]
    controller = LobbyController(root, "maps/miniwind_world.json", identity="a" * 64)
    controller.opened = True
    controller.host(local_only=True)
    original = controller.lobby.campaign_id
    monkeypatch.setattr(
        savegame,
        "read",
        lambda path: {
            "map": "miniwind_world.json",
            "coop": {"version": 1, "campaign_id": "../../outside", "members": [{}]},
        },
    )
    with pytest.raises(LobbyError, match="campaign identity"):
        controller.resume_campaign("untrusted.fiosave")
    assert controller.lobby.campaign_id == original
    controller.close()


def test_local_bot_lobby_works_when_lan_discovery_is_unavailable(monkeypatch):
    from pathlib import Path
    from game.multiplayer.lobby import LobbyController

    root = Path(__file__).resolve().parents[2]
    controller = LobbyController(root, "maps/miniwind_world.json", identity="a" * 64)

    def unavailable():
        raise OSError("No network available")

    monkeypatch.setattr(controller.network, "start_browser", unavailable)
    controller.open()
    assert controller.opened and controller.errors
    controller.host(local_only=True)
    controller.request("add", profile=profile())
    for index in range(1, 4):
        controller.request("add_bot", profile=profile(index))
    controller.request("ready", ready=True)
    controller.request("start")
    assert controller.started
    assert controller.network.discovery is None and controller.network.listener is None
    controller.close()


def test_critical_quest_item_is_campaign_owned_even_when_its_finder_leaves():
    service = party(2)
    q = register_quest()
    q.coop_shared_items = ("silver_amulet",)
    inventory.add_item(
        service.players["1"].character.inventory, {"id": "silver_amulet", "qty": 1}
    )
    service.collect_shared_items()
    assert not inventory.has_item(
        service.players["1"].character.inventory, "silver_amulet"
    )
    assert service.quantity("silver_amulet") == 1
    assert service.take("silver_amulet", 1)
    assert service.quantity("silver_amulet") == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("race", "invented"),
        ("class", "invented"),
        ("birthsign", "invented"),
        ("head", "../../x"),
        ("name", "x\n"),
    ],
)
def test_profiles_reject_invalid_content(field, value):
    p = profile()
    p[field] = value
    with pytest.raises(LobbyError):
        validate_profile(p)


def test_input_normalises_diagonals_and_rejects_nonfinite_values():
    frame = InputFrame.from_dict({"move_x": 1, "move_z": 1, "held": ["block"]})
    assert frame.move_x**2 + frame.move_z**2 == pytest.approx(1.0)
    with pytest.raises(LobbyError):
        InputFrame.from_dict({"aim": float("nan")})
    with pytest.raises(LobbyError):
        InputFrame.from_dict({"held": ["give_gold"]})


def test_fragmented_and_coalesced_messages_round_trip():
    decoder = Decoder()
    packet = encode({"type": "hello", "name": "Éowyn"})
    assert decoder.feed(packet[:3]) == []
    assert decoder.feed(packet[3:]) == [{"type": "hello", "name": "Éowyn"}]
    assert len(decoder.feed(packet + packet)) == 2
    with pytest.raises(ValueError):
        Decoder().feed(struct.pack("!I", 2**30))
    with pytest.raises(ValueError):
        Decoder().feed(struct.pack("!I", 2) + b"[]")


def test_import_and_construction_open_no_sockets(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("socket before Multiplayer was shown")

    monkeypatch.setattr(socket, "socket", forbidden)
    service = NetworkService()
    assert service.discovery is None and service.listener is None
    service.close()


def test_leaving_during_hostname_resolution_never_opens_a_late_socket(monkeypatch):
    import threading

    resolving, resolved = threading.Event(), threading.Event()
    opened = []

    def lookup(*args, **kwargs):
        resolving.set()
        assert resolved.wait(2)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 39745))]

    def forbidden(*args, **kwargs):
        opened.append(True)
        raise AssertionError("A closed multiplayer section opened a socket")

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "socket", forbidden)
    service = NetworkService()
    try:
        service.join("delayed-hostname")
        assert resolving.wait(1)
        service.close()
    finally:
        resolved.set()
        if service._connecting is not None:
            service._connecting.join(1)
    assert not opened and not service.connections


def test_leaving_during_accept_does_not_leave_a_new_peer_alive(monkeypatch):
    import threading
    from types import SimpleNamespace
    from game.multiplayer.transport import Connection

    accepting, accepted = threading.Event(), threading.Event()
    closed, started = [], []
    sock = SimpleNamespace(
        close=lambda: closed.append(True), shutdown=lambda *args: None
    )

    def accept():
        accepting.set()
        assert accepted.wait(2)
        return sock, ("127.0.0.1", 1234)

    service = NetworkService()
    service.listener = SimpleNamespace(accept=accept, close=lambda: None)
    monkeypatch.setattr(Connection, "start", lambda self: started.append(True))
    service._accept_thread = threading.Thread(target=service._accept)
    service._accept_thread.start()
    try:
        assert accepting.wait(1)
        service.close()
    finally:
        accepted.set()
        service._accept_thread.join(1)
        service.close()
    assert closed and not started and not service.connections


def test_party_kills_are_combined_once_and_rewards_are_once_per_character():
    q = register_quest()
    service = party()
    assert service.start(q.id, "0")
    service.record("kill", ["wolf"], "wolf-a", "1")
    service.record("kill", ["wolf"], "wolf-a", "2")
    service.tick()
    assert service.players["0"].quests.stage_of(q.id) == 0
    service.record("kill", ["wolf"], "wolf-b", "3")
    service.tick()
    assert all(g.quests.stage_of(q.id) == 10 for g in service.players.values())
    service.set_stage(q.id, 20, "2")
    assert all(g.character.gold == 10 for g in service.players.values())
    service.complete(q.id, "1")
    service.complete(q.id, "2")
    assert all(g.character.gold == 10 for g in service.players.values())


def test_personal_admission_does_not_complete_everyones_quest():
    q = register_quest(scope="personal")
    service = party()
    service.start(q.id, "0")
    service.start(q.id, "1")
    service.record("kill", ["wolf"], "a", "0")
    service.record("kill", ["wolf"], "b", "0")
    service.tick()
    service.set_stage(q.id, 20, "0")
    assert service.players["0"].quests.is_complete(q.id)
    assert service.players["1"].quests.stage_of(q.id) == 0
    assert not service.players["2"].quests.state_of(q.id)


def test_split_fetch_hand_in_is_exact_and_failed_compound_action_rolls_back():
    service = party(2)
    inventory.add_item(
        service.players["0"].character.inventory, {"id": "wolf", "qty": 2}
    )
    inventory.add_item(
        service.players["1"].character.inventory, {"id": "wolf", "qty": 3}
    )
    assert service.take("wolf", 5)
    assert service.quantity("wolf") == 0
    copy.deepcopy(service.store.all())

    def broken():
        service.store.set("quest.test.state", "complete")
        service.players["0"].character.gold += 99
        service.take("wolf", 1)

    with pytest.raises(QuestError):
        service.transaction(broken)
    assert service.players["0"].character.gold == 0
    assert service.store.get("quest.test.state", "") == ""


def test_late_arrival_enrols_active_quest_without_receiving_old_rewards():
    service = party(1)
    q = register_quest()
    service.start(q.id, "0")
    second = CoopGameState(service, "late")
    service.attach("late", second)
    second.character.gold = 0
    service.complete(q.id, "0")
    assert second.character.gold == 10
    third = CoopGameState(service, "later")
    service.attach("later", third)
    third.character.gold = 0
    service.complete(q.id, "later")
    assert third.character.gold == 0


def test_solo_quest_log_still_uses_legacy_keys_and_reward_behaviour():
    from game.rpg.game_state import GameState

    q = register_quest()
    store = DictStore()
    game = GameState(store)
    game.character.gold = 0
    assert game.start_quest(q.id)
    assert store.get(f"quest.{q.id}.state") == "active"
    game.complete_quest(q.id)
    game.complete_quest(q.id)
    assert game.character.gold == 10
