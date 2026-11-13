"""MiniWind's meadow (game/meadow.py): the odd tuft of grass all over the land.

Sparse, fuller, taller tufts of their own green, so they read as grass from
the overhead camera; thinned by the grass setting, gone at Off -- where the
wheat fields, a crop the farms and the seasons depend on, still grow in full.
"""

import numpy as np
import pytest

pytest.importorskip("OpenGL", reason="engine.terrain imports PyOpenGL")

from engine import terrain_biomes as tb   # noqa: E402
from engine.terrain import Terrain        # noqa: E402
from game import meadow                   # noqa: E402

pytestmark = [pytest.mark.qt, pytest.mark.miniwind]


@pytest.fixture
def terrain():
    t = Terrain(seed=11)
    t.set_biome('grassy_hills')
    t.set_bounds(-1, 0, -1, 0)
    t.set_grass(True, density=0.05, height_range=(0, 1))
    t.table.ensure_bounds(t._chunk_bounds(), t.chunk_size, t.offset_x, t.offset_z)
    return t


def _slots(t):
    return [int(s) for s in t.table.live_slots()]


def test_play_grows_a_sparse_meadow_of_green_tufts(terrain):
    assert all(len(terrain._generate_grass_blades(s)) == 0 for s in _slots(terrain))
    assert meadow.apply(terrain) is True
    blades = [terrain._generate_meadow_blades(s) for s in _slots(terrain)]
    assert sum(len(b) for b in blades) > 0, "no meadow anywhere"
    size = float(terrain.chunk_size)
    for b in blades:
        # Occasional: never more than the sparse density's tufts to a chunk.
        assert len(b) <= meadow.MEADOW_DENSITY * size * size * meadow.BLADES_PER_TUFT
        if len(b):
            np.testing.assert_allclose(b[:, 6:9], np.tile(meadow.COLOUR, (len(b), 1)),
                                       rtol=1e-6)
            assert b[:, 3].min() >= 0.65 * meadow.BLADE_SCALE - 1e-4


def test_grass_keeps_its_detail_only_near_the_player(terrain):
    assert (terrain.GRASS_LOD_START, terrain.GRASS_LOD_DISTANCE) == (350.0, 700.0)   # Fio's
    meadow.apply(terrain)
    assert terrain.GRASS_LOD_START == meadow.DETAIL_START < meadow.DETAIL_END
    frame = terrain.publish()
    assert (frame.grass_lod_start, frame.grass_lod_distance) == (
        meadow.DETAIL_START, meadow.DETAIL_END)


def test_applying_again_changes_nothing_and_regrows_nothing(terrain):
    meadow.apply(terrain)
    table = terrain.table
    table.grass_dirty[:] = False
    assert meadow.apply(terrain) is False
    assert not table.grass_dirty[table.live_slots()].any()


def test_the_grass_setting_thins_the_meadow_and_off_leaves_only_the_wheat(terrain):
    meadow.apply(terrain)
    slots = _slots(terrain)
    counts = {}
    for quality in ("high", "medium", "low", "off"):
        terrain.set_grass_quality(quality)
        counts[quality] = sum(len(terrain._generate_meadow_blades(s)) for s in slots)
    assert counts["high"] > counts["medium"] > counts["low"] > counts["off"] == 0

    biome_map = np.zeros((2, 2, 5), dtype=np.uint8)
    biome_map[..., tb.WHEAT] = 255
    terrain.set_biome_map(biome_map)
    terrain.set_grass_quality("high")
    wheat_high = sum(len(terrain._generate_wheat_blades(s)) for s in slots)
    terrain.set_grass_quality("off")
    off = [terrain._generate_grass_blades(s) for s in slots]
    assert wheat_high > 0
    # At Off every blade left is wheat, and all of the wheat is there.
    assert sum(len(b) for b in off) == wheat_high
