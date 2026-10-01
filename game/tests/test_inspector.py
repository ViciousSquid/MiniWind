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


# ------------------------------------------------------------ place links

class _FocusLogic(_Logic):
    def __init__(self, things, session):
        super().__init__(things, session)
        self.camera_focus = None
        self.glides = []

    def set_camera_focus(self, point=None, glide=True):
        self.camera_focus = None if point is None else tuple(point)
        self.glides.append(glide)


class _Named(_Session):
    def __init__(self, places, things):
        super().__init__(places)
        self.things = things

    def _find_named(self, name):
        return next((t for t in self.things if t.properties.get("name") == name), None)


def _linked_world():
    forge = _Thing((300.0, 0.0, 400.0), type="marker", name="thalen_forge")
    smith = _Thing((0.0, 0.0, 0.0), type="npc", display_name="Thalen",
                   schedule=SCHEDULE, home=[10.0, 0.0, 20.0],
                   work_location="thalen_forge")
    session = _Named({}, [forge, smith])
    logic = _FocusLogic([forge, smith], session)
    view = _View(logic)
    return smith, forge, logic, view


def test_schedule_places_resolve_to_where_they_are(qt_app):
    smith, forge, logic, _view = _linked_world()
    session = logic._miniwind
    assert inspector.resolve_place(session, smith, "home") == ([10.0, 0.0, 20.0], None, "home")
    pos, entity, label = inspector.resolve_place(session, smith, "work")
    assert (pos, entity) == ([300.0, 0.0, 400.0], forge) and "thalen_forge" in label
    assert inspector.resolve_place(session, smith, "thalen_forge")[1] is forge
    assert inspector.resolve_place(session, smith, "nowhere") is None


def test_a_place_link_swings_the_camera_there_and_back(qt_app):
    smith, forge, logic, view = _linked_world()
    win = inspector.open_inspector(view, smith)
    win._place_action("work")()
    assert logic.camera_focus == (300.0, 0.0, 400.0)
    assert inspector.focused_place(logic)["entity"] is forge   # its sprite is shown
    assert any(kind == "back" for kind, _t, _v in win.build_rows())

    win._place_action("work")()                     # the same link again: back
    assert logic.camera_focus is None and inspector.focused_place(logic) is None


def test_home_or_another_tool_moving_the_camera_drops_the_beacon(qt_app):
    smith, forge, logic, view = _linked_world()
    win = inspector.open_inspector(view, smith)
    win._place_action("home")()
    logic.set_camera_focus(None, glide=False)       # HOME in the view
    assert inspector.focused_place(logic) is None


def test_closing_the_window_snaps_the_camera_back(qt_app):
    smith, forge, logic, view = _linked_world()
    win = inspector.open_inspector(view, smith)
    win._place_action("home")()
    win.on_close()
    assert logic.camera_focus is None and logic.glides[-1] is False


def test_walking_brings_the_camera_back(qt_app):
    smith, forge, logic, view = _linked_world()
    win = inspector.open_inspector(view, smith)
    win._place_action("home")()

    class _Ctx:
        def __init__(self, down):
            self.down = down

        def key_down(self, name):
            return name in self.down

    inspector.cancel_focus_on_move(logic, _Ctx(set()))
    assert logic.camera_focus is not None
    inspector.cancel_focus_on_move(logic, _Ctx({"w"}))
    assert logic.camera_focus is None
