"""
The ``inspect`` debug window (:mod:`game.ui.inspector`): an actor's schedule,
where it is heading and why, and its AI state, in a floating window that can
be closed; with a line in the world from the actor to its destination.

Run:  python -m pytest game/tests/test_inspector.py -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")

from engine.floating_windows import WindowManager   # noqa: E402
from ..ui import inspector                          # noqa: E402


class _Thing:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = dict(props)


class _Clock:
    hour = 10.0


class _Session:
    clock = _Clock()
    _arrest_guard = None
    _arrest_state = ""
    _arrest_pursuers = ()

    def __init__(self, places):
        self.places = places

    def _schedule_entry(self, npc):
        from ..rpg import schedule as sched
        return sched.evaluate(npc.properties.get("schedule") or [], self.clock.hour)

    def _resolve_location(self, npc, key):
        return self.places.get(key)

    def head_mark(self, npc):
        return None


class _Logic:
    def __init__(self, things, session):
        self.things = things
        self._miniwind = session
        self.player = None


class _View:
    def __init__(self, logic):
        self.logic_thread = logic
        self.window_manager = WindowManager()

    def width(self):
        return 1280

    def height(self):
        return 720

    def update(self):
        pass


SCHEDULE = [{"hour": 6, "state": "IDLE", "location": "home"},
            {"hour": 9, "state": "WORKING", "location": "work"},
            {"hour": 18, "state": "GOING_HOME", "location": "home"}]


def _world():
    smith = _Thing((0.0, 0.0, 0.0), type="npc", npc_role="blacksmith",
                   display_name="Thalen", schedule=SCHEDULE, health=70,
                   sched_state="WORKING")
    session = _Session({"work": [300.0, 0.0, 400.0], "home": [0.0, 0.0, 0.0]})
    logic = _Logic([smith], session)
    return smith, session, logic, _View(logic)


def test_the_destination_follows_the_schedule_unless_something_overrides_it(qt_app):
    smith, session, logic, _view = _world()
    pos, why = inspector.destination(session, logic, smith)
    assert pos == [300.0, 0.0, 400.0] and "work" in why

    smith.properties["_dest"] = [10.0, 0.0, 20.0]          # a chase, an errand
    smith.properties["sched_state"] = "PURSUE"
    assert inspector.destination(session, logic, smith) == ([10.0, 0.0, 20.0], "pursue")

    smith.properties["dead"] = True
    assert inspector.destination(session, logic, smith) is None


def test_a_fight_points_at_whoever_is_being_fought(qt_app):
    smith, session, logic, _view = _world()
    wolf = _Thing((50.0, 0.0, 60.0), type="creature", display_name="Wolf")
    logic.things.append(wolf)
    smith.properties["_aggro_target"] = id(wolf)
    pos, why = inspector.destination(session, logic, smith)
    assert pos == [50.0, 0.0, 60.0] and why == "fighting Wolf"


def test_the_window_shows_the_schedule_with_the_current_entry_marked(qt_app):
    smith, session, logic, view = _world()
    win = inspector.open_inspector(view, smith)
    rows = win.build_rows()
    sched = [(kind, text) for kind, text, _v in rows if kind in ("sched", "sched_now")]
    assert len(sched) == 3
    assert [text for kind, text in sched if kind == "sched_now"][0].startswith("09:00  WORKING")
    values = {text: value for kind, text, value in rows if kind == "row"}
    assert values["Heading to"].startswith("300, 400")
    assert "work" in values["Because"]

    pixmap = QtGui.QPixmap(1280, 720)
    painter = QtGui.QPainter(pixmap)
    try:
        view.window_manager.draw_all(painter)        # paints without error
    finally:
        painter.end()


def test_one_window_per_actor_and_the_close_button_closes_it(qt_app):
    smith, session, logic, view = _world()
    first = inspector.open_inspector(view, smith)
    assert inspector.open_inspector(view, smith) is first
    assert len(view.window_manager.windows) == 1
    assert first.wants_cursor

    rect = first._full_rect()
    press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                              QtCore.QPoint(rect.right() - 10, rect.y() + 10),
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                              QtCore.Qt.NoModifier)
    assert view.window_manager.handle_mouse_press(press)
    assert inspector.open_windows(view) == []
