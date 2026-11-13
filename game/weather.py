"""
Weather: clear skies, cloud, rain and storms over the Vale, and what they do.

One weather for the world, changing by itself over the game's hours: a spell
of clear sky, cloud gathering, rain, now and then a storm, clearing again.
How hard it rains eases in and out rather than switching; the ground gets
wet in the rain and dries afterwards, faster under a clear sky.

What it does to fire (:mod:`game.grass_fire`, :mod:`game.burning`):

* rain makes burning grass burn out faster and spread slower -- heavy rain
  stops a fire spreading at all and soon puts it out;
* wet ground barely catches (its fuel is scaled by :meth:`Weather.dryness`);
* someone burning, and a Flare's fire on the ground, go out sooner.

The look is drawn by :mod:`game.ui.rain` over the scene. It is plain state
advanced by game time -- no Qt, no GL -- so it is tested headless.
"""

from __future__ import annotations

import random

CLEAR, OVERCAST, RAIN, STORM = "clear", "overcast", "rain", "storm"
KINDS = (CLEAR, OVERCAST, RAIN, STORM)
#: How hard it rains in each, 0..1, and how long a spell of each lasts
#: (game hours, min..max).
RAIN_OF = {CLEAR: 0.0, OVERCAST: 0.0, RAIN: 0.55, STORM: 1.0}
SPELL_HOURS = {CLEAR: (6.0, 20.0), OVERCAST: (2.0, 6.0), RAIN: (1.0, 5.0), STORM: (0.5, 2.0)}
#: What follows what, and how likely.
NEXT = {CLEAR: ((OVERCAST, 1.0),),
        OVERCAST: ((RAIN, 0.55), (CLEAR, 0.35), (STORM, 0.10)),
        RAIN: ((OVERCAST, 0.6), (STORM, 0.15), (CLEAR, 0.25)),
        STORM: ((RAIN, 0.7), (OVERCAST, 0.3))}
#: How fast the rain eases toward what the sky is doing (per game hour).
EASE_PER_HOUR = 3.0
#: Wetness: how fast rain soaks the ground, and how fast it dries (per game
#: hour; clear sky dries twice as fast as cloud).
SOAK_PER_HOUR = 1.5
DRY_PER_HOUR = 0.12
#: How dark the sky is over each (a wash over the scene, 0..1).
GLOOM_OF = {CLEAR: 0.0, OVERCAST: 0.18, RAIN: 0.3, STORM: 0.45}


class Weather:
    def __init__(self, rng=None, kind=CLEAR):
        self.rng = rng or random.Random()
        self.kind = kind
        self.left = self._spell(kind)
        self.rain = RAIN_OF[kind]
        self.gloom = GLOOM_OF[kind]
        self.wet = 0.0
        #: A spell forced from the console: (kind, hours) or None.
        self.forced = False

    def _spell(self, kind) -> float:
        lo, hi = SPELL_HOURS[kind]
        return self.rng.uniform(lo, hi)

    def set(self, kind, hours=None) -> bool:
        """Make it *kind* now, for *hours* (or a spell of the usual length)."""
        if kind not in KINDS:
            return False
        self.kind = kind
        self.left = float(hours) if hours else self._spell(kind)
        self.forced = True
        return True

    def update(self, hours: float) -> None:
        """Advance the weather by *hours* of game time."""
        hours = max(0.0, min(2.0, float(hours)))
        if hours <= 0.0:
            return
        self.left -= hours
        if self.left <= 0.0:
            self.kind = self._roll(NEXT[self.kind])
            self.left = self._spell(self.kind)
            self.forced = False
        k = min(1.0, EASE_PER_HOUR * hours)
        self.rain += (RAIN_OF[self.kind] - self.rain) * k
        self.gloom += (GLOOM_OF[self.kind] - self.gloom) * k
        if self.rain > 0.05:
            self.wet = min(1.0, self.wet + SOAK_PER_HOUR * self.rain * hours)
        else:
            dry = DRY_PER_HOUR * (2.0 if self.kind == CLEAR else 1.0)
            self.wet = max(0.0, self.wet - dry * hours)

    def _roll(self, options):
        r = self.rng.random() * sum(w for _k, w in options)
        for kind, w in options:
            r -= w
            if r <= 0.0:
                return kind
        return options[-1][0]

    # -- what it does ------------------------------------------------------------
    def raining(self) -> bool:
        return self.rain > 0.08

    def dryness(self) -> float:
        """How readily grass burns (0 soaked .. 1 dry)."""
        return max(0.05, 1.0 - 0.9 * self.wet)

    def douse(self) -> float:
        """How hard the rain fights fire this instant (0..1)."""
        return max(0.0, min(1.0, self.rain))

    def snapshot(self) -> dict:
        return {"kind": self.kind, "left": round(self.left, 3), "rain": round(self.rain, 3),
                "gloom": round(self.gloom, 3), "wet": round(self.wet, 3)}

    def restore(self, data) -> None:
        if not isinstance(data, dict) or data.get("kind") not in KINDS:
            return
        self.kind = data["kind"]
        for key in ("left", "rain", "gloom", "wet"):
            try:
                setattr(self, key, float(data.get(key, getattr(self, key))))
            except (TypeError, ValueError):
                pass
