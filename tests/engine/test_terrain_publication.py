"""M5: the terrain publishes tables; a renderer never holds the Terrain.

``Terrain.advance`` does the CPU upkeep (streaming, LOD, building) with no
GL; ``Terrain.publish`` returns an immutable ``TerrainFrame`` -- the dense
table, the per-slot products and paint maps, the appearance as numbers.
Height grids can be built on a background thread; the table is written on
the caller's thread either way, and the grids are the same.
"""

import threading
import time

import glm
import numpy as np
import pytest

from engine.terrain import Terrain
from engine.terrain_frame import TerrainFrame, frustum_planes
from engine.terrain_table import TerrainTable

ORIGIN = glm.vec3(0.0, 0.0, 0.0)


def _settle(terrain, camera=ORIGIN, frames=400):
    for _ in range(frames):
        terrain.advance(camera)
        table = terrain.table
        live = table.live_slots()
        if (not terrain.builds_pending() and bool(np.all(table.built[live]))
                and not bool(np.any(table.dirty[live]))):
            return
        if terrain.BACKGROUND_BUILDS:
            time.sleep(0.002)
    raise AssertionError("the terrain did not finish building")


@pytest.fixture
def background():
    made = []

    def make(**kwargs):
        terrain = Terrain(**kwargs)
        terrain.BACKGROUND_BUILDS = True
        made.append(terrain)
        return terrain
    yield make
    for terrain in made:
        terrain.cleanup()
    assert not [t for t in threading.enumerate() if t.name == 'TerrainBuilder']


def test_the_frame_is_immutable_and_holds_no_terrain():
    terrain = Terrain(seed=3)
    terrain.advance(ORIGIN)
    frame = terrain.publish()
    assert isinstance(frame, TerrainFrame) and isinstance(frame.table, TerrainTable)
    with pytest.raises(AttributeError):
        frame.enabled = False
    with pytest.raises(AttributeError):
        del frame.table
    with pytest.raises(TypeError):
        frame.appearance['uTerraceMode'] = 1
    with pytest.raises(TypeError):
        frame.paint_versions[(0, 0)] = 1
    # Nothing published leads back to the Terrain object.
    for name in TerrainFrame.__slots__:
        value = getattr(frame, name)
        assert value is not terrain
        assert getattr(value, '__self__', None) is not terrain, name


def test_each_terrain_publishes_under_its_own_key():
    a, b = Terrain(), Terrain()
    assert a.publish().key == a.publish().key != b.publish().key


def test_the_frame_carries_the_appearance_as_numbers():
    terrain = Terrain(seed=3)
    terrain.set_grass(True, 0.02)
    frame = terrain.publish()
    assert set(frame.appearance) == set(terrain.appearance_uniforms())
    count, H, C, W, D = frame.gradient
    assert count == len(terrain.biome.color_gradient)
    assert frame.grass_enabled and frame.grass_height == terrain.grass_height
    assert frame.triangle_count == terrain.table.triangle_count()
    terrain.flat_mode = True
    assert frame.flat_mode is False and terrain.publish().flat_mode is True


def test_advance_builds_within_its_budget_and_publishes_versions():
    terrain = Terrain(seed=3)
    terrain.advance(ORIGIN)
    table = terrain.table
    first = int(table.built.sum())
    assert 0 < first <= terrain.MAX_UPDATES_PER_FRAME
    _settle(terrain)
    assert int(table.built.sum()) == table.count
    versions = table.version[table.live_slots()].copy()
    terrain.mark_all_dirty()
    _settle(terrain)
    assert np.all(table.version[table.live_slots()] > versions)


def test_grass_is_published_as_a_product_of_the_slot():
    terrain = Terrain(seed=3)
    terrain.meadow_grass = True       # off by default in MiniWind
    terrain.set_grass(True, 0.05)
    _settle(terrain)
    for _ in range(200):
        terrain.advance(ORIGIN)
    products, table = terrain.products, terrain.table
    slots = table.live_slots()
    assert set(products.grass) == set(slots.tolist())
    for slot in slots.tolist():
        version, order, blades = products.grass[slot]
        assert order == int(table.order[slot]) and blades.shape[1] == 9
        assert not blades.flags.writeable
    terrain.set_grass(False)
    terrain.advance(ORIGIN)
    assert not products.grass


def test_block_terraces_publish_a_mesh_with_each_grid():
    terrain = Terrain(seed=3)
    terrain.apply_appearance_preset('voxel_blocks')
    _settle(terrain)
    assert terrain.publish().blocks
    assert set(terrain.products.blocks) == set(terrain.table.live_slots().tolist())
    assert all(mesh.shape[1] == 14 for _, _, mesh in terrain.products.blocks.values())


def test_a_freed_slot_takes_its_products_with_it():
    terrain = Terrain(seed=3)
    terrain.meadow_grass = True       # off by default in MiniWind
    terrain.set_grass(True, 0.05)
    _settle(terrain)
    for _ in range(100):
        terrain.advance(ORIGIN)
    assert terrain.products.grass
    terrain.cleanup()
    assert not terrain.products.grass and terrain.table.count == 0


def test_background_builds_give_the_same_grids(background):
    inline = Terrain(seed=11)
    _settle(inline)
    threaded = background(seed=11)
    _settle(threaded)
    a, b = inline.table, threaded.table
    assert a.count == b.count
    for coord, slot in a.slot_of_coord.items():
        other = b.slot_of_coord[coord]
        n = int(a.grid_res[slot]) + 3
        assert a.grid_res[slot] == b.grid_res[other]
        assert np.array_equal(a.heights[slot, :n, :n], b.heights[other, :n, :n])
        assert a.min_y[slot] == b.min_y[other] and a.max_y[slot] == b.max_y[other]


def test_background_builds_never_run_on_the_calling_thread(background):
    terrain = background(seed=5)
    callers = []
    real = terrain._grid_heights
    terrain._grid_heights = lambda *a: callers.append(threading.current_thread().name) or real(*a)
    _settle(terrain)
    assert callers and set(callers) == {'TerrainBuilder'}


def test_an_edit_during_a_background_build_is_not_lost(background):
    terrain = background(seed=5)
    _settle(terrain)
    table = terrain.table
    slot = int(table.live_slots()[0])
    gate, entered = threading.Event(), threading.Event()
    real = terrain._grid_heights

    def slow(*args):
        entered.set()
        gate.wait(5.0)
        return real(*args)

    terrain._grid_heights = slow
    before = int(table.version[slot])
    table.dirty[slot] = True
    terrain.advance(ORIGIN)                     # asks the builder for it
    assert entered.wait(5.0)
    table.dirty[slot] = True                    # an edit lands mid-build
    terrain._grid_heights = real
    gate.set()
    _settle(terrain)
    # The grid in flight was stored, and the edit's rebuild followed it.
    assert int(table.version[slot]) >= before + 2


def test_a_grid_for_a_slot_that_was_reused_is_dropped(background):
    terrain = background(seed=5)
    terrain.set_streaming(True, radius=600.0)
    gate = threading.Event()
    real = terrain._grid_heights
    terrain._grid_heights = lambda *a: (gate.wait(5.0), real(*a))[1]
    terrain.advance(ORIGIN)
    asked = dict(terrain._building)
    assert asked
    far = glm.vec3(50000.0, 0.0, 50000.0)
    terrain.advance(far)                        # everything asked for is evicted
    gate.set()
    terrain._grid_heights = real
    _settle(terrain, far)
    table = terrain.table
    for slot in table.live_slots().tolist():
        # Every stored grid is its own chunk's: the height at its origin.
        x, z = float(table.world[slot, 0]), float(table.world[slot, 1])
        assert table.heights[slot, 1, 1] == pytest.approx(
            float(terrain._get_heights_batch(np.float32([x]), np.float32([z]))[0]), abs=1e-3)


def test_frustum_planes_match_the_tables_convention():
    projection = glm.perspective(glm.radians(70.0), 1.0, 1.0, 5000.0)
    view = glm.lookAt(glm.vec3(0, 200, 0), glm.vec3(0, 150, -500), glm.vec3(0, 1, 0))
    planes = frustum_planes(projection * view)
    assert len(planes) == 6
    ahead, behind = (0.0, 150.0, -500.0), (0.0, 150.0, 500.0)
    inside = lambda p: all(a * p[0] + b * p[1] + c * p[2] + d >= 0 for a, b, c, d in planes)
    assert inside(ahead) and not inside(behind)


def test_view_ready_says_when_the_ground_around_a_point_is_built(background):
    """After a jump, chunks stream in over a few frames and the camera sees
    through the world until they do; ``view_ready`` lets a game wait for the
    ground before uncovering the view."""
    terrain = background(seed=7)
    terrain.set_streaming(True, radius=900.0)
    cs = terrain.chunk_size
    far = glm.vec3(terrain.offset_x + (terrain.max_chunk_x - 3) * cs, 0.0,
                   terrain.offset_z + (terrain.max_chunk_z - 3) * cs)
    assert not terrain.view_ready(far.x, far.z, 700.0), "nothing is resident there yet"
    gate = threading.Event()
    real = terrain._grid_heights
    terrain._grid_heights = lambda *a: (gate.wait(5.0), real(*a))[1]
    terrain.advance(far)                        # resident, but not built
    assert terrain.table.count > 0
    assert not terrain.view_ready(far.x, far.z, 700.0)
    gate.set()
    terrain._grid_heights = real
    _settle(terrain, far)
    assert terrain.view_ready(far.x, far.z, 700.0)
    # A radius beyond the stream radius can never be resident: it is capped.
    assert terrain.view_ready(far.x, far.z, 50000.0)


def _grassy(terrain):
    terrain.set_biome('grassy_hills')
    terrain.set_bounds(-1, 0, -1, 0)
    terrain.set_grass(True, density=0.05, height_range=(0, 1))
    terrain.meadow_grass = True
    return terrain


def _settle_grass(terrain, camera=ORIGIN, frames=600):
    _settle(terrain, camera)
    for _ in range(frames):
        terrain.advance(camera)
        if not terrain.work_due and not terrain.grass_pending():
            return
        if terrain.BACKGROUND_BUILDS:
            time.sleep(0.002)
    raise AssertionError("the grass did not finish growing")


def test_background_grass_is_grown_on_the_builder_and_is_the_same(background):
    """Grass is 75-600 ms of numpy a chunk: grown on the TerrainBuilder
    thread, never the caller's, and blade for blade what growing it here
    gives."""
    inline = _grassy(Terrain(seed=11))
    _settle_grass(inline)
    threaded = _grassy(background(seed=11))
    callers = []
    real = threaded._generate_grass_blades
    threaded._generate_grass_blades = (
        lambda *a: callers.append(threading.current_thread().name) or real(*a))
    _settle_grass(threaded)
    assert callers and set(callers) == {'TerrainBuilder'}
    a, b = inline.table, threaded.table
    grown = 0
    for coord, slot in a.slot_of_coord.items():
        other = b.slot_of_coord[coord]
        mine, theirs = inline.products.grass.get(slot), threaded.products.grass.get(other)
        assert (mine is None) == (theirs is None)
        if mine is not None:
            np.testing.assert_array_equal(mine[2], theirs[2])
            grown += len(mine[2])
    assert grown, "no grass grew at all"


def test_grass_for_a_slot_that_was_reused_is_dropped(background):
    terrain = _grassy(background(seed=5))
    _settle(terrain)
    gate = threading.Event()
    real = terrain._generate_grass_blades
    terrain._generate_grass_blades = lambda *a: (gate.wait(5.0), real(*a))[1]
    terrain.advance(ORIGIN)                     # asks the builder for grass
    asked = dict(terrain._growing)
    assert asked
    table = terrain.table
    released = list(asked)
    table.release(np.array(released))           # those chunks go away
    terrain._released(np.array(released))
    gate.set()
    terrain._generate_grass_blades = real
    deadline = time.time() + 5.0
    while terrain._build_results.empty() and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    terrain._collect_built()
    for slot in released:
        assert slot not in terrain.products.grass
    assert not terrain.grass_pending()
