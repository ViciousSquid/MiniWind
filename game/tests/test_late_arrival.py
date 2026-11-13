"""Late arrival: the host chooses whether players may join a party after the
adventure has started. Off, they can only join in the lobby before Start,
and anyone new is told: "Game has already started and does not allow late
arrival"."""

from __future__ import annotations

import time

import pytest

from game.multiplayer.model import LATE_ARRIVAL_CLOSED, Lobby, LobbyError
from game.tests.test_multiplayer import profile
from game.tests.test_multiplayer_network import advance, guest, host


def test_on_by_default_and_only_the_host_changes_it_before_start():
    lobby = Lobby(host="host")
    assert lobby.late_arrival is True
    with pytest.raises(LobbyError):
        lobby.set_late_arrival("someone", False)
    lobby.set_late_arrival("host", False)
    assert lobby.late_arrival is False and lobby.snapshot()["late_arrival"] is False
    lobby.add("host", profile(0))
    lobby.ready("host", True)
    lobby.start("host")
    with pytest.raises(LobbyError):
        lobby.set_late_arrival("host", True)


def test_closed_party_refuses_new_characters_after_start():
    lobby = Lobby(host="host")
    lobby.set_late_arrival("host", False)
    lobby.add("host", profile(0))
    lobby.ready("host", True)
    lobby.start("host")
    with pytest.raises(LobbyError, match=LATE_ARRIVAL_CLOSED):
        lobby.add("friend", profile(1))


def _started(server, late):
    server.request("late_arrival", enabled=late)
    server.request("add", profile=profile(0))
    server.request("ready", ready=True)
    server.request("start")
    assert server.started


def test_a_newcomer_is_turned_away_from_a_started_closed_game():
    server = host()
    _started(server, False)
    client = guest(server)
    try:
        advance([server, client], lambda: bool(client.errors))
        assert client.errors[0] == "Game has already started and does not allow late arrival"
        assert not server.peers
    finally:
        client.close()
        server.close()


def test_with_late_arrival_a_newcomer_joins_the_running_game():
    server = host()
    _started(server, True)
    client = guest(server)
    try:
        advance([server, client], lambda: client.state is not None and len(server.peers) == 1)
        client.request("add", profile=profile(1, "keyboard"))
        advance([server, client], lambda: len(server.lobby.members) == 2)
    finally:
        client.close()
        server.close()


def test_a_joiners_hello_is_never_handled_before_its_connection(monkeypatch):
    """Under load the new peer's reader can queue its hello before the accept
    thread queues "connected"; the host must still see "connected" first
    (found by running real instances: a late arrival was refused with
    "Handshake already completed")."""
    import game.multiplayer.transport as transport
    real_start = transport.Connection.start

    def reader_wins(self):
        real_start(self)
        if self.peer != "host":
            time.sleep(0.4)      # the accept thread is held; the hello comes in

    monkeypatch.setattr(transport.Connection, "start", reader_wins)
    server = host()
    client = guest(server)
    try:
        advance([server, client], lambda: client.state is not None)
        assert not client.errors
    finally:
        client.close()
        server.close()
