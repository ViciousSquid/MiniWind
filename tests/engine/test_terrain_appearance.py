"""``Terrain`` appearance wiring: terraced collision, grass placement, save/load.

``engine.terrain`` imports PyOpenGL at module level, so this is the ``qt`` tier
(PyOpenGL importable, never called: every GL upload is avoided).
"""

import numpy as np
import pytest

pytest.importorskip("OpenGL", reason="engine.terrain imports PyOpenGL")

from engine import terrain_biomes as tb
from engine import terrain_style as ts                 # noqa: E402
from engine.terrain import Terrain, grass_vertex_count  # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture
def terrain():
    t = Terrain(seed=11)
    # Pinned, so a change of the default biome cannot move these tests.
    t.set_biome('grassy_hills')
    t.set_bounds(-1, 0, -1, 0)
    return t


def _build(t, res=16):
    """Make every in-bounds chunk resident and build its heightfield (no GL)."""
    t.table.ensure_bounds(t._chunk_bounds(), t.chunk_size, t.offset_x, t.offset_z)
    for slot in t.table.live_slots():
        t.table.store(int(slot), res, 0, t._chunk_heights(int(slot), res))


def _slot(t, cx=0, cz=0):
    t.table.ensure_bounds(t._chunk_bounds(), t.chunk_size, t.offset_x, t.offset_z)
    slots = t.table.live_slots()
    coords = t.table.coord[slots]
    hit = slots[(coords[:, 0] == cx) & (coords[:, 1] == cz)]
    assert len(hit) == 1
    return int(hit[0])


POINTS = [(12.3, -40.1), (-100.7, 7.9), (55.5, 55.5), (-3.0, -200.0)]


@pytest.mark.parametrize("mode", ["none", "smooth", "sharp", "blocks"])
def test_height_function_is_terraced_consistently(terrain, mode):
    terrain.set_appearance(terrace_mode=mode, terrace_step=9.0)
    xs = np.array([p[0] for p in POINTS], dtype=np.float32)
    zs = np.array([p[1] for p in POINTS], dtype=np.float32)
    batch = terrain._get_heights_batch(xs, zs)
    for (x, z), b in zip(POINTS, batch):
        # Unbuilt terrain: collision falls back to the height function.
        assert terrain._get_height_scalar(x, z) == pytest.approx(float(b), abs=1e-3)
        assert terrain.get_height_at(x, z) == pytest.approx(float(b), abs=1e-3)


@pytest.mark.parametrize("mode", ["smooth", "sharp"])
def test_built_terraces_are_what_collision_reads(terrain, mode):
    """The heightfield is built from the terraced surface, so its flats are flat."""
    terrain.set_appearance(terrace_mode=mode, terrace_step=9.0, terrace_ramp=0.3)
    _build(terrain, res=48)
    step = terrain._terrace_step_world()
    on_flats = 0
    points = [(x, z) for x in np.linspace(-240.0, 240.0, 9)
              for z in np.linspace(-240.0, 240.0, 9)]
    for x, z in points:
        h = terrain.get_height_at(x, z)
        assert h == pytest.approx(terrain._get_height_scalar(x, z), abs=step * 0.5)
        on_flats += abs(h / step - round(h / step)) < 1e-3
    # Most of a gently terraced hill is flat steps.
    assert on_flats >= len(points) * 0.25


def test_built_blocks_are_flat_for_collision(terrain):
    """Across a whole block, collision reads the block's one height."""
    terrain.set_appearance(terrace_mode='blocks', block_size=16.0, terrace_step=8.0)
    _build(terrain, res=48)
    for bx, bz in [(8.0, 8.0), (-40.0, 72.0), (120.0, -200.0)]:
        cx, cz = terrain._block_centre(bx, bz)
        expected = terrain._get_height_scalar(cx, cz)
        for dx in (-7.9, 0.0, 7.9):
            for dz in (-7.9, 7.9):
                assert terrain.get_height_at(cx + dx, cz + dz) == pytest.approx(
                    expected, abs=1e-3)


def test_blocks_are_flat(terrain):
    terrain.set_appearance(terrace_mode='blocks', block_size=16.0, terrace_step=8.0)
    xs = np.linspace(0.5, 15.5, 16, dtype=np.float32)
    h = terrain._get_heights_batch(xs, np.full_like(xs, 3.0))
    assert np.ptp(h) == 0.0
    assert float(h[0]) % 8.0 == pytest.approx(0.0, abs=1e-3)


def test_block_mesh_has_tops_and_walls(terrain):
    terrain.set_appearance(terrace_mode='blocks')
    verts = terrain._block_mesh(_slot(terrain)).reshape(-1, 14)
    normals = verts[:, 3:6]
    assert np.any(normals[:, 1] > 0.5)           # tops
    assert np.any(np.abs(normals[:, 1]) < 0.5)   # walls
    assert np.all(np.isin(np.round(np.abs(normals), 6), [0.0, 1.0]))
    # Tops sit exactly on the stepped surface.
    tops = verts[normals[:, 1] > 0.5]
    step = terrain._terrace_step_world()
    np.testing.assert_allclose(tops[:, 1] / step, np.round(tops[:, 1] / step), atol=1e-4)


def test_shape_changes_rebuild_and_colour_changes_do_not(terrain):
    _build(terrain)
    slot = _slot(terrain)
    assert not terrain.table.dirty[slot]
    terrain.set_appearance(contour_lines=0.5, palette='autumn')
    assert not terrain.table.dirty[slot]
    terrain.set_appearance(terrace_mode='sharp')
    assert terrain.table.dirty[slot]


def test_manual_change_marks_the_look_custom(terrain):
    terrain.apply_appearance_preset('retro_tiles')
    assert terrain.appearance.preset == 'retro_tiles'
    terrain.set_appearance(slope_rock=0.2)
    assert terrain.appearance.preset == 'retro_tiles'   # layers are separate
    terrain.set_appearance(grid_lines=0.0)
    assert terrain.appearance.preset == 'custom'


def test_unknown_option_is_rejected(terrain):
    with pytest.raises(AttributeError):
        terrain.set_appearance(sparkle=1.0)


def test_biome_brings_its_own_layer_heights(terrain):
    terrain.set_appearance(layer_heights=(0.1, 0.2, 0.3))
    terrain.set_biome('mountains')
    assert terrain._layer_heights() == ts.BIOME_LAYER_HEIGHTS['mountains']


def test_height_range_spans_the_terrain(terrain):
    lo, hi = terrain._layer_height_range()
    xs = np.random.default_rng(0).uniform(-256, 256, 400).astype(np.float32)
    zs = np.random.default_rng(1).uniform(-256, 256, 400).astype(np.float32)
    h = terrain._get_raw_heights_batch(xs, zs)
    assert lo < hi
    assert np.mean((h >= lo - 1.0) & (h <= hi + 1.0)) > 0.97


def test_appearance_survives_save_and_load(terrain):
    terrain.apply_appearance_preset('painted_strata')
    terrain.set_appearance(layer_heights=(0.1, 0.45, 0.9), wall_color=(0.1, 0.2, 0.3))
    loaded = Terrain(seed=1)
    loaded.from_dict(terrain.to_dict())
    assert loaded.appearance == terrain.appearance


def test_old_maps_load_with_the_original_look(terrain):
    data = terrain.to_dict()
    data.pop('appearance')
    terrain.apply_appearance_preset('voxel_blocks')
    terrain.from_dict(data)
    assert terrain.appearance == ts.TerrainAppearance()


# ---------------------------------------------------------------------------
# Grass
# ---------------------------------------------------------------------------

def test_grass_colours(terrain):
    terrain.set_grass(True, color=(0.2, 0.5, 0.1))
    auto_tip = terrain.grass_tip_colour()
    assert auto_tip != (0.2, 0.5, 0.1)          # derived, lighter and drier
    terrain.set_grass(True, tip_color=(0.9, 0.8, 0.3))
    assert terrain.grass_tip_colour() == (0.9, 0.8, 0.3)
    loaded = Terrain(seed=1)
    loaded.from_dict(terrain.to_dict())
    assert loaded.grass_color == (0.2, 0.5, 0.1)
    assert loaded.grass_tip_colour() == (0.9, 0.8, 0.3)
    terrain.set_grass(True, tip_color='auto')
    assert terrain.grass_tip_colour() == auto_tip


def test_colour_changes_do_not_rebuild_grass(terrain):
    terrain.set_grass(True, density=0.03)
    _build(terrain)
    terrain.table.grass_dirty[:] = False
    terrain.set_grass(True, color=(0.3, 0.3, 0.1), tip_color=(0.8, 0.8, 0.4))
    assert not terrain.table.grass_dirty.any()
    terrain.set_grass(True, density=0.04)
    assert terrain.table.grass_dirty[terrain.table.live_slots()].all()


def test_grass_vertex_counts():
    assert grass_vertex_count(1) == 3
    assert grass_vertex_count(5) == 27


def _paint_vegetation(terrain, biome, channels=5):
    biome_map = np.zeros((2, 2, channels), dtype=np.uint8)
    if biome is not None:
        biome_map[..., biome] = 255
    terrain.set_biome_map(biome_map)


@pytest.mark.parametrize("biome", [None, tb.DESERT, tb.SNOW, tb.SWAMP])
def test_ordinary_terrain_has_no_grass_or_reeds(terrain, biome):
    terrain.set_grass(True, density=0.06)
    assert terrain._generate_grass_blades(_slot(terrain)).shape == (0, 9)
    _paint_vegetation(terrain, biome)
    assert terrain._generate_grass_blades(_slot(terrain)).shape == (0, 9)


@pytest.mark.parametrize("channels, biome", [(4, tb.WHEAT), (5, tb.WHEAT), (5, tb.TUNDRA)])
@pytest.mark.parametrize("quality", ["low", "high"])
def test_wheat_and_tundra_keep_their_full_blade_populations(terrain, channels, biome, quality):
    terrain.set_grass(True, density=0.05)
    terrain.set_grass_quality(quality)
    _paint_vegetation(terrain, biome, channels)
    slot = _slot(terrain)
    expected = (terrain._generate_wheat_blades(slot) if biome == tb.WHEAT
                else terrain._generate_tundra_blades(slot))
    assert len(expected) > 0
    np.testing.assert_array_equal(terrain._generate_grass_blades(slot), expected)


@pytest.mark.parametrize("biome", [tb.WHEAT, tb.TUNDRA])
def test_grass_blades_sit_on_the_ground(terrain, biome):
    _paint_vegetation(terrain, biome)
    terrain.set_grass(True, density=0.05)
    for mode in ('none', 'blocks'):
        terrain.set_appearance(terrace_mode=mode)
        blades = terrain._generate_grass_blades(_slot(terrain))
        assert len(blades) > 0
        ground = terrain._get_heights_batch(blades[:, 0], blades[:, 2])
        np.testing.assert_allclose(blades[:, 1], ground, atol=1e-3)


@pytest.mark.parametrize("biome", [tb.WHEAT, tb.TUNDRA])
def test_grass_is_deterministic(terrain, biome):
    _paint_vegetation(terrain, biome)
    terrain.set_grass(True, density=0.05)
    a = terrain._generate_grass_blades(_slot(terrain))
    b = terrain._generate_grass_blades(_slot(terrain))
    np.testing.assert_array_equal(a, b)


def test_editing_a_band_colour_makes_a_custom_palette(terrain):
    terrain.apply_appearance_preset('painted_strata')
    before = ts.palette_colors(terrain.appearance)
    terrain.set_palette_color(2, (0.1, 0.2, 0.9))
    a = terrain.appearance
    assert a.palette == 'custom'
    assert a.custom_palette[2] == (0.1, 0.2, 0.9)
    assert a.custom_palette[:2] == before[:2] and a.custom_palette[3:] == before[3:]
    terrain.resize_palette(8)
    assert len(terrain.appearance.custom_palette) == 8
    terrain.resize_palette(1)
    assert len(terrain.appearance.custom_palette) == ts.MIN_PALETTE
    loaded = Terrain(seed=1)
    loaded.from_dict(terrain.to_dict())
    assert loaded.appearance.custom_palette == terrain.appearance.custom_palette


def test_choosing_custom_starts_from_the_current_colours(terrain):
    terrain.set_appearance(palette='autumn')
    terrain.set_appearance(palette='custom')
    assert terrain.appearance.custom_palette == ts.PALETTES['autumn']


def test_grass_height_range_is_controllable(terrain):
    """Authored grass height settings still round-trip with the terrain."""
    terrain.set_grass(True, density=0.06)
    terrain.GRASS_MIN_NORMAL_Y = 0.0
    terrain.set_appearance(layer_blend=0.02)
    assert terrain.grass_height_bounds() == terrain._layer_heights()[:2]

    terrain.set_grass(True, height_range=(0.45, 0.7))
    assert terrain.grass_height_range == (0.45, 0.7)

    terrain.set_grass(True, height_range=(0.9, 0.2))    # given backwards
    assert terrain.grass_height_range == (0.2, 0.9)

    loaded = Terrain(seed=1)
    loaded.from_dict(terrain.to_dict())
    assert loaded.grass_height_range == (0.2, 0.9)

    terrain.set_grass(True, height_range='auto')
    assert terrain.grass_height_range is None
    assert terrain.grass_height_bounds() == terrain._layer_heights()[:2]


def test_changing_the_grass_range_rebuilds_grass(terrain):
    terrain.set_grass(True, density=0.03)
    _build(terrain)
    terrain.table.grass_dirty[:] = False
    terrain.set_grass(True, height_range=(0.1, 0.5))
    assert terrain.table.grass_dirty[terrain.table.live_slots()].all()


def test_ground_coloured_grass_follows_look_changes(terrain):
    terrain.set_grass(True, density=0.03)
    _build(terrain)
    live = terrain.table.live_slots()
    terrain.table.grass_dirty[:] = False
    terrain.set_appearance(palette='autumn')
    assert terrain.table.grass_dirty[live].all()
    terrain.table.grass_dirty[:] = False
    terrain.set_use_textures(not terrain.use_textures)
    assert terrain.table.grass_dirty[live].all()

    # A chosen colour overrides the ground; 'ground' goes back to it.
    terrain.set_grass(True, color=(0.2, 0.6, 0.1))
    assert terrain.grass_color_custom
    terrain.table.grass_dirty[:] = False
    terrain.set_appearance(palette='meadow')
    assert not terrain.table.grass_dirty[live].any()
    terrain.set_grass(True, color='ground')
    assert not terrain.grass_color_custom
    assert terrain.table.grass_dirty[live].all()
