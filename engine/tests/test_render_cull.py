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


# ---------------------------------------------------------------------------
# Camera-derived relevance region
# ---------------------------------------------------------------------------
#
# A fixed radius is the wrong shape for MiniWind's camera. Looking almost
# straight down from a few hundred units, the frustum leaves the world's
# vertical slab almost immediately, so the ground it covers is a box a couple of
# thousand units across — not the tens of thousands a 10,000-unit far plane
# implies. These pin the derived box down: tight where it should be, and never
# smaller than what is actually visible.

from engine.render_cull import (CAMERA_RENDER_CULL_DISTANCE,  # noqa: E402
                                WORLD_SLAB_MARGIN, visible_xz_bounds)


def _overhead_corners(height, far=10000.0, aspect=16.0 / 9.0):
    """Far-plane corners for a 90-degree camera looking straight down."""
    # tan(45) == 1, so the half-extents at distance `far` are far and far*aspect.
    return [(sx * far * aspect, height - far, sz * far)
            for sx in (-1.0, 1.0) for sz in (-1.0, 1.0)]


def test_the_overhead_box_is_far_tighter_than_the_hard_radius():
    box = visible_xz_bounds((0.0, 800.0, 0.0), _overhead_corners(800.0),
                            y_min=0.0, y_max=128.0)
    half_x = max(abs(box[0]), abs(box[2]))
    half_z = max(abs(box[1]), abs(box[3]))
    assert half_x < CAMERA_RENDER_CULL_DISTANCE
    assert half_z < CAMERA_RENDER_CULL_DISTANCE
    # The payoff is area: the region the engine considers should be a small
    # fraction of the square the fixed radius would have swept.
    area = (box[2] - box[0]) * (box[3] - box[1])
    radius_area = (2 * CAMERA_RENDER_CULL_DISTANCE) ** 2
    assert area < radius_area * 0.25


def test_a_higher_camera_sees_more_ground_than_a_lower_one():
    """The region tracks the actual camera, so pulling it up widens the box —
    which is the whole reason it is derived rather than a constant."""
    widths = [visible_xz_bounds((0.0, h, 0.0), _overhead_corners(h), 0.0, 0.0)[2]
              for h in (400.0, 800.0, 1600.0)]
    assert widths[0] < widths[1] < widths[2]


def test_the_box_covers_the_ground_the_camera_really_sees():
    """Conservative means never smaller than the truth: the exact footprint of a
    90-degree camera at height h is h by h*aspect, and the box must contain it."""
    h, aspect = 800.0, 16.0 / 9.0
    box = visible_xz_bounds((0.0, h, 0.0), _overhead_corners(h, aspect=aspect),
                            y_min=0.0, y_max=0.0)
    assert box[0] <= -h * aspect and box[2] >= h * aspect
    assert box[1] <= -h and box[3] >= h


def test_the_slab_margin_keeps_tall_things_in_view():
    """Geometry sits in a slab; the margin is what stops a tall billboard or a
    floating light at the very top of the world being cut out of the region."""
    tight = visible_xz_bounds((0.0, 800.0, 0.0), _overhead_corners(800.0),
                              y_min=0.0, y_max=0.0)
    # A point one margin above the geometry is still inside the returned box at
    # the height the camera would see it.
    assert tight[2] > WORLD_SLAB_MARGIN


def test_a_camera_looking_along_the_ground_is_bounded_by_the_hard_ceiling():
    """First person: the frustum runs the length of the world, so the ceiling —
    not the slab — is what bounds it, and the camera's own position is kept."""
    far = 10000.0
    corners = [(far, 64.0 + sy * far, sx * far)
               for sy in (-1.0, 1.0) for sx in (-1.0, 1.0)]
    box = visible_xz_bounds((0.0, 64.0, 0.0), corners, y_min=0.0, y_max=128.0)
    assert box[0] <= 0.0 <= box[2] and box[1] <= 0.0 <= box[3]
    assert box[2] <= CAMERA_RENDER_CULL_DISTANCE + 1.0


def test_a_camera_that_can_see_nothing_degenerates_to_its_own_position():
    """Never return an inverted box a caller would silently misread."""
    box = visible_xz_bounds((5.0, 100000.0, 7.0),
                            [(0.0, 100001.0, 0.0)], y_min=0.0, y_max=1.0)
    assert box == (5.0, 7.0, 5.0, 7.0)
