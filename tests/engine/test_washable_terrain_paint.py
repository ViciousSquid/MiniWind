"""Temporary terrain paint washes off without erasing authored ground paint."""

import numpy as np
import pytest

from engine.terrain import Terrain


def _terrain():
    terrain = Terrain(seed=7)
    terrain.chunk_size = 64.0
    terrain.TERRAIN_PAINT_RESOLUTION = 32
    colours = {"road": (30, 160, 50), "mark": (220, 10, 5)}

    def load(texture):
        image = np.zeros((2, 2, 4), dtype=np.uint8)
        image[..., :3] = colours[texture]
        image[..., 3] = 255
        return image

    terrain._load_texture_rgba = load
    return terrain


def _paint(terrain, texture="mark", x=32.0, washable=True):
    assert terrain.paint_texture_at(x, 32., 24., texture, feather=0., washable=washable)


def test_washing_reveals_the_original_road_without_modifying_it():
    terrain = _terrain()
    _paint(terrain, "road", washable=False)
    road = terrain.texture_paint_maps[(0, 0)].copy()
    _paint(terrain)
    np.testing.assert_array_equal(terrain._composite_texture_paint((0, 0))[16, 16],
                                  [220, 10, 5, 255])

    assert terrain.wash_texture_paint(.5) == 1
    midway = terrain._composite_texture_paint((0, 0))[16, 16]
    assert 30 < midway[0] < 220 and 10 < midway[1] < 160
    assert midway[3] == 255
    np.testing.assert_array_equal(terrain.texture_paint_maps[(0, 0)], road)

    assert terrain.wash_texture_paint(.5) == 1
    assert not terrain.washable_texture_paint_maps
    np.testing.assert_array_equal(terrain._composite_texture_paint((0, 0)), road)


def test_small_rain_steps_accumulate_at_the_same_rate_as_a_large_step():
    stepped, single = _terrain(), _terrain()
    _paint(stepped)
    _paint(single)
    for _ in range(600):
        stepped.wash_texture_paint(.5 / 600)
    single.wash_texture_paint(.5)
    np.testing.assert_array_equal(stepped.washable_texture_paint_maps[(0, 0)],
                                  single.washable_texture_paint_maps[(0, 0)])


def test_fully_washed_temporary_paint_disables_its_atlas_entry():
    terrain = _terrain()
    _paint(terrain)
    for _ in range(600):
        terrain.wash_texture_paint(1. / 600)
    assert not terrain.washable_texture_paint_maps
    assert not terrain._washable_paint_alpha
    assert not terrain._paint_map_versions


def test_grass_coverage_samples_include_the_washable_layer_and_clear_with_it():
    terrain = _terrain()
    _paint(terrain)
    assert terrain._paint_alpha_batch([32.], [32.])[0] == 1.
    terrain.wash_texture_paint(.5)
    assert terrain._paint_alpha_batch([32.], [32.])[0] == pytest.approx(128. / 255.)
    terrain.wash_texture_paint(1.)
    assert terrain._paint_alpha_batch([32.], [32.])[0] == 0.


def test_washing_respects_world_bounds_and_shelter_masks():
    terrain = _terrain()
    _paint(terrain)
    before = terrain.washable_texture_paint_maps[(0, 0)].copy()
    seen = []

    def exposed(xs, zs):
        seen.append((xs.copy(), zs.copy()))
        return xs < 32.

    assert terrain.wash_texture_paint(.5, bounds=(0., 0., 64., 64.), exposed=exposed) == 1
    assert seen and np.all(seen[0][0] >= 0.) and np.all(seen[0][1] <= 64.)
    layer = terrain.washable_texture_paint_maps[(0, 0)]
    assert layer[10, 16, 3] < before[10, 16, 3]
    assert layer[22, 16, 3] == before[22, 16, 3]

    left = layer[:16].copy()
    assert terrain.wash_texture_paint(1., bounds=(32., 0., 64., 64.)) == 1
    np.testing.assert_array_equal(layer[:16], left)
    assert layer[22, 16, 3] == 0


def test_bounded_washing_does_not_enumerate_offscreen_paint_chunks():
    terrain = _terrain()
    _paint(terrain)
    _paint(terrain, x=64032.)
    distant = terrain.washable_texture_paint_maps[(1000, 0)].copy()

    class NoGlobalScan(dict):
        def __iter__(self):
            raise AssertionError("bounded washing scanned the world")

    terrain.washable_texture_paint_maps = NoGlobalScan(terrain.washable_texture_paint_maps)
    assert terrain.wash_texture_paint(1., bounds=(0., 0., 64., 64.)) == 1
    np.testing.assert_array_equal(terrain.washable_texture_paint_maps[(1000, 0)], distant)


def test_both_paint_layers_save_separately_and_remain_washable_after_loading():
    terrain = _terrain()
    _paint(terrain, "road", washable=False)
    _paint(terrain)
    terrain.wash_texture_paint(.25)
    data = terrain.to_dict()
    assert data["texture_paint"] and data["washable_texture_paint"]
    restored = _terrain()
    restored.from_dict(data)
    np.testing.assert_array_equal(restored.texture_paint_maps[(0, 0)],
                                  terrain.texture_paint_maps[(0, 0)])
    np.testing.assert_array_equal(restored.washable_texture_paint_maps[(0, 0)],
                                  terrain.washable_texture_paint_maps[(0, 0)])
    restored.wash_texture_paint(1.)
    np.testing.assert_array_equal(restored._composite_texture_paint((0, 0)),
                                  terrain.texture_paint_maps[(0, 0)])


def test_clearing_all_paint_clears_temporary_marks_and_loading_legacy_maps_does_too():
    terrain = _terrain()
    _paint(terrain)
    terrain.clear_texture_paint()
    assert not terrain.washable_texture_paint_maps and not terrain._washable_paint_alpha
    assert not terrain._paint_map_versions
    _paint(terrain)
    terrain.from_dict({})
    assert not terrain.washable_texture_paint_maps and not terrain._washable_paint_alpha


@pytest.mark.parametrize("amount", [0., -1., float("nan"), float("inf")])
def test_non_positive_or_invalid_washing_leaves_paint_unchanged(amount):
    terrain = _terrain()
    _paint(terrain)
    before = terrain.washable_texture_paint_maps[(0, 0)].copy()
    assert terrain.wash_texture_paint(amount) == 0
    np.testing.assert_array_equal(terrain.washable_texture_paint_maps[(0, 0)], before)
