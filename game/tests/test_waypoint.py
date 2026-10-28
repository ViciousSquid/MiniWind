"""The player's map waypoint: one at a time, set by a click on the map,
taken away by a click on it, reached by walking there, and pointed at by an
orange arrow round the head."""

from __future__ import annotations

import pytest

from .test_menu_clicks import _Logic


def _session():
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    return s


def test_one_waypoint_moves_with_each_click_and_a_click_on_it_takes_it_away():
    s = _session()
    assert s.waypoint() is None
    assert s.toggle_waypoint(2000.0, -500.0, pick=100.0) == (2000.0, -500.0)
    assert s.toggle_waypoint(-3000.0, 800.0, pick=100.0) == (-3000.0, 800.0)
    assert s.waypoint() == (-3000.0, 800.0)          # only ever one
    assert s.toggle_waypoint(-3040.0, 830.0, pick=100.0) is None
    assert s.waypoint() is None


def test_walking_to_the_waypoint_reaches_and_clears_it():
    from ..runtime import WAYPOINT_REACHED
    s = _session()
    s.set_waypoint(5000.0, 0.0)
    s._check_waypoint()
    assert s.waypoint() == (5000.0, 0.0)
    s.logic.player.pos = [5000.0 - WAYPOINT_REACHED / 2, 0.0, 0.0]
    s._check_waypoint()
    assert s.waypoint() is None
    assert any("Waypoint reached" in str(n) for n in s.notifications)


def test_the_map_features_carry_the_waypoint():
    from ..ui import worldmap
    s = _session()
    assert worldmap.map_features(s)["waypoint"] is None
    s.set_waypoint(10.0, 20.0)
    assert worldmap.map_features(s)["waypoint"] == (10.0, 20.0)


@pytest.mark.qt
def test_a_click_on_the_map_page_sets_the_waypoint_and_a_drag_only_pans(qt_app):
    from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt
    from ..ui.map_page import MapPage
    clicks = []
    features = {"player": (0.0, 0.0, 0.0), "places": [], "quests": [], "waypoint": None}
    page = MapPage(read_data=lambda: (None, dict(features)), update=lambda: None,
                   on_close=lambda: None,
                   on_waypoint=lambda x, z, pick: clicks.append((x, z, pick)))
    page.open()
    page._rect = QRectF(0, 0, 800, 600)
    centre = page.centre
    # A drag pans and sets nothing.
    page.handle_mouse_press(QPoint(400, 300))
    page.handle_mouse_move(QPoint(450, 300), Qt.LeftButton)
    page.handle_mouse_release()
    assert not clicks and page.centre != centre
    # A click sets it where it lands, at once.
    page.handle_mouse_press(QPoint(500, 200))
    page.handle_mouse_release()
    (x, z, pick), = clicks
    assert page.features["waypoint"] == (x, z)
    assert (x, z) == pytest.approx(page.to_world(page._rect, QPointF(500, 200)))
    page.refresh()                     # the game has not applied it yet
    assert page.features["waypoint"] == (x, z)
    # A click on it takes it away.
    page.handle_mouse_press(QPoint(503, 202))
    page.handle_mouse_release()
    assert page.features["waypoint"] is None
    assert len(clicks) == 2


@pytest.mark.qt
def test_the_hud_arrow_for_the_waypoint_is_orange(qt_app, monkeypatch):
    from PyQt5.QtGui import QImage, QPainter, QColor
    from ..ui import hud, theme
    s = _session()
    s.quest_arrow_targets = lambda: []
    drawn = []
    monkeypatch.setattr(hud, "_draw_one_quest_arrow",
                        lambda painter, cx, cy, rel, orbit, color, *a: drawn.append(color))
    image = QImage(400, 300, QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        hud._draw_quest_arrow(painter, s, 400, 300)
        assert drawn == []
        s.set_waypoint(3000.0, 0.0)
        hud._draw_quest_arrow(painter, s, 400, 300)
    finally:
        painter.end()
    assert drawn == [theme.WAYPOINT]
    assert all(QColor(c).name() != theme.WAYPOINT.name() for c in hud._QUEST_ARROW_COLORS)
