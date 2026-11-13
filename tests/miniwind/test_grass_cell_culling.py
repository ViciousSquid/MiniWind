"""Grass outside the camera's view is never drawn.

Each chunk's blades are uploaded sorted into cells
(engine/renderer/core/terrain_gl.py, GRASS_CELLS a side) and only the cells
whose blades can reach into the frustum are drawn, neighbouring cells as one
run. Pure NumPy here: the sort, the per-cell test and the runs.
"""

import glm
import numpy as np
import pytest

from engine.renderer.core import terrain_gl as tg
from engine.terrain_frame import frustum_planes

pytestmark = pytest.mark.miniwind

SIZE = 1024.0
CELLS = tg.grass_cells_for(SIZE)


def _blades(n=20000, seed=4):
    rng = np.random.default_rng(seed)
    data = np.zeros((n, 9), np.float32)
    data[:, 0] = rng.random(n) * SIZE
    data[:, 2] = rng.random(n) * SIZE
    data[:, 1] = rng.random(n) * 3.0
    data[:, 1] += 0.0
    data[:, 3] = rng.uniform(0.6, 1.3, n)
    data[:, 4] = rng.random(n)            # a tag to follow each blade
    return data


def _planes(eye, target, fov=50.0, aspect=16 / 9, far=2000.0):
    projection = glm.perspective(glm.radians(fov), aspect, 1.0, far)
    view = glm.lookAt(glm.vec3(*eye), glm.vec3(*target), glm.vec3(0, 1, 0))
    return np.asarray(frustum_planes(projection * view), np.float64).reshape(-1, 4)


def _inside(points, planes, pad):
    norm = np.linalg.norm(planes[:, :3], axis=1)
    return ((points @ planes[:, :3].T + planes[:, 3]) / norm >= -pad).all(axis=1)


class _Stub:
    """The bits of TerrainGL that _grass_runs reads."""
    _grass_runs = tg.TerrainGL._grass_runs

    def __init__(self, data):
        sorted_data, starts, counts, boxes = tg._sort_grass_cells(data, 0.0, 0.0, SIZE)
        self.data = sorted_data
        self._grass_count = {0: len(data)}
        self._grass_cells = {0: (starts, counts, boxes)}


def test_cells_are_about_128_units_and_a_power_of_two_a_side():
    assert [tg.grass_cells_for(s) for s in (64, 256, 1024, 2048, 8192)] == [1, 2, 8, 16, 16]


def test_blades_are_sorted_into_whole_cells_and_none_is_lost():
    data = _blades()
    sorted_data, starts, counts, boxes = tg._sort_grass_cells(data, 0.0, 0.0, SIZE)
    assert counts.sum() == len(data) and len(starts) <= CELLS ** 2
    np.testing.assert_array_equal(np.sort(sorted_data[:, 4]), np.sort(data[:, 4]))
    cell = SIZE / CELLS
    for start, count, box in zip(starts, counts, boxes):
        part = sorted_data[start:start + count]
        assert box[0] <= part[:, 0].min() and part[:, 0].max() <= box[1]
        assert box[5] <= part[:, 2].min() and part[:, 2].max() <= box[6]
        assert box[1] - box[0] <= cell and box[6] - box[5] <= cell   # one cell each


@pytest.mark.parametrize("eye,target", [
    ((512, 120, -80), (512, 0, 200)),        # looking in from one edge
    ((-300, 400, -300), (150, 0, 150)),      # high, at a corner
    ((1200, 20, 512), (1600, 0, 512)),       # looking away: nothing
    ((512, 1500, 512), (512, 0, 513)),      # straight down on it: all of it
])
def test_only_cells_in_view_are_drawn_and_every_blade_in_view_is(eye, target):
    stub = _Stub(_blades())
    planes = _planes(eye, target)
    height, width = 4.0, 0.45
    runs = stub._grass_runs(0, planes, height, width)
    drawn = np.zeros(len(stub.data), bool)
    for start, count, _detailed, _pushed in runs:
        drawn[start:start + count] = True
    roots = stub.data[:, :3].astype(np.float64)
    # Every blade whose root is in view is drawn ...
    assert drawn[_inside(roots, planes, 0.0)].all()
    # ... and nothing drawn lies far outside: only cells reaching into view.
    cell = SIZE / CELLS
    far_out = ~_inside(roots, planes, cell * 1.5 + height * 1.3 * 1.3 + 2)
    assert not drawn[far_out].any()


def test_neighbouring_cells_are_one_draw():
    stub = _Stub(_blades())
    planes = _planes((512, 1500, 512), (512, 0, 513))
    assert stub._grass_runs(0, planes, 4.0, 0.45) == [(0, len(stub.data), True, False)]
    assert stub._grass_runs(0, _planes((1200, 20, 512), (1600, 0, 512)), 4.0, 0.45) == []
    runs = stub._grass_runs(0, _planes((512, 120, -80), (512, 0, 200)), 4.0, 0.45)
    assert 1 <= len(runs) <= CELLS ** 2 // 2


def test_cells_beyond_the_detail_distance_draw_single_triangles():
    """Only cells within the detail distance of the camera point are drawn
    detailed; the rest are one triangle a blade, in runs of their own."""
    stub = _Stub(_blades())
    planes = _planes((512, 1500, 512), (512, 0, 513))     # all in view
    runs = stub._grass_runs(0, planes, 4.0, 0.45, near=(100.0, 100.0, 300.0))
    assert sum(r[1] for r in runs) == len(stub.data)
    detailed = np.zeros(len(stub.data), bool)
    for start, count, is_detailed, _pushed in runs:
        detailed[start:start + count] = is_detailed
    reach = np.hypot(stub.data[:, 0] - 100.0, stub.data[:, 2] - 100.0)
    assert detailed[reach < 300.0].all()                  # every near blade detailed
    assert not detailed[reach > 300.0 + SIZE / CELLS * 1.5].any()
    assert detailed.mean() < 0.3


def test_only_runs_an_actor_reaches_loop_over_the_actors():
    """A run of cells no actor's circle reaches is drawn without the
    shader's per-actor parting loop; every blade an actor can part keeps it."""
    stub = _Stub(_blades())
    planes = _planes((512, 1500, 512), (512, 0, 513))
    pushers = np.array([[300.0, 300.0, 40.0], [700.0, 650.0, 30.0]])
    runs = stub._grass_runs(0, planes, 4.0, 0.45, pushers=pushers)
    assert sum(r[1] for r in runs) == len(stub.data)
    pushed = np.zeros(len(stub.data), bool)
    for start, count, _detailed, is_pushed in runs:
        pushed[start:start + count] = is_pushed
    x, z = stub.data[:, 0], stub.data[:, 2]
    reached = np.zeros(len(x), bool)
    for px, pz, r in pushers:
        reached |= np.hypot(x - px, z - pz) < r
    assert reached.any() and pushed[reached].all()
    assert pushed.mean() < 0.1                    # the rest skip the loop
    assert stub._grass_runs(0, planes, 4.0, 0.45, pushers=None) == [
        (0, len(stub.data), True, False)]


def test_small_runs_fold_into_their_neighbours_the_costlier_way():
    runs = [(0, 1000, False, False), (1000, 100, True, False), (1100, 2000, False, True),
            (5000, 50, False, False)]
    assert tg.GRASS_MERGE_RUN > 100                       # after a gap: stays apart
    assert tg._merge_small_runs(runs) == [(0, 1100, True, False),
                                          (1100, 2000, False, True),
                                          (5000, 50, False, False)]
