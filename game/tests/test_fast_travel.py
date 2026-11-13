"""Fast travel from the map, to discovered places only: "You haven't
discovered that location yet."."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import entities
from .test_quest_files import _FakeLogic, _G


class _Player:
    def __init__(self, pos):
        import glm
        self.pos = glm.vec3(*pos)
        self.velocity = glm.vec3(0, 0, 0)
        self.angle = 0.0


def _world(discovered=True):
    from ..runtime import MiniwindSession, StateStore
    cross = entities.Marker(pos=[9000.0, 0.0, 6000.0], properties={
        "name": "loc_cross", "marker_kind": "location", "place_name": "Hollin's Cross",
        "_discovered": discovered})
    mill = entities.Marker(pos=[9000.0, 0.0, -5000.0], properties={
        "name": "loc_mill", "marker_kind": "location", "place_name": "Old Mill"})
    logic = _FakeLogic([cross, mill])
    logic.player = _Player([0.0, 0.0, 0.0])
    s = MiniwindSession(logic, cfg={})
    store = StateStore(_G(), "miniwind")
    s.store = store
    s.game.store = store
    s.begin_new_character("Tamsin", "imperial", "warrior", "warrior")
    return s, logic


def test_fast_travel_takes_you_to_a_discovered_place_and_the_hours_pass():
    s, logic = _world()
    ok, text = s.fast_travel_check("Hollin's Cross")
    assert ok and text.startswith("Fast travel to Hollin's Cross?")
    day, hour = s.clock.day, s.clock.hour
    assert s.fast_travel("Hollin's Cross")
    assert (logic.player.pos.x, logic.player.pos.z) == pytest.approx((9000.0, 6000.0), abs=700)
    assert (s.clock.day, s.clock.hour) != (day, hour), "the journey's hours pass"
    told = s.notifications[-1]["text"]
    assert told.startswith("You travel to Hollin's Cross.") and told.endswith(("passes.", "pass."))
    assert "hour pass." not in told
    ok, text = s.fast_travel_check("Hollin's Cross")
    assert not ok and text == "You are already at Hollin's Cross."


def test_an_undiscovered_place_cannot_be_travelled_to():
    s, logic = _world()
    ok, text = s.fast_travel_check("Old Mill")
    assert not ok and text == "You haven't discovered that location yet."
    assert not s.fast_travel("Old Mill")
    assert (logic.player.pos.x, logic.player.pos.z) == (0.0, 0.0)


def test_no_fast_travel_with_enemies_near_or_carrying_too_much():
    s, logic = _world()
    wolf = entities.Creature(pos=[300.0, 0.0, 0.0], properties={"npc_role": "wolf",
                                                                 "aggression": "hostile"})
    logic.things.append(wolf)
    ok, text = s.fast_travel_check("Hollin's Cross")
    assert not ok and text == "You cannot fast travel with enemies nearby."
    logic.things.remove(wolf)
    s.game.character.inventory.append({"id": "iron_ingot", "name": "Anvil", "qty": 1,
                                       "type": "misc", "value": 1, "weight": 100000.0})
    ok, text = s.fast_travel_check("Hollin's Cross")
    assert not ok and text == "You cannot fast travel while carrying too much."


@pytest.mark.qt
def test_the_map_asks_before_travelling_and_says_when_a_place_is_unknown(qt_app):
    from PyQt5.QtCore import QPoint, QRectF, Qt
    from ..ui.map_page import MapPage
    asked, went, waypoints = [], [], []
    features = {"player": (0.0, 0.0, 0.0), "places": [("Hollin's Cross", 2000.0, 1000.0)],
                "quests": [("Trouble at the Old Mill", 2000.0, -2000.0, "mill_bandits", True)],
                "unknown": [(2100.0, -2050.0)], "waypoint": None}
    page = MapPage(read_data=lambda: (None, dict(features)), update=lambda: None,
                   on_close=lambda: None,
                   on_waypoint=lambda x, z, pick: waypoints.append((x, z)),
                   check_travel=lambda name: (asked.append(name) or True,
                                              f"Fast travel to {name}? About an hour on the road."),
                   on_travel=lambda name: went.append(name))
    page.open()
    page._rect = QRectF(0, 0, 800, 600)
    cross = page.to_screen(page._rect, 2000.0, 1000.0)
    page.handle_mouse_press(QPoint(int(cross.x()), int(cross.y())))
    page.handle_mouse_release()
    assert asked == ["Hollin's Cross"] and page.prompt["ok"] and not waypoints
    page.handle_key(Qt.Key_Escape)
    assert page.prompt is None and not went
    page.handle_mouse_press(QPoint(int(cross.x()), int(cross.y())))
    page.handle_mouse_release()
    page.handle_key(Qt.Key_Return)
    assert went == ["Hollin's Cross"]
    mill = page.to_screen(page._rect, 2000.0, -2000.0)
    page.handle_mouse_press(QPoint(int(mill.x()), int(mill.y())))
    page.handle_mouse_release()
    assert page.prompt["text"] == "You haven't discovered that location yet."
    assert not page.prompt["ok"] and waypoints, "the waypoint still goes on the marker"
