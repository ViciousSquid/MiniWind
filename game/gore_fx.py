"""
Blood: the spray of a wound, the splash where it lands, the pool under the
dead, the chunks of a body blown apart, and the player's own blood on the edge
of the screen.

Everything here is plain data in world coordinates, advanced by time. Blood
that comes to rest is **stamped into the surface it lies on** through
:attr:`GoreFX.stamp` -- baked into the terrain's own paint, so it is part of
the ground, cannot z-fight, and stays -- a few each update so a massacre does
not stall a frame. A pool still spreading, and blood on a surface that cannot
take a stamp (a brush floor), are laid on the floor in the 3D pass under the
actors standing in it (:func:`game.ui.blood_gl.draw_decals`); blood in flight
is drawn by the HUD (:func:`game.ui.hud.draw_gore`) over the world. Droplets
fly on real arcs and land as splats that stay on the ground; a killing blow opens a pool that spreads under the body; a gib throws
dark chunks, a much bigger spray and the body itself in pieces: its own
picture broken into jagged shards that tumble out, land and lie a few seconds
before fading. Old blood dries and fades.

Safe to feed from the game tick and draw from the UI thread (one lock).
Pure Python: no Qt, so it is tested headless.
"""

from __future__ import annotations

import math
import os
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
#: A body blown apart breaks along a GIB_GRID x GIB_GRID jagged grid of its
#: own picture; a few of those pieces fly off whole (:func:`pieces_for`),
#: tumble, land and lie a while before fading. The rest goes as blood.
GIB_GRID = 3
#: A person-sized gib (body mass 1.0): droplets, dark chunks and pools.
GIB_DROPS = 100
GIB_CHUNKS = 9
GIB_POOLS = 7
PIECE_REST = 7.0
PIECE_FADE = 2.0
#: A bite out of a piece (crabs feeding, game/crab_frenzy.py): a circle of
#: the piece's picture this big (a share of the whole picture's width), and
#: the share of the piece that may be left when it counts as eaten.
BITE_RADIUS = (0.07, 0.11)
EATEN_LEFT = 0.08
#: Points sampled across a piece (per side) to tell how much is left.
_SAMPLES = 9
#: Seconds a pool takes to spread to its full size.
POOL_SPREAD = 2.5
#: Most splats stamped into the ground per update (each costs a little).
STAMPS_PER_UPDATE = 6
#: How long the red flash at the screen's edge lasts, and screen blood.
FLASH_SECONDS = 0.35
SCREEN_BLOOD_SECONDS = 2.2

#: The blood stamps, by kind (assets/sprites/miniwind/blood_stamps, made by
#: game/tools/make_blood_stamps.py).
STAMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "sprites", "miniwind", "blood_stamps")
_STAMPS: Dict[str, List[str]] = {}
#: How opaque blood lying on the ground is drawn, stamped or not.
STAMP_OPACITY = 0.92


def stamp_image(kind, seed):
    """A stamp image for a splat of *kind*, picked stably by *seed*: what
    blood baked into the terrain looks like, and blood lying on a floor."""
    kind = kind if kind in ("splash", "drop", "pool", "chunk") else "splash"
    if kind not in _STAMPS:
        try:
            _STAMPS[kind] = sorted(
                os.path.join(STAMP_DIR, f) for f in os.listdir(STAMP_DIR)
                if f.startswith(kind + "_") and f.endswith(".png"))
        except OSError:
            _STAMPS[kind] = []
    files = _STAMPS[kind]
    return files[int(float(seed) * 1e6) % len(files)] if files else None


def pieces_for(mass) -> int:
    """How many whole pieces fly off a body of *mass*: a hen 2, a small body
    3, a person 4, a bear 6, anything huge 8."""
    m = float(mass)
    return 2 if m < 0.2 else 3 if m < 0.6 else 4 if m < 1.5 else 6 if m < 2.6 else 8


def _small(mass) -> float:
    """Scale for blood that a person sheds in full: less from a smaller body,
    never more from a bigger one."""
    return min(1.0, math.sqrt(max(0.0, float(mass))))


def _rest_from(p) -> float:
    """When a piece's rest counts from: its landing, or -- while something
    feeds on it -- so that it starts fading only when the hold runs out."""
    held = p.get("held_until", 0.0)
    return max(p["rest"], held - (PIECE_REST - PIECE_FADE)) if held else p["rest"]


def _inside(quad, u, v) -> bool:
    """Whether (u, v) lies in the convex *quad* (the piece's outline)."""
    sign = 0
    for i in range(4):
        (au, av), (bu, bv) = quad[i], quad[(i + 1) % 4]
        cross = (bu - au) * (v - av) - (bv - av) * (u - au)
        if cross:
            if sign and (cross > 0) != (sign > 0):
                return False
            sign = 1 if cross > 0 else -1
    return True


def _remaining_points(p):
    """Sample points of piece *p* not yet bitten away: ``[(u, v, edge)]``,
    *edge* true where a neighbouring sample is gone or outside."""
    quad, bites = p["quad"], p.get("bites", ())
    us = [q[0] for q in quad]
    vs = [q[1] for q in quad]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    n = _SAMPLES
    step_u, step_v = (u1 - u0) / n, (v1 - v0) / n

    def there(i, j):
        u, v = u0 + (i + 0.5) * step_u, v0 + (j + 0.5) * step_v
        if not _inside(quad, u, v):
            return None
        for bu, bv, br in bites:
            if (u - bu) ** 2 + (v - bv) ** 2 <= br * br:
                return None
        return u, v

    grid = {(i, j): there(i, j) for i in range(n) for j in range(n)}
    out = []
    for (i, j), point in grid.items():
        if point is None:
            continue
        edge = any(grid.get((i + di, j + dj)) is None
                   for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        out.append((point[0], point[1], edge))
    return out


class GoreFX:
    """The blood in the world right now (see the module docstring)."""

    def __init__(self, rng=None, clock=time.monotonic):
        self.rng = rng or random.Random()
        self.clock = clock
        self._lock = threading.Lock()
        #: Droplets and chunks in flight.
        self.particles: List[Dict] = []
        #: Pieces of a body blown apart: flying, then lying where they fell.
        self.pieces: List[Dict] = []
        #: Blood on the ground: splashes and pools.
        self.splats: List[Dict] = []
        #: Blotches on the screen's edge (fractions of the view), the player's own.
        self.screen: List[Dict] = []
        self.flash = (0.0, 0.0)            # (strength 0..1, when)
        #: ``stamp(splat) -> bool``: bake a splat into the surface under it;
        #: True when it took (it is then forgotten here). None: never stamp.
        self.stamp = None
        #: ``ground(x, y, z) -> height or None``: the floor a splat at
        #: (x, y, z) lies on -- a built floor's top, not the terrain under
        #: it. None: a splat lies where it landed.
        self.ground = None

    # ---------------------------------------------------------- spawning
    def wound(self, pos, damage, max_health=30.0, away=None, crit=False, mass=1.0):
        """A blow lands at *pos* (the victim's feet): blood sprays, more the
        harder it hit relative to the victim, flung *away* (an (x, z)
        direction) from whoever struck it. *mass* is how much body it is
        (:func:`game.rpg.bestiary.body_mass`): a hen bleeds less than a man."""
        frac = max(0.05, min(3.0, float(damage) / max(1.0, float(max_health))))
        small = _small(mass)
        count = max(2, int((10 + 34 * min(1.0, frac) + (18 if crit else 0)) * small))
        speed = 90.0 + 150.0 * min(1.0, frac) + (80.0 if crit else 0.0)
        self._spray(pos, count, speed, away, size=(3.0, 8.0))
        # A splash where it was struck.
        self._splat(pos, (20.0 + 38.0 * min(1.0, frac)) * small, kind="splash")

    def kill(self, pos, max_health=30.0, mass=1.0):
        """A killing blow: a pool spreads under the body, as big as the body."""
        size = (66.0 + min(100.0, float(max_health) * 0.9)) * _small(mass)
        self._splat(pos, size, kind="pool")

    def gib(self, pos, damage=60.0, away=None, sprite=None, body=64.0, mass=1.0):
        """A body blown apart: chunks, a great spray and a wide spread of blood
        -- and, given the *sprite* it was drawn with (*body* world units
        across), that picture broken into pieces flung every way. All of it
        in proportion to *mass* (:func:`game.rpg.bestiary.body_mass`): a hen bursts into a
        few scraps, a person into a mess, a bear into a slaughterhouse."""
        m = max(0.1, min(3.0, float(mass)))
        k = math.sqrt(m)
        if sprite:
            self._pieces(pos, sprite, float(body or 64.0), away, keep=pieces_for(m))
        self._spray(pos, max(8, int(GIB_DROPS * m)), 320.0 * min(1.0, 0.6 + 0.4 * k), away,
                    size=(3.0 * min(1.0, k + 0.3), 9.0 * min(1.0, k + 0.3)))
        for _ in range(max(1, int(round(GIB_CHUNKS * m)))):
            self._spray(pos, 1, 260.0, away, size=(8.0 * min(1.4, k), 18.0 * min(1.4, k)),
                        kind="chunk")
        spread = 70.0 * min(1.6, k)
        for _ in range(max(1, int(round(GIB_POOLS * m)))):
            dx, dz = self.rng.uniform(-spread, spread), self.rng.uniform(-spread, spread)
            self._splat((pos[0] + dx, pos[1], pos[2] + dz),
                        self.rng.uniform(52, 104) * min(1.2, k), kind="pool")

    def _pieces(self, pos, sprite, body, away, keep=None, grid=GIB_GRID):
        """Break *sprite* into jagged pieces: a grid whose inner corners are
        jittered, so the pieces fit back together like a shattered picture;
        each flies out from where it was in the body, spinning."""
        n = max(1, int(grid))
        rng = self.rng
        corner = {}
        for i in range(n + 1):
            for j in range(n + 1):
                u, v = i / n, j / n
                if 0 < i < n:
                    u += rng.uniform(-0.3, 0.3) / n
                if 0 < j < n:
                    v += rng.uniform(-0.3, 0.3) / n
                corner[i, j] = (u, v)
        ax, az = away if away else (0.0, 0.0)
        alen = math.hypot(ax, az)
        now = self.clock()
        cells = [(i, j) for i in range(n) for j in range(n)]
        if keep is not None and keep < len(cells):
            # Only some of the body comes off whole; the rest is blood.
            cells = rng.sample(cells, max(1, int(keep)))
        with self._lock:
            for i, j in cells:
                quad = [corner[i, j], corner[i + 1, j], corner[i + 1, j + 1], corner[i, j + 1]]
                cu = sum(q[0] for q in quad) / 4.0
                cv = sum(q[1] for q in quad) / 4.0
                # Out from the body's middle (u across = x, v down = +z
                # on a top-down picture), harder the further out it was.
                ox, oz = (cu - 0.5), (cv - 0.5)
                olen = math.hypot(ox, oz) or 1.0
                spd = rng.uniform(140.0, 300.0)
                vx, vz = ox / olen * spd, oz / olen * spd
                if alen > 1e-6:
                    vx += ax / alen * 150.0
                    vz += az / alen * 150.0
                self.pieces.append({
                    "sprite": sprite, "quad": quad, "cu": cu, "cv": cv, "body": body,
                    "x": float(pos[0]) + ox * body, "z": float(pos[2]) + oz * body,
                    "y": float(pos[1]) + rng.uniform(20, 50), "gy": float(pos[1]),
                    "vx": vx, "vz": vz, "vy": rng.uniform(220, 420),
                    "spin": rng.uniform(-720.0, 720.0), "t0": now,
                    "rest": None, "seed": rng.random()})
            del self.pieces[:-64]

    # ---------------------------------------------------------- feeding
    def hold(self, pos, radius, seconds):
        """Keep the pieces within *radius* of *pos* lying where they are, not
        fading, for *seconds* (something is coming to eat them); the pieces."""
        now = self.clock()
        held = []
        with self._lock:
            for p in self.pieces:
                x, _y, z = (p["rest_pose"][:3] if p.get("rest") is not None
                            else self.position(p, now))
                if math.hypot(x - pos[0], z - pos[2]) <= radius:
                    p["held_until"] = max(p.get("held_until", 0.0), now + seconds)
                    held.append(p)
        return held

    def bite(self, p) -> bool:
        """Take a bite out of piece *p*: a chunk of its picture gone, from an
        edge already bitten or open. True once (almost) nothing is left --
        it is then gone."""
        rng = self.rng
        with self._lock:
            if p not in self.pieces:
                return True
            left = _remaining_points(p)
            if not left:
                self.pieces.remove(p)
                return True
            full = p.setdefault("_whole", len(left))
            # Nibble from the outside in: a point next to what is already
            # gone (or the outline), not from the middle.
            edge = [pt for pt in left if pt[2]] or left
            u, v, _edge = rng.choice(edge)
            p.setdefault("bites", []).append((u, v, rng.uniform(*BITE_RADIUS)))
            if len(_remaining_points(p)) <= EATEN_LEFT * full:
                self.pieces.remove(p)
                return True
            return False

    def piece_pose(self, p, now=None):
        """``(x, y, z, degrees, opacity)`` of a piece: in flight, tumbling;
        landed, still; fading at the end of its rest (held a while if
        something is feeding on it); None once gone."""
        now = self.clock() if now is None else now
        if p.get("rest") is not None:
            age = now - _rest_from(p)
            if age >= PIECE_REST:
                return None
            x, y, z, deg = p["rest_pose"]
            return x, y, z, deg, max(0.0, min(1.0, (PIECE_REST - age) / PIECE_FADE))
        t = now - p["t0"]
        x, y, z = self.position(p, now)
        return x, y, z, p["spin"] * t, 1.0

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
            kept = []
            for p in self.pieces:
                if p["rest"] is None:
                    t = now - p["t0"]
                    if self._height(p, t) <= p["gy"] and t > 0.05:
                        x, _y, z = self.position(p, now)
                        p["rest"] = now
                        p["rest_pose"] = (x, p["gy"], z, p["spin"] * t)
                        landed.append(dict(p, kind="chunk", size=p["body"] / GIB_GRID * 0.5))
                elif now - _rest_from(p) >= PIECE_REST:
                    continue
                kept.append(p)
            self.pieces = kept
            self.splats = [s for s in self.splats if now - s["t0"] < SPLAT_LIFE]
            self.screen = [s for s in self.screen if now - s["t0"] < SCREEN_BLOOD_SECONDS]
        for p in landed:
            if "rest_pose" in p:            # a piece: a smear where it lands
                x, _y, z, _deg = p["rest_pose"]
                self._splat((x, p["gy"], z), p["size"] * 2.4, kind="chunk")
                continue
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

    def floor_decals(self, now=None):
        """The blood lying on the ground that is not part of it yet, as
        ``(pos, rot, image, size, opacity)`` decals for the 3D pass to lay on
        the floor under the actors (game/ui/blood_gl.py)."""
        now = self.clock() if now is None else now
        out = []
        for s in self.snapshot()[1]:
            image = stamp_image(s["kind"], s.get("seed", 0.0))
            opacity = STAMP_OPACITY * self.splat_alpha(s, now)
            if image is None or opacity <= 0.0:
                continue
            out.append(((s["x"], self.floor_of(s), s["z"]), float(s.get("rot", 0.0)), image,
                        self.splat_size(s, now), opacity))
        return out

    def floor_of(self, s) -> float:
        """The height of the floor splat *s* lies on, found once and kept: a
        decal laid at the height a body's feet were given can be under a
        built floor, hidden by it."""
        floor = s.get("floor")
        if floor is None:
            found = None
            if self.ground is not None:
                try:
                    found = self.ground(s["x"], s["y"], s["z"])
                except Exception:
                    found = None
            floor = s["floor"] = float(s["y"] if found is None else found)
        return floor

    def snapshot(self):
        """``(particles, splats, screen)`` copies to draw from."""
        with self._lock:
            return list(self.particles), list(self.splats), list(self.screen)

    def pieces_snapshot(self):
        """The pieces of bodies blown apart, a copy to draw from."""
        with self._lock:
            return list(self.pieces)

    def clear(self):
        with self._lock:
            self.particles, self.splats, self.screen = [], [], []
            self.pieces = []
