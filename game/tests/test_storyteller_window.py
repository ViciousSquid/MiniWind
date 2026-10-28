"""Console-driven floating inspector: live, complete, scrollable and read-only."""

from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QImage, QPainter

from engine.floating_windows import WindowManager
from ..console import ConsoleContext, cmd_storyteller
from ..living.journeys import KINDS
from ..ui.storyteller_window import StorytellerWindow, open_storyteller, rows_for
from .test_storyteller import rising, setup


pytestmark = pytest.mark.qt


class View:
    def __init__(self, story, width=1280, height=720):
        self.logic_thread = SimpleNamespace(_miniwind=SimpleNamespace(storyteller=story))
        self.window_manager = WindowManager()
        self.updates = 0
        self.size = width, height

    def width(self):
        return self.size[0]

    def height(self):
        return self.size[1]

    def update(self):
        self.updates += 1


def paint(win, view):
    image = QImage(view.width(), view.height(), QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        win.draw(painter)
    finally:
        painter.end()


def test_command_opens_one_live_window_and_raises_it_on_repeat(qt_app):
    story, _director, _hooks, _store = setup()
    view = View(story)
    ctx = ConsoleContext(logic_thread=view.logic_thread, play_mode=True,
                         main_window=SimpleNamespace(view_3d=view))
    cmd_storyteller(ctx, "")
    win = view.window_manager.windows[0]
    assert isinstance(win, StorytellerWindow)
    other = object()
    view.window_manager.add(other)
    cmd_storyteller(ctx, "")
    assert view.window_manager.windows == [other, win]
    win.active = False
    assert open_storyteller(view) is not win


def test_all_effective_levers_and_ten_observations_are_live_and_read_only(qt_app):
    story, _director, hooks, store = setup()
    rising(story)
    for i in range(12):
        hooks.health = 0.8
        story.tick(9 + i)
    before = dict(store.d)
    observations = story.observations
    rows = rows_for(story)
    text = "\n".join(text for _kind, text in rows)
    assert f"State: {story.state}" in text
    assert all(f"{kind}: weight" in text for kind in KINDS)
    assert "Road population" in text and "Hunter bounty threshold" in text
    assert "New lair refill delay multiplier" in text and "Market trip chance" in text
    assert "Town destination multiplier" in text and "Vendetta arrival multiplier" in text
    assert text.count("health 80%") == 10
    assert all(o["reason"] in text for o in observations)
    assert [text.index(o["reason"]) for o in observations] == sorted(text.index(o["reason"]) for o in observations)
    assert store.d == before
    story.reset()
    text = "\n".join(text for _kind, text in rows_for(story))
    assert "State: CALM" in text and "No observations yet" in text
    assert f"trader: weight {KINDS['trader']['weight']}" in text  # inherited defaults are visible
    rising(story)
    assert "bandits: weight 6; departs 18:00–06:00 (overnight)" in "\n".join(t for _, t in rows_for(story))


@pytest.mark.parametrize("width,height", [(1280, 720), (640, 360)])
def test_long_history_fits_small_view_and_can_be_scrolled_by_wheel_and_buttons(qt_app, width, height):
    story, _director, _hooks, _store = setup()
    for i in range(12):
        story.tick(i)
    view = View(story, width, height)
    win = open_storyteller(view)
    paint(win, view)
    assert win._full_rect().right() < width and win._full_rect().bottom() < height
    assert win._scroll_max > 0
    assert win.handle_wheel(SimpleNamespace(angleDelta=lambda: QPoint(0, -120)))
    assert win._scroll > 0
    paint(win, view)
    rect, _direction = win._buttons[-1]
    before = win._scroll
    assert win.handle_body_click(rect.center().x(), rect.center().y())
    assert win._scroll > before
    win._scroll_by(100000)
    assert win._scroll == win._scroll_max
    win._scroll_by(-100000)
    assert win._scroll == 0


def test_inspector_survives_session_end_and_can_open_on_new_session(qt_app):
    story, _director, _hooks, _store = setup()
    view = View(story)
    win = open_storyteller(view)
    view.logic_thread._miniwind = None
    paint(win, view)
    assert rows_for(win._storyteller()) == [("text", "No active MiniWind storyteller.")]
    assert open_storyteller(view) is None
    replacement = setup()[0]
    view.logic_thread._miniwind = SimpleNamespace(storyteller=replacement)
    assert open_storyteller(view) is win
    assert win._storyteller() is replacement


def test_studio_drags_a_numeric_cell_into_live_board_data_and_retains_edits(qt_app):
    from ..storyteller import Storyteller
    from .test_storyteller import board

    story, director, hooks, store = setup()
    view = View(story)
    win = open_storyteller(view)
    win.tab, win.edit_state = "Levers", "CALM"
    paint(win, view)
    rect, (path, value) = next(c for c in win._cells if c[1][0] == ("population",))
    point = rect.center()
    assert win.handle_body_click(point.x(), point.y())
    assert win.mouse_captured
    moved = SimpleNamespace(x=lambda: point.x() + 15, y=lambda: point.y())
    assert view.window_manager.handle_mouse_move(moved, view.width(), view.height())
    assert view.window_manager.handle_mouse_release(moved)
    assert not win.mouse_captured
    assert story.levers["population"] == value + 3
    assert board(story)._lever("population", 0) == value + 3
    assert Storyteller(store, director, hooks).levers == story.levers
    assert "Studio edit" in dict(story.inspector_rows())


def test_studio_resize_uses_window_manager_capture_and_reflows_scroll_area(qt_app):
    story, _director, _hooks, _store = setup()
    view = View(story)
    win = open_storyteller(view)
    paint(win, view)
    old_width, old_height = win.width, win.content_height()
    point = win._resize_rect.center()
    press = SimpleNamespace(pos=lambda: point, x=lambda: point.x(), y=lambda: point.y())
    assert view.window_manager.handle_mouse_press(press)
    assert win.mouse_captured
    moved = SimpleNamespace(x=lambda: point.x() + 120, y=lambda: point.y() + 40)
    assert view.window_manager.handle_mouse_move(moved, view.width(), view.height())
    view.window_manager.handle_mouse_release(moved)
    paint(win, view)
    assert win.width == old_width + 120
    assert win.content_height() == old_height + 40
    assert win._full_rect().right() < view.width() and win._full_rect().bottom() < view.height()
    # Explicit size survives painting; smaller viewports still bound the window.
    paint(win, view)
    assert win.width == old_width + 120
    view.size = (640, 360)
    paint(win, view)
    assert win._full_rect().right() < 640 and win._full_rect().bottom() < 360


def test_studio_world_tab_and_causal_history_share_read_only_evidence(qt_app, monkeypatch):
    from .. import sim_editor
    from .test_storyteller import actor, remember

    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    ev, _fact = remember(store, director.bus, witness)
    rising(story)
    view = View(story)
    win = open_storyteller(view)
    win.tab = "World"
    before = dict(store.d), story.observations
    paint(win, view)
    from PyQt5 import QtCore, QtWidgets
    window = sim_editor._WorldWindow(None, QtWidgets, QtCore)
    window._timer.stop()
    session = SimpleNamespace(storyteller=story)
    window._refresh_history(session, director)
    window._refresh_pacing(session)
    threads = next(window.pacing.topLevelItem(i) for i in range(window.pacing.topLevelItemCount())
                   if window.pacing.topLevelItem(i).text(0) == "Unreported threads")
    item = threads.child(0)
    assert "b" in item.text(0) and "theft" in item.text(1)
    assert item.data(0, QtCore.Qt.UserRole) == [ev.id]
    window.pacing.setCurrentItem(item)
    assert window.history.currentItem().data(0, QtCore.Qt.UserRole) == ev.id
    assert (store.d, story.observations) == before
    window.close()
