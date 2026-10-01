"""The pause menu's MAP page (game/ui/map_page.py)."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt5 import QtCore, QtGui

from ..ui import worldmap
from ..ui.map_page import MIN_SPAN
from .test_pause_menu import _Editor, _View, _choose, _draw, _key
from ..ui.pause_menu import PauseMenu


@pytest.fixture(scope="module")
def app(qt_app):
    yield qt_app


def _world():
    w = worldmap.WorldMap()
    w.bounds = ((-5000.0, 5000.0), (-5000.0, 5000.0))
    w.cell = 10000.0 / 64
    w.rgb = np.full((64, 64, 3), 90, dtype=np.uint8)
    return w


class _MapEditor(_Editor):
    def __init__(self):
        super().__init__()
        self.world = _world()
        self.features = {"player": (100.0, 200.0, 0.0),
                         "places": [("Millbrook", 0.0, 0.0)],
                         "quests": [("The Lost Ring", 3000.0, -1000.0, "ring", True)]}

    def pause_menu_map_data(self):
        return self.world, self.features


def _menu():
    return PauseMenu(_View(_MapEditor()))


def test_map_is_on_the_root_row_and_opens_on_the_player(app):
    menu = _menu()
    menu.open()
    _choose(menu, "MAP")
    assert menu.page == "map"
    assert menu.map.centre == (100.0, 200.0)
    _draw(menu)
    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert menu.page == "root" and menu.active
    assert menu._items()[menu.index][1] == "MAP"


def test_opened_from_play_it_returns_to_play(app):
    menu = _menu()
    menu.open_map((3000.0, -1000.0, "The Lost Ring"))
    assert menu.active and menu.page == "map"
    assert menu.map.centre == (3000.0, -1000.0)
    _draw(menu)
    menu.handle_key(_key(QtCore.Qt.Key_M))
    assert not menu.active


def test_zoom_and_pan_stay_in_bounds_and_space_comes_home(app):
    menu = _menu()
    menu.open_map()
    _draw(menu)
    for _ in range(40):
        menu.handle_key(_key(QtCore.Qt.Key_Plus))
    assert menu.map.span == MIN_SPAN
    for _ in range(40):
        menu.handle_key(_key(QtCore.Qt.Key_Minus))
    assert menu.map.span <= 10000.0 * 1.06
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert menu.map.centre[0] > 100.0
    menu.handle_key(_key(QtCore.Qt.Key_Space))
    assert menu.map.centre == (100.0, 200.0)


def test_wheel_zoom_keeps_the_point_under_the_pointer(app):
    menu = _menu()
    menu.open_map()
    _draw(menu)
    rect = menu.map._rect
    point = QtCore.QPointF(rect.center().x() + 150, rect.center().y() - 80)
    before = menu.map.to_world(rect, point)
    menu.map.handle_wheel(point.toPoint(), 120)
    after = menu.map.to_world(rect, point)
    assert after == pytest.approx(before, abs=1.0)


def test_drag_pans(app):
    menu = _menu()
    menu.open_map()
    _draw(menu)
    menu.map.handle_mouse_press(QtCore.QPoint(400, 300))
    menu.map.handle_mouse_move(QtCore.QPoint(500, 300), QtCore.Qt.LeftButton)
    assert menu.map.centre[0] < 100.0
    menu.map.handle_mouse_release()


def test_features_read_discovered_places_and_quest_objectives():
    class _Q:
        id, name = "ring", "The Lost Ring"

    class _Marker:
        def __init__(self, name, pos, found):
            self.pos = pos
            self.properties = {"place_name": name, "_discovered": found}

    class _Quests:
        def active_quests(self):
            return [_Q()]

    class _Game:
        quests = _Quests()

    class _Player:
        pos = [1.0, 0.0, 2.0]
        angle = 0.5

    class _Logic:
        player = _Player()

    class _Session:
        logic = _Logic()
        game = _Game()

        def _markers_of_kind(self, kind):
            return [_Marker("Millbrook", [5, 0, 6], True),
                    _Marker("Hidden Vale", [9, 0, 9], False)]

        def tracked_quest_id(self):
            return "ring"

        def _arrow_destination(self, q):
            return [30.0, 0.0, 40.0]

    f = worldmap.map_features(_Session())
    assert f["player"] == (1.0, 2.0, 0.5)
    assert f["places"] == [("Millbrook", 5.0, 6.0)]
    assert f["quests"] == [("The Lost Ring", 30.0, 40.0, "ring", True)]


# ----------------------------------------------------- opening from the game
class _Menu:
    def __init__(self):
        self.opened = []

    def open_map(self, focus=None):
        self.opened.append(focus)


class _ViewWithMenu:
    def __init__(self):
        self.play_menu = _Menu()


class _S:
    map_request = None
    open_screen = "quest"


def test_the_host_opens_the_map_for_a_request(app):
    from ..host import MiniwindGame
    serve = MiniwindGame._serve_map_request
    view, session = _ViewWithMenu(), _S()
    session.map_request = (30.0, 40.0, "The Lost Ring")
    serve(session, view)
    assert session.map_request is None and session.open_screen is None
    app.processEvents()
    assert view.play_menu.opened == [(30.0, 40.0, "The Lost Ring")]
    session.map_request = "player"
    serve(session, view)
    app.processEvents()
    assert view.play_menu.opened[-1] is None


def test_the_quest_screen_m_key_asks_for_the_objective():
    from ..ui import screens

    class _Q:
        id, name = "ring", "The Lost Ring"

    class _Log:
        def active_quests(self):
            return [_Q()]

        def completed_quests(self):
            return []

        def is_active(self, qid):
            return True

    class _Game:
        quests = _Log()

    class _Session:
        game = _Game()
        open_screen = "quest"
        map_request = None

        def quest_guidance(self, q):
            return {"target_pos": [30.0, 0.0, 40.0]}

    s = _Session()
    screens._handle_quest(s, "m")
    assert s.map_request == (30.0, 40.0, "The Lost Ring")
