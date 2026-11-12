"""A launch straight into the game builds the editor dormant: hidden, its
panels unfilled, doing no work until the player leaves fullscreen
(``MainWindow(dormant=True)``, ``begin_dormant_launch``)."""

import pytest
from PyQt5.QtWidgets import QDockWidget

pytestmark = pytest.mark.qt


@pytest.fixture
def dormant_window(qt_app, tmp_path, monkeypatch):
    import conftest
    from editor.main_window import MainWindow
    monkeypatch.chdir(tmp_path)
    window = MainWindow(conftest._ROOT, dormant=True)
    window.begin_dormant_launch()
    window.show()
    qt_app.processEvents()
    if qt_app.platformName() == "offscreen":
        window.view_3d._start_logic_thread()
    try:
        yield window
    finally:
        window.unsaved_changes = False
        window.close()
        window.deleteLater()
        conftest._flush_deferred_deletes(qt_app)


def _tabs(window):
    from editor.asset_browser import AssetBrowserTab
    return window.asset_browser.findChildren(AssetBrowserTab)


def _level():
    return {'version': 3, 'brushes': [
        {'id': 'b%d' % i, 'pos': [i * 64, 0, 0], 'size': [64, 64, 64]} for i in range(5)],
        'things': [{'type': 'playerstart', 'pos': [0, 40, 0], 'properties': {'id': 'start'}}]}


def test_the_dormant_editor_is_hidden_and_its_asset_browser_unfilled(dormant_window):
    w = dormant_window
    assert w.editor_dormant
    assert not w.menuBar().isVisible() and not w.statusBar().isVisible()
    hidden = [d for d in w.findChildren(QDockWidget) if d is not w.view_3d_dock]
    assert hidden and not any(d.isVisible() for d in hidden)
    assert w.view_3d_dock.isVisible()
    tabs = _tabs(w)
    assert tabs and all(t._initial_load_pending and not t.items for t in tabs)


def test_a_level_loaded_while_dormant_does_not_build_the_hierarchy(dormant_window):
    w = dormant_window
    w.state.load_from_data(_level(), save_undo=False)
    w.update_all_ui()
    assert w.scene_hierarchy._refresh_deferred
    assert w.scene_hierarchy.tree.topLevelItemCount() == 0


def test_entering_the_game_keeps_the_saved_editor_layout(dormant_window, monkeypatch):
    w = dormant_window
    saved = []
    monkeypatch.setattr(type(w), 'save_layout', lambda self: saved.append(1))
    monkeypatch.setattr(type(w), 'enter_play_mode', lambda self: None)
    w.enter_kiosk_mode()
    assert w.is_kiosk_mode and w.editor_dormant
    assert saved == [], "the hidden chrome must not be saved as the editor's layout"
    assert not w._dormant_launch


def test_leaving_fullscreen_wakes_every_deferred_panel(dormant_window, monkeypatch, qt_app):
    w = dormant_window
    monkeypatch.setattr(type(w), 'enter_play_mode', lambda self: None)
    w.state.load_from_data(_level(), save_undo=False)
    w.update_all_ui()
    w.enter_kiosk_mode()
    w.exit_kiosk_mode(keep_play_mode=True)
    qt_app.processEvents()
    assert not w.editor_dormant
    w.scene_hierarchy_dock.setVisible(True)
    w.asset_browser_dock.setVisible(True)
    qt_app.processEvents()
    assert not w.scene_hierarchy._refresh_deferred
    assert w.scene_hierarchy.tree.topLevelItemCount() > 0
    shown = [t for t in _tabs(w) if t.isVisible()]
    assert shown and all(not t._initial_load_pending for t in shown)


def test_a_dormant_launch_that_never_reaches_the_game_wakes_the_editor(dormant_window, qt_app):
    w = dormant_window
    w.wake_editor()
    qt_app.processEvents()
    assert not w.editor_dormant
    assert w.menuBar().isVisible() and w.statusBar().isVisible()


def test_an_ordinary_editor_start_fills_its_panels(main_window):
    assert not main_window.editor_dormant
    assert all(not t._initial_load_pending for t in _tabs(main_window))


def test_a_dormant_editor_does_not_autosave(dormant_window, monkeypatch):
    w = dormant_window
    written = []
    monkeypatch.setattr(type(w), '_write_autosave', lambda self: written.append(1))
    w.unsaved_changes = True
    w.autosave()
    assert written == []
    w.wake_editor()
    w.autosave()
    assert written == [1]
