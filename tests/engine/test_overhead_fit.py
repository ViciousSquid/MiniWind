"""What MiniWind's engine copy adds for an overhead game: the camera's ground
footprint, and an AI that thinks less often about monsters off screen.

The AI's off-screen pass only runs when Big World reports its tiers are
fitted to the camera (``sim_tiers_fit_view``): without that, an ACTIVE
monster may be on screen and keeps full rate.
"""

import types

import glm
import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="engine.logic_thread imports the editor tier")

from engine.logic_thread import LogicThread               # noqa: E402
from engine.monster_ai import MonsterAI                   # noqa: E402
from engine.spatial import SIM_TIER_KEY, TIER_ACTIVE, TIER_DORMANT, TIER_NEAR  # noqa: E402


class _Camera:
    """What overhead_ground_footprint reads off the logic thread."""
    overhead_ground_footprint = LogicThread.overhead_ground_footprint
    _overhead_camera = LogicThread._overhead_camera
    _safe_up = staticmethod(LogicThread._safe_up)

    def __init__(self, aspect=16 / 9, height=800.0, tilt=0.0, overhead=True):
        self.frustum_aspect = aspect
        self.overhead_height = height
        self.overhead_tilt = tilt
        self.overhead_orientation = "north"
        self.player = types.SimpleNamespace(pos=glm.vec3(100.0, 50.0, -40.0), angle=0.0)
        self._overhead = overhead

    def is_overhead(self):
        return self._overhead


def test_a_straight_down_camera_shows_height_by_aspect():
    hx, hz = _Camera(aspect=16 / 9).overhead_ground_footprint()
    # 90 degree vertical field of view: half-height equals the camera height.
    assert hz == pytest.approx(800.0, rel=1e-4)
    assert hx == pytest.approx(800.0 * 16 / 9, rel=1e-4)


def test_the_footprint_scales_with_the_camera_height():
    low = _Camera(height=400.0).overhead_ground_footprint()
    high = _Camera(height=1200.0).overhead_ground_footprint()
    assert high[0] == pytest.approx(3 * low[0], rel=1e-4)


def test_no_footprint_when_not_overhead_or_looking_at_the_horizon():
    assert _Camera(overhead=False).overhead_ground_footprint() is None
    assert _Camera(tilt=60.0).overhead_ground_footprint() is None


def _thing(tier=None):
    props = {} if tier is None else {SIM_TIER_KEY: tier}
    return types.SimpleNamespace(properties=props, pos=[0.0, 0.0, 0.0])


def _ai(fit):
    ai = MonsterAI.__new__(MonsterAI)
    ai.lt = types.SimpleNamespace(sim_tiers_fit_view=fit)
    return ai


def test_off_screen_monsters_run_every_interval_with_the_time_they_skipped():
    ai = _ai(fit=True)
    monsters = [_thing(TIER_NEAR), _thing(TIER_ACTIVE), _thing()]
    runs = []
    for _ in range(60):                       # two seconds at 30 Hz
        mask, off_dt = ai._offscreen_rows(monsters, 1 / 30)
        assert mask is not None and mask.tolist() == [False, True, False]
        if off_dt > 0:
            runs.append(off_dt)
    # Each run carries at least the interval, and no time is lost.
    assert all(r >= ai.OFFSCREEN_INTERVAL for r in runs)
    assert len(runs) >= int(2.0 / ai.OFFSCREEN_INTERVAL) - 2
    assert sum(runs) + ai._offscreen_accum == pytest.approx(2.0)


def test_without_a_fitted_view_every_monster_runs_every_tick():
    ai = _ai(fit=False)
    mask, off_dt = ai._offscreen_rows([_thing(TIER_ACTIVE)], 1 / 30)
    assert mask is None and off_dt == 0.0


def test_a_per_row_delta_of_zero_sits_a_monster_out():
    """The dense pass takes one delta per row; 0 means 'not this tick'."""
    dt = np.where(np.array([False, True]), 0.0, 1 / 30)
    assert (dt <= 0.0).tolist() == [False, True]
    assert TIER_DORMANT > TIER_ACTIVE      # parked rows never reach the pass
