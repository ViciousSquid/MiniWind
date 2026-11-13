"""Scalar and dense crossfire agree on small populations and ray boundaries."""

from types import SimpleNamespace

import numpy as np
import pytest

from engine.monster_table import MonsterTable


@pytest.mark.parametrize('count', [0, 1, 2, 4, 8, 16, 32])
def test_scalar_crossfire_matches_dense(count, monkeypatch):
    rng = np.random.default_rng(31 + count)
    for trial in range(30):
        monsters = [SimpleNamespace(
            pos=rng.uniform(-500, 500, 3).tolist(),
            properties={'id': str(i), 'team': ('red', 'blue', '')[i % 3],
                        'dead': i % 11 == 7, 'hidden': i % 13 == 9})
            for i in range(count)]
        table = MonsterTable()
        table.gather(monsters)
        start, end = rng.uniform(-600, 600, (2, 3))
        if trial == 0:
            end = start.copy()  # zero-length rays never hit
        elif trial == 1:
            end = start + [0.5, 0., 0.]
        radius = (24., 80., 300.)[trial % 3]
        monkeypatch.setattr(MonsterTable, 'CROSSFIRE_NUMPY_MIN', 101)
        scalar = table.crossfire(0, start, end, radius)
        table.gather(monsters)
        monkeypatch.setattr(MonsterTable, 'CROSSFIRE_NUMPY_MIN', 0)
        dense = table.crossfire(0, start, end, radius)
        assert scalar is dense, (count, trial)


@pytest.mark.parametrize('threshold', [0, 8])
@pytest.mark.parametrize('centre,expected', [
    ((200., 0., 80.), True),   # tangent
    ((80., 0., 0.), False),   # entry at the origin
    ((1080., 0., 0.), False), # entry at the end
    ((0., 0., 0.), False),    # eye inside a sphere
])
def test_crossfire_ray_boundaries(threshold, centre, expected, monkeypatch):
    monsters = [SimpleNamespace(pos=[-200., 0., 0.], properties={'team': 'red'}),
                SimpleNamespace(pos=list(centre), properties={'team': 'blue'})]
    table = MonsterTable()
    table.gather(monsters)
    monkeypatch.setattr(MonsterTable, 'CROSSFIRE_NUMPY_MIN', threshold + 1 if threshold else 0)
    # The ray runs through the spheres' middle: Fio 3.5 centres a monster's
    # crossfire sphere on its body (monster_body_rise), not 64 above pos.
    from engine.monster_constants import monster_body_rise
    y = monster_body_rise({})
    got = table.crossfire(0, (0., y, 0.), (1000., y, 0.))
    assert got is (monsters[1] if expected else None)
