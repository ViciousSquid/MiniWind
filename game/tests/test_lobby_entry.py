"""Into the lobby with a character, and no starting without one.

A friend who had joined a party but had no character in it (their "Add local
player" was refused: both computers offer the same head first) was taken
into the adventure as an onlooker when the host pressed Start -- one player
on the screen where there should have been two. So:

* a joiner brings its character with it and is in the party at once, with a
  free head should its own be taken;
* the host cannot start while a connected computer has no character;
* Start is the host's own Ready, and one player's change clears only their
  own readiness;
* the launcher's lobby needs one press: Ready for a joiner, Start for the
  host.
"""

from __future__ import annotations

import pytest

from game.multiplayer import friend_code as fc
from game.multiplayer.lobby import LobbyController
from game.multiplayer.model import Lobby, LobbyError, default_profile, start_blocker
from game.rpg import heads
from game.tests.test_multiplayer import profile
from game.tests.test_multiplayer_network import ROOT, advance, guest, host


def _guest_with_character(server, character, identity="b" * 64):
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity=identity)
    client.opened = True
    client.signature = "matching-build"
    client.profile = character
    client.join("127.0.0.1", server.network.port)
    return client


def _mine(controller):
    return [m for m in (controller.state or {}).get("members", [])
            if m["owner"] == controller.owner]


# -- the rules ----------------------------------------------------------------------
def test_a_joiner_is_in_the_party_at_once_with_a_free_head():
    server = host()
    server.request("add", profile=default_profile("Host"))
    # The friend's launcher offers the very same head: that used to refuse them.
    client = _guest_with_character(server, default_profile("Friend"))
    try:
        advance([server, client], lambda: client.state is not None and bool(_mine(client)))
        mine = _mine(client)
        assert [m["profile"]["name"] for m in mine] == ["Friend"]
        assert mine[0]["profile"]["head"] == heads.HEAD_IDS[1]
        assert server.lobby.members[0].profile["head"] == heads.HEAD_IDS[0]
        assert client.state["waiting"] == 0 and not client.errors
    finally:
        client.close()
        server.close()


def test_the_host_cannot_start_over_a_friend_who_has_no_character():
    server = host()
    server.request("add", profile=profile(0))
    server.request("ready", ready=True)
    client = guest(server)                      # connected, but brings no character
    try:
        advance([server, client], lambda: client.state is not None and bool(server.peers))
        assert server.lobby.waiting() == [client.owner]
        assert server.state["waiting"] == 1 and not server.lobby.can_start
        with pytest.raises(LobbyError, match="no character"):
            server.request("start")
        assert not server.started and not server.lobby.started
        client.request("add", profile=profile(1))
        advance([server, client], lambda: bool(_mine(client)))
        with pytest.raises(LobbyError, match="Ready"):
            server.request("start")
        client.request("ready", ready=True)
        advance([server, client], lambda: not start_blocker(server.lobby.snapshot()))
        server.request("start")
        advance([server, client], lambda: client.started)
        assert len(client.state["members"]) == 2
    finally:
        client.close()
        server.close()


def test_a_friend_who_leaves_no_longer_holds_the_start_back():
    server = host()
    server.request("add", profile=profile(0))
    client = guest(server)
    try:
        advance([server, client], lambda: bool(server.peers))
        assert start_blocker(server.lobby.snapshot())
        client.close()
        advance([server], lambda: not server.peers)
        assert not server.lobby.waiting()
        server.request("start")
        assert server.started
    finally:
        client.close()
        server.close()


def test_a_computer_without_a_character_stays_in_the_lobby_at_start():
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity="b" * 64)
    client.signature = "matching-build"
    client.owner = "friend"
    lobby = Lobby(signature="matching-build", map_name="maps/miniwind_world.json")
    lobby.add("host", profile(0))
    lobby.start("host")
    assert client.handle("host", {"type": "start", "state": lobby.snapshot()})
    assert client.state["started"] and not client.started     # the lobby of a running game
    lobby.started = False
    lobby.add("friend", profile(1))
    lobby.started = True
    client.handle("host", {"type": "start", "state": lobby.snapshot()})
    assert client.started
    client.network.close()


def test_start_is_the_hosts_own_ready():
    lobby = Lobby()
    mine = lobby.add("host", profile(0))
    friend = lobby.add("friend", profile(1))
    assert start_blocker(lobby.snapshot()) == f"Waiting for {friend.profile['name']} to press Ready."
    lobby.ready("friend", True)
    assert not mine.ready and not start_blocker(lobby.snapshot())
    lobby.start("host")
    assert lobby.started and mine.ready


def test_one_players_change_clears_only_their_own_readiness():
    lobby = Lobby()
    lobby.add("host", profile(0))
    friend = lobby.add("friend", profile(1))
    lobby.ready("friend", True)
    other = lobby.add("other", profile(2))          # somebody else arrives
    assert friend.ready and not other.ready
    lobby.update("other", other.player_id, profile(3))
    assert friend.ready
    lobby.update("friend", friend.player_id, dict(profile(1), name="Renamed"))
    assert not friend.ready


def test_a_full_party_turns_a_joiner_away_at_the_door():
    server = host()
    for i in range(4):
        server.request("add", profile=profile(i, "keyboard" if i == 0 else f"pad:{i}"))
    client = _guest_with_character(server, default_profile("Fifth"))
    try:
        advance([server, client], lambda: bool(client.errors))
        assert "full" in client.errors[0]
        assert not server.peers and not server.lobby.waiting()
    finally:
        client.close()
        server.close()


def test_a_newcomer_to_a_running_game_chooses_before_entering():
    """Late arrival: the character cannot be changed once it is in the game,
    so it is not put in for the newcomer -- they join from their lobby."""
    server = host()
    server.request("add", profile=profile(0))
    server.request("start")
    client = _guest_with_character(server, default_profile("Late"))
    try:
        advance([server, client], lambda: client.state is not None)
        assert client.state["started"] and not _mine(client) and not client.started
        client.request("add", profile=client.profile)
        client.request("ready", ready=True)
        advance([server, client], lambda: client.started)
        assert _mine(client)[0]["profile"]["head"] == heads.HEAD_IDS[1]
    finally:
        client.close()
        server.close()


# -- the launcher's lobby -----------------------------------------------------------
def _dialog(controller, tmp_path=None):
    from game.ui.multiplayer import MultiplayerDialog

    return MultiplayerDialog(
        ROOT, controller=controller,
        profile_path=(tmp_path / "profile.json") if tmp_path is not None else None)


def _pump(controllers, dialogs, predicate):
    def both():
        for dialog in dialogs:
            dialog._render_lobby()
        return predicate()
    advance(controllers, both)


def test_code_to_lobby_to_ready_to_start_is_one_press_each(qt_app, tmp_path):
    server = host()
    hosting = _dialog(server)
    hosting.name.setText("Rufus")
    server.request("add", profile=hosting._profile())
    hosting._render_lobby()
    friend = LobbyController(ROOT, "maps/miniwind_world.json", identity="b" * 64)
    friend.opened = True
    friend.signature = "matching-build"
    joining = _dialog(friend, tmp_path)
    joining.name.setText("Sam")
    try:
        # The friend: the code (here an address) and Join -- nothing else.
        joining.code_entry.setText(f"127.0.0.1:{server.network.port}")
        joining.join_button.click()
        _pump([server, friend], [hosting, joining], lambda: bool(_mine(friend)))
        assert joining.pages.currentIndex() == 1
        assert [m["profile"]["name"] for m in friend.state["members"]] == ["Rufus", "Sam"]
        assert joining.head.currentData() == heads.HEAD_IDS[1]       # a free head, shown
        assert joining.ready_button.isVisibleTo(joining) and joining.ready_button.text() == "Ready"
        assert not joining.start_button.isVisibleTo(joining)
        # The host waits for the friend, and is told so.
        assert not hosting.start_button.isEnabled()
        assert hosting.wait_label.text() == "Waiting for Sam to press Ready."
        assert not hosting.ready_button.isVisibleTo(hosting)
        # A change to the character applies by itself.
        joining.klass.setCurrentIndex(joining.klass.findData("mage"))
        joining._apply_edit()
        _pump([server, friend], [hosting, joining],
              lambda: server.lobby.members[1].profile["class"] == "mage")
        joining.ready_button.click()
        _pump([server, friend], [hosting, joining], lambda: hosting.start_button.isEnabled())
        assert hosting.wait_label.text() == "Everyone is ready!"
        hosting.start_button.click()
        advance([server, friend], lambda: friend.started)
        assert server.started and len(friend.state["members"]) == 2
        # The friend's character is remembered for next time.
        remembered = _dialog(LobbyController(ROOT, "maps/miniwind_world.json", identity="c" * 64),
                             tmp_path)
        assert remembered.name.text() == "Sam" and remembered.klass.currentData() == "mage"
        remembered.controller.network.close()
    finally:
        friend.close()
        server.close()


def test_a_head_somebody_else_wears_cannot_be_picked(qt_app):
    server = host()
    hosting = _dialog(server)
    server.request("add", profile=hosting._profile())
    server.lobby.add("friend", dict(profile(1), head=heads.HEAD_IDS[5]))
    server._publish()
    hosting._render_lobby()
    model = hosting.head.model()
    taken = hosting.head.findData(heads.HEAD_IDS[5])
    own = hosting.head.findData(heads.HEAD_IDS[0])
    assert not model.item(taken).isEnabled()
    assert model.item(own).isEnabled() and model.item(taken + 1).isEnabled()
    server.close()


def test_nobody_removes_their_own_last_character(qt_app):
    server = host()
    hosting = _dialog(server)
    server.request("add", profile=hosting._profile())
    hosting._render_lobby()
    hosting.members.setCurrentRow(0)
    assert not hosting.remove_button.isEnabled()
    hosting._add_bot()
    assert hosting._selected()["bot"] and hosting.remove_button.isEnabled()
    assert hosting.form_box.title() == "AI companion"
    assert hosting.start_button.isEnabled()                 # a host and a bot: go
    server.close()


def test_pasting_a_whole_friend_code_joins_by_itself(qt_app):
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity="c" * 64)
    client.opened = True
    joined = []
    client.join_code = lambda text, tcp=False: joined.append((text, tcp))
    dialog = _dialog(client)
    code = fc.encode("203.0.113.7", 40001, 4242)
    dialog.code_entry.setText(code[:-1])                    # not a whole code yet
    dialog.code_entry.setText("192.168.1.9")                # an address: waits for Join
    assert not joined
    dialog.code_entry.setText(code)
    assert joined == [(code, False)]
    assert client.profile["name"] == "Adventurer" and client.profile["device"] == "keyboard"
    dialog.join_button.click()                              # already on its way in
    assert len(joined) == 1
    client.network.close()
