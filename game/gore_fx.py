"""
Blood: the spray of a wound, the splash where it lands, the pool under the
dead, the chunks of a body blown apart, and the player's own blood on the edge
of the screen.

Everything here is plain data in world coordinates, advanced by time. Blood
that comes to rest is **stamped into the surface it lies on** through
:attr:`GoreFX.stamp` -- baked into the terrain's own paint, so it is part of
the ground, cannot z-fight, and stays -- a few each update so a massacre does
not stall a frame. Blood in flight, a pool still spreading, and blood on a
surface that cannot take a stamp (a brush floor) are drawn by the HUD
(:func:`game.ui.hud.draw_gore`) over the world, masked out under living
actors so it never paints over anyone standing in it. Droplets fly on real arcs and land as splats that stay on the
ground; a killing blow opens a pool that spreads under the body; a gib throws
dark chunks and a much bigger spray. Old blood dries and fades.

Safe to feed from the game tick and draw from the UI thread (one lock).
Pure Python: no Qt, so it is tested headless.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Dict, List

#: World units per second squared pulling droplets down.
GRAVITY = 1400.0
#: How long blood lies on the ground before it has dried away (s), and the
#: last stretch of that over which it fades.
SPLAT_LIFE = 240.0
SPLAT_FADE = 30.0
#: However bloody it gets, no more than this many at once (oldest go first).
MAX_SPLATS = 600
MAX_PARTICLES = 500
#: Seconds a pool takes to spread to its full size.
POOL_SPREAD = 2.5
#: Most splats stamped into the ground per update (each costs a little).
STAMPS_PER_UPDATE = 6
#: How long the red flash at the screen's edge lasts, and screen blood.
FLASH_SECONDS = 0.35
SCREEN_BLOOD_SECONDS = 2.2


class GoreFX:
    """The blood in the world right now (see the module docstring)."""

    def __init__(self, rng=None, clock=time.monotonic):
        self.rng = rng or random.Random()
        self.clock = clock
        self._lock = threading.Lock()
        #: Droplets and chunks in flight.
        self.particles: List[Dict] = []
        #: Blood on the ground: splashes and pools.
        self.splats: List[Dict] = []
        #: Blotches on the screen's edge (fractions of the view), the player's own.
        self.screen: List[Dict] = []
        self.flash = (0.0, 0.0)            # (strength 0..1, when)
        #: ``stamp(splat) -> bool``: bake a splat into the surface under it;
        #: True when it took (it is then forgotten here). None: never stamp.
        self.stamp = None

    # ---------------------------------------------------------- spawning
    def wound(self, pos, damage, max_health=30.0, away=None, crit=False):
        """A blow lands at *pos* (the victim's feet): blood sprays, more the
        harder it hit relative to the victim, flung *away* (an (x, z)
        direction) from whoever struck it."""
        frac = max(0.05, min(3.0, float(damage) / max(1.0, float(max_health))))
        count = int(8 + 30 * min(1.0, frac)) + (16 if crit else 0)
        speed = 90.0 + 150.0 * min(1.0, frac) + (80.0 if crit else 0.0)
        self._spray(pos, count, speed, away, size=(3.0, 8.0))
        # A splash where it was struck.
        self._splat(pos, 18.0 + 34.0 * min(1.0, frac), kind="splash")

    def kill(self, pos, max_health=30.0):
        """A killing blow: a pool spreads under the body."""
        size = 60.0 + min(90.0, float(max_health) * 0.8)
        self._splat(pos, size, kind="pool")

    def gib(self, pos, damage=60.0, away=None):
        """A body blown apart: chunks, a great spray and a wide spread of blood."""
        self._spray(pos, 80, 320.0, away, size=(3.0, 9.0))
        for _ in range(16):
            self._spray(pos, 1, 260.0, away, size=(8.0, 18.0), kind="chunk")
        for _ in range(6):
            dx, dz = self.rng.uniform(-70, 70), self.rng.uniform(-70, 70)
            self._splat((pos[0] + dx, pos[1], pos[2] + dz),
                        self.rng.uniform(45, 90), kind="pool")

    def hurt(self, fraction):
        """The player is struck for *fraction* of their health: their blood on
        the screen's edge, more for a harder blow."""
        n = 1 + int(min(1.0, float(fraction)) * 6)
        now = self.clock()
        with self._lock:
            for _ in range(n):
                edge = self.rng.choice(("l", "r", "t", "b"))
                along = self.rng.uniform(0.1, 0.9)
                x, y = {"l": (0.0, along), "r": (1.0, along),
                        "t": (along, 0.0), "b": (along, 1.0)}[edge]
                self.screen.append({"x": x, "y": y, "size": self.rng.uniform(0.07, 0.16),
                                    "t0": now, "seed": self.rng.random()})
            del self.screen[:-24]

    def flash_red(self, strength):
        """A red pulse at the screen's edge (a kill, a crit)."""
        if strength > self.flash_level():
            self.flash = (min(1.0, float(strength)), self.clock())

    def _spray(self, pos, count, speed, away, size, kind="drop"):
        now = self.clock()
        ax, az = away if away else (0.0, 0.0)
        alen = math.hypot(ax, az)
        with self._lock:
            for _ in range(int(count)):
                ang = self.rng.uniform(0.0, 2.0 * math.pi)
                spd = speed * self.rng.uniform(0.35, 1.0)
                vx, vz = math.cos(ang) * spd, math.sin(ang) * spd
                if alen > 1e-6:                 # flung away from the blow
                    vx += ax / alen * speed * 0.8
                    vz += az / alen * speed * 0.8
                self.particles.append({
                    "x": float(pos[0]), "y": float(pos[1]) + self.rng.uniform(30, 70),
                    "z": float(pos[2]), "gy": float(pos[1]),
                    "vx": vx, "vy": self.rng.uniform(60, 280), "vz": vz,
                    "t0": now, "size": self.rng.uniform(*size), "kind": kind,
                    "seed": self.rng.random()})
            del self.particles[:-MAX_PARTICLES]

    def _splat(self, pos, size, kind="splash", t0=None):
        with self._lock:
            self.splats.append({"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2]),
                                "size": float(size), "kind": kind,
                                "t0": self.clock() if t0 is None else t0,
                                "rot": self.rng.uniform(0, math.pi),
                                "seed": self.rng.random()})
            del self.splats[:-MAX_SPLATS]

    # ----------------------------------------------------------- the clock
    def update(self):
        """Land what has fallen (it becomes a splat) and forget dried blood."""
        now = self.clock()
        landed = []
        self._stamp_settled(now)
        with self._lock:
            flying = []
            for p in self.particles:
                t = now - p["t0"]
                if self._height(p, t) <= p["gy"] and t > 0.05:
                    landed.append(p)
                else:
                    flying.append(p)
            self.particles = flying
            self.splats = [s for s in self.splats if now - s["t0"] < SPLAT_LIFE]
            self.screen = [s for s in self.screen if now - s["t0"] < SCREEN_BLOOD_SECONDS]
        for p in landed:
            x, _y, z = self.position(p, now)
            self._splat((x, p["gy"], z), p["size"] * (2.8 if p["kind"] == "chunk" else 2.4),
                        kind="chunk" if p["kind"] == "chunk" else "drop")

    def _stamp_settled(self, now):
        """Bake blood that has come to rest into the ground, a few at a time;
        what will not take a stamp stays drawn as it is."""
        if self.stamp is None:
            return
        with self._lock:
            ready = [s for s in self.splats if not s.get("stamp_tried")
                     and (s["kind"] != "pool" or now - s["t0"] >= POOL_SPREAD)]
        stamped = set()
        for s in ready[:STAMPS_PER_UPDATE]:
            s["stamp_tried"] = True
            try:
                if self.stamp(dict(s, size=self.splat_size(s, now))):
                    stamped.add(id(s))
            except Exception:
                pass
        if stamped:
            with self._lock:
                self.splats = [s for s in self.splats if id(s) not in stamped]

    @staticmethod
    def _height(p, t):
        return p["y"] + p["vy"] * t - 0.5 * GRAVITY * t * t

    def position(self, p, now=None):
        """Where a particle in flight is at *now*."""
        now = self.clock() if now is None else now
        t = now - p["t0"]
        return (p["x"] + p["vx"] * t, max(p["gy"], self._height(p, t)), p["z"] + p["vz"] * t)

    # ------------------------------------------------------------- reading
    def flash_level(self) -> float:
        strength, when = self.flash
        left = 1.0 - (self.clock() - when) / FLASH_SECONDS
        return strength * left if left > 0 else 0.0

    def splat_alpha(self, s, now=None) -> float:
        """How visible a splat is: full until it starts to dry, then fading."""
        now = self.clock() if now is None else now
        age = now - s["t0"]
        return max(0.0, min(1.0, (SPLAT_LIFE - age) / SPLAT_FADE))

    def splat_size(self, s, now=None) -> float:
        """A pool spreads to its size; everything else lands at full size."""
        if s["kind"] != "pool":
            return s["size"]
        now = self.clock() if now is None else now
        k = max(0.0, min(1.0, (now - s["t0"]) / POOL_SPREAD))
        return s["size"] * (0.15 + 0.85 * (1.0 - (1.0 - k) ** 2))

    def snapshot(self):
        """``(particles, splats, screen)`` copies to draw from."""
        with self._lock:
            return list(self.particles), list(self.splats), list(self.screen)

    def clear(self):
        with self._lock:
            self.particles, self.splats, self.screen = [], [], []
