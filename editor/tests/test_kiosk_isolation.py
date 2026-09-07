"""
Play mode must not leave marks on the editor's window.

Play mode is presented in the editor's *own* main window — hidden UI,
fullscreen or a fixed resolution — so its size, position and frame have to be
strictly transient. They were not: entering play persisted the layout, and
quitting straight from play persisted the *game's* window as the editor's
layout, so the editor would reopen at the game resolution.

These tests pin the two rules that keep the launcher's display settings out of
the editor, without needing a real MainWindow (which needs OpenGL): they run
the actual methods against a minimal QMainWindow stand-in carrying the same
attributes.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

# ``editor.main_window`` pulls in the render stack at import time, and PyOpenGL
# cannot even be imported on a machine with no GL driver (a CI container, a
# headless build box). The rules under test are pure window bookkeeping and
# touch none of it, so the GL modules are stubbed for the import only — the code
# being exercised below is still MainWindow's own.
def _import_main_window():
    from unittest import mock

    stubbed = {name: mock.MagicMock(name=name) for name in (
        "OpenGL", "OpenGL.GL", "OpenGL.GLU", "OpenGL.GLUT",
        "OpenGL.GL.shaders", "OpenGL.arrays", "OpenGL.arrays.vbo",
    ) if name not in sys.modules}
    with mock.patch.dict(sys.modules, stubbed):
        from editor.main_window import MainWindow
    return MainWindow


try:
    MainWindow = _import_main_window()
except Exception as exc:                       # pragma: no cover - env-specific
    pytest.skip(f"editor.main_window is not importable here ({exc})",
                allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Window(QtWidgets.QMainWindow):
    """Just enough of MainWindow to exercise the layout rules directly.

    The real class cannot be built in a test (it opens an OpenGL context), so
    the three methods under test are bound to this stand-in — the code being
    exercised is MainWindow's own, not a copy of it."""

    save_layout = MainWindow.save_layout
    enter_kiosk_mode = MainWindow.enter_kiosk_mode
    _apply_kiosk_display_mode = MainWindow._apply_kiosk_display_mode
    standalone_play_session = False

    def __init__(self, config_path):
        from unittest import mock

        super().__init__()
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self.config_path = config_path
        self.is_kiosk_mode = False
        self._editor_layout = None

        # The pieces enter_kiosk_mode hides on its way into play. Real widgets
        # where the method calls widget API on them, mocks where it does not,
        # so the method runs to completion exactly as it does in the editor.
        self.view_3d_dock = QtWidgets.QDockWidget("3D", self)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.view_3d_dock)
        self.play_button = QtWidgets.QPushButton("Play", self)
        self.view_3d = mock.MagicMock()
        self.view_3d.play_mode = False
        self.entered_play = False

    def enter_play_mode(self):
        self.entered_play = True

    def save_config(self):
        with open(self.config_path, "w") as f:
            self.config.write(f)


@pytest.fixture
def win(app, tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("[Kiosk]\nwindow_mode = Windowed\nres_width = 1280\n"
                    "res_height = 720\n")
    w = _Window(str(path))
    w.resize(1000, 800)
    w.move(40, 60)
    w.show()
    app.processEvents()
    yield w
    w.close()


def _saved_geometry(win):
    return win.config.get("Layout", "geometry", fallback="")


def test_entering_play_snapshots_the_layout_instead_of_persisting_it(win, app):
    """Entering play must not write to [Layout].

    It used to: launching straight into Play from the launcher overwrote
    whatever layout the user had arranged with the default startup geometry."""
    editor_geometry = win.saveGeometry()

    win.enter_kiosk_mode()
    app.processEvents()

    assert _saved_geometry(win) == "", "nothing was persisted on the way in"
    assert win._editor_layout is not None, "but it was remembered"
    assert win._editor_layout[0] == editor_geometry
    assert win.entered_play, "and play mode actually started"


def test_entering_play_hides_the_editor_ui(win, app):
    win.enter_kiosk_mode()
    app.processEvents()
    assert not win.statusBar().isVisible()
    assert not win.play_button.isVisible()


def test_saving_while_playing_persists_the_editor_window_not_the_game(win, app):
    """Quitting straight from play used to save the game's window as the
    editor's layout, so the editor reopened at the game resolution."""
    editor_geometry = win.saveGeometry()
    win._editor_layout = (editor_geometry, win.saveState())

    # Play mode resizes the same window to the configured game resolution.
    win._apply_kiosk_display_mode()
    app.processEvents()
    assert win.saveGeometry() != editor_geometry, "the game did resize it"

    win.save_layout()          # what closeEvent does on quit
    assert _saved_geometry(win) == editor_geometry.toHex().data().decode()


def test_with_no_play_session_the_live_window_is_what_gets_saved(win):
    win._editor_layout = None
    win.resize(1234, 567)
    win.save_layout()
    assert _saved_geometry(win) == win.saveGeometry().toHex().data().decode()


def test_windowed_play_uses_the_configured_resolution(win, app):
    win._apply_kiosk_display_mode()
    app.processEvents()
    assert (win.width(), win.height()) == (1280, 720)


def test_fullscreen_play_ignores_the_resolution(win, app):
    win.config.set("Kiosk", "window_mode", "Fullscreen")
    win._apply_kiosk_display_mode()
    app.processEvents()
    assert win.isFullScreen()


def test_borderless_play_drops_the_frame_and_remembers_the_old_flags(win, app):
    before = win.windowFlags()
    win.config.set("Kiosk", "window_mode", "Borderless")
    win._apply_kiosk_display_mode()
    app.processEvents()
    assert win.windowFlags() & QtCore.Qt.FramelessWindowHint
    assert win._kiosk_prev_flags == before, "so exiting can put the frame back"


def test_a_launched_game_is_marked_standalone_but_an_editor_preview_is_not(win):
    """Escape's meaning hangs on this flag.

    A session the player came for — the launcher's Play button, or an imported
    package — pauses on Escape and offers the pause menu. Play mode started from
    the editor (including F12's kiosk toggle, which passes nothing) keeps the old
    behaviour: Escape stops the preview and hands the map back.
    """
    win.enter_kiosk_mode(standalone=True)
    assert win.standalone_play_session is True


def test_the_kiosk_toggle_from_inside_the_editor_stays_a_preview(win):
    win.enter_kiosk_mode()
    assert win.standalone_play_session is False
