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


def test_multiplayer_button_is_royal_purple_and_under_play_and_edit(qt_app, tmp_path):
    from PyQt5.QtGui import QColor

    launcher = Launcher(
        str(Path(__file__).resolve().parents[2]), str(tmp_path / "settings.ini")
    )
    try:
        button = launcher.multiplayer_button
        launcher.show()
        qt_app.processEvents()
        image = button.grab().toImage()
        centre = QColor(image.pixel(image.width() // 8, image.height() // 2))
        assert (centre.red(), centre.green(), centre.blue()) == (0x78, 0x51, 0xA9)

        # Directly under PLAY and EDIT, spanning exactly the two of them.
        def span(widget):
            left = widget.mapTo(launcher, widget.rect().topLeft())
            return left.x(), left.x() + widget.width(), left.y()

        play, edit, multi = (span(launcher.play_button), span(launcher.edit_button),
                             span(button))
        assert multi[0] == play[0] and multi[1] == edit[1]
        assert multi[2] > play[2] + launcher.play_button.height() - 1
        assert multi[0] > span(launcher.reset_button)[1], "blank space to its left"
    finally:
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


def test_host_can_add_four_ai_companions_on_top_with_distinct_heads(qt_app):
    from game.multiplayer.lobby import LobbyController
    from game.tests.test_multiplayer import profile

    root = Path(__file__).resolve().parents[2]
    controller = LobbyController(root, "maps/miniwind_world.json", identity="a" * 64)
    controller.opened = True
    controller.host(local_only=True)
    controller.request("add", profile=profile())
    dialog = MultiplayerDialog(root, controller=controller)
    dialog._render_lobby()
    dialog.respawn_at_village.setChecked(True)
    assert controller.lobby.respawn_at_village
    for _ in range(4):
        dialog._add_bot()
    assert len(controller.lobby.members) == 5
    assert sum(m.bot for m in controller.lobby.members) == 4
    assert len({m.profile["head"] for m in controller.lobby.members}) == 5
    assert not dialog.bot_button.isEnabled()         # four AI at most
    assert dialog.add_button.isEnabled()             # humans still have room
    dialog._ready()
    dialog._render_lobby()
    assert dialog.start_button.isEnabled()
    dialog.close()
