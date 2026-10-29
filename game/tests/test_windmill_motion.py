"""Starts, stops and reversals preserve speed, phase and elapsed real time."""

import pytest

from ..windmills import RotorMotion, RUN_SPEED, SPIN_DOWN_SECONDS, SPIN_UP_SECONDS


def test_a_mill_accelerates_then_runs_at_steady_speed():
    motion = RotorMotion()
    motion.advance(SPIN_UP_SECONDS / 2, True)
    assert motion.speed == pytest.approx(RUN_SPEED / 2)
    assert motion.angle == pytest.approx(RUN_SPEED * SPIN_UP_SECONDS / 8)
    motion.advance(SPIN_UP_SECONDS / 2, True)
    assert motion.speed == RUN_SPEED
    angle = motion.angle
    motion.advance(1.0, True)
    assert motion.angle - angle == pytest.approx(RUN_SPEED)


def test_a_stopped_mill_coasts_to_rest_and_keeps_its_angle():
    motion = RotorMotion(angle=100, speed=RUN_SPEED)
    motion.advance(SPIN_DOWN_SECONDS / 2, False)
    assert motion.speed == pytest.approx(RUN_SPEED / 2)
    assert motion.angle > 100
    motion.advance(SPIN_DOWN_SECONDS / 2, False)
    assert motion.speed == 0
    assert motion.angle == pytest.approx(100 + RUN_SPEED * SPIN_DOWN_SECONDS / 2)
    angle = motion.angle
    motion.advance(30.0, False)
    assert motion.angle == angle
    motion.advance(0.1, True)
    assert motion.angle > angle
    assert 0 < motion.speed < RUN_SPEED


def test_reversing_a_transition_continues_from_the_current_speed():
    motion = RotorMotion()
    motion.advance(0.6 * SPIN_UP_SECONDS, True)
    speed, angle = motion.speed, motion.angle
    motion.advance(0.1, False)
    assert 0 < motion.speed < speed
    assert motion.angle > angle
    speed, angle = motion.speed, motion.angle
    motion.advance(0.1, True)
    assert speed < motion.speed < RUN_SPEED
    assert motion.angle > angle


@pytest.mark.parametrize('steps', [1, 30, 60, 144])
def test_motion_is_independent_of_tick_size_even_when_a_tick_finishes_a_ramp(steps):
    motion = RotorMotion()
    for producing, seconds in [(True, 2.25), (False, 0.4), (True, 1.1), (False, 3.0)]:
        for _ in range(steps):
            motion.advance(seconds / steps, producing)
    reference = RotorMotion()
    for producing, seconds in [(True, 2.25), (False, 0.4), (True, 1.1), (False, 3.0)]:
        reference.advance(seconds, producing)
    assert motion.angle == pytest.approx(reference.angle)
    assert motion.speed == reference.speed == 0.0


@pytest.mark.parametrize('delta', [0.0, -1.0, float('nan'), float('inf')])
def test_invalid_or_paused_ticks_leave_motion_unchanged(delta):
    motion = RotorMotion(angle=23, speed=15)
    motion.advance(delta, True)
    assert motion.angle == 23 and motion.speed == 15


def test_many_revolutions_keep_the_angle_bounded():
    motion = RotorMotion(speed=RUN_SPEED)
    motion.advance(10000.5, True)
    assert motion.angle == pytest.approx((10000.5 * RUN_SPEED) % 360)
