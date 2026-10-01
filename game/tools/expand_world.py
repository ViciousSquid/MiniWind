"""
Expand the Vale of MiniWind into a huge, spread-out world.

Takes the hand-built village map (``maps/village_walled_source.json``) and:

* **Grows the terrain** from 11 x 11 chunks (about 22 km square in world
  units) to ``--chunks`` per side (default 40: about 82 000 units square).
  Millbrook stays at the origin, untouched.
* **Spreads the sites out.** Every place outside the village moves *rigidly*
  (buildings, props, people, creatures, lights, the ground they stand on)
  further from Millbrook: a site ``r`` units out ends up
  ``R0 + SPREAD * (r - R0)`` units out, so nothing near the village moves and
  the far sites move furthest. Sites that belong together (the lake and its
  shores, a town and its fields) move as one.
* **Carries the ground with each site.** The terrain under a moved site is
  re-sculpted at its new place to the exact heights it had before, feathered
  into the new surroundings, so nothing is buried or left floating. Sculpting
  that belonged to no site (old roads between places that are now far apart)
  is dropped.
* **Raises mountains** in the empty land with a heightmap overlay: a
  mountain wall around the world's edge and the Emberpeaks, a massif far to
  the north-east. The mountains are kept clear of every site.
* **Builds the Emberpeak Shrine** high in the Emberpeaks, reached by a pass
  marked with cairns: the old altar from the Ashen Circle with the Ember Tome
  (the firebolt spellbook) on it, wolves on the way up. The book is
  the ``ember_tome`` quest item of Thalen's quest "The Ember Tome"
  (``game/rpg/quests_content.py``); the quest arrow points at the book.
* Removes the invisible floor slabs the 2.4 map stood on: 2.5 terrain is
  solid, and the slabs would have stopped the moved sites carrying their own
  ground. The ground is raised under the flat road, floor and hearth brushes
  that were laid on the slabs, so they rest on it.
* Makes every water body one water brush over a sculpted depression: the
  2.4 lake's 27 stacked strips become a single brush, its waterline set just
  below the real shore, the bed kept below it and the bank above it wherever
  the brush reaches. The new ponds are built the same way.

The map records that it has been expanded, so the tool refuses to run on its
own output (``--force`` overrides).

Run from the repo root::

    python -m game.tools.expand_world
    python -m game.tools.expand_world --preview preview.png
"""

from __future__ import annotations

import argparse
import base64
import collections
import copy
import io
import json
import math
import os
import uuid

import numpy as np

MAP = os.path.join("maps", "village_walled_source.json")

#: Sites closer than this to Millbrook do not move.
R0 = 1500.0
#: How much further out the rest of the world moves (see module doc).
SPREAD = 3.0
#: Objects closer than this (single-link) are one rigid piece.
LINK = 300.0
#: Sculpt grid cells within this distance of a piece move with it.
SCULPT_REACH = 520.0
#: Ground reproduced around a moved piece's objects, then feathered out.
FOOTPRINT_PAD = 224.0
FOOTPRINT_FEATHER = 256.0

#: Location markers that move together with another (the anchor).
SITE_GROUPS = {
    "Mirrormere": ("Reedhollow", "Smugglers' Cove", "Dunstan's Camp"),
    "Greywood": ("Fenwick's Lodge", "Abandoned Camp"),
}
#: Extra anchors that are not location markers: (marker name, reach).
EXTRA_ANCHORS = (("bryn_watch", 1700.0),)

#: Heightmap overlay: resolution and strength (offset = (h - 0.5) * strength).
HM_SIZE = 768
HM_STRENGTH = 4000.0

#: The Emberpeak Shrine, far to the north-east in the Emberpeaks.
SHRINE = (25600.0, -26400.0)
SHRINE_ELEVATION = 620.0       # above the lowland surface
#: The pass up to it: (x, z) way points from the foothills to the shrine.
PASS = ((13800.0, -11600.0), (16800.0, -15600.0), (19200.0, -18200.0),
        (21000.0, -21800.0), (23400.0, -24300.0), SHRINE)

FLOOR_SLAB_Y = 76.0


def _uid():
    return str(uuid.uuid4())


def _props(t):
    return t.setdefault("properties", {})


def _is_floor_slab(b):
    return (b.get("pos", [0, 0, 0])[1] == FLOOR_SLAB_Y and not b.get("shader")
            and all(v == "nodraw.jpg" for v in b.get("textures", {}).values()))


_GLOBAL_THINGS = {"bigworldsettings", "miniwindsettings", "logic_command",
                  "logiccommand", "playerstart", "logic_state"}


# ---------------------------------------------------------------------------
# Terrain helpers
# ---------------------------------------------------------------------------

def _terrain(terrain_data, heightmap=None, sculpt=True):
    from engine.terrain import Terrain
    t = Terrain()
    data = dict(terrain_data)
    if not sculpt:
        data.pop("sculpt_offsets", None)
    data.pop("heightmap_blob", None)
    t.from_dict(data)
    if heightmap is not None:
        t.heightmap_data = heightmap
        t.heightmap_strength = HM_STRENGTH
        t.heightmap_blend = "additive"
    return t


def _heights(terrain, xs, zs):
    return terrain._get_raw_heights_batch(np.asarray(xs, np.float32),
                                          np.asarray(zs, np.float32))


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _value_noise(xs, zs, scale, seed):
    """Smooth value noise in -1..1 on world coordinates (vectorised)."""
    rng = np.random.default_rng(seed)
    n = 257
    lattice = rng.uniform(-1.0, 1.0, (n, n)).astype(np.float32)
    fx = xs / scale
    fz = zs / scale
    x0 = np.floor(fx).astype(np.int64)
    z0 = np.floor(fz).astype(np.int64)
    tx = fx - x0
    tz = fz - z0
    tx = tx * tx * (3 - 2 * tx)
    tz = tz * tz * (3 - 2 * tz)

    def g(ix, iz):
        return lattice[ix % n, iz % n]
    a = g(x0, z0) * (1 - tx) + g(x0 + 1, z0) * tx
    b = g(x0, z0 + 1) * (1 - tx) + g(x0 + 1, z0 + 1) * tx
    return a * (1 - tz) + b * tz


def _ridged(xs, zs, scale, seed, octaves=4):
    total = np.zeros_like(xs, dtype=np.float32)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = 1.0 - np.abs(_value_noise(xs * freq, zs * freq, scale, seed + o))
        total += (n * n) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return total / norm


def _dist_to_polyline(xs, zs, pts):
    """Distance to the polyline and the 0..1 position along it of the
    nearest point."""
    best = np.full(xs.shape, np.inf, np.float32)
    along = np.zeros(xs.shape, np.float32)
    lengths = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(lengths)
    run = 0.0
    for i, seg in enumerate(lengths):
        (ax, az), (bx, bz) = pts[i], pts[i + 1]
        dx, dz = bx - ax, bz - az
        t = np.clip(((xs - ax) * dx + (zs - az) * dz) / (seg * seg), 0.0, 1.0)
        px, pz = ax + t * dx, az + t * dz
        d = np.hypot(xs - px, zs - pz)
        closer = d < best
        best = np.where(closer, d, best)
        along = np.where(closer, (run + t * seg) / total, along)
        run += seg
    return best, along


def _box_blur(a, r):
    """Mean over a (2r+1)-square window, edges clamped."""
    a = np.pad(a, r, mode="edge")
    for axis in (0, 1):
        c = np.cumsum(a, axis=axis)
        c = np.insert(c, 0, 0.0, axis=axis)
        n = a.shape[axis]
        hi = np.take(c, np.arange(2 * r + 1, n + 1), axis=axis)
        lo = np.take(c, np.arange(0, n - 2 * r), axis=axis)
        a = (hi - lo) / (2 * r + 1)
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        a = np.pad(a, pad, mode="edge")
    return a[r:-r, r:-r]


def _dilate_distance(mask, cell, max_cells):
    """Approximate distance (world units) from every pixel to *mask*."""
    dist = np.where(mask, 0.0, np.inf).astype(np.float32)
    cur = mask.copy()
    for step in range(1, max_cells + 1):
        grown = cur.copy()
        grown[1:, :] |= cur[:-1, :]
        grown[:-1, :] |= cur[1:, :]
        grown[:, 1:] |= cur[:, :-1]
        grown[:, :-1] |= cur[:, 1:]
        if step % 2 == 0:       # alternate in diagonals: an octagonal metric
            grown[1:, 1:] |= cur[:-1, :-1]
            grown[:-1, :-1] |= cur[1:, 1:]
            grown[1:, :-1] |= cur[:-1, 1:]
            grown[:-1, 1:] |= cur[1:, :-1]
        new = grown & ~cur
        dist[new] = step * cell
        cur = grown
    return dist


# ---------------------------------------------------------------------------
# The expansion
# ---------------------------------------------------------------------------

class Expander:
    def __init__(self, world, chunks=40, report=print):
        self.world = world
        self.chunks = int(chunks)
        self.report = report
        self.old_td = dict(world["terrain_data"])
        self.old_terrain = _terrain(self.old_td)

    # -- pieces and where they go ------------------------------------------
    def _objects(self):
        objs = []
        for i, b in enumerate(self.world["brushes"]):
            objs.append(("b", i, b["pos"][0], b["pos"][2]))
        for i, t in enumerate(self.world["things"]):
            if str(t.get("type", "")).lower() in _GLOBAL_THINGS:
                continue
            objs.append(("t", i, t["pos"][0], t["pos"][2]))
        return objs

    def _pieces(self, pts):
        n = len(pts)
        parent = list(range(n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        grid = collections.defaultdict(list)
        for i, (x, z) in enumerate(pts):
            grid[(int(x // LINK), int(z // LINK))].append(i)
        for (gx, gz), ids in grid.items():
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in grid.get((gx + dx, gz + dz), ()):
                        for i in ids:
                            if i < j and (pts[i][0] - pts[j][0]) ** 2 + \
                                    (pts[i][1] - pts[j][1]) ** 2 <= LINK * LINK:
                                parent[find(i)] = find(j)
        groups = collections.defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)
        return list(groups.values())

    @staticmethod
    def warp_offset(x, z):
        r = math.hypot(x, z)
        if r <= R0:
            return 0.0, 0.0
        grow = (SPREAD - 1.0) * (r - R0)
        return x / r * grow, z / r * grow

    @staticmethod
    def _snap(v, step=16.0):
        return float(round(v / step) * step)

    def _anchors(self):
        """``[(name, x, z, reach, (dx, dz))]`` for every site anchor."""
        markers = {}
        for t in self.world["things"]:
            p = t.get("properties", {})
            if str(t.get("type")) != "marker":
                continue
            markers[p.get("name")] = t
            if str(p.get("marker_kind", "")).lower() == "location":
                markers[p.get("place_name")] = t
        anchors = []
        grouped = {m: lead for lead, members in SITE_GROUPS.items() for m in members}
        for t in self.world["things"]:
            p = t.get("properties", {})
            if str(t.get("type")) != "marker" or \
                    str(p.get("marker_kind", "")).lower() != "location":
                continue
            name = p.get("place_name") or p.get("name")
            x, z = t["pos"][0], t["pos"][2]
            lead = markers.get(grouped.get(name), t)
            dx, dz = self.warp_offset(lead["pos"][0], lead["pos"][2])
            reach = float(p.get("discover_radius", 600.0)) + 900.0
            anchors.append((name, x, z, reach, (self._snap(dx), self._snap(dz))))
        for name, reach in EXTRA_ANCHORS:
            t = markers.get(name)
            if t is not None:
                dx, dz = self.warp_offset(t["pos"][0], t["pos"][2])
                anchors.append((name, t["pos"][0], t["pos"][2], reach,
                                (self._snap(dx), self._snap(dz))))
        return anchors

    def plan(self):
        self.world["brushes"] = [b for b in self.world["brushes"]
                                 if not _is_floor_slab(b)]
        objs = self._objects()
        pts = [(o[2], o[3]) for o in objs]
        anchors = self._anchors()
        self.pieces = []
        for members in self._pieces(pts):
            cx = sum(pts[i][0] for i in members) / len(members)
            cz = sum(pts[i][1] for i in members) / len(members)
            best = None
            for name, ax, az, reach, off in anchors:
                d = math.hypot(cx - ax, cz - az)
                if d <= reach and (best is None or d < best[0]):
                    best = (d, name, off)
            if best is not None:
                site, off = best[1], best[2]
            else:
                dx, dz = self.warp_offset(cx, cz)
                site, off = None, (self._snap(dx), self._snap(dz))
            self.pieces.append({"members": [objs[i] for i in members],
                                "centre": (cx, cz), "site": site, "offset": off})
        moved = [p for p in self.pieces if p["offset"] != (0.0, 0.0)]
        self.report(f"{len(self.pieces)} pieces, {len(moved)} move; "
                    f"{len(self.world['brushes'])} brushes after dropping floor slabs")

    # -- coordinates -------------------------------------------------------
    def _piece_index(self):
        """Spatial lookup: grid cell -> [(x, z, piece)] over every member."""
        index = collections.defaultdict(list)
        for piece in self.pieces:
            for kind, i, x, z in piece["members"]:
                index[(int(x // 512), int(z // 512))].append((x, z, piece))
        self._index = index

    def offset_at(self, x, z, reach=700.0):
        """The offset of the piece nearest (x, z), or the warp there."""
        best, off = None, None
        cx, cz = int(x // 512), int(z // 512)
        span = int(reach // 512) + 1
        for gx in range(cx - span, cx + span + 1):
            for gz in range(cz - span, cz + span + 1):
                for px, pz, piece in self._index.get((gx, gz), ()):
                    d = (px - x) ** 2 + (pz - z) ** 2
                    if d <= reach * reach and (best is None or d < best):
                        best, off = d, piece["offset"]
        if off is not None:
            return off
        dx, dz = self.warp_offset(x, z)
        return self._snap(dx), self._snap(dz)

    # -- heightmap ---------------------------------------------------------
    def build_heightmap(self):
        half = self.chunks // 2
        cs = float(self.old_td["chunk_size"])
        self.min_c, self.max_c = -half, self.chunks - half - 1
        lo, hi = self.min_c * cs, (self.max_c + 1) * cs
        self.bounds = (lo, hi)
        cell = (hi - lo) / (HM_SIZE - 1)
        axis = lo + np.arange(HM_SIZE, dtype=np.float32) * cell
        X, Z = np.meshgrid(axis, axis)          # rows: z, columns: x
        edge = np.maximum(np.abs(X), np.abs(Z))
        # A mountain wall around the world's edge.
        wall = _smoothstep(hi - 9000.0, hi - 1500.0, edge) * \
            (1200.0 + 900.0 * _ridged(X, Z, 5200.0, 11))
        # The Emberpeaks: a massif far to the north-east.
        sx, sz = SHRINE
        d_shrine = np.hypot(X - sx, Z - sz)
        massif = _smoothstep(15500.0, 6500.0, d_shrine) * \
            (700.0 + 1500.0 * _ridged(X, Z, 3600.0, 23))
        # Rolling uplands to the south-west, gentler.
        uplands = _smoothstep(0.2, 0.75, _value_noise(X, Z, 9000.0, 31) * 0.5 + 0.5) * \
            _smoothstep(16000.0, 9000.0, np.hypot(X + 20000.0, Z - 18000.0)) * \
            (250.0 + 650.0 * _ridged(X, Z, 2600.0, 37))
        M = np.maximum(np.maximum(wall, massif), uplands)
        # The pass: a valley climbing steadily to the shrine.
        d_pass, along = _dist_to_polyline(X, Z, PASS)
        road = SHRINE_ELEVATION * _smoothstep(0.0, 1.0, along)
        valley = _smoothstep(1500.0, 500.0, d_pass)
        M = M * (1.0 - valley) + np.minimum(M, road) * valley
        # The shrine's high basin.
        basin = _smoothstep(1400.0, 700.0, d_shrine)
        M = M * (1.0 - basin) + SHRINE_ELEVATION * basin
        # Keep every site on the lowland: no mountain within reach of one.
        mask = np.zeros(M.shape, bool)
        for piece in self.pieces:
            ox, oz = piece["offset"]
            for kind, i, x, z in piece["members"]:
                if kind == "b" and self._is_tree(self.world["brushes"][i]):
                    continue
                c = int(round((x + ox - lo) / cell))
                r = int(round((z + oz - lo) / cell))
                if 0 <= r < HM_SIZE and 0 <= c < HM_SIZE:
                    mask[r, c] = True
        # The shrine's own content sits in its basin, not on the lowland.
        clear = _dilate_distance(mask, cell, int(3200 / cell) + 2)
        M = M * _smoothstep(1100.0, 3000.0, clear)
        self.heightmap = (0.5 + M / HM_STRENGTH).astype(np.float32)
        self.report(f"heightmap {HM_SIZE}^2, peaks {M.max():.0f} units above the lowland")

    @staticmethod
    def _is_tree(b):
        top = str(b.get("textures", {}).get("top", ""))
        return top.startswith("tree") or top.startswith("trees")

    # -- ground ------------------------------------------------------------
    def build_terrain(self):
        td = self.world["terrain_data"]
        td["min_chunk_x"] = td["min_chunk_z"] = self.min_c
        td["max_chunk_x"] = td["max_chunk_z"] = self.max_c
        self.new_base = _terrain(td, heightmap=self.heightmap, sculpt=False)
        res = float(self.old_td.get("sculpt_grid_resolution", 16.0))
        old_sculpt = {(int(gx), int(gz)): float(v)
                      for gx, gz, v in self.old_td.get("sculpt_offsets", [])}
        new = {}
        # The village keeps its own sculpting exactly.
        for (gx, gz), v in old_sculpt.items():
            if self.offset_at(gx * res, gz * res, SCULPT_REACH) == (0.0, 0.0):
                if math.hypot(gx * res, gz * res) < 6000:
                    new[(gx, gz)] = v
        # Every moved piece takes its ground with it.
        weights = {}
        for piece in self.pieces:
            ox, oz = piece["offset"]
            if (ox, oz) == (0.0, 0.0):
                continue
            cells = self._footprint(piece, res, old_sculpt)
            if not cells:
                continue
            keys = np.array(list(cells.keys()), np.int64)
            w = np.array(list(cells.values()), np.float32)
            old_x, old_z = keys[:, 0] * res, keys[:, 1] * res
            old_h = _heights(self.old_terrain, old_x, old_z)
            sx, sz = int(round(ox / res)), int(round(oz / res))
            new_h = _heights(self.new_base, old_x + sx * res, old_z + sz * res)
            for (gx, gz), wt, target, base in zip(keys, w, old_h, new_h):
                key = (int(gx) + sx, int(gz) + sz)
                if wt <= weights.get(key, 0.0):
                    continue
                weights[key] = float(wt)
                new[key] = float(wt * (target - base))
        self.sculpt = {k: v for k, v in new.items() if abs(v) >= 0.25}
        self.res = res
        self._store_terrain()
        self.report(f"terrain {self.chunks}x{self.chunks} chunks "
                    f"({self.bounds[0]:.0f}..{self.bounds[1]:.0f}), "
                    f"{len(self.sculpt)} sculpt cells")

    def _store_terrain(self):
        """Write the sculpt and heightmap into the map and rebuild the
        terrain the placement code samples."""
        td = self.world["terrain_data"]
        td["sculpt_offsets"] = [[gx, gz, round(v, 2)] for (gx, gz), v in
                                sorted(self.sculpt.items()) if abs(v) >= 0.25]
        td["sculpt_grid_resolution"] = self.res
        buf = io.BytesIO()
        np.save(buf, self.heightmap)
        td["heightmap_blob"] = base64.b64encode(buf.getvalue()).decode("ascii")
        td["heightmap_strength"] = HM_STRENGTH
        td["heightmap_blend"] = "additive"
        self.new_terrain = _terrain(td, heightmap=self.heightmap)
        self._stored_sculpt = dict(self.sculpt)

    def _grid_heights(self, gx, gz):
        """Ground height at sculpt grid points, including sculpting not yet
        stored into the terrain."""
        gx = np.asarray(gx, np.int64).ravel()
        gz = np.asarray(gz, np.int64).ravel()
        h = _heights(self.new_terrain, gx * self.res, gz * self.res).astype(np.float64)
        pending = np.array([self.sculpt.get((a, b), 0.0) - self._stored_sculpt.get((a, b), 0.0)
                            for a, b in zip(gx.tolist(), gz.tolist())])
        return h + pending

    def _reshape(self, gx, gz, want, mode):
        """Raise (``mode='raise'``) or lower the ground at grid points to
        *want* where it is below / above it."""
        cur = self._grid_heights(gx, gz)
        want = np.asarray(want, np.float64).ravel()
        change = np.maximum(want - cur, 0.0) if mode == "raise" else np.minimum(want - cur, 0.0)
        for a, b, d in zip(np.ravel(gx).tolist(), np.ravel(gz).tolist(), change.tolist()):
            if d:
                self.sculpt[(a, b)] = self.sculpt.get((a, b), 0.0) + d

    # -- ground decals and water -------------------------------------------
    def seat_ground_decals(self):
        """Raise the ground under the flat ground-level brushes (roads,
        floors, tiles, fires) the 2.4 map laid on its floor slabs, so they
        rest on the terrain instead of hovering over its dips."""
        res = self.res
        for b in self.world["brushes"]:
            if b.get("water_plane") or self._is_tree(b) or b["size"][1] > 4.0:
                continue
            bottom = b["pos"][1] - b["size"][1] / 2.0
            if not (184.0 <= bottom <= 204.0):
                continue
            hx, hz = b["size"][0] / 2.0, b["size"][2] / 2.0
            feather = 96.0
            gxs = np.arange(int((b["pos"][0] - hx - feather) // res),
                            int((b["pos"][0] + hx + feather) // res) + 2)
            gzs = np.arange(int((b["pos"][2] - hz - feather) // res),
                            int((b["pos"][2] + hz + feather) // res) + 2)
            GX, GZ = np.meshgrid(gxs, gzs, indexing="ij")
            dx = np.maximum(np.abs(GX * res - b["pos"][0]) - hx, 0.0)
            dz = np.maximum(np.abs(GZ * res - b["pos"][2]) - hz, 0.0)
            d = np.hypot(dx, dz)
            want = bottom - 1.0 - d * 0.5          # a gentle shoulder off the edge
            self._reshape(GX, GZ, want, "raise")
        self.report("ground raised under the ground-level brushes the floor slabs carried")

    @staticmethod
    def _water_props(proto=None):
        props = {"shader": "Water", "is_fog": False, "water_opacity": 0.5,
                 "water_reflectivity": 0.5, "water_tint": [0.05, 0.35, 0.5],
                 "water_wave_enabled": False, "water_wave_height": 0.5,
                 "is_trigger": False, "water_plane": True}
        if proto:
            props.update({k: proto[k] for k in props if k in proto})
        return props

    def _fill_basin(self, x0, z0, x1, z1, inside, surface=None, proto=None, name="",
                    smooth=0.0, ragged=0.0, seed=0):
        """Make a water body: one water brush over a sculpted depression.

        *inside(wx, wz)* says where the water is, within the rectangle
        (x0, z0)-(x1, z1). The ground there is lowered below the waterline;
        the rest of the rectangle -- which the single brush also covers -- is
        kept above it as bank, feathered out beyond the rectangle. Without a
        *surface*, the waterline sits just below the natural shore. Returns
        the brush. *smooth* rounds the outline off over that many units and
        *ragged* frays it with noise, for a natural shore.
        """
        res = self.res
        # The brush reaches a margin past the water on every side, so its
        # straight edges lie under dry bank, well clear of the shoreline even
        # where the terrain mesh is coarser than the sculpt grid.
        margin = 128.0
        x0, z0, x1, z1 = x0 - margin, z0 - margin, x1 + margin, z1 + margin
        feather = 160.0
        gxs = np.arange(int((x0 - feather) // res), int((x1 + feather) // res) + 2)
        gzs = np.arange(int((z0 - feather) // res), int((z1 + feather) // res) + 2)
        GX, GZ = np.meshgrid(gxs, gzs, indexing="ij")
        WX, WZ = GX * res, GZ * res
        water = inside(WX, WZ)
        if smooth > 0.0:
            r = max(1, int(smooth / res / 2))
            field = _box_blur(_box_blur(water.astype(np.float32), r), r)
            if ragged > 0.0:
                field = field + ragged * _value_noise(WX.astype(np.float32),
                                                      WZ.astype(np.float32), 260.0, seed)
            water = field >= 0.5
            # Never past the brush.
            water &= (WX >= x0 + 32) & (WX <= x1 - 32) & (WZ >= z0 + 32) & (WZ <= z1 - 32)
        h = self._grid_heights(GX, GZ).reshape(GX.shape)
        d_out = _dilate_distance(water, res, int(96 // res) + 1)
        d_in = _dilate_distance(~water, res, int(2400 // res) + 1)
        shore = ~water & (d_out <= 96.0)
        if surface is None:
            surface = float(np.percentile(h[shore], 20)) - 4.0
        # Underwater: below the line, deepening away from the shore.
        bed = surface - 14.0 - np.minimum(d_in * 0.35, 110.0)
        self._reshape(GX[water], GZ[water], bed[water], "lower")
        # Bank: everything else the brush covers stays above the line, and
        # the ground outside the rectangle ramps down to meet it.
        beyond = np.hypot(np.maximum(np.maximum(x0 - WX, WX - x1), 0.0),
                          np.maximum(np.maximum(z0 - WZ, WZ - z1), 0.0))
        bank = surface + 12.0 - beyond * 0.5
        land = ~water
        self._reshape(GX[land], GZ[land], bank[land], "raise")
        floor = float(self._grid_heights(GX[water], GZ[water]).min()) - 10.0
        height = max(surface - floor, 40.0)
        brush = {"pos": [round((x0 + x1) / 2.0, 1), round(surface - height / 2.0, 1),
                         round((z0 + z1) / 2.0, 1)],
                 "size": [round(x1 - x0, 1), round(height, 1), round(z1 - z0, 1)],
                 "textures": self._textured("nodraw.jpg"), "id": _uid()}
        brush.update(self._water_props(proto))
        if name:
            brush["name"] = name
        self.world["brushes"].append(brush)
        return brush

    def merge_water(self):
        """Turn every water body built of several brushes (the 2.4 lake is
        27 strips) into one brush over a sculpted depression."""
        water = [b for b in self.world["brushes"] if b.get("water_plane")]
        n = len(water)
        parent = list(range(n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def rect(b):
            return (b["pos"][0] - b["size"][0] / 2, b["pos"][2] - b["size"][2] / 2,
                    b["pos"][0] + b["size"][0] / 2, b["pos"][2] + b["size"][2] / 2)
        rects = [rect(b) for b in water]
        for i in range(n):
            for j in range(i + 1, n):
                a, c = rects[i], rects[j]
                if a[0] <= c[2] + 1 and c[0] <= a[2] + 1 and a[1] <= c[3] + 1 and c[1] <= a[3] + 1:
                    parent[find(i)] = find(j)
        groups = collections.defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)
        merged = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            rs = np.array([rects[i] for i in members])

            def inside(wx, wz, rs=rs):
                hit = np.zeros(wx.shape, bool)
                for x0, z0, x1, z1 in rs:
                    hit |= (wx >= x0) & (wx <= x1) & (wz >= z0) & (wz <= z1)
                return hit
            proto = water[members[0]]
            for i in members:
                self.world["brushes"].remove(water[i])
            b = self._fill_basin(rs[:, 0].min(), rs[:, 1].min(), rs[:, 2].max(),
                                 rs[:, 3].max(), inside, proto=proto,
                                 smooth=320.0, ragged=0.12, seed=len(members))
            merged += 1
            self.report(f"lake of {len(members)} water brushes -> one brush "
                        f"{b['size'][0]:.0f} x {b['size'][2]:.0f}, waterline "
                        f"{b['pos'][1] + b['size'][1] / 2:.0f}")
        self._store_terrain()

    def _footprint(self, piece, res, old_sculpt):
        """``{old cell: weight}``: the ground a piece stands on (weight 1),
        feathered out, plus the sculpting within its reach."""
        cells = {}
        reach = FOOTPRINT_PAD + FOOTPRINT_FEATHER
        for kind, i, x, z in piece["members"]:
            if kind == "b":
                b = self.world["brushes"][i]
                if self._is_tree(b):
                    continue
                hx, hz = b["size"][0] / 2.0, b["size"][2] / 2.0
            else:
                hx = hz = 0.0
            gx0 = int(math.floor((x - hx - reach) / res))
            gx1 = int(math.ceil((x + hx + reach) / res))
            gz0 = int(math.floor((z - hz - reach) / res))
            gz1 = int(math.ceil((z + hz + reach) / res))
            gxs = np.arange(gx0, gx1 + 1)
            gzs = np.arange(gz0, gz1 + 1)
            GX, GZ = np.meshgrid(gxs, gzs, indexing="ij")
            ddx = np.maximum(np.abs(GX * res - x) - hx, 0.0)
            ddz = np.maximum(np.abs(GZ * res - z) - hz, 0.0)
            d = np.hypot(ddx, ddz)
            w = 1.0 - _smoothstep(FOOTPRINT_PAD, reach, d)
            for gx, gz, wt in zip(GX.ravel(), GZ.ravel(), w.ravel()):
                if wt > 0.0:
                    k = (int(gx), int(gz))
                    if wt > cells.get(k, 0.0):
                        cells[k] = float(wt)
        # Sculpting near the piece (hills, the lake bowl) comes with it.
        members = [(x, z) for _k, _i, x, z in piece["members"]]
        xs = np.array([m[0] for m in members])
        zs = np.array([m[1] for m in members])
        bx0, bx1 = xs.min() - SCULPT_REACH, xs.max() + SCULPT_REACH
        bz0, bz1 = zs.min() - SCULPT_REACH, zs.max() + SCULPT_REACH
        for (gx, gz), v in old_sculpt.items():
            wx, wz = gx * res, gz * res
            if not (bx0 <= wx <= bx1 and bz0 <= wz <= bz1):
                continue
            if self.offset_at(wx, wz, SCULPT_REACH) != piece["offset"]:
                continue
            if 1.0 > cells.get((gx, gz), 0.0):
                cells[(gx, gz)] = 1.0
        return cells

    # -- objects -----------------------------------------------------------
    def move_objects(self):
        self._thing_offset = {}
        for piece in self.pieces:
            ox, oz = piece["offset"]
            if (ox, oz) == (0.0, 0.0):
                continue
            for kind, i, x, z in piece["members"]:
                obj = (self.world["brushes"] if kind == "b" else self.world["things"])[i]
                obj["pos"] = [obj["pos"][0] + ox, obj["pos"][1], obj["pos"][2] + oz]
                if kind == "t":
                    self._thing_offset[i] = (ox, oz)
        for t in self.world["things"]:
            p = _props(t)
            for key in ("home", "_anchor", "_dest", "_wander_dest"):
                v = p.get(key)
                if isinstance(v, list) and len(v) == 3:
                    ox, oz = self.offset_at(v[0], v[2])
                    p[key] = [v[0] + ox, v[1], v[2] + oz]
            pts = p.get("_patrol_pts")
            if isinstance(pts, list):
                p["_patrol_pts"] = [[q[0] + self.offset_at(q[0], q[2])[0], q[1],
                                     q[2] + self.offset_at(q[0], q[2])[1]]
                                    if isinstance(q, list) and len(q) == 3 else q
                                    for q in pts]
        self._settle_loose_things()
        self._drop_buried_trees()

    def _mountain(self, x, z):
        """How far the heightmap lifts the ground at (x, z)."""
        return float(self.new_base._sample_heightmap_batch(
            np.array([x], np.float32), np.array([z], np.float32),
            np.zeros(1, np.float32))[0])

    def _drop_buried_trees(self):
        keep, dropped = [], 0
        for b in self.world["brushes"]:
            if self._is_tree(b) and self._mountain(b["pos"][0], b["pos"][2]) > 120.0:
                dropped += 1
                continue
            keep.append(b)
        self.world["brushes"] = keep
        if dropped:
            self.report(f"{dropped} trees left behind under the new mountains")

    def _settle_loose_things(self):
        """A thing whose ground changed under it (outside every footprint)
        keeps its height above the ground."""
        for i, t in enumerate(self.world["things"]):
            if str(t.get("type", "")).lower() in _GLOBAL_THINGS:
                continue
            x, y, z = t["pos"]
            ox, oz = self._thing_offset.get(i, (0.0, 0.0))
            new = float(_heights(self.new_terrain, [x], [z])[0])
            old = float(_heights(self.old_terrain, [x - ox], [z - oz])[0])
            if abs(new - old) > 4.0:
                t["pos"] = [x, round(y + (new - old), 1), z]

    # -- the shrine --------------------------------------------------------
    def _ground(self, x, z):
        return float(_heights(self.new_terrain, [x], [z])[0])

    def build_shrine(self):
        things = self.world["things"]
        brushes = self.world["brushes"]
        book = next(t for t in things if t["type"] == "spellbook")
        bx, by, bz = book["pos"]
        # The altar: the tile floor, the stone block and its fire, beside the book.
        altar = [b for b in brushes
                 if math.hypot(b["pos"][0] - bx, b["pos"][2] - (bz + 140.0)) < 20.0
                 and b["size"][0] <= 220.0]
        if len(altar) < 3:
            raise SystemExit("could not find the altar beside the spellbook")
        ax, az = altar[0]["pos"][0], altar[0]["pos"][2]
        old_ground = float(_heights(self.new_terrain, [ax], [az])[0])
        sx, sz = SHRINE
        ground = self._ground(sx, sz)
        lift = ground - old_ground
        for b in altar:
            b["pos"] = [b["pos"][0] - ax + sx, b["pos"][1] + lift, b["pos"][2] - az + sz]
        book["pos"] = [bx - ax + sx, by + lift, bz - az + sz]
        bp = _props(book)
        bp.update({"name": "Ember_Tome", "title": "The Ember Tome",
                   "spell": "firebolt", "cover": "red", "quest_item": "ember_tome"})
        stone = {"north": "Stone_09-512x512.png", "south": "Stone_09-512x512.png",
                 "east": "Stone_09-512x512.png", "west": "Stone_09-512x512.png",
                 "top": "Stone_09-512x512.png", "down": "Stone_09-512x512.png"}

        def brush(pos, size, textures=stone):
            g = self._ground(pos[0], pos[2])
            brushes.append({"pos": [pos[0], g + size[1] / 2.0 - 8.0, pos[2]],
                            "size": list(size), "textures": dict(textures),
                            "id": _uid()})
        # A ring of standing stones about the altar.
        for k in range(9):
            a = 2.0 * math.pi * k / 9.0
            tall = 300.0 if k % 2 == 0 else 200.0
            brush((sx + math.cos(a) * 520.0, 0.0, sz + math.sin(a) * 520.0),
                  (76.0, tall, 76.0))
        # Cairns along the pass, a lantern on every other one.
        lights = 0
        for k, (x, z) in enumerate(PASS[:-1]):
            nx, nz = PASS[k + 1]
            for f in (0.0, 0.5):
                cx, cz = x + (nx - x) * f, z + (nz - z) * f
                brush((cx + 260.0, 0.0, cz + 260.0), (90.0, 120.0, 90.0))
                if f == 0.0:
                    things.append(self._light(f"Light_Pass{k}",
                                              [cx + 260.0, self._ground(cx, cz) + 220.0,
                                               cz + 260.0], 520.0, [255, 170, 110]))
                    lights += 1
        things.append(self._light("Light_Shrine", [sx, ground + 260.0, sz],
                                  900.0, [255, 140, 80]))
        things.append(self._light("Light_ShrineFire", [sx, ground + 120.0, sz + 140.0],
                                  420.0, [255, 110, 40]))
        things.append({"type": "marker", "pos": [sx, ground + 72.0, sz],
                       "properties": {"type": "marker", "name": "loc_emberpeak_shrine",
                                      "id": _uid(), "marker_kind": "location",
                                      "place_name": "Emberpeak Shrine",
                                      "discover_radius": 900.0},
                       "io_connections": []})
        things.append({"type": "marker", "pos": [PASS[1][0], self._ground(*PASS[1]) + 72.0,
                                                 PASS[1][1]],
                       "properties": {"type": "marker", "name": "loc_emberpeak_pass",
                                      "id": _uid(), "marker_kind": "location",
                                      "place_name": "The Emberpeak Pass",
                                      "discover_radius": 1200.0},
                       "io_connections": []})
        # Wolves and a bear on the way up.
        spawn = next((t for t in things if t["type"] == "creaturespawn"
                      and "wolf" in str(_props(t).get("name", "")).lower()), None)
        if spawn is not None:
            for k, (x, z) in enumerate((PASS[2], PASS[4])):
                s = copy.deepcopy(spawn)
                s["pos"] = [x - 500.0, self._ground(x - 500.0, z + 400.0) + 40.0, z + 400.0]
                _props(s).update({"name": f"Spawn_wolf_pass{k}", "id": _uid()})
                things.append(s)
        self.report(f"Emberpeak Shrine at {sx:.0f},{ground:.0f},{sz:.0f} "
                    f"({math.hypot(sx, sz):.0f} units from Millbrook), "
                    f"{lights + 2} lights")

    @staticmethod
    def _light(name, pos, radius, colour):
        return {"type": "light", "pos": [round(v, 1) for v in pos],
                "properties": {"type": "light", "name": name, "id": _uid(),
                               "colour": list(colour), "intensity": 2.0,
                               "radius": float(radius), "state": "on",
                               "show_radius": False, "casts_shadows": False,
                               "parent_mover": "", "parent_offset": [0.0, 0.0, 0.0]},
                "io_connections": []}

    # -- the wilds ---------------------------------------------------------
    #: Landmarks for the open land between the sites and the mountains:
    #: (place name, kind). Placed far from everything else and each other.
    WILDS = (("Stillwater Tarn", "pond"), ("Old Watchtower", "tower"),
             ("The Seven Sisters", "stones"), ("Hunter's Rest", "camp"),
             ("Heron Pool", "pond"), ("Thornwatch Ruin", "tower"),
             ("Brigand's Hollow", "bandits"), ("Greyfen Tarn", "pond"),
             ("Sunken Stones", "stones"), ("Kingsfall Tower", "tower"))
    #: Roaming wildlife for the open land: (creature role, how many spawners).
    WILDLIFE = (("wolf", 4), ("boar", 3), ("bear", 2))

    def _content_points(self):
        pts = [(b["pos"][0], b["pos"][2]) for b in self.world["brushes"]
               if not self._is_tree(b)]
        pts += [(t["pos"][0], t["pos"][2]) for t in self.world["things"]]
        return np.array(pts, np.float32)

    def _open_spots(self, count, rng, min_r, max_r, clear, apart):
        """*count* places on open lowland, *clear* from all content and
        *apart* from each other."""
        content = self._content_points()
        spots = []
        for _ in range(count * 400):
            if len(spots) >= count:
                break
            a = rng.uniform(0.0, 2.0 * math.pi)
            r = rng.uniform(min_r, max_r)
            x, z = math.cos(a) * r, math.sin(a) * r
            if self._mountain(x, z) > 20.0:
                continue
            if np.min(np.hypot(content[:, 0] - x, content[:, 1] - z)) < clear:
                continue
            if any(math.hypot(x - sx, z - sz) < apart for sx, sz in spots):
                continue
            spots.append((x, z))
        return spots

    def _brush(self, pos, size, textures, ground=None, sink=8.0, **extra):
        g = self._ground(pos[0], pos[2]) if ground is None else ground
        b = {"pos": [round(pos[0], 1), round(g + size[1] / 2.0 - sink, 1), round(pos[2], 1)],
             "size": [float(v) for v in size], "textures": dict(textures), "id": _uid()}
        b.update(extra)
        self.world["brushes"].append(b)
        return b

    @staticmethod
    def _textured(name, top=None):
        t = {k: name for k in ("north", "south", "east", "west", "down")}
        t["top"] = top or name
        return t

    def _marker(self, name, x, z, radius):
        slug = "loc_" + "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
        self.world["things"].append({
            "type": "marker", "pos": [round(x, 1), round(self._ground(x, z) + 72.0, 1), round(z, 1)],
            "properties": {"type": "marker", "name": slug, "id": _uid(),
                           "marker_kind": "location", "place_name": name,
                           "discover_radius": float(radius)},
            "io_connections": []})

    def _spawn(self, role, x, z, count, faction="wildlife"):
        proto = next((t for t in self.world["things"] if t["type"] == "creaturespawn"
                      and _props(t).get("creature_role") == "wolf"), None)
        if proto is None:
            return
        s = copy.deepcopy(proto)
        p = _props(s)
        for k in [k for k in p if k.startswith("_")]:
            del p[k]
        p.update({"name": f"Spawn_{role}_wild{len(self.world['things'])}", "id": _uid(),
                  "creature_role": role, "faction": faction, "count": int(count)})
        s["pos"] = [round(x, 1), round(self._ground(x, z) + 40.0, 1), round(z, 1)]
        self.world["things"].append(s)

    def _container(self, x, z, kind, items):
        proto = next(t for t in self.world["things"] if t["type"] == "container")
        c = copy.deepcopy(proto)
        p = _props(c)
        for k in [k for k in p if k.startswith("_")]:
            del p[k]
        from ..rpg import items as rpg_items
        inv = []
        for iid, qty in items:
            it = rpg_items.make(iid, qty) if hasattr(rpg_items, "make") else None
            inv.append(it or {"id": iid, "qty": qty})
        p.update({"name": f"{kind.title()}_wild{len(self.world['things'])}", "id": _uid(),
                  "container_kind": kind, "display_name": kind.title(), "inventory": inv,
                  "custom_idle": f"assets/sprites/miniwind/container_{kind}.png"})
        c["pos"] = [round(x, 1), round(self._ground(x, z) + 48.0, 1), round(z, 1)]
        self.world["things"].append(c)

    def add_wilds(self, seed=19):
        rng = np.random.default_rng(seed)
        spots = self._open_spots(len(self.WILDS), rng, 13000.0, 30000.0, 4500.0, 7000.0)
        stone = self._textured("Stone_09-512x512.png")
        wall = self._textured("stone-wall-v0-63mmfjnritm81.png")
        for (name, kind), (x, z) in zip(self.WILDS, spots):
            if kind == "pond":
                self._pond(x, z, float(rng.uniform(360.0, 560.0)))
                self._marker(name, x, z, 900.0)
            elif kind == "tower":
                g = self._ground(x, z)
                self._brush((x, 0, z), (420.0, 4.0, 420.0),
                            self._textured("nodraw.jpg", "flagstone.jpg"), ground=g, sink=0.0)
                for k, (dx, dz, sx, sz) in enumerate(((0, -200, 420, 32), (0, 200, 420, 32),
                                                      (-200, 0, 32, 420), (200, 0, 32, 160))):
                    h = float(rng.uniform(70.0, 300.0))
                    self._brush((x + dx, 0, z + dz), (sx, h, sz), wall, ground=g)
                self._brush((x + 200, 0, z + 150), (32.0, 90.0, 120.0), wall, ground=g)
                self._container(x - 90, z - 90, "chest",
                                [("gold", int(rng.integers(20, 60))), ("potion_heal", 1)])
                self._marker(name, x, z, 800.0)
            elif kind == "stones":
                for k in range(7):
                    a = 2.0 * math.pi * k / 7.0
                    self._brush((x + math.cos(a) * 420.0, 0, z + math.sin(a) * 420.0),
                                (70.0, float(rng.uniform(150.0, 300.0)), 70.0), stone)
                self.world["things"].append(self._light(
                    f"Light_{name.replace(' ', '')}", [x, self._ground(x, z) + 240.0, z],
                    600.0, [180, 200, 255]))
                self._marker(name, x, z, 800.0)
            elif kind in ("camp", "bandits"):
                g = self._ground(x, z)
                self._brush((x, 0, z), (120.0, 24.0, 100.0),
                            self._textured("Stone_09-512x512.png", "fire01.png"), ground=g)
                self._brush((x + 260, 0, z - 120), (180.0, 126.0, 176.0),
                            self._textured("nodraw.jpg", "canopy02.png"), ground=g)
                self._brush((x - 240, 0, z + 140), (180.0, 126.0, 176.0),
                            self._textured("nodraw.jpg", "canopy03.png"), ground=g)
                self.world["things"].append(self._light(
                    f"Light_{name.replace(' ', '').replace(chr(39), '')}",
                    [x, g + 160.0, z], 520.0, [255, 160, 90]))
                self._container(x + 120, z + 220, "barrel" if kind == "camp" else "chest",
                                [("gold", int(rng.integers(10, 80)))])
                if kind == "bandits":
                    self._spawn("bandit", x + 500, z + 300, 3, faction="bandits")
                    self._spawn("bandit_archer", x - 500, z - 300, 2, faction="bandits")
                self._marker(name, x, z, 800.0)
        self._store_terrain()
        roles = [r for r, n in self.WILDLIFE for _ in range(n)]
        dens = self._open_spots(len(roles), rng, 9000.0, 31000.0, 3000.0, 5000.0)
        for role, (x, z) in zip(roles, dens):
            self._spawn(role, x, z, 2 if role != "bear" else 1)
        self.report(f"{len(spots)} wild landmarks ({', '.join(n for n, _ in self.WILDS[:len(spots)])}), "
                    f"{len(dens)} wildlife spawners")

    def _pond(self, x, z, radius):
        """A still pond: a round sculpted depression, filled by one water
        brush."""
        r2 = radius * radius

        def inside(wx, wz):
            return (wx - x) ** 2 + (wz - z) ** 2 <= r2
        self._fill_basin(x - radius, z - radius, x + radius, z + radius, inside,
                         smooth=96.0, ragged=0.25, seed=int(abs(x) + abs(z)) % 997)

    # -- trees -------------------------------------------------------------
    def scatter_trees(self, count=900, seed=7):
        """A thin scatter of trees across the new land (not on sites, not on
        the mountains' upper slopes), in the style of the map's own."""
        rng = np.random.default_rng(seed)
        protos = [copy.deepcopy(b) for b in self.world["brushes"] if self._is_tree(b)]
        if not protos:
            return
        lo, hi = self.bounds
        occupied = collections.defaultdict(list)
        for b in self.world["brushes"]:
            occupied[(int(b["pos"][0] // 1024), int(b["pos"][2] // 1024))].append(b)
        for t in self.world["things"]:
            occupied[(int(t["pos"][0] // 1024), int(t["pos"][2] // 1024))].append(t)
        placed = 0
        tries = 0
        while placed < count and tries < count * 20:
            tries += 1
            # Groves: pick a centre, then a few trees around it.
            gx, gz = rng.uniform(lo + 3000, hi - 3000, 2)
            if math.hypot(gx, gz) < 6000:
                continue
            for _ in range(int(rng.integers(3, 9))):
                x = float(gx + rng.normal(0, 420))
                z = float(gz + rng.normal(0, 420))
                if occupied.get((int(x // 1024), int(z // 1024))):
                    continue
                if self._mountain(x, z) > 120.0:
                    continue
                g = self._ground(x, z)
                b = copy.deepcopy(protos[int(rng.integers(len(protos)))])
                s = float(rng.uniform(0.8, 1.25))
                b["pos"] = [round(x, 1), round(g + 190.0, 1), round(z, 1)]
                b["size"] = [round(b["size"][0] * s, 1), b["size"][1],
                             round(b["size"][2] * s, 1)]
                b["id"] = _uid()
                self.world["brushes"].append(b)
                placed += 1
        self.report(f"{placed} trees scattered over the new land")

    # -- all of it ---------------------------------------------------------
    def run(self):
        self.plan()
        self._piece_index()
        self.build_heightmap()
        self.build_terrain()
        self.move_objects()
        self.seat_ground_decals()
        self.merge_water()
        self.build_shrine()
        self.add_wilds()
        self.scatter_trees()
        self.world["_miniwind_world"] = {"expanded": True, "spread": SPREAD,
                                         "chunks": self.chunks}
        return self.world


def dump(world, path):
    """Write the map as the editor does (indented), with the bulky terrain
    arrays kept compact."""
    td = world["terrain_data"]
    sculpt = td.pop("sculpt_offsets", [])
    blob = td.pop("heightmap_blob", None)
    text = json.dumps(world, indent=4)
    marker = '"terrain_data": {'
    head, tail = text.split(marker, 1)
    extra = '\n        "sculpt_offsets": ' + json.dumps(sculpt, separators=(",", ":")) + ","
    if blob is not None:
        extra += '\n        "heightmap_blob": "' + blob + '",'
    text = head + marker + extra + tail
    td["sculpt_offsets"] = sculpt
    if blob is not None:
        td["heightmap_blob"] = blob
    with open(path, "w", newline="\r\n") as f:
        f.write(text)


def preview(world, path, size=1100):
    """A top-down picture of the world: ground, water, sites."""
    from PIL import Image, ImageDraw
    terrain = _terrain(world["terrain_data"],
                       heightmap=_load_heightmap(world["terrain_data"]))
    (lo, hi), _ = terrain.get_terrain_bounds()
    axis = np.linspace(lo, hi, size, dtype=np.float32)
    X, Z = np.meshgrid(axis, axis)
    H = _heights(terrain, X.ravel(), Z.ravel()).reshape(size, size)
    g = np.clip((H - 100.0) / 1900.0, 0, 1)
    shade = np.clip(1.0 + np.gradient(H, axis=1) / 60.0, 0.6, 1.3)
    rgb = np.stack([60 + g * 190, 95 + g * 150, 50 + g * 190], -1) * shade[..., None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    def px(x, z):
        return ((x - lo) / (hi - lo) * size, (z - lo) / (hi - lo) * size)
    for b in world["brushes"]:
        x, _, z = b["pos"]
        if b.get("water_plane"):
            a = px(x - b["size"][0] / 2, z - b["size"][2] / 2)
            c = px(x + b["size"][0] / 2, z + b["size"][2] / 2)
            d.rectangle([a, c], fill=(40, 90, 200))
        elif Expander._is_tree(b):
            d.point(px(x, z), fill=(25, 70, 25))
        else:
            d.point(px(x, z), fill=(120, 80, 60))
    colours = {"npc": (255, 255, 255), "creature": (230, 60, 60),
               "spellbook": (255, 0, 255), "playerstart": (0, 255, 255)}
    for t in world["things"]:
        x, _, z = t["pos"]
        c = colours.get(t["type"])
        if c:
            a = px(x, z)
            d.ellipse([a[0] - 2, a[1] - 2, a[0] + 2, a[1] + 2], fill=c)
        p = t.get("properties", {})
        if t["type"] == "marker" and p.get("marker_kind") == "location":
            a = px(x, z)
            d.text((a[0] + 4, a[1] - 6), p.get("place_name", ""), fill=(255, 255, 190))
    img.save(path)


def _load_heightmap(td):
    blob = td.get("heightmap_blob")
    if not blob:
        return None
    return np.load(io.BytesIO(base64.b64decode(blob)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?", default=MAP)
    ap.add_argument("-o", "--out", help="write here instead of over the input")
    ap.add_argument("--chunks", type=int, default=40,
                    help="terrain chunks per side (default 40)")
    ap.add_argument("--preview", help="also write a top-down PNG of the result")
    ap.add_argument("--force", action="store_true",
                    help="expand a map this tool has already expanded")
    args = ap.parse_args()
    with open(args.map) as f:
        world = json.load(f)
    if world.get("_miniwind_world", {}).get("expanded") and not args.force:
        raise SystemExit(f"{args.map} is already expanded (use --force to do it again)")
    Expander(world, chunks=args.chunks).run()
    out = args.out or args.map
    dump(world, out)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB, "
          f"{len(world['brushes'])} brushes, {len(world['things'])} things)")
    if args.preview:
        preview(world, args.preview)
        print(f"preview {args.preview}")


if __name__ == "__main__":
    main()
