"""
The border glow: a faint wash of colour inside each district along its
border, fading in only as the player is about to cross (after the "city
limits" of a certain strategy game).

Green on the side the player stands in, Fio orange on the side ahead; they
swap the moment the player crosses. Each side has a crisp edge right against
the hand-drawn ink (it follows the pen's wobble: :func:`game.districts
.stroke_path`) over a soft fill that fades out :data:`FILL` units inward.

It costs nothing away from a border: :meth:`Glow.update` only measures the
distance to the nearest border (a few grid cells of segments, a few times a
second) until the player comes within :data:`RANGE`; then a small strip of
ground along the border near the player is built (rebuilt as they move) and
drawn under the actors (:mod:`game.ui.district_glow_gl`). Settings ›
Game › *Border glow* (``[GAME] border_glow`` in settings.ini) turns it off.

Pure Python + NumPy: no Qt, no GL, tested headless.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

#: The glow starts to show this far from a border, and is full this near.
RANGE = 900.0
FULL = 250.0
#: How far inward the fill reaches from the ink's edge (world units).
FILL = 700.0
#: How much border either way of the player is built.
ALONG = 2200.0
#: Rows of the fill beyond the ink's edge, and how strong each is.
FILL_ROWS = (0.0, 20.0, 60.0, 130.0, 240.0, 400.0, 560.0, FILL)
#: The edge: a crisp band right against the ink.
EDGE_ROWS = (0.0, 4.0, 13.0, 18.0)
EDGE_ALPHA = (0.0, 0.85, 0.85, 0.0)
FILL_STRENGTH = 0.36
#: Fio green (the player's district) and Fio orange (the one ahead), 0..1.
HERE = (120 / 255.0, 200 / 255.0, 80 / 255.0)
AHEAD = (240 / 255.0, 128 / 255.0, 0.0)
#: Rebuild the strip when the player has moved this far, or this often.
REBUILD_DISTANCE = 220.0
REFRESH_SECONDS = 1.5
#: How often the distance to the border is measured (seconds).
CHECK_SECONDS = 0.2
#: Lift above the ground (world units).
LIFT = 6.0
_CELL = 2048.0


def fade(distance: float) -> float:
    """How much of the glow shows *distance* from the nearest border."""
    t = min(1.0, max(0.0, (RANGE - float(distance)) / (RANGE - FULL)))
    return t * t * (3.0 - 2.0 * t)


class Glow:
    """The glow along a map's borders; see the module notes.

    *districts* is a :class:`game.districts.Districts` (its border lines);
    *height* ``(xs, zs) -> heights`` lays the strip on the ground."""

    def __init__(self, districts, height):
        self.districts = districts
        self.height = height
        self.width = float(districts.border["width"])
        self.lines = [np.asarray(line, np.float64) for line in districts.border_lines()
                      if len(line) > 1]
        # Which district lies on each side of each line (left, right): its
        # middle, a little either side.
        self.sides: List[Tuple[int, int]] = []
        for pts in self.lines:
            k = len(pts) // 2
            a, b = pts[max(0, k - 1)], pts[min(len(pts) - 1, k + 1)]
            t = b - a
            n = np.array((-t[1], t[0])) / max(float(np.hypot(*t)), 1e-9)
            mid = pts[k]
            left = int(districts.index_at(*(mid + n * 160.0)))
            right = int(districts.index_at(*(mid - n * 160.0)))
            self.sides.append((left, right))
        # A grid of segments, for the nearest-border check.
        self.grid: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for li, pts in enumerate(self.lines):
            for si in range(len(pts) - 1):
                (ax, az), (bx, bz) = pts[si], pts[si + 1]
                for cx in range(int(math.floor(min(ax, bx) / _CELL)), int(math.floor(max(ax, bx) / _CELL)) + 1):
                    for cz in range(int(math.floor(min(az, bz) / _CELL)), int(math.floor(max(az, bz) / _CELL)) + 1):
                        self.grid.setdefault((cx, cz), []).append((li, si))
        self.show = 0.0
        self.fill = None          # (n, 7) float32: x, y, z, r, g, b, a
        self.edge = None
        #: Bumped on every rebuild, so a renderer re-uploads only then.
        self.version = 0
        self._checked = None
        self._built = None
        self._built_at = None
        self._here = None
        self._distance = math.inf

    # -- where the borders are -------------------------------------------------
    def nearest(self, x: float, z: float, reach: float = RANGE) -> float:
        """Distance from (x, z) to the nearest border within *reach* (inf
        when none is that near)."""
        r = int(math.ceil(reach / _CELL))
        cx0, cz0 = int(math.floor(x / _CELL)), int(math.floor(z / _CELL))
        best = math.inf
        for cx in range(cx0 - r, cx0 + r + 1):
            for cz in range(cz0 - r, cz0 + r + 1):
                for li, si in self.grid.get((cx, cz), ()):
                    (ax, az), (bx, bz) = self.lines[li][si], self.lines[li][si + 1]
                    ex, ez = bx - ax, bz - az
                    length2 = ex * ex + ez * ez
                    t = 0.0 if length2 < 1e-9 else max(0.0, min(1.0, ((x - ax) * ex + (z - az) * ez) / length2))
                    best = min(best, math.hypot(x - (ax + t * ex), z - (az + t * ez)))
        return best

    # -- per frame ---------------------------------------------------------------
    def update(self, x: float, z: float, now: float) -> float:
        """The glow for a player at (x, z) at time *now* (seconds); returns
        how much of it shows (0: nothing to draw, and nothing was built)."""
        if self._checked is None or now - self._checked[2] >= CHECK_SECONDS or \
                math.hypot(x - self._checked[0], z - self._checked[1]) > 60.0:
            self._distance = self.nearest(x, z)
            self._checked = (x, z, now)
        self.show = fade(self._distance)
        if self.show <= 0.0:
            if self.fill is not None:
                self.fill = self.edge = None
                self._built = None
            return 0.0
        here = int(self.districts.index_at(np.float64(x), np.float64(z)))
        if (self._built is None or here != self._here
                or math.hypot(x - self._built[0], z - self._built[1]) > REBUILD_DISTANCE
                or now - self._built_at > REFRESH_SECONDS):
            self._build(x, z, here)
            self._built, self._built_at, self._here = (x, z), now, here
        return self.show

    def _build(self, x, z, here):
        fills, edges = [], []
        r2 = (ALONG + FILL) ** 2
        for li, pts in enumerate(self.lines):
            near = ((pts[:, 0] - x) ** 2 + (pts[:, 1] - z) ** 2) <= r2
            if not near.any():
                continue
            # Each run of consecutive points near the player.
            idx = np.flatnonzero(near)
            breaks = np.flatnonzero(np.diff(idx) > 1)
            for run in np.split(idx, breaks + 1):
                if len(run) < 2:
                    continue
                seg = pts[run]
                for side, sign in ((0, 1.0), (1, -1.0)):
                    district = self.sides[li][side]
                    colour = HERE if district == here else AHEAD
                    fills.append(self._strip(seg, sign, FILL_ROWS,
                                             [FILL_STRENGTH * (1.0 - r / FILL) ** 1.3 for r in FILL_ROWS],
                                             colour))
                    edges.append(self._strip(seg, sign, EDGE_ROWS, EDGE_ALPHA, colour))
        self.fill = np.concatenate(fills).astype(np.float32) if fills else None
        self.edge = np.concatenate(edges).astype(np.float32) if edges else None
        self.version += 1

    def _strip(self, pts, sign, rows, alphas, colour):
        """Triangles for one side of a run of border points: *rows* beyond the
        ink's edge, each of alpha *alphas*, in *colour*."""
        ahead = np.vstack([pts[1:], pts[-1:]])
        behind = np.vstack([pts[:1], pts[:-1]])
        t = ahead - behind
        length = np.hypot(t[:, 0], t[:, 1])
        length[length < 1e-9] = 1.0
        n = np.stack([-t[:, 1] / length, t[:, 0] / length], axis=1)   # +d: left
        from .districts import stroke_path
        tremor, half, _pressure = stroke_path(pts[:, 0], pts[:, 1], self.width)
        edge = -tremor + sign * half                  # where the drawn ink ends
        grid = []
        for r, a in zip(rows, alphas):
            d = edge + sign * r
            xz = pts + n * d[:, None]
            grid.append((xz, float(a)))
        xs = np.concatenate([g[0][:, 0] for g in grid])
        zs = np.concatenate([g[0][:, 1] for g in grid])
        ys = np.asarray(self.height(xs, zs), np.float64) + LIFT
        alpha = np.concatenate([np.full(len(pts), g[1]) for g in grid])
        alpha *= np.tile(self.districts.edge_fade(pts[:, 0], pts[:, 1]), len(rows))
        if self.districts.water:
            alpha[self.districts.under_water(xs, zs, ys - LIFT)] = 0.0
        m = len(pts)
        verts = np.stack([xs, ys, zs, np.full(len(xs), colour[0]), np.full(len(xs), colour[1]),
                          np.full(len(xs), colour[2]), alpha], axis=1).reshape(len(rows), m, 7)
        a, b = verts[:-1, :-1], verts[1:, :-1]
        c, d = verts[:-1, 1:], verts[1:, 1:]
        return np.stack([a, b, c, c, b, d], axis=2).reshape(-1, 7)
