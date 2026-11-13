"""Rain on the lens (game/lens_water.py): drops gather while it rains, run
together, the heavy ones slide down and off, and they dry when it stops."""

import random

from .. import lens_water as lw


def _run(w, seconds, rain):
    for _ in range(int(seconds / 0.05)):
        w.update(0.05, rain)


def test_drops_gather_in_the_rain_and_dry_after():
    w = lw.LensWater(random.Random(1))
    _run(w, 0.5, 0.0)
    assert not w.drops
    _run(w, 8.0, 1.0)
    assert 10 <= len(w.drops) <= lw.MAX_DROPS
    assert all(0.0 <= x <= 1.0 and 0.0 < r for x, _y, r, _w in w.frame())
    _run(w, 20.0, 0.0)
    assert not w.drops


def test_heavy_drops_slide_down_and_off_leaving_beads():
    w = lw.LensWater(random.Random(2))
    w.drops = [[0.5, 0.2, lw.SLIDE_RADIUS * 1.2, 1.0, 0.0, 0.0]]
    ys = []
    for _ in range(10):
        w.update(0.1, 0.5)
        big = max(w.drops, key=lambda d: d[2])
        ys.append(big[1])
    assert ys[-1] > ys[0]                                     # it slid
    assert len(w.drops) > 1                                   # a trail of beads
    _run(w, 20.0, 0.0)
    assert all(d[1] - d[2] <= 1.0 for d in w.drops)


def test_touching_drops_run_together():
    w = lw.LensWater(random.Random(3))
    w.drops = [[0.5, 0.5, 0.01, 1.0, 0.0, 0.0], [0.505, 0.5, 0.01, 1.0, 0.0, 0.0]]
    w._merge()
    assert len(w.drops) == 1 and w.drops[0][2] > 0.01
