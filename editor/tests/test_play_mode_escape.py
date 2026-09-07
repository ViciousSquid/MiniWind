"""
Escape must always be a way out of play mode.

Play mode launched *from the editor* is a preview, and Escape ends it — but it
was reachable only when nothing else had quietly taken the key first, and two
things routinely did:

  * MiniWind's character creation. Escape was handed to the game plugin
    whenever any screen was open, on the assumption the screen would close.
    Character creation (and the level-up screen) deliberately refuse Escape, so
    the key vanished into them and play mode could not be left at all — which is
    exactly the state a preview starts in.
  * The play console. Its line edit closes itself on Escape only while it holds
    focus; click the viewport behind it and the key arrived at the window with
    the console still up and nothing left to dismiss it.

Both now end up where the player expects, and leaving an editor preview asks
first ("Exit Play mode?") instead of throwing the session away on a stray press.
A game the *player* launched is untouched: Escape still raises the pause menu.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from conftest import install_gl_stubs          # noqa: E402

install_gl_stubs()
try:
    from editor.main_window import MainWindow
except Exception as exc:                       # pragma: no cover - env-specific
    pytest.skip(f"editor.main_window is not importable here ({exc})",
                allow_module_level=True)

Qt = QtCore.Qt


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _PauseMenu:
    def __init__(self):
        self.active = False
        self.opened = 0

    def open(self):
        self.opened += 1


class _View:
    """The 3D view as Escape sees it."""

    def __init__(self):
        self.play_mode = True
        self.pause_mode = False
        self.pause_menu = _PauseMenu()
        self.logic_thread = None
        self.console_overlay_active = False
        self.closed_console = 0
        self.focused = 0

    def _close_console_overlay(self):
        self.closed_console += 1
        self.console_overlay_active = False

    def play_mode_cursor_visible(self):
        return False

    def apply_play_cursor_shape(self):
        pass

    def setFocus(self):
        self.focused += 1


class _Session:
    """A game plugin session, with control over what Escape would close."""

    def __init__(self, closes):
        self._closes = closes
        self.open_screen = None
        self.dialogue = None

    def escape_closes_modal(self):
        return self._closes


class _Window(QtWidgets.QMainWindow):
    """Just enough of MainWindow to run its real Escape handling.

    The real class opens an OpenGL context, so the methods under test are bound
    to this stand-in — the code being exercised is MainWindow's own.
    """

    keyPressEvent = MainWindow.keyPressEvent
    _game_modal_wants_escape = MainWindow._game_modal_wants_escape
    _confirm_exit_play_mode = MainWindow._confirm_exit_play_mode

    def __init__(self):
        super().__init__()
        self.view_3d = _View()
        self.keys_pressed = set()
        self.standalone_play_session = False
        self.is_kiosk_mode = False
        self.camera_movement_learned = True
        self.console_visible = False
        self.exited = 0
        self.confirmed = 0

        self.debug_console = mock.MagicMock()
        self.console_handler = mock.MagicMock()
        self.key_bindings = {}

    # -- the bits Escape leans on ------------------------------------------
    def _is_play_console_visible(self):
        return self.console_visible

    def _hide_play_console_overlay(self):
        self.console_visible = False

    def _exit_play_mode(self):
        self.exited += 1
        self.view_3d.play_mode = False

    def toggle_debug_console(self):
        self.console_visible = not self.console_visible


def _key(key):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, Qt.NoModifier)


@pytest.fixture
def win(app):
    window = _Window()
    yield window
    window.deleteLater()
    app.processEvents()


def _answer(yes):
    """Patch the confirmation box to answer for us, and count the asking."""
    result = QtWidgets.QMessageBox.Yes if yes else QtWidgets.QMessageBox.No
    return mock.patch.object(QtWidgets.QMessageBox, "question", return_value=result)


# ===========================================================================
# Who owns Escape while a game is running
# ===========================================================================
def test_no_plugin_means_escape_belongs_to_play_mode(win):
    assert win._game_modal_wants_escape() is False


def test_a_screen_that_closes_on_escape_gets_the_key(win):
    win.view_3d.logic_thread = mock.Mock(_miniwind=_Session(closes=True))
    assert win._game_modal_wants_escape() is True


def test_a_screen_that_refuses_escape_does_not_get_the_key(win):
    """Character creation would swallow it and leave the player stuck."""
    win.view_3d.logic_thread = mock.Mock(_miniwind=_Session(closes=False))
    assert win._game_modal_wants_escape() is False


def test_an_older_session_falls_back_to_anything_open(win):
    """A plugin without the question is read the way it always was."""
    session = mock.Mock(spec=["open_screen", "dialogue"])
    session.open_screen = "inventory"
    session.dialogue = None
    win.view_3d.logic_thread = mock.Mock(_miniwind=session)
    assert win._game_modal_wants_escape() is True
    session.open_screen = None
    assert win._game_modal_wants_escape() is False


def test_a_session_that_raises_is_not_allowed_to_trap_the_player(win):
    session = mock.Mock(spec=["escape_closes_modal", "open_screen", "dialogue"])
    session.escape_closes_modal.side_effect = RuntimeError("boom")
    session.open_screen = None
    session.dialogue = None
    win.view_3d.logic_thread = mock.Mock(_miniwind=session)
    assert win._game_modal_wants_escape() is False


# ===========================================================================
# Escape in an editor preview
# ===========================================================================
def test_escape_asks_before_leaving_an_editor_preview(win):
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert question.called, "a stray Escape must not silently end the session"
    assert win.exited == 1


def test_saying_no_keeps_playing(win):
    with _answer(yes=False):
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert win.exited == 0
    assert win.view_3d.play_mode is True
    assert win.view_3d.focused, "the game must get the keyboard back"


def test_escape_out_of_character_creation_still_offers_the_way_out(win):
    """The bug: the key used to disappear into a screen that never closes."""
    win.view_3d.logic_thread = mock.Mock(_miniwind=_Session(closes=False))
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert question.called
    assert win.exited == 1


def test_escape_inside_an_ordinary_screen_belongs_to_the_game(win):
    win.view_3d.logic_thread = mock.Mock(_miniwind=_Session(closes=True))
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert not question.called
    assert win.exited == 0
    assert Qt.Key_Escape in win.keys_pressed


def test_the_prompt_pauses_the_world_and_thaws_it_again_on_no(win):
    logic = mock.Mock(gameplay_paused=False, _menu_paused=False)
    win.view_3d.logic_thread = logic
    del logic._miniwind                       # no game plugin, just the thread
    with _answer(yes=False):
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert logic._menu_paused is False
    assert logic.gameplay_paused is False


def test_the_prompt_drops_keys_held_when_escape_landed(win):
    """Otherwise the player walks into a wall while the box is up."""
    win.keys_pressed.update({Qt.Key_W, Qt.Key_D})
    with _answer(yes=False):
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert not win.keys_pressed


# ===========================================================================
# A game the player launched is untouched
# ===========================================================================
def test_a_standalone_session_still_raises_the_pause_menu(win):
    win.standalone_play_session = True
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert win.view_3d.pause_menu.opened == 1
    assert not question.called, "a player's game pauses, it does not ask to quit"
    assert win.exited == 0


def test_an_open_pause_menu_keeps_every_key(win):
    win.view_3d.pause_menu.active = True
    win.view_3d.pause_menu.handle_key = mock.Mock()
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert win.view_3d.pause_menu.handle_key.called
    assert not question.called


# ===========================================================================
# Escape and the console
# ===========================================================================
def test_escape_hides_the_editor_play_console(win):
    win.console_visible = True
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert win.console_visible is False
    assert not question.called, "the console was the thing to dismiss, not play mode"


def test_escape_hides_the_view_console_even_after_focus_drifts(win):
    """Click the viewport behind the overlay and the key lands here instead."""
    win.view_3d.console_overlay_active = True
    with _answer(yes=True) as question:
        win.keyPressEvent(_key(Qt.Key_Escape))
    assert win.view_3d.closed_console == 1
    assert not question.called
    assert win.exited == 0


def test_tilde_also_closes_the_view_console_from_here(win):
    win.view_3d.console_overlay_active = True
    win.keyPressEvent(_key(Qt.Key_QuoteLeft))
    assert win.view_3d.closed_console == 1


def test_gameplay_keys_do_not_reach_the_game_behind_an_open_console(win):
    win.view_3d.console_overlay_active = True
    win.keyPressEvent(_key(Qt.Key_W))
    assert Qt.Key_W not in win.keys_pressed
