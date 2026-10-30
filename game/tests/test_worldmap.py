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


def test_painted_biome_colours_are_visible_on_the_map():
    """The map reflects region paint, not just the old height-only relief."""
    from engine import terrain_biomes as tb

    h = np.tile(np.linspace(0.0, 180.0, 40, dtype=np.float32), (40, 1))
    weights = np.zeros((40, 40, 5), np.float32)
    weights[:, 20:, tb.TUNDRA] = 1.0
    original = worldmap.colour_terrain(h, 20.0)
    painted = worldmap.colour_terrain(h, 20.0, weights)
    np.testing.assert_array_equal(painted[:, :20], original[:, :20])
    assert not np.array_equal(painted[:, 20:], original[:, 20:])
    # The heath has russet-brown ground, rather than the upland height ramp.
    r, g, b = painted[20, 30].astype(int)
    assert r > g > b
    # The normal hillshade remains, including where a biome is fully painted.
    assert np.unique(painted[20, 20:, 0]).size > 1


def test_the_worldmap_builder_samples_current_biome_paint(tmp_path, monkeypatch):
    """Both the minimap and MAP page consume the shared newly painted image."""
    from engine import terrain_biomes as tb

    class BiomeTerrain:
        biome_map = np.zeros((2, 2, 5), np.uint8)

        def get_terrain_bounds(self):
            return ((-1000.0, 1000.0), (-1000.0, 1000.0))

        def _get_heights_batch(self, x, z):
            return np.zeros_like(x, dtype=np.float32)

        def biome_weights_batch(self, x, z):
            out = np.zeros((len(x), 5), dtype=np.float32)
            out[np.asarray(x) < 0, tb.DESERT] = 1.0
            out[np.asarray(x) >= 0, tb.TUNDRA] = 1.0
            return out

    monkeypatch.setattr(worldmap, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(worldmap, "RESOLUTION", 64)
    world = worldmap.WorldMap()
    world.ensure(BiomeTerrain(), [], terrain_data={"seed": 2})
    deadline = time.time() + 10
    while not world.ready and world.error is None and time.time() < deadline:
        time.sleep(0.02)
    assert world.error is None
    assert world.ready
    desert = world.rgb[32, 10].astype(int)
    tundra = world.rgb[32, 50].astype(int)
    assert desert.sum() > tundra.sum()
    assert tundra[0] > tundra[1] > tundra[2]


def test_replacing_the_world_file_invalidates_the_cached_picture(tmp_path):
    path = tmp_path / "world.json"
    path.write_text("first version", encoding="utf-8")
    first = worldmap.WorldMap.cache_key(path, None)
    path.write_text("second version with new geography", encoding="utf-8")
    assert worldmap.WorldMap.cache_key(path, None) != first


def test_baked_road_texture_paint_is_visible_on_both_maps():
    """Roads are terrain RGBA paint, not brushes or biome paint."""
    class PaintedTerrain(_Terrain):
        chunk_size = 1000.0
        offset_x = -1000.0
        offset_z = -1000.0

        def __init__(self):
            road = np.zeros((4, 4, 4), np.uint8)
            road[:, :, :3] = (180, 102, 48)
            road[:, :, 3] = 255
            self.texture_paint_maps = {(0, 0): road}

    terrain = PaintedTerrain()
    base = np.full((8, 8, 3), 70, np.uint8)
    worldmap.paint_texture_paint(base, terrain,
                                ((-1000, 1000), (-1000, 1000)), 250.0)
    # Terrain paint arrays index x first, while the map indexes z first.
    assert tuple(base[1, 1]) == (180, 102, 48)
    assert tuple(base[1, 6]) == (70, 70, 70)
    assert tuple(base[6, 1]) == (70, 70, 70)


def test_rebuilding_paints_baked_roads(tmp_path, monkeypatch):
    class PaintedTerrain(_Terrain):
        chunk_size = 2000.0
        offset_x = -1000.0
        offset_z = -1000.0

        def __init__(self):
            road = np.zeros((16, 16, 4), np.uint8)
            road[4:12, :, :3] = (190, 110, 60)
            road[4:12, :, 3] = 255
            self.texture_paint_maps = {(0, 0): road}

    monkeypatch.setattr(worldmap, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(worldmap, "RESOLUTION", 64)
    world = worldmap.WorldMap()
    world.ensure(PaintedTerrain(), [], terrain_data={"seed": 999})
    deadline = time.time() + 10
    while not world.ready and world.error is None and time.time() < deadline:
        time.sleep(0.02)
    assert world.error is None
    assert world.ready
    road = world.rgb[32, 32].astype(int)
    off_road = world.rgb[32, 5].astype(int)
    assert road[0] > road[1] > road[2]
    assert not np.array_equal(road, off_road)


def test_fallback_cache_key_includes_late_terrain_changes():
    first = {"heightmap_blob": "a" * 6000 + "old"}
    second = {"heightmap_blob": "a" * 6000 + "new"}
    assert worldmap.WorldMap.cache_key(None, first) != worldmap.WorldMap.cache_key(None, second)
