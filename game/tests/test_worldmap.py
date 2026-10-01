"""
The world's map picture and the minimap (:mod:`game.ui.worldmap`).

Run:  python -m pytest game/tests/test_worldmap.py -q
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

QtGui = pytest.importorskip("PyQt5.QtGui")

from ..ui import worldmap        # noqa: E402


def test_brushes_are_told_apart():
    kind = worldmap._brush_kind
    assert kind({"textures": {"f": "tree03.png"}, "size": [64, 300, 64]}) == "tree"
    assert kind({"is_water": True}) == "water"
    assert kind({"textures": {"f": "flagstone.jpg"}, "size": [400, 8, 400]}) == "paving"
    assert kind({"textures": {"f": "brick.jpg"}, "size": [200, 160, 32]}) == "building"
    assert kind({"textures": {"a": "nodraw.jpg", "b": "nodraw.jpg"}}) is None


def test_terrain_colours_follow_height_and_slope():
    h = np.zeros((40, 40), np.float32)
    h[:, 20:] = np.linspace(0, 2000, 20)[None, :]      # a steep rise on the right
    rgb = worldmap.colour_terrain(h, 80.0)
    assert rgb.shape == (40, 40, 3) and rgb.dtype == np.uint8
    flat, high = rgb[20, 5].astype(int), rgb[20, 39].astype(int)
    assert flat[1] > flat[0] and flat[1] > flat[2]      # meadow is green
    assert high.sum() > flat.sum()                       # snow-capped heights


def test_brushes_are_painted_where_they_stand():
    rgb = np.zeros((100, 100, 3), np.uint8)
    bounds = ((0.0, 1000.0), (0.0, 1000.0))
    worldmap.paint_brushes(rgb, [{"is_water": True, "pos": [500, 0, 250],
                                  "size": [100, 50, 100]}], bounds, 10.0)
    assert tuple(rgb[25, 50]) == (62, 112, 168)          # row = z, column = x
    assert tuple(rgb[80, 80]) == (0, 0, 0)


class _Terrain:
    def get_terrain_bounds(self):
        return (-1000.0, 1000.0), (-1000.0, 1000.0)

    def _get_heights_batch(self, x, z):
        return np.hypot(x, z) * 0.5


def test_a_world_is_painted_in_the_background_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(worldmap, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(worldmap, "RESOLUTION", 64)
    world = worldmap.WorldMap()
    world.ensure(_Terrain(), [], terrain_data={"seed": 1})
    deadline = time.time() + 10
    while not world.ready and time.time() < deadline:
        time.sleep(0.02)
    assert world.ready and world.rgb.shape == (64, 64, 3)
    assert os.listdir(tmp_path)                           # cached

    again = worldmap.WorldMap()
    again.ensure(None, [], terrain_data={"seed": 1})      # no terrain needed now
    assert again.ready and np.array_equal(again.rgb, world.rgb)


class _Player:
    pos = [0.0, 0.0, 0.0]
    angle = 0.0


class _Session:
    def __init__(self, actors):
        self.logic = type("L", (), {"player": _Player()})()
        self._actors = actors

    def _live_actors(self):
        return self._actors

    def quest_arrow_targets(self):
        return [([5000.0, 0.0, 0.0], "q", "Quest")]       # off the map: on the rim


class _Thing:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = props


def test_the_minimap_paints_with_and_without_a_picture(qt_app):
    session = _Session([_Thing((300, 0, 0), team="bandits", aggression="hostile"),
                        _Thing((-200, 0, 100), team="villagers")])
    pixmap = QtGui.QPixmap(1280, 720)
    for world in (worldmap.WorldMap(), _ready_world()):
        painter = QtGui.QPainter(pixmap)
        try:
            worldmap.draw_minimap(painter, session, None, 1280, 720, world=world)
        finally:
            painter.end()


def _ready_world():
    w = worldmap.WorldMap()
    w.rgb = np.full((64, 64, 3), 90, np.uint8)
    w.bounds = ((-3200.0, 3200.0), (-3200.0, 3200.0))
    w.cell = 100.0
    return w
