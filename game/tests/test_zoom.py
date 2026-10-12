"""
Mouse-wheel zoom of the top-down camera.

Each wheel notch moves the camera's target height by ZOOM_STEP, between
ZOOM_MIN_HEIGHT and ZOOM_MAX_HEIGHT and never above Big World's ceiling; the
session eases the camera there. The camera follows the player, so the zoom is
centred on them.

Run:  python -m pytest game/tests/test_zoom.py -q
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import runtime as rt
from .fio_logic import FioLogic


def _session(height=800.0, limit=None):
    class _Logic(FioLogic):
        def __init__(self):
            self.things = []
            self.player = None
    logic = _Logic()
    logic.camera = SimpleNamespace(overhead_height=height, overhead_height_limit=limit)
    return rt.MiniwindSession(logic, cfg={"start_hour": 12.0,
                                          "minutes_per_day": 999999.0}), logic.camera


def test_wheel_in_moves_closer_and_out_moves_away():
    s, cam = _session()
    s.zoom(1)
    assert s.zoom_height < 800.0
    s.zoom(-2)
    assert s.zoom_height > 800.0


def test_zoom_stays_between_the_limits():
    s, cam = _session()
    s.zoom(50)
    assert s.zoom_height == rt.ZOOM_MIN_HEIGHT
    s.zoom(-50)
    assert s.zoom_height == rt.ZOOM_MAX_HEIGHT


def test_zoom_never_goes_above_big_worlds_ceiling():
    s, cam = _session(height=800.0, limit=900.0)
    s.zoom(-50)
    assert s.zoom_height == 900.0


def test_the_camera_eases_to_the_zoom():
    s, cam = _session()
    s.zoom(2)
    target = s.zoom_height
    s._ease_zoom(1 / 60)
    assert target < cam.overhead_height < 800.0
    for _ in range(120):
        s._ease_zoom(1 / 60)
    assert cam.overhead_height == target


def test_without_a_zoom_the_camera_is_left_alone():
    s, cam = _session(height=750.0)
    s._ease_zoom(1 / 60)
    assert cam.overhead_height == 750.0
