"""MiniWind's terrain features in Fio 3.5's ownership model.

The terrain layer computes and publishes (no GL): the regional biome map,
its version and bounds; the actors parting the grass; grass only where the
camera can see it. The renderer's ``TerrainGL`` owns what it builds from
them (``tests/visual/test_terrain_biomes_gl.py``).
"""

import ast
import os

import numpy as np
import pytest

glm = pytest.importorskip("glm")

from engine import terrain_biomes as tb                      # noqa: E402
from engine.terrain import Terrain                           # noqa: E402
from engine.terrain_frame import TerrainFrame                # noqa: E402

ORIGIN = glm.vec3(0.0, 100.0, 0.0)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _settle(terrain, camera=ORIGIN, frames=400):
    for _ in range(frames):
        terrain.advance(camera)
        slots = terrain.table.live_slots()
        if terrain.table.built[slots].all() and not terrain.builds_pending():
            break


def _wheat(terrain, channels=4):
    biome = np.zeros((4, 4, channels), dtype=np.uint8)
    biome[..., tb.WHEAT] = 255
    terrain.set_biome_map(biome)
    return biome


def test_the_terrain_layer_imports_no_opengl():
    """CPU generation and publication only: GL belongs to the renderer."""
    for name in ("terrain.py", "terrain_biomes.py", "terrain_frame.py"):
        with open(os.path.join(ROOT, "engine", name), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert all(n.split(".")[0] != "OpenGL" for n in names), (name, names)


def test_the_frame_publishes_the_biome_map_as_a_read_only_copy():
    terrain = Terrain(seed=3)
    assert terrain.publish().biome_map is None
    assert terrain.publish().biome_bounds is None
    source = _wheat(terrain, channels=5)
    frame = terrain.publish()
    assert frame.biome_map.shape == (4, 4, tb.GPU_CHANNELS)      # tundra is CPU-only
    assert frame.biome_map.dtype == np.uint8 and not frame.biome_map.flags.writeable
    assert frame.biome_map.flags.c_contiguous
    # The published array is the frame's own: editing the terrain's map in
    # place afterwards cannot reach a frame already handed out.
    terrain.biome_map[..., tb.WHEAT] = 0
    assert frame.biome_map[..., tb.WHEAT].min() == 255
    (x0, x1), (z0, z1) = terrain.get_terrain_bounds()
    assert frame.biome_bounds == pytest.approx(
        (x0, z0, 1.0 / (x1 - x0), 1.0 / (z1 - z0)))
    with pytest.raises(AttributeError):
        frame.biome_map = source


def test_a_new_biome_map_is_a_new_version_and_regrows_the_grass():
    terrain = Terrain(seed=3)
    _settle(terrain)
    first = terrain.publish().biome_version
    terrain.table.grass_dirty[:] = False
    _wheat(terrain)
    second = terrain.publish()
    assert second.biome_version != first
    assert terrain.table.grass_dirty[terrain.table.live_slots()].all()
    assert terrain.publish().biome_version == second.biome_version   # stable until replaced
    terrain.set_biome_map(None)
    cleared = terrain.publish()
    assert cleared.biome_map is None and cleared.biome_version != second.biome_version


def test_the_biome_map_survives_a_save_and_load():
    terrain = Terrain(seed=3)
    source = _wheat(terrain, channels=5)
    source[1, 2, tb.TUNDRA] = 200
    terrain.set_biome_map(source)
    loaded = Terrain()
    loaded.from_dict(terrain.to_dict())
    assert np.array_equal(loaded.biome_map, source)
    assert np.array_equal(loaded.publish().biome_map, source[..., :tb.GPU_CHANNELS])
    bare = Terrain()
    bare.from_dict(Terrain(seed=3).to_dict())
    assert bare.biome_map is None and bare.publish().biome_map is None


def test_a_frame_without_the_miniwind_fields_reads_them_as_none():
    """A renderer plugin or a test may build a frame from Fio's fields alone."""
    frame = TerrainFrame(key=1, enabled=True)
    assert frame.biome_map is None and frame.grass_pushers is None


def test_grass_pushers_are_published_as_numbers_and_fade_out(monkeypatch):
    from engine import terrain as terrain_module
    clock = [100.0]
    monkeypatch.setattr(terrain_module.time, "perf_counter", lambda: clock[0])
    terrain = Terrain(seed=3)
    assert terrain.publish().grass_pushers is None
    terrain.set_grass_pushers([("player", 10.0, 20.0, 14.0)])
    rows = terrain.publish().grass_pushers
    assert rows.dtype == np.float32 and rows.shape == (2, 4) and not rows.flags.writeable
    assert rows[0].tolist() == [10.0, 20.0, 14.0, 1.0]           # where the actor stands
    # The actor walks on: its old place fades as the grass springs back.
    clock[0] += 0.5
    terrain.set_grass_pushers([("player", 60.0, 20.0, 14.0)])
    rows = terrain.publish().grass_pushers
    assert rows[0].tolist() == [60.0, 20.0, 14.0, 1.0]
    trail = rows[rows[:, 0] == 10.0]
    assert len(trail) == 1 and 0.0 < trail[0, 3] < 1.0
    clock[0] += terrain.GRASS_RECOVER_SECONDS + 0.1
    terrain.set_grass_pushers([])
    assert terrain.publish().grass_pushers is None
    # Never more than the shader holds.
    terrain.set_grass_pushers([(i, float(i) * 50.0, 0.0, 10.0) for i in range(80)])
    assert len(terrain.publish().grass_pushers) == terrain.MAX_GRASS_PUSHERS


def test_grass_not_allowed_grows_and_publishes_none_and_regrows_when_allowed():
    """settings.ini [Renderer] grass = False, handed over by the host."""
    terrain = Terrain(seed=3)
    terrain.set_grass(True, 0.05)
    _wheat(terrain)
    _settle(terrain)
    for _ in range(60):
        terrain.advance(ORIGIN)
    assert terrain.products.grass and terrain.publish().grass_enabled
    terrain.grass_allowed = False
    terrain.advance(ORIGIN)
    assert not terrain.products.grass and not terrain.publish().grass_enabled
    terrain.grass_allowed = True
    for _ in range(60):
        terrain.advance(ORIGIN)
    assert terrain.products.grass and terrain.publish().grass_enabled


def test_grass_grows_nearest_first_and_only_within_reach():
    terrain = Terrain(seed=3)
    terrain.set_bounds(-8, 8, -1, 0)
    terrain.GRASS_MAX_DISTANCE = 600.0
    terrain.MAX_UPDATES_PER_FRAME = 64
    terrain.UPDATE_BUDGET_MS = 1.0e6
    terrain.set_grass(True, 0.05)
    _wheat(terrain)
    _settle(terrain)
    table = terrain.table
    terrain.MAX_UPDATES_PER_FRAME = 1
    terrain.products.clear_store(terrain.products.grass)
    table.mark_grass_dirty()
    terrain.advance(ORIGIN)
    slots = table.live_slots()
    dist = table.nearest_dist_sq(slots, 0.0, 0.0)
    first, = terrain.products.grass
    assert dist[slots.tolist().index(first)] == dist.min()
    terrain.MAX_UPDATES_PER_FRAME = 64
    for _ in range(20):
        terrain.advance(ORIGIN)
    grown = set(terrain.products.grass)
    reach_sq = terrain.GRASS_MAX_DISTANCE ** 2
    assert grown == {int(s) for s, d in zip(slots, dist) if d <= reach_sq}
    assert len(grown) < len(slots)


def test_grass_far_out_of_view_is_given_back_and_regrows_on_return():
    terrain = Terrain(seed=3)
    terrain.set_bounds(-8, 8, -1, 0)
    terrain.GRASS_MAX_DISTANCE = 600.0
    terrain.MAX_UPDATES_PER_FRAME = 64
    terrain.UPDATE_BUDGET_MS = 1.0e6
    terrain.set_grass(True, 0.05)
    _wheat(terrain)
    _settle(terrain)
    for _ in range(10):
        terrain.advance(ORIGIN)
    near_origin = set(terrain.products.grass)
    assert near_origin
    versions = {slot: terrain.products.grass[slot][0] for slot in near_origin}
    away = glm.vec3(1900.0, 100.0, 0.0)
    for _ in range(10):
        terrain.advance(away)
    table = terrain.table
    slots = table.live_slots()
    far = {int(s) for s, d in zip(slots, table.nearest_dist_sq(slots, 1900.0, 0.0))
           if d > terrain.GRASS_MAX_DISTANCE ** 2 * 2.56}
    assert far & near_origin
    assert not far & set(terrain.products.grass)
    assert table.grass_dirty[sorted(far & near_origin)].all()
    for _ in range(10):
        terrain.advance(ORIGIN)
    assert near_origin <= set(terrain.products.grass)
    regrown = far & near_origin
    assert all(terrain.products.grass[slot][0] != versions[slot] for slot in regrown)


def test_a_season_regrows_the_wheat_only_when_the_stage_visibly_changes():
    terrain = Terrain(seed=3)
    _wheat(terrain)
    _settle(terrain)
    table = terrain.table
    assert terrain.set_season(0.05) is True
    assert terrain.wheat_stage == tb.wheat_stage(0.05)
    assert table.grass_dirty[table.live_slots()].all()
    table.grass_dirty[:] = False
    assert terrain.set_season(0.0505) is False               # a game clock, every frame
    assert not table.grass_dirty[table.live_slots()].any()
    assert terrain.set_season(0.45) is True
    assert table.grass_dirty[table.live_slots()].all()


def test_ordinary_ground_stays_clear_unless_meadow_grass_is_asked_for():
    terrain = Terrain(seed=11)
    terrain.set_biome('grassy_hills')
    terrain.set_bounds(-1, 0, -1, 0)
    terrain.MAX_UPDATES_PER_FRAME = 64
    terrain.UPDATE_BUDGET_MS = 1.0e6
    _settle(terrain)
    terrain.set_grass(True, density=0.06, height_range=(0, 1))
    slot = int(terrain.table.live_slots()[0])
    assert terrain._generate_grass_blades(slot).shape == (0, 9)
    terrain.meadow_grass = True
    assert len(terrain._generate_grass_blades(slot)) > 0


def test_background_builds_reject_a_grid_built_for_a_replaced_chunk():
    """A grid computed for a slot that was freed and reused is thrown away."""
    terrain = Terrain(seed=3)
    terrain.BACKGROUND_BUILDS = True
    try:
        terrain.advance(ORIGIN)
        assert terrain.builds_pending() > 0
        table = terrain.table
        pending = dict(terrain._building)
        terrain.stop_builder()
        assert terrain.builds_pending() == 0
        assert terrain._builder is None
        # What was asked for and not stored is due again.
        for slot, order in pending.items():
            if table.live[slot] and int(table.order[slot]) == order and not table.built[slot]:
                assert table.dirty[slot]
        # A result that arrives for another allocation of the slot is dropped.
        slot = int(table.live_slots()[0])
        stale_order = int(table.order[slot]) + 1000
        terrain._building[slot] = stale_order
        terrain._build_results.put((slot, stale_order, 48, np.zeros((51, 51), np.float32)))
        version = int(table.version[slot])
        terrain._collect_built()
        assert int(table.version[slot]) == version and slot not in terrain._building
    finally:
        terrain.cleanup()
    assert terrain._builder is None
