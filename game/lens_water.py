"""
Rain on the lens: the camera gets wet when it rains.

While it rains, drops land on the camera's glass -- more in a storm -- and
run down it, as water does on a window or a camera lens in the rain. Drawn
from how games and shaders do it:

* Every drop runs downward, and the bigger it is the faster: a tiny bead
  clings to the glass and barely creeps (surface tension holds it), a
  middling drop wanders slowly down, and a big one races down and off the
  bottom (water drops on glass move once their weight beats what holds them).
* A drop that runs does so in fits and starts, snagging and slipping (the
  stick-slip of a drop on glass, as in the well-known "Heartfelt" rain on
  glass shader), and wanders a little from side to side as it goes.
* It leaves a trail of small beads behind it, losing water to them, and
  sweeps up whatever beads lie in its path: each one it gathers makes it
  heavier and faster.
* A running drop is drawn long, rounded at the bottom and narrowing above; a
  bead is egg-shaped, a little wider at the bottom (MotoGP's lens drops,
  studied on a sprayed office window).
* Small beads and the trails do not last: they fade off the glass after a
  few seconds even in the rain, so it never fills up. When the rain stops
  everything dries, the smallest first.
* When the camera moves quickly, the air pushes the drops back across the
  glass, against its movement (MotoGP's drops ran to the edge of the lens
  when the camera moved fast) -- big ones most.

Each drop is a little lens with no colour of its own: the picture behind it
is seen through it upside-down, mirrored and much smaller (nearly the whole
view fits in a drop), with a dark edge. That is drawn by
:func:`game.ui.magic_gl.draw_wet_lens`, a pass over the finished frame; this
module is only the drops, as plain data in screen fractions (x 0..1 across,
y 0..1 down; a radius as a share of the screen's height), advanced by real
time. No Qt, no GL: tested headless.
"""

from __future__ import annotations

import math
import random

#: Drops on the glass at once, at most (the shader's uniform array).
MAX_DROPS = 64
#: Drops landing a second at full rain, and their radius as they land (share
#: of the screen's height).
LAND_PER_SECOND = 9.0
LAND_RADIUS = (0.006, 0.03)
#: Below this radius a bead clings to the glass and only creeps.
PIN_RADIUS = 0.011
#: A drop this big runs at RUN_SPEED (screen heights a second); between the
#: two the speed rises steeply with size (``t ** 1.5``). Bigger still runs
#: faster yet, up to MAX_SPEED.
RUN_RADIUS = 0.045
RUN_SPEED = 0.55
MAX_SPEED = 0.9
#: How fast a clinging bead creeps down.
CREEP_SPEED = 0.006
#: Stick-slip: the speed swings between SNAG (stuck) and a surge, averaging
#: the size's speed; snags come and go this often (a second) for a small
#: runner, twice as often for a big one.
SNAG = 0.3
SLIP_RATE = 0.6
#: Side-to-side wander of a running drop (share of the screen's width).
WANDER = 0.012
#: A runner leaves a bead behind every this-many of its own radii of travel,
#: each bead this share of its radius.
TRAIL_GAP = (1.3, 2.4)
TRAIL_BEAD = (0.16, 0.3)
#: Seconds a bead lasts on the glass even in the rain (trail beads, then
#: small landed beads), so the glass never fills up.
TRAIL_LIFE = (1.5, 4.5)
BEAD_LIFE = (6.0, 14.0)
#: Seconds a drop takes to dry once the rain stops (the smallest first).
DRY_SECONDS = (2.5, 9.0)
#: How far a running drop stretches with speed (1 = round), and the most.
STRETCH_PER_SPEED = 1.6
MAX_STRETCH = 1.7
#: Camera movement: *motion* 1 (fast) pushes a RUN_RADIUS drop back across
#: the glass at this speed (screen heights a second), smaller ones less.
AIR_PUSH = 0.18


class Drop:
    """One drop on the glass."""

    __slots__ = ("x", "y", "r", "wet", "phase", "gap", "seed", "life", "trail",
                 "speed", "x0")

    def __init__(self, x, y, r, wet=0.2, *, rng=None, trail=False):
        rng = rng or random
        self.x = self.x0 = float(x)       # x0: where it would be without wandering
        self.y = float(y)
        self.r = float(r)
        self.wet = float(wet)
        self.phase = rng.random() * 6.2831853
        self.gap = self.r * rng.uniform(*TRAIL_GAP)
        self.seed = rng.random() * 100.0
        self.life = rng.uniform(*(TRAIL_LIFE if trail else BEAD_LIFE))
        self.trail = trail
        self.speed = 0.0                   # how fast it moved last update

    def stretch(self) -> float:
        return min(MAX_STRETCH, 1.0 + self.speed * STRETCH_PER_SPEED)


def run_speed(r: float) -> float:
    """How fast a drop of radius *r* runs down the glass, on average (screen
    heights a second): bigger is faster."""
    if r <= PIN_RADIUS:
        return CREEP_SPEED
    t = (r - PIN_RADIUS) / (RUN_RADIUS - PIN_RADIUS)
    if t <= 1.0:
        return CREEP_SPEED + (RUN_SPEED - CREEP_SPEED) * t ** 1.5
    return min(MAX_SPEED, RUN_SPEED * (r / RUN_RADIUS) ** 1.5)


def _slip(phase: float) -> float:
    """The stick-slip swing: averages 1 over a cycle, SNAG at its least."""
    pulse = max(0.0, math.sin(phase)) ** 2          # averages 1/4
    return SNAG + (1.0 - SNAG) * 4.0 * pulse


def _wander(y: float, seed: float) -> float:
    """Side-to-side offset at height *y*: mostly straight, now and then a
    sideways jink (Heartfelt's ``sin(3w) * sin(w)^6``)."""
    w = y * 9.0 + seed
    return math.sin(3.0 * w) * math.sin(w) ** 6


class LensWater:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.drops: list[Drop] = []
        self._carry = 0.0

    def update(self, seconds: float, rain: float, motion=(0.0, 0.0)) -> None:
        """Advance by *seconds* of real time with rain at *rain* (0..1);
        *motion* is the camera's movement across the screen, ``(x, y)``
        with length 1 for fast."""
        dt = max(0.0, min(0.25, float(seconds)))
        rng = self.rng
        rain = max(0.0, min(1.0, float(rain)))
        mx, my = (float(motion[0]), float(motion[1])) if motion else (0.0, 0.0)
        m = math.hypot(mx, my)
        if m > 1.0:
            mx, my = mx / m, my / m
        # New drops land.
        self._carry += LAND_PER_SECOND * rain * dt
        while self._carry >= 1.0:
            self._carry -= 1.0
            self._land(rng.random(), rng.random() * 0.95, rng.uniform(*LAND_RADIUS))
        kept = []
        beads = []
        for d in self.drops:
            fading = False
            if d.r <= PIN_RADIUS * 1.2:
                # Beads and trails fade off the glass, even in the rain.
                d.life -= dt
                fading = d.life <= 0.0
            if fading:
                d.wet -= dt * 1.5
            elif rain < 0.05:
                # Drying: small drops go first.
                d.wet -= dt / (DRY_SECONDS[0] + (DRY_SECONDS[1] - DRY_SECONDS[0])
                               * min(1.0, d.r / RUN_RADIUS))
            else:
                d.wet = min(1.0, d.wet + dt * 2.0)
            if d.wet <= 0.0:
                continue
            running = d.r > PIN_RADIUS
            speed = run_speed(d.r)
            if running:
                d.phase += dt * 6.2831853 * SLIP_RATE * (1.0 + min(1.0, d.r / RUN_RADIUS))
                speed *= _slip(d.phase)
            dy = speed * dt
            d.y += dy
            # The air pushes it back against the camera's movement.
            push = AIR_PUSH * min(1.5, d.r / RUN_RADIUS) * dt
            d.x0 -= mx * push
            d.y -= my * push
            d.x = d.x0 + (WANDER * _wander(d.y, d.seed) if running else 0.0)
            d.speed = speed
            if running:
                d.gap -= dy
                if d.gap <= 0.0:
                    d.gap = d.r * rng.uniform(*TRAIL_GAP)
                    b = d.r * rng.uniform(*TRAIL_BEAD)
                    # Behind its tail, just clear of it (so it is not
                    # gathered straight back).
                    back = (d.r + b) * 0.85 + d.r * (d.stretch() - 1.0)
                    beads.append(Drop(d.x, d.y - back, b, d.wet, rng=rng, trail=True))
                    d.r = math.sqrt(max(PIN_RADIUS ** 2 * 0.5, d.r * d.r - b * b))
            if d.y - d.r > 1.0 or d.y + d.r < 0.0 or d.x + d.r < -0.1 or d.x - d.r > 1.1:
                continue                           # off the glass
            kept.append(d)
        room = MAX_DROPS - len(kept)
        if beads and room > 0:
            kept.extend(beads[:room])
        self.drops = kept[-MAX_DROPS:]
        self._merge()

    def _land(self, x, y, r) -> None:
        self.drops.append(Drop(x, y, r, 0.2, rng=self.rng))
        if len(self.drops) > MAX_DROPS:
            # The glass is full: the smallest bead gives way.
            i = min(range(len(self.drops) - 1), key=lambda k: self.drops[k].r)
            del self.drops[i]

    def _merge(self) -> None:
        """Drops that touch run together into one bigger drop -- a runner
        sweeping up the beads in its path grows, and so runs faster."""
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
                if math.hypot(a.x - b.x, a.y - b.y) < (a.r + b.r) * 0.8:
                    # Area adds; the bigger keeps its place and its way.
                    big, small = (a, b) if a.r >= b.r else (b, a)
                    big.r = math.sqrt(big.r ** 2 + small.r ** 2)
                    big.wet = max(big.wet, small.wet)
                    big.life = max(big.life, small.life)
                    big.trail = big.trail and small.trail
                    gone.add(j if big is a else i)
                    if big is b:
                        break
        if gone:
            self.drops = [d for k, d in enumerate(drops) if k not in gone]

    def frame(self):
        """``[(x, y, radius, wetness, stretch)]`` for the lens pass."""
        return [(d.x, d.y, d.r, d.wet, d.stretch()) for d in self.drops]

    def clear(self) -> None:
        self.drops = []
