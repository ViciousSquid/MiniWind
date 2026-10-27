"""The HUD's movable, collapsible panels (:mod:`game.ui.hud_layout`)."""

import configparser
import json

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtGui  # noqa: E402
from PyQt5.QtCore import QPoint, QRect  # noqa: E402

from game.ui import hud_layout as layout  # noqa: E402

pytestmark = pytest.mark.qt

W, H = 1280, 720


@pytest.fixture(autouse=True)
def fresh():
    config = configparser.ConfigParser()
    saves = []
    layout.configure(config, lambda: saves.append(1))
    layout._rects.clear()
    layout._drawn.clear()
    layout.arranging = False
    yield config, saves
    layout.configure(None)
    layout._rects.clear()
    layout._drawn.clear()
    layout.arranging = False


class _Painter:
    """Records the translation a panel is drawn under."""

    def __init__(self):
        self.offset = (0, 0)

    def save(self):
        pass

    def restore(self):
        self.offset = (0, 0)

    def translate(self, dx, dy):
        self.offset = (dx, dy)


def _draw(pid, rect=QRect(100, 100, 200, 50)):
    painter = _Painter()
    seen = []
    layout.begin_frame()
    layout.panel(painter, pid, lambda: seen.append(painter.offset) or rect, W, H)
    return seen


def test_a_panel_draws_where_it_was_put():
    _draw("clock")
    layout.move_to("clock", 40, -30, W, H)
    assert _draw("clock") == [(40, -30)]
    assert layout.screen_rect("clock", W, H) == QRect(140, 70, 200, 50)


def test_a_panel_is_held_on_screen():
    _draw("clock")
    layout.move_to("clock", -5000, 9000, W, H)
    r = layout.screen_rect("clock", W, H)
    assert r.left() == 0 and r.bottom() == H - 1


def test_a_collapsed_panel_draws_nothing_and_leaves_a_tab(fresh):
    _config, saves = fresh
    _draw("dice")
    layout.toggle("dice")
    assert saves                                   # saved at once
    assert _draw("dice") == []
    assert not layout.visible("dice")
    tab = layout.tab_rect("dice", W, H)
    assert layout.hit(tab.center(), W, H) == ("toggle", "dice")
    layout.toggle("dice")
    assert _draw("dice") == [(0, 0)]


def test_the_collapse_button_is_on_the_panels_corner_while_it_shows():
    _draw("quest")
    button = layout.button_rect("quest", W, H)
    assert button.topLeft() == QRect(100, 100, 200, 50).topRight() + QPoint(2, 0)
    assert layout.hit(button.center(), W, H) == ("toggle", "quest")
    layout.begin_frame()                           # a frame it did not draw in
    assert layout.hit(button.center(), W, H) is None


def test_the_layout_is_saved_and_read_back(fresh):
    config, _saves = fresh
    _draw("active")
    layout.move_to("active", -20, 15, W, H)
    layout.toggle("toasts")
    layout.save()
    saved = json.loads(config.get("HUD", "layout"))
    assert saved["active"]["dx"] == -20 and saved["toasts"]["collapsed"]
    layout.configure(config)
    assert layout.offset("active") == (-20, 15)
    assert layout.collapsed("toasts")


def test_reset_puts_everything_back(fresh):
    _draw("clock")
    layout.move_to("clock", 30, 30, W, H)
    layout.toggle("rolls")
    layout.reset()
    assert layout.offset("clock") == (0, 0) and not layout.collapsed("rolls")


def test_the_status_frame_is_not_a_panel():
    assert not {"minimap", "bars", "frame", "health"} & set(layout.PANELS)


def test_in_rearrange_mode_panels_are_dragged_and_buttons_answer():
    layout.arranging = True
    # Every panel is outlined even before it has ever shown.
    for pid in layout.PANELS:
        assert not layout.screen_rect(pid, W, H).isEmpty()
    buttons = layout.arrange_buttons(W, H)
    assert layout.hit(buttons["done"].center(), W, H) == ("done",)
    assert layout.hit(buttons["reset"].center(), W, H) == ("reset",)
    compass = layout.screen_rect("compass", W, H)
    assert layout.hit(compass.center() + QPoint(-40, 0), W, H) == ("drag", "compass")


def _mouse(kind, x, y):
    return QtGui.QMouseEvent(kind, QtCore.QPointF(x, y), QtCore.Qt.LeftButton,
                             QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)


def test_the_hud_window_drags_a_panel_and_finishes(qt_app):
    win = layout.HudWindow()
    win.place(W, H)
    assert not win.hit(QPoint(W // 2, H // 2))     # in play, only its buttons
    layout.start_arranging()
    assert win.hit(QPoint(W // 2, H // 2))         # rearranging: every click
    start = layout.screen_rect("compass", W, H).center() + QPoint(-40, 0)
    assert win.handle_mouse_press(_mouse(QtCore.QEvent.MouseButtonPress, start.x(), start.y()))
    assert win.mouse_captured
    win.handle_mouse_move(_mouse(QtCore.QEvent.MouseMove, start.x() + 50, start.y() + 70),
                          W, H)
    win.handle_mouse_release(_mouse(QtCore.QEvent.MouseButtonRelease, 0, 0))
    assert layout.offset("compass") == (50, 70)
    done = layout.arrange_buttons(W, H)["done"].center()
    win.handle_mouse_press(_mouse(QtCore.QEvent.MouseButtonPress, done.x(), done.y()))
    assert not layout.arranging


def test_the_chrome_paints(qt_app):
    image = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QtGui.QPainter(image)
    try:
        _draw("dice")
        layout.toggle("rolls")
        layout.draw_chrome(painter, W, H)
        layout.arranging = True
        layout.draw_chrome(painter, W, H, pointer=(W // 2, H // 2))
    finally:
        painter.end()


class _Runtime:
    def __init__(self):
        self.held = {}

    def set_world_paused(self, owner, paused):
        self.held[owner] = paused


def _play_session():
    from types import SimpleNamespace
    return SimpleNamespace(
        needs_char_creation=False, dialogue=None, open_screen=None,
        game=SimpleNamespace(character=SimpleNamespace(is_dead=False)),
        logic=SimpleNamespace(session_runtime=_Runtime()))


def test_the_host_keeps_the_hud_window_on_top_and_pauses_while_arranging(qt_app):
    from types import SimpleNamespace
    from engine.floating_windows import FloatingWindow, WindowManager
    from game.host import MiniwindGame
    host = MiniwindGame.__new__(MiniwindGame)
    wm = WindowManager()
    wm.add(FloatingWindow("strip"))
    viewport = SimpleNamespace(window_manager=wm)
    session = _play_session()
    host._sync_hud_window(session, viewport, W, H)
    assert isinstance(wm.windows[-1], layout.HudWindow)
    layout.start_arranging()
    host._sync_hud_window(session, viewport, W, H)
    assert session.logic.session_runtime.held["hud_arrange"] is True
    session.open_screen = "inventory"              # a screen ends rearranging
    host._sync_hud_window(session, viewport, W, H)
    assert not layout.arranging
    assert session.logic.session_runtime.held["hud_arrange"] is False
    assert not any(isinstance(w, layout.HudWindow) for w in wm.windows)


def test_a_new_session_never_starts_rearranging(qt_app):
    from types import SimpleNamespace
    from engine.floating_windows import WindowManager
    from game.host import MiniwindGame
    host = MiniwindGame.__new__(MiniwindGame)
    layout.arranging = True                        # left over from the last game
    session = _play_session()
    host._sync_hud_window(session, SimpleNamespace(window_manager=WindowManager()), W, H)
    assert not layout.arranging
    assert session.logic.session_runtime.held.get("hud_arrange") in (None, False)
