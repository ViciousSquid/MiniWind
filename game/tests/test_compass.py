"""Compass damping must settle gently, including turns across north's wrap."""

import math

import pytest

from game.compass import CompassNeedle


def test_first_frame_starts_at_current_north_without_a_false_sweep():
    needle = CompassNeedle()
    assert needle.update(1.2, 0.0) == pytest.approx(1.2)


def test_needle_trails_a_turn_then_settles_without_wobbling():
    needle = CompassNeedle()
    needle.update(0, 0)
    angles = [needle.update(math.pi / 2, frame / 60) for frame in range(1, 61)]
    assert 0 < angles[0] < math.pi / 2
    assert all(a <= b <= math.pi / 2 for a, b in zip(angles, angles[1:]))
    assert abs(angles[18] - math.pi / 2) < math.radians(4)
    assert angles[-1] == pytest.approx(math.pi / 2, abs=1e-5)


@pytest.mark.parametrize("sign", [-1, 1])
def test_wraparound_takes_the_short_path_in_both_directions(sign):
    needle = CompassNeedle()
    start, target = sign * math.radians(179), -sign * math.radians(179)
    needle.update(start, 0)
    angle = needle.update(target, 1 / 60)
    change = math.atan2(math.sin(angle - start), math.cos(angle - start))
    assert 0 < sign * change < math.radians(2)
    assert abs(angle) > math.radians(178)


@pytest.mark.parametrize("fps", [30, 60, 144])
def test_settling_is_consistent_across_frame_rates(fps):
    needle = CompassNeedle()
    needle.update(0, 0)
    for frame in range(1, fps // 2 + 1):
        angle = needle.update(1.0, frame / fps)
    reference = CompassNeedle()
    reference.update(0, 0)
    reference.update(1.0, .25)
    expected = reference.update(1.0, .5)
    assert angle == pytest.approx(expected, abs=1e-12)


def test_reopening_after_a_pause_resets_old_heading_and_momentum():
    needle = CompassNeedle()
    needle.update(0, 0)
    needle.update(1.0, .1)
    assert needle.velocity > 0
    assert needle.update(-2.0, 10) == pytest.approx(-2.0)
    assert needle.velocity == 0


def test_repainting_without_elapsed_time_does_not_advance_the_needle():
    needle = CompassNeedle()
    needle.update(0, 0)
    angle = needle.update(1.0, .1)
    assert needle.update(1.0, .1) == pytest.approx(angle)
