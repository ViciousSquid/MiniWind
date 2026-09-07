"""
The editor's default dock arrangement.

On a first run — no ``[Layout]`` in settings.ini — the docks lay out by
proportion: the scene tree down the left, then the 3D view and the Properties /
Debug Console column splitting what is left 50:50. View ▸ Restore Layout puts
that back at any time. The asset browser is a tool you open when you want it,
not a pane that eats a strip of the 3D view on every launch.

Run against a minimal QMainWindow carrying real QDockWidgets, like the other
window-rule tests here: a full MainWindow builds an OpenGL viewport and a logic
thread, which is both unnecessary for a layout rule and unstable to leave lying
around in a shared Qt process. The methods bound below are MainWindow's own.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from conftest import install_gl_stubs          # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
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
    """The docks apply_default_layout arranges, and nothing else."""

    apply_default_layout = MainWindow.apply_default_layout
    restore_layout = MainWindow.restore_layout
    has_saved_layout = MainWindow.has_saved_layout
    DEFAULT_SCENE_FRACTION = MainWindow.DEFAULT_SCENE_FRACTION
    DEFAULT_VIEW_3D_FRACTION = MainWindow.DEFAULT_VIEW_3D_FRACTION
    DEFAULT_PROPERTIES_FRACTION = MainWindow.DEFAULT_PROPERTIES_FRACTION

    def __init__(self):
        super().__init__()
        self.config = configparser.ConfigParser()
        self.toasts = []

        def dock(title, name, area):
            d = QtWidgets.QDockWidget(title, self)
            d.setObjectName(name)
            d.setWidget(QtWidgets.QWidget())
            self.addDockWidget(area, d)
            return d

        right = QtCore.Qt.RightDockWidgetArea
        self.scene_hierarchy_dock = dock("Scene", "SceneDock",
                                         QtCore.Qt.LeftDockWidgetArea)
        self.view_3d_dock = dock("3D View", "View3DDock", right)
        self.right_dock = dock("2D Views", "2DViewsDock", right)
        self.properties_dock = dock("Properties", "PropertiesDock", right)
        self.asset_browser_dock = dock("Assets", "AssetBrowserDock", right)

        # What the editor's own startup visibility settings leave behind: the 2D
        # views off, the properties column on.
        self.right_dock.setVisible(False)
        # The scene dock is capped at 10% of the *screen*; offscreen that screen
        # is tiny, so pin the cap a real 1920-wide display would give it.
        self.scene_hierarchy_dock.setMaximumWidth(192)

    def show_toast(self, message, is_error=False, duration=None):
        self.toasts.append(message)


@pytest.fixture
def win(app):
    window = _Window()
    window.resize(1920, 1080)
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _fraction(window, dock):
    return dock.width() / window.width()


def test_the_3d_view_and_the_properties_column_split_the_space_evenly(win, app):
    win.apply_default_layout()
    app.processEvents()
    view = _fraction(win, win.view_3d_dock)
    props = _fraction(win, win.properties_dock)
    assert view == pytest.approx(props, abs=0.02), "the two panes must be 50:50"
    assert view == pytest.approx(0.45, abs=0.02)


def test_the_scene_tree_keeps_its_tenth(win, app):
    win.apply_default_layout()
    app.processEvents()
    assert _fraction(win, win.scene_hierarchy_dock) == pytest.approx(0.10, abs=0.02)


def test_the_asset_browser_starts_closed(win, app):
    win.asset_browser_dock.setVisible(True)
    win.apply_default_layout()
    app.processEvents()
    assert win.asset_browser_dock.isHidden()


def test_restore_layout_brings_a_dragged_layout_back(win, app):
    win.apply_default_layout()
    app.processEvents()
    # Drag the split hard over to one side, and open the asset browser.
    win.resizeDocks([win.view_3d_dock, win.properties_dock], [1600, 100],
                    QtCore.Qt.Horizontal)
    win.asset_browser_dock.setVisible(True)
    app.processEvents()
    assert _fraction(win, win.view_3d_dock) > 0.6      # genuinely lopsided now

    win.restore_layout()
    app.processEvents()
    assert _fraction(win, win.view_3d_dock) == pytest.approx(
        _fraction(win, win.properties_dock), abs=0.02)
    assert win.asset_browser_dock.isHidden()
    assert win.toasts == ["Layout restored"]


def test_the_2d_views_share_the_right_hand_column_when_shown(win, app):
    """Turning them on must not steal the 3D view's half."""
    win.right_dock.setVisible(True)
    win.apply_default_layout()
    app.processEvents()
    assert _fraction(win, win.view_3d_dock) == pytest.approx(0.45, abs=0.03)
    assert _fraction(win, win.right_dock) == pytest.approx(0.45, abs=0.03)
    assert _fraction(win, win.properties_dock) == pytest.approx(0.45, abs=0.03)


def test_a_saved_layout_in_settings_ini_still_wins_at_startup(win):
    """The proportional default is a fallback, not an override."""
    assert win.has_saved_layout() is False
    win.config.add_section("Layout")
    win.config["Layout"]["geometry"] = "00"
    assert win.has_saved_layout() is False      # a half-written section is not one
    win.config["Layout"]["state"] = "00"
    assert win.has_saved_layout() is True
