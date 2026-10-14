"""
Held weapons that follow a turn rather than being bolted to the head.

When the player turns, each weapon trails the turn a touch and overshoots by
a hair before settling: a damped spring on its facing, per hand. The two
hands' springs are tuned differently, so a dual wielder's weapons never move
in lockstep. The effect is kept small -- the lag is capped at a few degrees
and the overshoot dies within a fraction of a second -- noticeable as weight,
never as wobble for its own sake.

Pure maths; the viewport asks once per frame, through
:meth:`game.runtime.MiniwindSession.overhead_player_weapon`, for each hand's
offset from the head's facing.
"""

from __future__ import annotations

import math

#: Per hand: (stiffness, damping ratio). Underdamped, so a turn ends with a
#: small overshoot; different for the two hands, so they stay out of step.
HANDS = {
    "main": (230.0, 0.52),
    "off": (175.0, 0.44),
}
#: The most a weapon ever trails or overshoots its facing (radians, ~7 deg).
MAX_LAG = 0.12
#: Longer frame gaps than this are not integrated (a hitch, a pause).
MAX_STEP = 1.0 / 30.0


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


class Spring:
    """One hand's facing, chasing the head's."""

    __slots__ = ("k", "c", "angle", "vel", "last")

    def __init__(self, stiffness: float, damping_ratio: float):
        self.k = float(stiffness)
        self.c = 2.0 * float(damping_ratio) * math.sqrt(self.k)
        self.angle = None
        self.vel = 0.0
        self.last = None

    def offset(self, target: float, now: float) -> float:
        """Where this hand points relative to *target* (the head's facing),
        advanced to time *now*: positive or negative, at most MAX_LAG."""
        if self.angle is None or self.last is None:
            self.angle, self.vel, self.last = float(target), 0.0, now
            return 0.0
        dt = max(0.0, min(MAX_STEP, now - self.last))
        self.last = now
        # Integrate in a couple of sub-steps: stable at any frame rate.
        steps = 2
        h = dt / steps
        for _ in range(steps):
            error = _wrap(target - self.angle)
            acc = self.k * error - self.c * self.vel
            self.vel += acc * h
            self.angle += self.vel * h
        lag = _wrap(self.angle - target)
        if abs(lag) > MAX_LAG:
            # Held to the cap: dragged along at the head's pace, not lost.
            lag = math.copysign(MAX_LAG, lag)
            self.angle = target + lag
            self.vel *= 0.5
        return lag


class WeaponSway:
    """Both hands' springs for one player."""

    def __init__(self):
        self.springs = {hand: Spring(*tune) for hand, tune in HANDS.items()}

    def offset(self, hand: str, facing: float, now: float) -> float:
        spring = self.springs.get(hand)
        return spring.offset(facing, now) if spring is not None else 0.0
