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

The borders are **purely visual**: the terrain shader draws them from the
same seats, warp and biome map every frame (:meth:`Districts.overlay`, the
renderer's ``district_overlay``). Nothing is baked into the world or saved;
they cost a few dozen shader operations per ground pixel, and none at all
when off. They stop at water: no border where the ground lies under a water
brush's surface (the sea, a lake). The warp's noise hashes in 32-bit
unsigned integers, so this module and the shader agree exactly.
:meth:`Districts.border_lines` traces the same borders as lines, for maps
and tools (game/tools/district_map.py).

Pure Python + NumPy: no Qt, no GL, tested headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

DEFAULTS = {
    "terrain_seed": None,
    "bounds": [-40960.0, -40960.0, 40960.0, 40960.0],
    "warp": 5000.0,
    "warp_scale": 15000.0,
    "seed": 1187,
    "biome_bias": 6000.0,
    "border": {"width": 30.0, "colour": [24, 22, 28], "alpha": 0.7,
               "cell": 160.0, "smoothing": 3},
    "districts": [],
}

#: Home biomes, as the shader numbers them.
BIOMES = ("lowland", "desert", "snow")
#: How many seats, districts and water boxes the shader holds.
MAX_SEATS = 24
MAX_DISTRICTS = 16
MAX_WATER = 16
#: The hash's multipliers (shared with terrain.frag).
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
        #: The seed of the terrain these districts divide (None: any).
        self.terrain_seed = cfg.get("terrain_seed")
        self.warp = float(cfg["warp"])
        self.warp_scale = max(1.0, float(cfg["warp_scale"]))
        self.seed = int(cfg["seed"])
        self.biome_bias = max(0.0, float(cfg["biome_bias"]))
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

    def under_water(self, x, z, y):
        """Whether ground at height *y* at (x, z) lies under a water brush's
        surface (vectorised)."""
        x, z, y = (np.asarray(v, np.float64) for v in (x, z, y))
        wet = np.zeros(np.broadcast(x, z, y).shape, bool)
        for x0, z0, x1, z1, top in self.water:
            wet |= (x >= x0) & (x <= x1) & (z >= z0) & (z <= z1) & (y < top)
        return wet

    # -- the shader's copy -------------------------------------------------------
    def overlay(self) -> Dict:
        """What the terrain shader needs to draw the borders (cached; the
        renderer's ``district_overlay``)."""
        if self._overlay is None:
            b = self.border
            r, g, bl = (float(c) / 255.0 for c in b["colour"])
            water = np.zeros((MAX_WATER, 4), np.float32)
            tops = np.full(MAX_WATER, -1e9, np.float32)
            for i, (x0, z0, x1, z1, top) in enumerate(self.water):
                water[i] = (x0, z0, x1, z1)
                tops[i] = top
            self._overlay = {
                "seats": np.ascontiguousarray(self._seats, np.float32),
                "seat_of": np.ascontiguousarray(self._seat_of, np.int32),
                "biome": np.ascontiguousarray(self._biome_of, np.int32),
                "warp": (self.warp, 1.0 / self.warp_scale, self.biome_bias, float(b["width"])),
                "seed": seed_term(self.seed),
                "line": (r, g, bl, float(b["alpha"])),
                "water": water, "water_top": tops, "water_count": len(self.water),
            }
        return self._overlay

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
            self._lines = self._dry(self._trace())
        return self._lines

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


def load(name: str = "districts", biome_weights: Optional[Callable] = None,
         water=(), height=None) -> Districts:
    """The game's districts, from ``game/data/districts.json`` and mods."""
    from . import data
    return Districts(data.load(name, replace_lists=True), biome_weights, water, height)
