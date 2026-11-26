"""The world's edge as game/tools/reshape_edge.py left it: lowland all the
way round, Sunfall Oasis spilling over the south edge, no tree over water."""

import json
import os

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP = os.path.join(ROOT, "maps", "miniwind_world.json")


@pytest.fixture(scope="module")
def world():
    from game.tools import make_road_map as rm
    with open(MAP, encoding="utf-8") as f:
        data = json.load(f)
    return data, rm.terrain_of(data)


def test_the_map_records_the_reshaping(world):
    data, _terrain = world
    flags = data["_miniwind_world"]
    assert flags.get("edge_wall_removed") and flags.get("oasis") == "Sunfall Oasis"


def test_no_mountains_stand_round_the_edge(world):
    _data, terrain = world
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    s = np.linspace(min_x + 1.0, max_x - 1.0, 161).astype(np.float32)
    inset = 1500.0
    rings = [(s, np.full_like(s, min_z + inset)), (s, np.full_like(s, max_z - inset)),
             (np.full_like(s, min_x + inset), s), (np.full_like(s, max_x - inset), s)]
    for xs, zs in rings:
        h = terrain._get_heights_batch(xs, zs)
        # The old wall stood 1200-2100 above the lowland here.
        assert float(h.max()) < 700.0


def test_the_oasis_spills_over_the_south_edge(world):
    from engine.renderer.core.terrain_gl import TerrainGL
    data, terrain = world
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    lake = next(b for b in data["brushes"] if b.get("name") == "sunfall_oasis_water")
    (x, y, z), (sx, sy, sz) = lake["pos"], lake["size"]
    assert z + sz / 2 == pytest.approx(max_z)                # on the edge
    assert x < 0.0                                           # towards the west
    falls = TerrainGL.edge_falls((min_x, max_x, min_z, max_z), [lake["pos"]],
                                 [[sx / 2, sy / 2, sz / 2]])
    assert [f[0] for f in falls] == [3]                      # +z: the south edge
    top = y + sy / 2
    xs = np.linspace(x - sx / 2, x + sx / 2, 400).astype(np.float32)
    wet = terrain._get_heights_batch(xs, np.full_like(xs, max_z - 0.5)) < top
    # It falls in two, the islet between them, one fall wider than the other.
    runs, start = [], None
    for i, w in enumerate(wet.tolist() + [False]):
        if w and start is None:
            start = i
        elif not w and start is not None:
            runs.append(i - start)
            start = None
    falls_wide = sorted(r for r in runs if r > 10)
    assert len(falls_wide) == 2
    assert falls_wide[1] > 1.4 * falls_wide[0]


def test_no_tree_stands_over_water(world):
    from game.tools import make_road_map as rm
    from game.tools.reshape_edge import over_water
    data, terrain = world
    trees = [b for b in data["brushes"] if rm._is_tree(b)]
    assert not over_water(terrain, data, trees).any()
