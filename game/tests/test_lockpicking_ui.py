"""Qt logical-coordinate input, readable UI and real-time host routing."""
from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")

from ..host import MiniwindGame, SCREEN_PAUSE
from ..ui import hits, screens
from ..ui.lockpicking import LockpickWindow
from .test_lockpicking import _picking, _locked


@pytest.fixture(autouse=True)
def clean_hits():
    hits.clear()
    yield
    hits.clear()


@pytest.mark.parametrize("size,dpr", [((820, 560), 1), ((820, 560), 2), ((410, 280), 2), ((1100, 750), 1.5)])
def test_draw_scales_art_and_button_targets_in_logical_pixels(qt_app, size, dpr):
    s, _ = _picking(_locked(lock_difficulty="master"), skill=5)
    w, h = size
    image = QtGui.QImage(round(w * dpr), round(h * dpr), QtGui.QImage.Format_ARGB32)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QtGui.QPainter(image)
    try:
        hits.begin()
        screens.draw_in_rect(painter, s, 0, 0, w, h)
        hits.end()
    finally:
        painter.end()
    targets = hits.targets()
    assert {"Apply tension", "Leave", "Guide: OFF"} <= {label for _, label in targets}
    assert all(QtCore.QRect(0, 0, w, h).contains(rect) for rect, _ in targets)
    rect = next(r for r, label in targets if label == "Apply tension")
    assert hits.click(rect.center().x(), rect.center().y())
    hits.run_clicks(s)
    assert s.lockpick_attempt.tension


def _mouse(kind, x, y, button=QtCore.Qt.LeftButton, modifiers=QtCore.Qt.NoModifier):
    return QtGui.QMouseEvent(kind, QtCore.QPointF(x, y), button, button, modifiers)


@pytest.mark.parametrize("scale", [.5, 1, 1.5, 2])
def test_same_relative_drag_has_same_effect_at_every_window_scale(qt_app, scale):
    s, _ = _picking()
    win = LockpickWindow("screen:lockpicking", "Lockpicking", lambda *args: None,
                        width=int(820 * scale), body_height=int(560 * scale), x=0, y=0)
    win.session = s
    ox, oy, actual = win._geometry()
    x, y = ox + 232 * actual, oy + 294 * actual
    assert win.handle_mouse_press(_mouse(QtCore.QEvent.MouseButtonPress, x, y))
    win.handle_mouse_move(_mouse(QtCore.QEvent.MouseMove, x, y - 12 * actual), 2000, 1600)
    hits.run_clicks(s)
    assert s.lockpick_attempt.angle == pytest.approx(16, abs=.7)
    assert win.mouse_captured
    win.handle_mouse_release(_mouse(QtCore.QEvent.MouseButtonRelease, -100, -100))
    assert not win.mouse_captured


def test_right_button_releases_outside_window_and_old_drag_cannot_change_another_lock(qt_app):
    s, _ = _picking()
    win = LockpickWindow("screen:lockpicking", "Lockpicking", lambda *a: None, width=820, body_height=560)
    win.session = s
    ox, oy, scale = win._geometry()
    x, y = ox + 232 * scale, oy + 294 * scale
    win.handle_mouse_press(_mouse(QtCore.QEvent.MouseButtonPress, x, y, QtCore.Qt.RightButton))
    hits.run_clicks(s)
    assert s.lockpick_attempt.tension
    win.handle_mouse_release(_mouse(QtCore.QEvent.MouseButtonRelease, -100, -100, QtCore.Qt.RightButton))
    hits.run_clicks(s)
    assert not s.lockpick_attempt.tension
    win._queue("mouse", 20)
    s.close_lockpicking()
    other = _locked(id="other-lock")
    s.logic.things.append(other)
    s.open_container(other)
    hits.run_clicks(s)
    assert s.lockpick_attempt.angle == 0


def test_single_button_controls_toggle_tension_and_escape_wins_over_space():
    from ..ui.lockpicking import handle_input
    s, _ = _picking()
    ctx = SimpleNamespace(delta=.05, key_down=lambda key: False)
    handle_input(s, {"space"}, ctx)
    assert s.lockpick_attempt.tension
    handle_input(s, {"space"}, ctx)
    assert not s.lockpick_attempt.tension
    handle_input(s, {"space", "escape"}, ctx)
    assert s.open_screen is None


def test_fractional_trackpad_motion_is_not_rounded_away(qt_app):
    s, _ = _picking()
    win = LockpickWindow("screen:lockpicking", "Lockpicking", lambda *a: None, width=820, body_height=560)
    win.session = s
    ox, oy, scale = win._geometry()
    x, y = ox + 232 * scale, oy + 294 * scale
    win.handle_mouse_press(_mouse(QtCore.QEvent.MouseButtonPress, x, y))
    win.handle_mouse_move(_mouse(QtCore.QEvent.MouseMove, x, y - .25), 1600, 1200)
    hits.run_clicks(s)
    assert s.lockpick_attempt.angle == pytest.approx(1 / 3)


def _context(delta=.05):
    from plugins.api import TickContext
    return TickContext(delta=delta, keys=frozenset())


def test_host_advances_world_while_picking_but_does_not_route_combat_input(monkeypatch):
    s, _ = _picking()
    s.logic._miniwind = s
    host = MiniwindGame.__new__(MiniwindGame)
    called = []
    old_tick = s.tick
    monkeypatch.setattr(s, "tick", lambda dt: called.append(dt))
    monkeypatch.setattr(host, "_handle_gameplay_input", lambda *a: pytest.fail("combat input leaked"))
    monkeypatch.setattr(host, "_handle_interaction", lambda *a: pytest.fail("interaction input leaked"))
    a = s.lockpick_attempt
    a.angle = a.target
    a.set_tension(True)
    host.on_tick(s.logic, _context())
    assert called == [.05]
    assert a.turn > 0
    assert SCREEN_PAUSE not in getattr(s.logic, "_pause_owners", ())
    # Use the actual simulation as well: its clock must keep advancing.
    before = s.clock.hour
    old_tick(.05)
    assert s.clock.hour > before


def test_external_pause_also_freezes_lock_tension():
    s, _ = _picking()
    s.logic._miniwind = s
    from .. import fio
    fio.set_world_paused(s.logic, "external-menu", True)
    a = s.lockpick_attempt
    a.angle = a.target
    a.set_tension(True)
    MiniwindGame.__new__(MiniwindGame).on_tick(s.logic, _context())
    assert a.turn == 0


def test_close_button_preserves_progress_and_host_uses_lockpick_window(qt_app):
    from engine.floating_windows import WindowManager
    s, chest = _picking()
    s.lockpick_attempt.pins_set = 1
    viewport = SimpleNamespace(window_manager=WindowManager())
    host = MiniwindGame.__new__(MiniwindGame)
    host._sync_overlay_windows(s, viewport, 1280, 800)
    assert isinstance(s._overlay_win, LockpickWindow)
    assert s._overlay_win.wants_cursor
    s._overlay_win.on_close()
    assert s.open_screen is None
    assert chest.properties["lockpick_state"]["pins_set"] == 1


def test_knock_icon_is_a_loadable_spell_icon(qt_app):
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "assets/sprites/spells/knock.png"
    pixmap = QtGui.QPixmap(str(path))
    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (100, 100)
