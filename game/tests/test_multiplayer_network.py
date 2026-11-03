"""Real loopback connections: mixed parties, reconnects and bounded framing."""

import time
from pathlib import Path

from game.multiplayer.lobby import LobbyController
from game.multiplayer.model import Lobby
from game.multiplayer.transport import NetworkService
from game.tests.test_multiplayer import profile

ROOT = Path(__file__).resolve().parents[2]


def advance(controllers, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for controller in controllers:
            controller.poll()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(
        "Loopback session did not reach the expected state: "
        + str([c.errors for c in controllers])
    )


def host():
    network = NetworkService()
    network.host(port=0, address="127.0.0.1")
    controller = LobbyController(
        ROOT, "maps/miniwind_world.json", network=network, identity="a" * 64
    )
    controller.opened = True
    controller.signature = "matching-build"
    controller.lobby = Lobby(
        signature=controller.signature, map_name="maps/miniwind_world.json"
    )
    return controller


def guest(server, identity="b" * 64):
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity=identity)
    client.opened = True
    client.signature = "matching-build"
    client.join("127.0.0.1", server.network.port)
    return client


def test_two_local_players_plus_two_network_players_and_reconnect():
    server = host()
    client = guest(server)
    again = None
    try:
        advance([server, client], lambda: client.state is not None)
        server.request("add", profile=profile(0))
        server.request("add", profile=profile(1))
        client.request("add", profile=profile(2, "keyboard"))
        client.request("add", profile=profile(3, "pad:9"))
        advance(
            [server, client],
            lambda: (
                len(server.lobby.members) == 4 and len(client.state["members"]) == 4
            ),
        )
        client.request("ready", ready=True)
        server.request("ready", ready=True)
        advance([server, client], lambda: server.lobby.can_start)
        ids = [m.player_id for m in server.lobby.members]
        server.request("start")
        advance([server, client], lambda: client.started)
        client.close()
        advance([server], lambda: sum(m.connected for m in server.lobby.members) == 2)
        again = guest(server)
        advance([server, again], lambda: again.started)
        assert [m.player_id for m in server.lobby.members] == ids
        assert all(m.connected for m in server.lobby.members)
    finally:
        client.close()
        if again is not None:
            again.close()
        server.close()
        assert not server.network.connections


def test_mismatched_content_is_rejected_before_a_player_can_join():
    server = host()
    client = guest(server)
    client.signature = "wrong-build"
    try:
        advance([server, client], lambda: bool(client.errors))
        assert "match" in client.errors[0]
        assert not server.peers
        assert not server.lobby.members
    finally:
        client.close()
        server.close()


def test_real_udp_discovery_reports_host_and_custom_game_port():
    server = host()
    browser = NetworkService()
    try:
        server._publish()
        browser.start_browser()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            browser.search("127.0.0.1")
            games = browser.found_games()
            if any(
                g["port"] == server.network.port and g["address"] == "127.0.0.1"
                for g in games
            ):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("LAN host did not reply to UDP discovery")
        found = next(
            g
            for g in browser.found_games()
            if g["port"] == server.network.port and g["address"] == "127.0.0.1"
        )
        assert found["maximum"] == 4 and found["players"] == 0
        assert found["address"] == "127.0.0.1"
        browser.stop_browser()
        assert browser.discovery is None and browser._discovery_thread is None
    finally:
        browser.close()
        server.close()
