"""Rain on the lens (game/lens_water.py): drops gather while it rains and run
down the glass -- the bigger the faster, in fits and starts, wandering a
little, leaving beads behind and gathering those in their way -- and dry
when it stops."""

import random

import pytest

from .. import lens_water as lw


@pytest.fixture
def no_landing(monkeypatch):
    """Only the drops a test puts on the glass (none land on top of them)."""
    monkeypatch.setattr(lw, "LAND_PER_SECOND", 0.0)


def _run(w, seconds, rain, motion=(0.0, 0.0)):
    for _ in range(int(round(seconds / 0.05))):
        w.update(0.05, rain, motion)


def _one(r, y=0.1, x=0.5, seed=2):
    w = lw.LensWater(random.Random(seed))
    d = lw.Drop(x, y, r, 1.0, rng=w.rng)
    w.drops = [d]
    return w, d


def test_drops_gather_in_the_rain_and_dry_after():
    w = lw.LensWater(random.Random(1))
    _run(w, 0.5, 0.0)
    assert not w.drops
    _run(w, 8.0, 1.0)
    assert 10 <= len(w.drops) <= lw.MAX_DROPS
    assert all(-0.1 <= x <= 1.1 and 0.0 < r and s >= 1.0 for x, _y, r, _w, s in w.frame())
    _run(w, 20.0, 0.0)
    assert not w.drops


def test_bigger_drops_run_down_faster(no_landing):
    assert lw.run_speed(0.005) == lw.run_speed(lw.PIN_RADIUS) == lw.CREEP_SPEED
    sizes = [0.005, 0.015, 0.025, 0.035, lw.RUN_RADIUS, 0.06]
    speeds = [lw.run_speed(r) for r in sizes]
    assert speeds == sorted(speeds) and len(set(speeds)) == len(speeds)
    assert speeds[-2] == lw.RUN_SPEED and speeds[-1] <= lw.MAX_SPEED
    # In the game: over two seconds a big drop goes much farther than a
    # middling one, and a bead barely creeps -- but every one moves down.
    gone = {}
    for r in (0.008, 0.022, 0.04):
        w, d = _one(r)
        y0 = d.y
        _run(w, 2.0, 0.5)
        gone[r] = max(w.drops, key=lambda e: e.r).y - y0 if w.drops else 1.0
    assert 0.0 < gone[0.008] < 0.03 < gone[0.022] < gone[0.04]


def test_a_runner_goes_in_fits_and_starts_and_wanders(no_landing):
    w, d = _one(0.03, y=0.05)
    steps, xs = [], []
    for _ in range(60):
        y = d.y
        w.update(0.02, 0.5)
        d = max(w.drops, key=lambda e: e.r)
        steps.append(d.y - y)
        xs.append(d.x)
    # It snags and slips: its pace swings by a factor of three or more.
    assert max(steps) > 3.0 * min(steps) > 0.0
    assert max(xs) - min(xs) > 0.001                       # not a ruler line
    assert d.stretch() > 1.05                              # drawn long as it runs


def test_a_runner_leaves_a_trail_of_beads_that_fade(no_landing):
    w, d = _one(0.04, y=0.05)
    r0 = d.r
    _run(w, 0.4, 0.5)
    trail = [e for e in w.drops if e.trail]
    assert trail and all(e.r <= lw.TRAIL_BEAD[1] * r0 for e in trail)
    assert all(e.y < max(w.drops, key=lambda e: e.r).y for e in trail)   # behind it
    runner = max(w.drops, key=lambda e: e.r)
    assert runner.r < r0                                   # water lost to them
    _run(w, 12.0, 0.5)                                     # even in the rain
    assert not [e for e in w.drops if e.trail]


def test_a_runner_sweeps_up_beads_and_speeds_up():
    w, d = _one(0.03, y=0.1)
    w.drops.append(lw.Drop(0.5, 0.135, 0.02, 1.0, rng=w.rng))
    w._merge()
    assert len(w.drops) == 1 and w.drops[0].r > 0.03
    assert lw.run_speed(w.drops[0].r) > lw.run_speed(0.03)


def test_moving_the_camera_pushes_drops_back_across_the_glass(no_landing):
    still, _ = _one(0.008, x=0.5, y=0.5)
    moved, _ = _one(0.008, x=0.5, y=0.5)
    _run(still, 1.0, 0.5)
    _run(moved, 1.0, 0.5, motion=(1.0, 0.0))               # the camera goes right
    assert moved.drops[0].x < still.drops[0].x - 0.01


def test_drops_run_off_the_bottom(no_landing):
    w, _ = _one(0.05, y=0.8)
    _run(w, 3.0, 0.0)
    assert all(e.y - e.r <= 1.0 for e in w.drops)
    assert all(e.r < 0.02 for e in w.drops)              # only its trail is left
