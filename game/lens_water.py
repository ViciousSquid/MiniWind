"""
Rain on the lens: the camera gets wet when it rains.

While it rains, drops land on the camera's glass -- more in a storm -- and
sit there: small beads, and larger drops that grow as others run into them.
A drop that grows heavy enough slides down the glass, leaving a trail of
small beads behind, and runs off the bottom. When the rain stops they dry
off, the smallest first.

Each drop is a little lens: the picture behind it is seen through it
upside-down and smaller, with a bright rim and a darker edge, as through real
water on glass. That is drawn by :func:`game.ui.magic_gl.draw_wet_lens`, a
pass over the finished frame; this module is only the drops, as plain data
in screen fractions (x 0..1 across, y 0..1 down; a radius as a share of the
screen's height), advanced by real time. No Qt, no GL: tested headless.
"""

from __future__ import annotations

import math
import random

#: Drops on the glass at once, at most (the shader's uniform array).
MAX_DROPS = 48
#: Drops landing a second at full rain.
LAND_PER_SECOND = 9.0
#: A drop's radius when it lands (share of screen height), and the size at
#: which it is heavy enough to slide.
LAND_RADIUS = (0.008, 0.032)
SLIDE_RADIUS = 0.04
#: How fast a heavy drop slides (screen heights a second), and how often it
#: leaves a bead behind.
SLIDE_SPEED = (0.05, 0.16)
TRAIL_EVERY = 0.06
#: Seconds a drop takes to dry once the rain stops (the smallest first).
DRY_SECONDS = (2.5, 9.0)


class LensWater:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        #: [x, y, radius, wetness 0..1, slide speed, trail clock]
        self.drops = []
        self._carry = 0.0

    def update(self, seconds: float, rain: float) -> None:
        """Advance by *seconds* of real time with rain at *rain* (0..1)."""
        dt = max(0.0, min(0.25, float(seconds)))
        rng = self.rng
        rain = max(0.0, min(1.0, float(rain)))
        # New drops land.
        self._carry += LAND_PER_SECOND * rain * dt
        while self._carry >= 1.0:
            self._carry -= 1.0
            self._land(rng.random(), rng.random() * 0.95, rng.uniform(*LAND_RADIUS))
        kept = []
        for d in self.drops:
            x, y, r, wet, speed, trail = d
            if rain < 0.05:
                # Drying: small drops go first.
                wet -= dt / (DRY_SECONDS[0] + (DRY_SECONDS[1] - DRY_SECONDS[0]) * min(1.0, r / SLIDE_RADIUS))
                if wet <= 0.0:
                    continue
            else:
                wet = min(1.0, wet + dt * 2.0)
            if r >= SLIDE_RADIUS:
                if speed <= 0.0:
                    speed = rng.uniform(*SLIDE_SPEED)
                y += speed * dt
                x += math.sin(y * 40.0 + r * 900.0) * 0.004 * dt   # a little wander
                trail -= dt
                if trail <= 0.0 and len(self.drops) < MAX_DROPS:
                    trail = TRAIL_EVERY
                    kept.append([x, y - r * 1.2, r * rng.uniform(0.18, 0.32), wet, 0.0, 0.0])
                r = max(LAND_RADIUS[0], r - dt * 0.004)            # it loses water as it runs
                if y - r > 1.0:
                    continue                                       # off the bottom
            kept.append([x, y, r, wet, speed, trail])
        self.drops = kept[-MAX_DROPS:]
        self._merge()

    def _land(self, x, y, r) -> None:
        self.drops.append([x, y, r, 0.2, 0.0, 0.0])
        if len(self.drops) > MAX_DROPS:
            # The glass is full: the smallest standing bead gives way.
            i = min(range(len(self.drops) - 1), key=lambda k: self.drops[k][2])
            del self.drops[i]

    def _merge(self) -> None:
        """Drops that touch run together into one bigger drop."""
        drops = self.drops
        n = len(drops)
        gone = set()
        for i in range(n):
            if i in gone:
                continue
            a = drops[i]
            for j in range(i + 1, n):
                if j in gone:
                    continue
                b = drops[j]
                if math.hypot(a[0] - b[0], (a[1] - b[1])) < (a[2] + b[2]) * 0.8:
                    # Area adds; the bigger keeps its place.
                    big, small = (a, b) if a[2] >= b[2] else (b, a)
                    big[2] = math.sqrt(big[2] ** 2 + small[2] ** 2)
                    big[3] = max(big[3], small[3])
                    gone.add(j if big is a else i)
                    if big is b:
                        break
        if gone:
            self.drops = [d for k, d in enumerate(drops) if k not in gone]

    def frame(self):
        """``[(x, y, radius, wetness)]`` for the lens pass."""
        return [(d[0], d[1], d[2], d[3]) for d in self.drops]

    def clear(self) -> None:
        self.drops = []
