"""
Grass fire (game/grass_fire.py): spreads through fuel, before the wind,
stops at what will not burn, never burns the same ground twice, and stays
within its limits.

Run:  python -m pytest game/tests/test_grass_fire.py -q
"""

from __future__ import annotations

import random

import numpy as np

from .. import grass_fire as gf
from ..wind import Wind


def _field(fuel_fn):
    return lambda xs, zs: np.array([fuel_fn(x, z) for x, z in zip(xs, zs)], np.float32)


def _run(fire, seconds):
    for _ in range(int(seconds / 0.05)):
        fire.update(0.05)


def test_fire_runs_through_long_grass_and_burns_out():
    fire = gf.GrassFire(_field(lambda x, z: 1.0), rng=random.Random(1))
    assert fire.ignite(10.0, 10.0)
    _run(fire, 6.0)
    assert len(fire.burning) + len(fire.burnt) > 20
    assert not fire.ignite(10.0, 10.0)                 # burning or burnt: not again


def test_nothing_burns_without_fuel_and_a_road_stops_it():
    road = lambda x, z: 0.0 if 0.0 <= x < gf.CELL * 2 else 1.0
    fire = gf.GrassFire(_field(road), rng=random.Random(2))
    assert not fire.ignite(gf.CELL * 0.5, 0.0)          # on the road
    assert fire.ignite(-gf.CELL * 3, 0.0)               # west of it
    _run(fire, 40.0)
    xs = [k[0] for k in list(fire.burning) + list(fire.burnt)]
    assert max(xs) < 0                                  # never crossed


def test_the_wind_drives_it():
    fire = gf.GrassFire(_field(lambda x, z: 1.0), wind=lambda: (1.0, 0.0), rng=random.Random(3))
    fire.ignite(0.0, 0.0)
    _run(fire, 8.0)
    xs = [k[0] for k in list(fire.burning) + list(fire.burnt)]
    assert max(xs) > 2 * -min(xs)                       # far further downwind (east)


def test_meadow_burns_poorly_heath_well():
    def spread(fuel, seed):
        fire = gf.GrassFire(_field(lambda x, z: fuel), rng=random.Random(seed))
        fire.ignite(0.0, 0.0)
        _run(fire, 12.0)
        return len(fire.burning) + len(fire.burnt)
    assert sum(spread(0.12, s) for s in range(5)) * 4 < sum(spread(1.0, s) for s in range(5))


def test_it_never_burns_more_than_its_limit_at_once():
    fire = gf.GrassFire(_field(lambda x, z: 1.0), wind=lambda: (0.8, 0.3), rng=random.Random(4))
    old = gf.MAX_BURNING
    try:
        gf.MAX_BURNING = 60
        fire.ignite(0.0, 0.0)
        for _ in range(400):
            fire.update(0.05)
            assert len(fire.burning) <= 60
    finally:
        gf.MAX_BURNING = old


def test_a_hitch_never_runs_the_fire_ahead():
    fire = gf.GrassFire(_field(lambda x, z: 1.0), rng=random.Random(5))
    fire.ignite(0.0, 0.0)
    fire.update(30.0)                                   # one frame of 30 s
    assert len(fire.burning) + len(fire.burnt) < 30


def test_heat_flares_burns_and_dies():
    assert gf.heat(10.0, 10.0) < 0.2
    assert gf.heat(5.0, 10.0) == 1.0
    assert gf.heat(0.4, 10.0) < 0.3


def test_burnt_ground_is_handed_on_to_be_scorched_once():
    fire = gf.GrassFire(_field(lambda x, z: 1.0), rng=random.Random(6))
    fire.ignite(0.0, 0.0)
    _run(fire, 30.0)
    first = fire.take_scorch(10)
    rest = fire.take_scorch(100000)
    assert len(first) == 10
    keys = {gf.cell_of(x, z) for x, z, _f in first + rest}
    assert len(keys) == len(first) + len(rest) and keys <= fire.burnt


def test_fuel_is_read_in_batches_and_kept():
    calls = []

    def fuel(xs, zs):
        calls.append(len(xs))
        return np.ones(len(xs), np.float32)
    fire = gf.GrassFire(fuel, rng=random.Random(7))
    fire.ignite(0.0, 0.0)
    assert calls[0] == 1 and calls[1] == 8              # the cell, then its neighbours at once
    before = len(calls)
    fire.fuel((0, 0))
    assert len(calls) == before


def test_wind_wanders_but_stays_in_bounds():
    w = Wind(random.Random(8))
    a0 = w.angle
    for _ in range(200):
        w.update(0.1)
        x, z = w.vector()
        assert 0.0 <= (x * x + z * z) ** 0.5 <= 1.0 + 1e-6
    assert w.angle != a0


def test_downwind_it_runs_at_about_a_jog_and_upwind_it_crawls():
    """In a fresh wind (0.7) the front runs some 15-60 units a second;
    upwind it barely moves."""
    reach, back = [], []
    for seed in range(6):
        fire = gf.GrassFire(_field(lambda x, z: 1.0), wind=lambda: (0.7, 0.0),
                            rng=random.Random(seed))
        fire.ignite(0.0, 0.0)
        _run(fire, 20.0)
        xs = [k[0] for k in list(fire.burning) + list(fire.burnt)]
        reach.append(max(xs) * gf.CELL / 20.0)
        back.append(-min(xs) * gf.CELL / 20.0)
    speed = sum(reach) / len(reach)
    assert 15.0 <= speed <= 60.0, speed
    assert sum(back) / len(back) < speed / 4


# --- the flames: FIRE Effects spawned where it burns -------------------------
class _Logic:
    def __init__(self):
        from types import SimpleNamespace
        self.editor_state = SimpleNamespace(things=[])
        self.rebuilds = 0


def _spawner():
    from types import SimpleNamespace
    from .. import fio
    from ..flame_spawner import FlameSpawner
    logic = _Logic()
    counted = fio.rebuild_entity_caches

    def rebuild(lg):
        lg.rebuilds += 1
    fio.rebuild_entity_caches = rebuild
    return FlameSpawner(SimpleNamespace(logic=logic)), logic, lambda: setattr(
        fio, "rebuild_entity_caches", counted)


def test_flames_stand_where_it_burns_and_go_when_it_is_out():
    from .. import flame_spawner as fs
    spawner, logic, restore = _spawner()
    try:
        fire = gf.GrassFire(_field(lambda x, z: 1.0), wind=lambda: (0.5, 0.0), rng=random.Random(9))
        fire.ignite(0.0, 0.0)
        for _ in range(200):                                 # 10 s
            fire.update(0.05)
            spawner.update(fire, (0.0, 0.0), 0.05)
        things = logic.editor_state.things
        assert 0 < len(things) <= fs.MAX_FLAMES
        assert all(t.properties["effect_type"] == "FIRE" and t.properties["grass_fire"] for t in things)
        assert logic.rebuilds <= 10 / fs.FLUSH_EVERY + 1     # batched, never per flame
        fire.extinguish()
        for _ in range(20):
            spawner.update(fire, (0.0, 0.0), 0.05)
        assert logic.editor_state.things == [] and not spawner.flames
    finally:
        restore()


def test_grass_flames_wear_every_fires_one_look():
    from .. import fire_look
    spawner, logic, restore = _spawner()
    try:
        fire = gf.GrassFire(_field(lambda x, z: 1.0), rng=random.Random(10))
        fire.ignite(0.0, 0.0)
        for _ in range(20):
            fire.update(0.05)
            spawner.update(fire, (0.0, 0.0), 0.05)
        assert {t.properties["fire_texture"] for t in logic.editor_state.things} == {fire_look.texture()}
    finally:
        restore()
