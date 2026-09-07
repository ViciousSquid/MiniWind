"""
The editor's default dock arrangement.

On a first run — no ``[Layout]`` in settings.ini — the docks lay out by
proportion: the scene tree down the left, then the 3D view and the Properties /
Debug Console column splitting what is left 50:50. View ▸ Restore Layout puts
that back at any time. The asset browser is a tool you open when you want it,
not a pane that eats a strip of the 3D view on every launch.

Builds a real MainWindow (offscreen, GL stubbed where there is no driver) so the
proportions are measured off real docks rather than asserted about the constants.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

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


@pytest.fixture(scope="module")
def win(app):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    window = MainWindow(root)
    # A real MainWindow persists its layout on close, and the layout it would
    # write is the offscreen one. Running the tests must not leave a [Layout] in
    # the developer's settings.ini — which would then override the very default
    # these tests exist to protect.
    window.save_config = lambda *a, **kw: None
    window.unsaved_changes = False
    window.resize(1920, 1080)
    window.show()
    app.processEvents()
    # The scene dock is capped at 10% of the *screen*; offscreen that screen is
    # tiny, so pin the cap a real 1920-wide display would give it.
    window.scene_hierarchy_dock.setMaximumWidth(192)
    yield window
    window.close()


def _fraction(window, dock):
    return dock.width() / window.width()


def test_the_3d_view_and_the_properties_column_split_the_space_evenly(win, app):
    win.apply_default_layout()
    app.processEvents()
    view = _fraction(win, win.view_3d_dock)
    props = _fraction(win, win.properties_dock)
    assert view == pytest.approx(props, abs=0.02), "the two panes must be 50:50"
    assert view == pytest.approx(0.45, abs=0.02)
    assert props == pytest.approx(0.45, abs=0.02)


def test_the_scene_tree_keeps_its_tenth(win, app):
    win.apply_default_layout()
    app.processEvents()
    assert _fraction(win, win.scene_hierarchy_dock) == pytest.approx(0.10, abs=0.02)


def test_the_asset_browser_starts_closed(win, app):
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


def test_a_saved_layout_in_settings_ini_still_wins_at_startup(win):
    """The proportional default is a fallback, not an override."""
    win.config.remove_section("Layout")
    assert win.has_saved_layout() is False
    win.config.add_section("Layout")
    win.config["Layout"]["geometry"] = "00"
    win.config["Layout"]["state"] = "00"
    assert win.has_saved_layout() is True
    win.config.remove_section("Layout")
