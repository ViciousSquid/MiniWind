"""
Editor shortcuts must let go of the keyboard in play mode.

A shortcut on a QAction or a toolbar button is a *window* shortcut: Qt fires it
before the focused widget ever sees the key. So the editor's H (Hide Brush),
T (Asset Browser), X (clip tool) and Shift+S / Shift+B were swallowing those
keys everywhere in play mode — H never reached MiniWind's heal binding, Shift+S
ate walking backwards, and typing a name with an H or a T in it in character
creation silently dropped the letter.

Entering play suspends exactly the single-key shortcuts (alone or with Shift)
and puts them back on the way out. Ctrl-, Alt- and function-key shortcuts are
left alone, so Ctrl+S still saves and F5 still toggles play.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from conftest import install_gl_stubs          # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

install_gl_stubs()
try:
    from editor.main_window import MainWindow
except Exception as exc:                       # pragma: no cover - env-specific
    pytest.skip(f"editor.main_window is not importable here ({exc})",
                allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Window(QtWidgets.QMainWindow):
    """A window carrying the editor's real mix of shortcut owners."""

    _suspend_editor_shortcuts = MainWindow._suspend_editor_shortcuts
    _restore_editor_shortcuts = MainWindow._restore_editor_shortcuts

    def __init__(self):
        super().__init__()
        self.owners = {}
        for label, key in (("hide", "H"), ("unhide", "Shift+H"),
                           ("assets", "T"), ("save", "Ctrl+S"),
                           ("sysmon", "F3"), ("play", "F5")):
            action = QtWidgets.QAction(label, self)
            action.setShortcut(key)
            self.addAction(action)
            self.owners[label] = action
        for label, key in (("clip", "X"), ("scale", "Shift+S"),
                           ("brush", "Shift+B"), ("export", "Ctrl+Shift+E")):
            button = QtWidgets.QPushButton(label, self)
            button.setShortcut(key)
            self.owners[label] = button

    def live(self):
        return {label: owner.shortcut().toString()
                for label, owner in self.owners.items()
                if not owner.shortcut().isEmpty()}


@pytest.fixture
def win(app):
    window = _Window()
    yield window
    window.deleteLater()
    app.processEvents()


#: The ones that collide with gameplay or with typing a name.
STOLEN = {"hide", "unhide", "assets", "clip", "scale", "brush"}
#: The ones a player will never press by accident.
KEPT = {"save", "sysmon", "play", "export"}


def test_play_mode_releases_the_keys_the_game_needs(win):
    win._suspend_editor_shortcuts()
    live = win.live()
    for label in STOLEN:
        assert label not in live, f"{label} is still holding its key"


def test_modifier_and_function_shortcuts_keep_working(win):
    win._suspend_editor_shortcuts()
    live = win.live()
    for label in KEPT:
        assert label in live, f"{label} should not have been suspended"
    assert live["save"] == "Ctrl+S"
    assert live["play"] == "F5"


def test_button_shortcuts_are_suspended_too(win):
    """The tool strip's X / Shift+S are buttons, and just as much a window shortcut."""
    win._suspend_editor_shortcuts()
    assert win.owners["clip"].shortcut().isEmpty()
    assert win.owners["scale"].shortcut().isEmpty()


def test_leaving_play_gives_every_shortcut_back(win):
    before = win.live()
    win._suspend_editor_shortcuts()
    win._restore_editor_shortcuts()
    assert win.live() == before


def test_suspending_twice_does_not_lose_the_originals(win):
    """Two enter_play_mode calls must not leave the editor permanently mute."""
    before = win.live()
    win._suspend_editor_shortcuts()
    win._suspend_editor_shortcuts()
    win._restore_editor_shortcuts()
    assert win.live() == before


def test_restoring_without_suspending_is_harmless(win):
    before = win.live()
    win._restore_editor_shortcuts()
    assert win.live() == before


def test_a_deleted_owner_does_not_break_the_restore(win, app):
    win._suspend_editor_shortcuts()
    win.owners.pop("clip").deleteLater()
    app.processEvents()
    win._restore_editor_shortcuts()             # must not raise
    assert win.owners["hide"].shortcut().toString() == "H"
