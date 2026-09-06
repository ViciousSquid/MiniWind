"""
Tests for the MiniWind camera render-distance cull (:mod:`engine.render_cull`).

The cull's geometry is deliberately GL-free so it can be checked without an
OpenGL context. These tests prove the contract the renderer relies on: objects
beyond the radius are excluded, objects within it are passed through unchanged
and in order, the test is a squared XZ distance (Y is ignored, no sqrt), the
``keep`` exemption and missing-position fail-open both retain objects, and the
reusable ``out`` buffer allocates nothing new across "frames".

Run:  python -m pytest engine/tests/test_render_cull.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import render_cull as rc


def _brush(x, y, z):
    return {"pos": [x, y, z]}


class _Thing:
    def __init__(self, pos, kind="thing"):
        self.pos = list(pos)
        self.kind = kind


def test_distant_objects_are_excluded_near_ones_kept():
    d = rc.CAMERA_RENDER_CULL_DISTANCE
    near = _brush(100.0, 0.0, 0.0)          # well inside
    edge = _brush(d - 1.0, 0.0, 0.0)        # just inside the radius
    far = _brush(d + 1.0, 0.0, 0.0)         # just outside
    very_far = _brush(10 * d, 0.0, 0.0)     # way outside
    out = rc.cull_by_distance([near, edge, far, very_far], 0.0, 0.0)
    assert near in out and edge in out
    assert far not in out and very_far not in out


def test_within_radius_is_passed_through_unchanged_and_in_order():
    objs = [_brush(0, 0, 0), _brush(500, 0, -500), _brush(-1000, 0, 200)]
    out = rc.cull_by_distance(objs, 0.0, 0.0)
    assert out == objs                       # same objects, same order, nothing added


def test_cull_uses_squared_xz_distance_ignoring_height():
    d = rc.CAMERA_RENDER_CULL_DISTANCE
    # A huge Y offset must not matter — only the XZ footprint is measured.
    high_but_near = _brush(10.0, 100000.0, 10.0)
    # Distance is measured on the diagonal: (3000, 3000) is ~4243 > 4096 → culled.
    diagonal_far = _brush(3000.0, 0.0, 3000.0)
    out = rc.cull_by_distance([high_but_near, diagonal_far], 0.0, 0.0)
    assert high_but_near in out
    assert diagonal_far not in out


def test_cull_is_measured_from_the_camera_centre():
    d = rc.CAMERA_RENDER_CULL_DISTANCE
    obj = _brush(5000.0, 0.0, 0.0)
    # From the origin it's culled; from a camera beside it, it's kept.
    assert obj not in rc.cull_by_distance([obj], 0.0, 0.0)
    assert obj in rc.cull_by_distance([obj], 5000.0, 0.0)


def test_keep_predicate_and_missing_position_fail_open():
    d = rc.CAMERA_RENDER_CULL_DISTANCE
    far_light = _Thing([10 * d, 0, 0], kind="light")   # far, but exempt
    far_plain = _Thing([10 * d, 0, 0], kind="thing")   # far, not exempt
    positionless = {"no": "pos"}                        # cannot be measured
    out = rc.cull_by_distance(
        [far_light, far_plain, positionless], 0.0, 0.0,
        keep=lambda o: getattr(o, "kind", "") == "light")
    assert far_light in out                             # kept by predicate
    assert positionless in out                          # kept: fail-open
    assert far_plain not in out                         # the only one culled


def test_out_buffer_is_reused_without_reallocating():
    buf = []
    first = rc.cull_by_distance([_brush(0, 0, 0)], 0.0, 0.0, out=buf)
    assert first is buf                                 # returns the same list object
    # A second "frame" clears and refills the *same* buffer — no new list.
    second = rc.cull_by_distance([_brush(10, 0, 10), _brush(20, 0, 20)], 0.0, 0.0, out=buf)
    assert second is buf
    assert len(buf) == 2


def test_camera_xz_accepts_sequences_and_vec_like():
    class _Vec:
        x, y, z = 1.0, 2.0, 3.0
    assert rc.camera_xz([1.0, 2.0, 3.0]) == (1.0, 3.0)
    assert rc.camera_xz(_Vec()) == (1.0, 3.0)


def test_threshold_is_the_configured_constant():
    assert rc.CAMERA_RENDER_CULL_DISTANCE == 4096.0
    assert rc.CAMERA_RENDER_CULL_DISTANCE_SQ == 4096.0 * 4096.0
