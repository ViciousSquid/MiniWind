"""Restoring part of a terrain's baked paint from a snapshot
(Terrain.snapshot_texture_paint / restore_texture_paint): a game's scorch,
say, cleared once the ground recovers, the rest of the paint untouched."""

import numpy as np



def _terrain(colour):
    from tests.engine.test_terrain_csg import _flat_terrain
    terrain = _flat_terrain()
    images = {}

    def load(path):
        return images[path]
    for name, rgb in colour.items():
        img = np.zeros((4, 4, 4), np.uint8)
        img[..., :3] = rgb
        img[..., 3] = 255
        images[name] = img
    terrain._load_texture_rgba = load
    return terrain


def _alpha_at(terrain, x, z):
    return float(terrain._paint_alpha_batch([x], [z])[0])


def test_a_scorch_comes_off_and_the_road_under_it_stays():
    terrain = _terrain({"road": (120, 110, 90), "scorch": (10, 8, 6)})
    terrain.paint_texture_at(0.0, 0.0, 40.0, "road", feather=0.0)
    road = terrain.texture_paint_maps[(0, 0)].copy()
    snap = terrain.snapshot_texture_paint((-200.0, -200.0, 200.0, 200.0))
    terrain.paint_texture_at(0.0, 0.0, 120.0, "scorch", feather=0.0)
    terrain.paint_texture_at(150.0, 0.0, 20.0, "scorch", feather=0.0)   # a second burn, outside
    assert _alpha_at(terrain, 80.0, 0.0) > 0.9                          # scorched bare ground
    before = terrain._paint_map_versions.get((0, 0))

    assert terrain.restore_texture_paint((-130.0, -130.0, 130.0, 130.0), snap)

    paint = terrain.texture_paint_maps[(0, 0)]
    res, cell = terrain.TERRAIN_PAINT_RESOLUTION, terrain.chunk_size / terrain.TERRAIN_PAINT_RESOLUTION
    i = int(10.0 / cell)
    np.testing.assert_array_equal(paint[i, i], road[i, i])             # the road again
    assert _alpha_at(terrain, 80.0, 0.0) == 0.0                        # bare ground clear
    assert _alpha_at(terrain, 150.0, 0.0) > 0.9                        # the other burn stays
    assert terrain._paint_map_versions.get((0, 0)) != before           # uploaded again
    assert res == paint.shape[0]


def test_restoring_where_nothing_was_painted_empties_the_chunk():
    terrain = _terrain({"scorch": (10, 8, 6)})
    snap = terrain.snapshot_texture_paint((-100.0, -100.0, 100.0, 100.0))
    terrain.paint_texture_at(40.0, 40.0, 30.0, "scorch", feather=0.0)
    assert (0, 0) in terrain.texture_paint_maps
    assert terrain.restore_texture_paint((0.0, 0.0, 100.0, 100.0), snap)
    assert (0, 0) not in terrain.texture_paint_maps
    assert not terrain.restore_texture_paint((0.0, 0.0, 100.0, 100.0), snap)   # nothing left to do
