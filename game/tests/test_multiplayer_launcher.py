"""The visible multiplayer section, rather than launcher construction, owns IO."""

from pathlib import Path

from game.ui.launcher import Launcher
from game.ui.multiplayer import MultiplayerDialog


class DormantController:
    def __init__(self):
        self.opened = 0
        self.closed = 0
        self.started = False
        self.state = None
        self.errors = []

    def open(self):
        self.opened += 1

    def close(self):
        self.closed += 1

    def poll(self):
        pass


def test_launcher_constructs_a_multiplayer_button_without_opening_network(
    qt_app, tmp_path, monkeypatch
):
    import socket

    def forbidden(*a, **k):
        raise AssertionError("launcher opened a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    launcher = Launcher(
        str(Path(__file__).resolve().parents[2]), str(tmp_path / "settings.ini")
    )
    assert launcher.multiplayer_button.text() == "MULTIPLAYER"
    launcher.close()


def test_multiplayer_only_opens_after_becoming_visible_and_closes_on_back(
    qt_app, monkeypatch
):
    controller = DormantController()
    dialog = MultiplayerDialog(
        str(Path(__file__).resolve().parents[2]), controller=controller
    )
    monkeypatch.setattr(dialog, "_refresh_devices", lambda: None)
    assert controller.opened == 0
    dialog.show()
    qt_app.processEvents()
    assert controller.opened == 1
    dialog.reject()
    qt_app.processEvents()
    assert controller.closed >= 1
    assert not dialog.timer.isActive()


def test_host_can_fill_empty_lobby_slots_with_distinct_bot_heads(qt_app):
    from game.multiplayer.lobby import LobbyController
    from game.tests.test_multiplayer import profile

    root = Path(__file__).resolve().parents[2]
    controller = LobbyController(root, "maps/miniwind_world.json", identity="a" * 64)
    controller.opened = True
    controller.host(local_only=True)
    controller.request("add", profile=profile())
    dialog = MultiplayerDialog(root, controller=controller)
    dialog._render_lobby()
    for _ in range(3):
        dialog._add_bot()
    assert len(controller.lobby.members) == 4
    assert sum(m.bot for m in controller.lobby.members) == 3
    assert len({m.profile["head"] for m in controller.lobby.members}) == 4
    assert not dialog.bot_button.isEnabled()
    dialog._ready()
    dialog._render_lobby()
    assert dialog.start_button.isEnabled()
    dialog.close()
