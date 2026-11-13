"""
Wind: which way it blows across the Vale, and how hard.

One wind for the whole world, wandering slowly: its direction drifts a few
degrees a minute and turns now and then, its strength rises and falls over
the hours between a still morning and a gusty afternoon. Fire in the grass
runs before it (:mod:`game.grass_fire`) and its smoke drifts down it.

It is plain state advanced by game time -- no Qt, no GL -- and keeps nothing
between sessions: each day's wind is new.
"""

from __future__ import annotations

import math
import random

#: Radians the direction may drift per game hour, at most.
DRIFT_PER_HOUR = 0.6
#: Strength never falls below this (a breath of air) nor above 1 (a gale).
CALM = 0.15
#: How fast strength follows its slowly wandering target (per game hour).
EASE_PER_HOUR = 0.8


class Wind:
    """The world's wind: :meth:`vector` is ``(x, z)`` scaled by strength."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.angle = self.rng.uniform(0.0, 2.0 * math.pi)   # the way it blows TO
        self.strength = self.rng.uniform(0.3, 0.7)
        self._target = self.strength
        self._turn = 0.0

    def update(self, hours: float) -> None:
        """Advance the wind by *hours* of game time."""
        hours = max(0.0, min(1.0, float(hours)))
        if hours <= 0.0:
            return
        rng = self.rng
        # The heading wanders: a slow random turn that itself changes.
        self._turn += rng.uniform(-1.0, 1.0) * hours * 2.0
        self._turn = max(-1.0, min(1.0, self._turn))
        self.angle = (self.angle + self._turn * DRIFT_PER_HOUR * hours) % (2.0 * math.pi)
        # Strength eases toward a target that is picked afresh now and then.
        if rng.random() < hours * 0.5:
            self._target = rng.uniform(CALM, 1.0)
        self.strength += (self._target - self.strength) * min(1.0, EASE_PER_HOUR * hours)
        self.strength = max(CALM, min(1.0, self.strength))

    def direction(self):
        """The unit ``(x, z)`` the wind blows toward."""
        return math.cos(self.angle), math.sin(self.angle)

    def vector(self):
        """``(x, z)``: the direction scaled by strength (0..1)."""
        dx, dz = self.direction()
        return dx * self.strength, dz * self.strength
