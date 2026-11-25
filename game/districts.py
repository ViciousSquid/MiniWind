"""
The Vale's districts: large named regions, and the borders between them.

Designer content is ``game/data/districts.json`` (a mod can override it at
``game/data/mods/<name>/districts.json``). Each district has one or more
*seats* and a home *biome*. A point belongs to the district that scores
lowest by this measure, taking its nearest seat:

    distance from the warped point to the seat
    + biome_bias * (1 - how much the point is the district's biome)

The *warp* moves the point by a smooth noise first, so borders wander like
old parish lines instead of running straight; the *biome* term pulls each
district onto its own ground, so a desert district takes the desert and a
lowland one the green, and borders follow the biome edges where they meet
(:meth:`Districts.index_at`). Every point belongs to exactly one district;
seats of one district never have a border between them. Biomes are the
terrain's painted regions as the GPU sees them: ``desert``, ``snow`` or
``lowland`` (everything else -- grass, wheat, swamp, tundra).

The borders are **purely visual** and cost **nothing** in play: they are
baked once into the map's own terrain paint (``python -m
game.tools.bake_districts``) as hand-drawn ink -- a pen line that wobbles,
swells and thins, bleeds at its edges, now and then runs dry, with a lighter
second stroke wandering off it and back (:func:`ink`). The bake records
what each inked texel was (:class:`Drawing`, beside the map), so they can be
taken out exactly (borders switched off) or moved (a script redrawing the
map: lift the old drawing, bake a new one) -- the only times they cost
anything. They stop at water: no border where the ground lies
under a water brush's surface (the sea, a lake). The warp's noise hashes in
32-bit unsigned integers (so it can be reproduced exactly elsewhere).
:meth:`Districts.border_lines` traces the borders as lines, for the bake,
maps and tools (game/tools/district_map.py).

Pure Python + NumPy: no Qt, no GL, tested headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

DEFAULTS = {
    "map": None,
    "terrain_seed": None,
    "bounds": [-40960.0, -40960.0, 40960.0, 40960.0],
    "warp": 5000.0,
    "warp_scale": 15000.0,
    "seed": 1187,
    "biome_bias": 6000.0,
    # The world is a square disc and nobody goes near its rim: borders end
    # this far from the edge of the land, tapering out over the last 'taper'.
    "edge_margin": 6000.0,
    "edge_taper": 3000.0,
    "border": {"width": 30.0, "colour": [46, 30, 20], "alpha": 0.85,
               "cell": 160.0, "smoothing": 3},
    "districts": [],
}

#: Home biomes, as the shader numbers them.
BIOMES = ("lowland", "desert", "snow")
#: How many seats and districts a map may have, and water boxes it heeds.
MAX_SEATS = 24
MAX_DISTRICTS = 16
MAX_WATER = 64
#: The warp hash's multipliers.
HASH_X, HASH_Z, HASH_SEED, HASH_MIX = 374761393, 668265263, 2654435761, 1274126177
_U32 = 0xFFFFFFFF


@dataclass(frozen=True)
class District:
    id: str
    name: str
    seats: Tuple[Tuple[float, float], ...]
    biome: str = "lowland"
    note: str = ""

    @property
    def seat(self) -> Tuple[float, float]:
        """The first (chief) seat."""
        return self.seats[0]


# -- the warp's noise: 32-bit hashing, exactly as terrain.frag does it ---------
def seed_term(seed: int) -> int:
    """The seed's part of the hash (``uDistrictSeed``)."""
    return (int(seed) * HASH_SEED) & _U32


def _hash(ix, iz, salt: int):
    """0..1 for integer lattice points, from a 32-bit hash (vectorised)."""
    ux = (np.asarray(ix, np.int64) & _U32).astype(np.uint32)
    uz = (np.asarray(iz, np.int64) & _U32).astype(np.uint32)
    with np.errstate(over="ignore"):
        h = ux * np.uint32(HASH_X) + uz * np.uint32(HASH_Z) + np.uint32(salt & _U32)
        h = (h ^ (h >> np.uint32(13))) * np.uint32(HASH_MIX)
        h = h ^ (h >> np.uint32(16))
    return (h & np.uint32(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def _value_noise(x, z, salt: int):
    x = np.asarray(x, np.float64)
    z = np.asarray(z, np.float64)
    fx0, fz0 = np.floor(x), np.floor(z)
    fx, fz = x - fx0, z - fz0
    ux, uz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    ix, iz = fx0.astype(np.int64), fz0.astype(np.int64)
    a = _hash(ix, iz, salt)
    b = _hash(ix + 1, iz, salt)
    c = _hash(ix, iz + 1, salt)
    d = _hash(ix + 1, iz + 1, salt)
    return a + (b - a) * ux + (c - a) * uz + (a - b - c + d) * ux * uz


def _fbm(x, z, salt: int):
    """-1..1, three octaves; octave k hashes with ``salt + k * HASH_SEED``."""
    return ((_value_noise(x, z, salt) - 0.5) * 1.2
            + (_value_noise(x * 2.03 + 7.1, z * 2.03 + 3.3, salt + HASH_SEED) - 0.5) * 0.6
            + (_value_noise(x * 4.1 + 1.7, z * 4.1 + 9.2, salt + 2 * HASH_SEED) - 0.5) * 0.3
            ) / 1.05


def chaikin(points: Sequence[Tuple[float, float]], rounds: int = 3):
    """*points* with their corners cut *rounds* times; the ends stay put."""
    pts = [tuple(p) for p in points]
    for _ in range(max(0, int(rounds))):
        if len(pts) < 3:
            break
        out = [pts[0]]
        for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * z0 + 0.25 * z1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * z0 + 0.75 * z1))
        out.append(pts[-1])
        pts = [out[0]] + out[2:-2] + [out[-1]] if len(out) > 4 else out
    return pts


def water_boxes(brushes) -> List[Tuple[float, float, float, float, float]]:
    """``[(x0, z0, x1, z1, top)]`` of the water brushes among *brushes*,
    largest first."""
    from engine.constants import is_water_brush
    out = []
    for b in brushes or ():
        try:
            if not is_water_brush(b) or b.get("hidden"):
                continue
            (x, y, z), (sx, sy, sz) = b["pos"], b["size"]
            out.append((float(x) - sx / 2, float(z) - sz / 2, float(x) + sx / 2,
                        float(z) + sz / 2, float(y) + sy / 2))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))
    return out


class Districts:
    """The districts of one map's land (see the module notes).

    *biome_weights* is ``(xs, zs) -> (n, >= 2)`` desert and snow weights
    (``Terrain.biome_weights_batch``); without it there is no biome pull.
    *water* is :func:`water_boxes`; *height* ``(xs, zs) -> heights`` lets
    :meth:`border_lines` stop at the water too."""

    def __init__(self, content: Optional[dict] = None,
                 biome_weights: Optional[Callable] = None, water=(), height=None):
        cfg = dict(DEFAULTS)
        cfg.update(content or {})
        border = dict(DEFAULTS["border"])
        border.update((content or {}).get("border") or {})
        cfg["border"] = border
        self.config = cfg
        self.bounds = tuple(float(v) for v in cfg["bounds"])
        #: The map these districts divide (repository-relative), and its
        #: terrain's seed (None: any).
        self.map = cfg.get("map")
        self.terrain_seed = cfg.get("terrain_seed")
        self.warp = float(cfg["warp"])
        self.warp_scale = max(1.0, float(cfg["warp_scale"]))
        self.seed = int(cfg["seed"])
        self.biome_bias = max(0.0, float(cfg["biome_bias"]))
        self.edge_margin = max(0.0, float(cfg["edge_margin"]))
        self.edge_taper = max(1.0, float(cfg["edge_taper"]))
        self.border = border
        self.biome_weights = biome_weights
        self.water = list(water or ())[:MAX_WATER]
        self.height = height
        self.districts: List[District] = []
        for d in cfg["districts"]:
            seats = d.get("seats") or [d["seat"]]
            biome = str(d.get("biome", "lowland"))
            if biome not in BIOMES:
                raise ValueError(f"districts: {d.get('id')}: biome must be one of {BIOMES}")
            self.districts.append(District(
                str(d["id"]), str(d.get("name", d["id"])),
                tuple((float(s[0]), float(s[1])) for s in seats), biome,
                str(d.get("note", ""))))
        if not self.districts:
            raise ValueError("districts: no districts defined")
        seat_rows = [(s, i) for i, d in enumerate(self.districts) for s in d.seats]
        if len(seat_rows) > MAX_SEATS or len(self.districts) > MAX_DISTRICTS:
            raise ValueError(f"districts: at most {MAX_DISTRICTS} districts and {MAX_SEATS} seats")
        self._seats = np.array([s for s, _ in seat_rows], np.float64)
        self._seat_of = np.array([i for _, i in seat_rows], np.int32)
        self._biome_of = np.array([BIOMES.index(d.biome) for d in self.districts], np.int32)
        self._by_id = {d.id: d for d in self.districts}
        self._lines = None
        self._overlay = None

    # -- membership ------------------------------------------------------------
    def warped(self, x, z):
        """The points (x, z) as the district map measures them."""
        x = np.asarray(x, np.float64)
        z = np.asarray(z, np.float64)
        s = self.warp_scale
        salt = seed_term(self.seed)
        wx = _fbm(x / s, z / s, salt)
        wz = _fbm(x / s + 31.7, z / s - 17.3, salt + 11 * HASH_SEED)
        return x + self.warp * wx, z + self.warp * wz

    def _biome_match(self, x, z):
        """``(..., 3)``: how much each point is lowland, desert, snow. With
        no biome map every point is every biome: no district is pulled."""
        shape = np.shape(x)
        if self.biome_weights is None:
            return np.ones(shape + (3,), np.float64)
        w = np.asarray(self.biome_weights(np.ravel(x), np.ravel(z)), np.float64)
        desert, snow = w[:, 0], w[:, 1]
        lowland = np.clip(1.0 - desert - snow, 0.0, 1.0)
        return np.stack([lowland, desert, snow], axis=-1).reshape(shape + (3,))

    def scores(self, x, z):
        """``(..., districts)``: each district's measure at each point (the
        lowest wins)."""
        x = np.asarray(x, np.float64)
        z = np.asarray(z, np.float64)
        wx, wz = self.warped(x, z)
        dx = wx[..., None] - self._seats[:, 0]
        dz = wz[..., None] - self._seats[:, 1]
        seat_d = np.sqrt(dx * dx + dz * dz)
        per = np.full(x.shape + (len(self.districts),), np.inf)
        for k, i in enumerate(self._seat_of):
            per[..., i] = np.minimum(per[..., i], seat_d[..., k])
        match = self._biome_match(x, z)
        per += self.biome_bias * (1.0 - match[..., self._biome_of])
        return per

    def index_at(self, x, z):
        """The index of the district each point lies in (vectorised)."""
        return np.argmin(self.scores(x, z), axis=-1)

    def at(self, x: float, z: float) -> District:
        """The district the point (x, z) lies in."""
        return self.districts[int(self.index_at(np.float64(x), np.float64(z)))]

    def get(self, district_id: str) -> Optional[District]:
        return self._by_id.get(district_id)

    def fits(self, terrain_data) -> bool:
        """Whether these districts belong to the map whose terrain is
        *terrain_data* (its seed; districts with no seed fit any terrain)."""
        if self.terrain_seed is None:
            return True
        try:
            return int((terrain_data or {}).get("seed")) == int(self.terrain_seed)
        except (TypeError, ValueError):
            return False

    def edge_distance(self, x, z):
        """How far (x, z) lies inside the edge of the land (vectorised)."""
        x0, z0, x1, z1 = self.bounds
        x, z = np.asarray(x, np.float64), np.asarray(z, np.float64)
        return np.minimum(np.minimum(x - x0, x1 - x), np.minimum(z - z0, z1 - z))

    def edge_fade(self, x, z):
        """0 within :attr:`edge_margin` of the land's edge, rising to 1 over
        :attr:`edge_taper`: how much of a border is drawn there."""
        t = (self.edge_distance(x, z) - self.edge_margin) / self.edge_taper
        t = np.clip(t, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    def under_water(self, x, z, y):
        """Whether ground at height *y* at (x, z) lies under a water brush's
        surface (vectorised)."""
        x, z, y = (np.asarray(v, np.float64) for v in (x, z, y))
        wet = np.zeros(np.broadcast(x, z, y).shape, bool)
        for x0, z0, x1, z1, top in self.water:
            wet |= (x >= x0) & (x <= x1) & (z >= z0) & (z <= z1) & (y < top)
        return wet

    # -- borders as lines (maps and tools) -------------------------------------
    def grid(self, cell: Optional[float] = None):
        """``(ids, x0, z0, cell)``: the district index of every cell of the
        land, row by row (z), at cell centres."""
        cell = float(cell or self.border["cell"])
        x0, z0, x1, z1 = self.bounds
        nx = max(2, int(math.ceil((x1 - x0) / cell)))
        nz = max(2, int(math.ceil((z1 - z0) / cell)))
        xs = x0 + (np.arange(nx) + 0.5) * cell
        zs = z0 + (np.arange(nz) + 0.5) * cell
        gx, gz = np.meshgrid(xs, zs)
        return self.index_at(gx, gz).astype(np.int32), x0, z0, cell

    def border_lines(self) -> List[List[Tuple[float, float]]]:
        """Every border as a smoothed line of (x, z) points, broken where it
        would cross water (cached)."""
        if self._lines is None:
            self._lines = self._inland(self._dry(self._trace()))
        return self._lines

    def _inland(self, lines):
        """The lines with every point the edge fade blanks taken out (nobody
        goes near the rim of the world)."""
        out = []
        for line in lines:
            pts = np.asarray(line, np.float64)
            keep = self.edge_fade(pts[:, 0], pts[:, 1]) > 0.0
            run = []
            for p, k in zip(line, keep):
                if k:
                    run.append(p)
                elif run:
                    if len(run) > 1:
                        out.append(run)
                    run = []
            if len(run) > 1:
                out.append(run)
        return out

    def cache_key(self, terrain) -> str:
        """What the drawn borders depend on: districts, warp, biomes, water,
        the terrain's paint grid and the ink's own version."""
        import hashlib
        import json as _json
        h = hashlib.sha1()
        h.update(_json.dumps(self.config, sort_keys=True, default=str).encode())
        h.update(repr((INK_VERSION, self.water, terrain.TERRAIN_PAINT_RESOLUTION,
                       terrain.chunk_size, terrain.offset_x, terrain.offset_z)).encode())
        biome = getattr(terrain, "biome_map", None)
        if biome is not None:
            h.update(np.ascontiguousarray(biome).data)
        return h.hexdigest()[:20]

    def alphas(self, terrain):
        """``{chunk: (res, res) uint8}``: how much ink the hand-drawn
        borders put on each texel of each chunk they cross (:func:`ink`).
        Touches no paint."""
        return self._draw(terrain)

    def bake(self, terrain, alphas=None):
        """Draw the borders into *terrain*'s paint, by hand (:func:`ink`).
        Returns the :class:`Drawing` that can take them out again."""
        drawing = Drawing(self.alphas(terrain) if alphas is None else alphas,
                          self.border["colour"], self.cache_key(terrain))
        drawing.lay(terrain)
        return drawing

    def _draw(self, terrain):
        res = int(terrain.TERRAIN_PAINT_RESOLUTION)
        size = float(terrain.chunk_size)
        cell = size / res
        ox, oz = float(terrain.offset_x), float(terrain.offset_z)
        width = float(self.border["width"])
        reach = REACH * width / 30.0
        opacity = float(self.border["alpha"])
        # The nearest border at each texel near one: signed distance, by chunk.
        near: Dict[Tuple[int, int], np.ndarray] = {}
        for line in self.border_lines():
            pts = np.asarray(line, np.float64)
            for (ax, az), (bx, bz) in zip(pts[:-1], pts[1:]):
                ex, ez = bx - ax, bz - az
                length2 = ex * ex + ez * ez
                if length2 < 1e-9:
                    continue
                lo_x, hi_x = min(ax, bx) - reach, max(ax, bx) + reach
                lo_z, hi_z = min(az, bz) - reach, max(az, bz) + reach
                for cx in range(int(math.floor((lo_x - ox) / size)), int(math.floor((hi_x - ox) / size)) + 1):
                    for cz in range(int(math.floor((lo_z - oz) / size)), int(math.floor((hi_z - oz) / size)) + 1):
                        x0c, z0c = ox + cx * size, oz + cz * size
                        i0 = max(0, int((lo_x - x0c) / cell))
                        i1 = min(res, int(math.ceil((hi_x - x0c) / cell)))
                        j0 = max(0, int((lo_z - z0c) / cell))
                        j1 = min(res, int(math.ceil((hi_z - z0c) / cell)))
                        if i1 <= i0 or j1 <= j0:
                            continue
                        px = (x0c + (np.arange(i0, i1) + 0.5) * cell)[:, None]
                        pz = (z0c + (np.arange(j0, j1) + 0.5) * cell)[None, :]
                        t = np.clip(((px - ax) * ex + (pz - az) * ez) / length2, 0.0, 1.0)
                        dx, dz = px - (ax + t * ex), pz - (az + t * ez)
                        dist = np.sqrt(dx * dx + dz * dz)
                        side = np.where(ex * (pz - az) - ez * (px - ax) >= 0.0, 1.0, -1.0)
                        block = near.get((cx, cz))
                        if block is None:
                            block = near[(cx, cz)] = np.full((res, res), np.inf, np.float32)
                        view = block[i0:i1, j0:j1]
                        closer = dist < np.abs(view)
                        view[closer] = (dist * side)[closer]
        out = {}
        for (cx, cz), signed in near.items():
            hit = np.isfinite(signed) & (np.abs(signed) < reach)
            if not hit.any():
                continue
            ii, jj = np.nonzero(hit)
            xs = ox + cx * size + (ii + 0.5) * cell
            zs = oz + cz * size + (jj + 0.5) * cell
            amount = ink(xs, zs, signed[hit], width) * opacity * self.edge_fade(xs, zs)
            if self.water and self.height is not None:
                # Heights only where a water box lies: most texels need none.
                boxed = np.zeros(len(xs), bool)
                for x0, z0, x1, z1, _top in self.water:
                    boxed |= (xs >= x0) & (xs <= x1) & (zs >= z0) & (zs <= z1)
                if boxed.any():
                    heights = np.asarray(self.height(xs[boxed], zs[boxed]), np.float64)
                    wet = self.under_water(xs[boxed], zs[boxed], heights)
                    sub = amount[boxed]
                    sub[wet] = 0.0
                    amount[boxed] = sub
            if not (amount > 0.004).any():
                continue
            alpha = np.zeros((res, res), np.uint8)
            alpha[ii, jj] = np.clip(amount * 255.0 + 0.5, 0, 255).astype(np.uint8)
            out[(cx, cz)] = alpha
        return out

    def _dry(self, lines):
        if not self.water or self.height is None:
            return lines
        out = []
        for line in lines:
            pts = np.asarray(line, np.float64)
            wet = self.under_water(pts[:, 0], pts[:, 1],
                                   np.asarray(self.height(pts[:, 0], pts[:, 1]), np.float64))
            run = []
            for p, w in zip(line, wet):
                if not w:
                    run.append(p)
                elif run:
                    if len(run) > 1:
                        out.append(run)
                    run = []
            if len(run) > 1:
                out.append(run)
        return out

    def _trace(self):
        ids, x0, z0, cell = self.grid()
        edges = []
        rows, cols = np.nonzero(ids[:, 1:] != ids[:, :-1])
        for i, j in zip(rows.tolist(), cols.tolist()):
            edges.append(((j + 1, i), (j + 1, i + 1)))
        rows, cols = np.nonzero(ids[1:, :] != ids[:-1, :])
        for i, j in zip(rows.tolist(), cols.tolist()):
            edges.append(((j, i + 1), (j + 1, i + 1)))
        links: Dict[Tuple[int, int], List[int]] = {}
        for k, (a, b) in enumerate(edges):
            links.setdefault(a, []).append(k)
            links.setdefault(b, []).append(k)
        used = [False] * len(edges)

        def walk(start, k):
            path = [start]
            here = start
            while True:
                used[k] = True
                a, b = edges[k]
                here = b if a == here else a
                path.append(here)
                nxt = [e for e in links[here] if not used[e]]
                if len(links[here]) != 2 or not nxt:
                    return path
                k = nxt[0]

        lines = []
        for corner, ks in links.items():
            if len(ks) == 2:
                continue
            for k in ks:
                if not used[k]:
                    lines.append(walk(corner, k))
        for k in range(len(edges)):
            if not used[k]:
                lines.append(walk(edges[k][0], k))
        rounds = int(self.border["smoothing"])
        out = []
        for path in lines:
            pts = [(x0 + cx * cell, z0 + cz * cell) for cx, cz in path]
            if len(pts) > 4:
                pts = pts[:1] + pts[1:-1:2] + pts[-1:]
            out.append(chaikin(pts, rounds))
        return out


# -- drawn by hand ---------------------------------------------------------------
#: How far either side of a border line the pen's strokes can wander (world
#: units, at the default width): the band :meth:`Districts.bake` paints in.
REACH = 210.0
_INK_SALT = 0x5EED1E55
#: Bump when :func:`ink` changes, so cached drawings are redrawn.
INK_VERSION = 1


def _n(x, z, scale, k):
    """Smooth 0..1 noise at (x, z) over *scale* world units (stream *k*)."""
    return _value_noise(np.asarray(x) / scale + k * 17.31, np.asarray(z) / scale - k * 9.73,
                        (_INK_SALT + k * HASH_SEED) & _U32)


def stroke_path(x, z, width=30.0):
    """``(tremor, half, pressure)`` of the pen's main stroke at (x, z): the
    stroke runs where ``d + tremor == 0`` (*d* signed across the true border,
    as :func:`ink` takes it) and is ``half`` either side of that at its
    fullest. What the border glow follows, so it hugs the drawn line."""
    x, z = np.asarray(x, np.float64), np.asarray(z, np.float64)
    w = float(width)
    tremor = (_n(x, z, 450.0, 1) - 0.5) * 8.0 * w + (_n(x, z, 110.0, 2) - 0.5) * 1.5 * w
    pressure = _n(x, z, 620.0, 3)
    half = 0.5 * w * (0.3 + 1.25 * pressure)
    return tremor, half, pressure


def ink(x, z, d, width=30.0):
    """How much ink (0..1) a pen line drawn by hand puts at (x, z), *d*
    world units (signed, across the line) from the true border.

    The line wobbles with the hand (a slow tremor and a quicker one), swells
    and thins with the pen's pressure -- darker where it presses -- bleeds
    unevenly at its edges, and here and there runs dry; a lighter second
    stroke wanders off it and back. Vectorised; texels of 8 units resolve it.
    """
    x, z, d = (np.asarray(v, np.float64) for v in (x, z, d))
    w = float(width)
    tremor, half, pressure = stroke_path(x, z, w)
    bleed = (_n(x, z, 28.0, 4) - 0.5) * 0.45 * w
    soft = 5.0                                   # a texel-wide soft edge

    def stroke(offset, scale):
        edge = half * scale + bleed
        return np.clip((edge - np.abs(d + offset)) / soft + 0.5, 0.0, 1.0)

    first = stroke(tremor, 1.0)
    drift = (_n(x, z, 900.0, 5) - 0.5) * 7.0 * w
    second = stroke(tremor * 1.4 + drift, 0.4)
    dry = np.clip((_n(x, z, 950.0, 6) - 0.16) / 0.14, 0.0, 1.0)
    return np.maximum(first, 0.55 * second) * (0.72 + 0.28 * pressure) * (0.2 + 0.8 * dry)


class Drawing:
    """Borders drawn into a terrain's paint, and what they covered.

    *alphas* is ``{chunk: (res, res) uint8}`` (:meth:`Districts.alphas`).
    :meth:`lay` paints them and records each covered texel's colour as it
    was; :meth:`lift` puts those texels back exactly, :meth:`lay` again
    redraws them exactly. The record is saved beside the map
    (:func:`record_path`), so a map baked once keeps its borders in its own
    paint -- nothing to do in play -- and can still lose them (borders
    switched off) or have them moved (a script redrawing the map)."""

    def __init__(self, alphas, colour, key=""):
        self.alphas = {tuple(int(v) for v in k): np.asarray(a, np.uint8) for k, a in alphas.items()}
        self.colour = tuple(float(c) for c in colour)
        self.key = str(key)
        #: chunk -> (flat texel index, rgba before the ink): set by lay().
        self.under = {}
        #: chunk -> (its array without the ink, its array with it), while
        #: neither has been replaced: lay and lift then just swap them.
        self._arrays = {}
        #: Whether the ink is in the paint now.
        self.laid = False

    #: How many inked texels :meth:`is_laid` looks at, from how many chunks.
    PROBES = 24
    PROBE_CHUNKS = 3

    def is_laid(self, terrain) -> bool:
        """Whether the ink is in *terrain*'s paint now: a few strongly inked
        texels are compared with what they were before the ink. So laying
        or lifting twice -- or after an undo brought the ink back -- never
        inks a texel twice or loses one."""
        if not self.under:
            return False
        differ = same = 0
        for coord in sorted(self.under)[:: max(1, len(self.under) // self.PROBE_CHUNKS)][:self.PROBE_CHUNKS]:
            index, before = self.under[coord]
            strength = self.alphas[coord].reshape(-1)[index]
            pick = np.argsort(strength)[::-1][: max(1, self.PROBES // self.PROBE_CHUNKS)]
            paint = terrain.texture_paint_maps.get(coord)
            now = (np.zeros((len(pick), 4), np.uint8) if paint is None
                   else paint.reshape(-1, 4)[index[pick]])
            hit = np.any(now != before[pick], axis=1)
            differ += int(hit.sum())
            same += int((~hit).sum())
        return differ > same

    def lay(self, terrain):
        """Paint the ink (if it is not in already), recording what each inked
        texel was. A chunk laid and lifted before, and untouched since, gets
        back the very array it had -- so the paint serialiser's cache holds."""
        res = int(terrain.TERRAIN_PAINT_RESOLUTION)
        if self.is_laid(terrain):
            self.laid = True
            return
        maps = terrain.texture_paint_maps
        for coord, alpha in self.alphas.items():
            if alpha.shape != (res, res):
                raise ValueError(f"drawn for {alpha.shape[0]}-texel paint, terrain has {res}")
            current = maps.get(coord)
            cached = self._arrays.get(coord)
            if cached is not None and cached[0] is current and current is not None:
                terrain.restore_paint(coord, cached[1])
                continue
            index = np.flatnonzero(alpha.reshape(-1))
            if not len(index):
                continue
            before = (np.zeros((len(index), 4), np.uint8) if current is None
                      else current.reshape(-1, 4)[index].copy())
            self.under[coord] = (index, before)
            terrain.blend_paint(coord, 0, 0, alpha.astype(np.float32) / 255.0, self.colour)
            if current is not None:
                self._arrays[coord] = (current, maps.get(coord))
        self.laid = True

    def lift(self, terrain):
        """Put back every texel the ink covered, exactly as it was (if the
        ink is in at all)."""
        if not self.is_laid(terrain):
            self.laid = False
            return
        maps = terrain.texture_paint_maps
        for coord, (index, before) in self.under.items():
            current = maps.get(coord)
            cached = self._arrays.get(coord)
            if cached is not None and cached[1] is current and current is not None:
                terrain.restore_paint(coord, cached[0])
                continue
            terrain.set_paint_texels(coord, index, before)
            lifted = maps.get(coord)
            if current is not None and lifted is not None:
                self._arrays[coord] = (lifted, current)
        self.laid = False

    # -- kept beside the map -----------------------------------------------------
    def save(self, path):
        coords = sorted(self.under)
        arrays = {"key": np.array(self.key), "colour": np.array(self.colour, np.float32),
                  "coords": np.array(coords, np.int32).reshape(-1, 2)}
        for i, coord in enumerate(coords):
            index, before = self.under[coord]
            arrays[f"i{i}"] = index.astype(np.int32)
            arrays[f"u{i}"] = before
            arrays[f"a{i}"] = self.alphas[coord].reshape(-1)[index]
        import os
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as fh:
            np.savez_compressed(fh, **arrays)

    @classmethod
    def load(cls, path, res):
        """The drawing saved at *path* (laid: the map's paint has its ink),
        for paint of *res* texels a side; None if there is none."""
        try:
            with np.load(path) as data:
                coords = [tuple(int(v) for v in c) for c in data["coords"]]
                drawing = cls({}, tuple(float(c) for c in data["colour"]), str(data["key"]))
                for i, coord in enumerate(coords):
                    index = data[f"i{i}"].astype(np.int64)
                    alpha = np.zeros(res * res, np.uint8)
                    alpha[index] = data[f"a{i}"]
                    drawing.alphas[coord] = alpha.reshape(res, res)
                    drawing.under[coord] = (index, data[f"u{i}"])
        except (OSError, KeyError, ValueError):
            return None
        drawing.laid = True
        return drawing


def record_path(map_path: str) -> str:
    """Where a map's drawn borders are recorded: ``<map>.districts.npz``
    (a relative *map_path* is the repository's)."""
    import os
    if not os.path.isabs(map_path):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        map_path = os.path.join(root, map_path)
    base, _ext = os.path.splitext(os.path.abspath(map_path))
    return base + ".districts.npz"


def load(name: str = "districts", biome_weights: Optional[Callable] = None,
         water=(), height=None) -> Districts:
    """The game's districts, from ``game/data/districts.json`` and mods."""
    from . import data
    return Districts(data.load(name, replace_lists=True), biome_weights, water, height)
