"""Make the road test map: the world map with roads between its settlements.

    python -m game.tools.make_road_map [source.json] [out.json] [preview.png]

Reads the world (``maps/village_walled_source.json`` by default) and writes a
copy (``maps/village_roads_test.json``) in which:

* **Settlements** are the location markers the living world itself calls a
  town, hamlet, inn or farm (:meth:`game.living.world.LivingWorld._classify_places`).
* **Roads** join them: a minimum spanning tree plus a short second link where
  that makes a loop. Each is routed by A* over the terrain so it goes *round*
  mountains (high ground above the settlements' level is very costly, cliffs
  all but impassable), keeps off open water and reuses road already laid, so
  forks become junctions. A smooth noise field in the cost and a gentle
  sideways wander make roads meander the way Morrowind's and Oblivion's do,
  rather than ruling lines between towns.
* **Terrain stamping** paints ``track.jpg`` along every road into the
  terrain's baked texture paint (``Terrain.stamp_texture_at``), so the road is
  part of the saved ground and grass does not grow on it.
* **PathNodes** named ``ROAD_0001``... stand along each road on the ground,
  every :data:`NODE_SPACING` units, merged where roads meet. Each node's
  ``next_node`` lists every neighbour, comma separated: the two-way
  navigation graph :mod:`game.road_nav` and :mod:`game.living.roads` walk.

* **Trees are canopies**: MiniWind is top down, so every tree brush is a flat
  8-unit slab floating 230 above the highest ground beneath it, over the
  player and every actor sprite and under the closest camera.
* **A south-west desert** over 30% of the map, blending through steppe into
  the green, with low dunes; and **a dense forest** of tree brushes of many
  sizes on open lowland, kept clear of roads, buildings and everything else.
* **Terrain realism**: craggier ridged mountains and gently rolling lowlands,
  baked into the heightmap. The terrain is untouched within
  :data:`PROTECT_IN` of every thing, brush footprint and settlement, and the
  tool refuses to save if the ground moves by more than 0.01 units under
  anything placed. Nothing can end up inside or under the terrain. Roads are
  routed afterwards, on the final ground.

It also renders a top-down preview of the result (``docs/screenshots/``).
Deterministic: the same source always gives the same map, ids included.
"""

from __future__ import annotations

import copy
import heapq
import json
import math
import os
import sys
import uuid
from types import SimpleNamespace

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE = os.path.join(ROOT, "maps", "village_walled_source.json")
OUT = os.path.join(ROOT, "maps", "village_roads_test.json")
PREVIEW = os.path.join(ROOT, "docs", "screenshots", "road-test-map.png")

#: Place kinds that count as settlements (roads join these).
SETTLEMENTS = ("town", "hamlet", "inn", "farm")
#: Routing grid cell (world units).
CELL = 256.0
#: A second link to a settlement's next-nearest neighbour, if no longer than this.
LOOP_MAX = 9000.0
#: Slope cost: a step costs length * (1 + SLOPE_COST * (rise/run)^2); steeper
#: than MAX_SLOPE is all but impassable, so roads never scale a cliff.
SLOPE_COST = 90.0
MAX_SLOPE = 0.35
STEEP_COST = 400.0
#: Mountains: ground above the settlements' own level costs up to
#: 1 + HIGH_COST times as much, so roads go round high ground, through the
#: valleys and passes, as Morrowind's and Oblivion's do.
HIGH_COST = 30.0
HIGH_ABOVE = 40.0
#: Meander: a smooth noise field (features about MEANDER_SCALE across)
#: scales each step's cost by 1 +/- MEANDER_COST, so a road bends round
#: invisible "soft ground" instead of ruling a line between towns.
MEANDER_SCALE = 3200.0
MEANDER_COST = 0.8
#: Then a gentle sideways wander along the routed line: up to WANDER world
#: units either side, over about WANDER_LENGTH, easing to nothing at each end.
WANDER = 230.0
WANDER_LENGTH = 1500.0
SEED = 1979
#: Walking on road already laid costs this fraction, so roads share and fork.
REUSE = 0.55
#: Stepping through open water costs this many times more.
WATER_COST = 40.0
#: Road paint: brush radius, spacing between stamps and edge softness.
ROAD_TEXTURE = "assets/textures/track.jpg"
ROAD_RADIUS = 96.0
STAMP_SPACING = 56.0
STAMP_FEATHER = 0.55
#: PathNodes: spacing along a road and the merge distance at junctions.
NODE_SPACING = 640.0
NODE_MERGE = 320.0
NODE_LIFT = 24.0
#: Terrain realism (world units): craggy ridged detail on mountains, up to
#: RIDGE_AMP, scaled by how far above the settlements' level the ground is;
#: gentle rolling relief of LOW_AMP on the lowlands.
RIDGE_AMP = 340.0
LOW_AMP = 34.0
#: Nothing placed is ever touched: the terrain is unchanged within
#: PROTECT_IN of every thing, every brush's footprint and every settlement,
#: and only fully reshaped beyond PROTECT_OUT.
PROTECT_IN = 320.0
PROTECT_OUT = 1100.0
#: The south-west desert: a quarter-disc from that corner covering
#: DESERT_AREA of the map, its edge wobbled by noise and blended over a band
#: DESERT_BAND (fraction of the map's width) wide, through steppe into green.
DESERT_AREA = 0.30
DESERT_BAND = 0.07
DESERT_WOBBLE = 0.05
DUNE_AMP = 48.0
DUNE_LENGTH = 900.0
#: The dense forest: radius, spacing between trunks, canopy sizes, and how
#: far trees keep from roads, settlements, water and other brushes.
FOREST_RADIUS = 5600.0
FOREST_SPACING = 175.0
TREE_SIZES = (110.0, 330.0)
#: MiniWind is top down: a tree is its canopy, a flat TREE_THICKNESS slab
#: floating TREE_CLEARANCE above the highest ground under it -- clear of the
#: player (100 tall) and the tallest actor sprite (210), and well under the
#: closest camera (300 above the player).
TREE_THICKNESS = 8.0
TREE_CLEARANCE = 230.0
CLEAR_ROAD = 230.0
CLEAR_BRUSH = 160.0
FOREST_TREES = {"broadleaf": ("tree01.png", "tree02.png", "tree03.png", "tree04.png",
                              "tree05.png", "tree06.png", "tree07.png", "trees0.png"),
                "pine": ("pine01.png", "pine02.png"), "willow": ("willow01.png",)}
ID_NAMESPACE = uuid.UUID("7d9b2e3e-58e4-4a6f-9b0a-6e2f1f4c1a77")


# --------------------------------------------------------------------- input
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def settlements(data):
    """``{key: place}`` for the settlements, as the living world classifies them."""
    from game.living.world import LivingWorld
    things = [SimpleNamespace(properties=t.get("properties", {}), pos=t.get("pos", [0, 0, 0]))
              for t in data["things"]]
    places = LivingWorld._classify_places(None, things)
    return {k: p for k, p in sorted(places.items()) if p["kind"] in SETTLEMENTS}


def terrain_of(data):
    from engine.terrain import Terrain
    t = Terrain()
    t.from_dict(data["terrain_data"])
    return t


def water_rects(data):
    out = []
    for b in data["brushes"]:
        if b.get("shader") == "Water" or b.get("water_plane"):
            (x, _y, z), (sx, _sy, sz) = b["pos"], b["size"]
            out.append((x - sx / 2, z - sz / 2, x + sx / 2, z + sz / 2))
    return out


# ------------------------------------------------------------------- terrain
def _pixel_world(terrain):
    """World x (per column) and z (per row) of every heightmap pixel."""
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    rows, cols = terrain.heightmap_data.shape
    return (min_x + np.arange(cols) * (max_x - min_x) / (cols - 1),
            min_z + np.arange(rows) * (max_z - min_z) / (rows - 1))


def protection(terrain, data, places):
    """Per-pixel weight 0..1: 0 wherever anything placed could be affected.

    The distance from each heightmap pixel to the nearest thing, brush
    footprint or settlement, eased from 0 at PROTECT_IN to 1 at PROTECT_OUT.
    PROTECT_IN exceeds a pixel's diagonal, so every pixel a protected point
    is interpolated from has weight 0: its ground cannot move at all."""
    xs, zs = _pixel_world(terrain)
    step = float(xs[1] - xs[0])
    dist = np.full((len(zs), len(xs)), np.inf)
    reach = PROTECT_OUT

    def mark(cx, cz, hx, hz):
        c0 = max(0, int((cx - hx - reach - xs[0]) // step))
        c1 = min(len(xs) - 1, int((cx + hx + reach - xs[0]) // step) + 1)
        r0 = max(0, int((cz - hz - reach - zs[0]) // step))
        r1 = min(len(zs) - 1, int((cz + hz + reach - zs[0]) // step) + 1)
        if c1 < c0 or r1 < r0:
            return
        dx = np.maximum(np.abs(xs[c0:c1 + 1] - cx) - hx, 0.0)[None, :]
        dz = np.maximum(np.abs(zs[r0:r1 + 1] - cz) - hz, 0.0)[:, None]
        window = dist[r0:r1 + 1, c0:c1 + 1]
        np.minimum(window, np.sqrt(dx * dx + dz * dz), out=window)

    for t in data["things"]:
        pos = t.get("pos") or (0, 0, 0)
        mark(float(pos[0]), float(pos[2]), 0.0, 0.0)
    for b in data["brushes"]:
        (x, _y, z), (sx, _sy, sz) = b["pos"], b["size"]
        mark(float(x), float(z), abs(float(sx)) / 2, abs(float(sz)) / 2)
    for p in places:
        r = float(p.get("radius", 900.0))
        mark(p["x"], p["z"], r * 0.7, r * 0.7)
    t = np.clip((dist - PROTECT_IN) / (PROTECT_OUT - PROTECT_IN), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ridged(shape, scale, seed, octaves=4):
    """Ridged multifractal in [0, 1]: sharp crests and creased gullies."""
    out = np.zeros(shape)
    total = 0.0
    for o in range(octaves):
        n = noise_field(shape[1], shape[0], scale / 2 ** o, seed + o).T
        r = 1.0 - np.abs(2.0 * n - 1.0)
        weight = 0.55 ** o
        out += weight * r * r
        total += weight
    return out / total


def desert_weight(terrain, xs, zs):
    """Desert coverage 0..1 at world points (arrays), smooth at the edge."""
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    width = max_x - min_x
    u = (np.asarray(xs, float) - min_x) / width
    v = (np.asarray(zs, float) - min_z) / (max_z - min_z)
    r = np.hypot(u, v)
    reach = math.sqrt(4.0 * DESERT_AREA / math.pi)
    # A wobbling edge: low-frequency waves round the arc.
    ang = np.arctan2(v, u)
    wobble = DESERT_WOBBLE * (0.6 * np.sin(ang * 7.0 + 1.3) + 0.4 * np.sin(ang * 17.0 + 4.1))
    t = np.clip((reach + wobble + DESERT_BAND - r) / (2 * DESERT_BAND), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def paint_desert(terrain):
    """Desert (R) over the biome map's south-west; snow, swamp and wheat
    fade out beneath it so the blend runs sand, steppe, meadow."""
    m = terrain.biome_map
    if m is None:
        m = np.zeros((1024, 1024, 4), np.uint8)
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    rows, cols = m.shape[:2]
    xs = min_x + (np.arange(cols) + 0.5) * (max_x - min_x) / cols
    zs = min_z + (np.arange(rows) + 0.5) * (max_z - min_z) / rows
    gx, gz = np.meshgrid(xs, zs)
    w = desert_weight(terrain, gx, gz)
    out = m.astype(np.float32)
    out[..., 0] = np.maximum(out[..., 0], w * 255.0)
    for ch in (1, 2, 3):
        out[..., ch] *= (1.0 - w)
    terrain.set_biome_map(np.clip(out + 0.5, 0, 255).astype(np.uint8))
    return float((w > 0.5).mean())


def realism(terrain, data, places):
    """Craggier mountains and gently rolling lowlands, away from anything placed.

    Returns ``(protected, max_change)``. Only heightmap pixels with
    protection weight above zero change."""
    hm = terrain.heightmap_data.astype(np.float64)
    xs, zs = _pixel_world(terrain)
    gx, gz = np.meshgrid(xs, zs)
    ground = terrain._get_heights_batch(gx.ravel().astype(np.float32),
                                        gz.ravel().astype(np.float32)).reshape(hm.shape)
    homes = [float(terrain.get_height_at(p["x"], p["z"])) for p in places] or [float(np.median(ground))]
    base = float(np.percentile(homes, 80)) + 80.0
    top = max(base + 1.0, float(np.percentile(ground, 99)))
    mountain = np.clip((ground - base) / (top - base), 0.0, 1.0) ** 0.8
    crags = ridged(hm.shape, 26.0, SEED + 11)            # ~2.8 km features down to ~350 m
    rolling = noise_field(hm.shape[1], hm.shape[0], 14.0, SEED + 23).T
    sand = desert_weight(terrain, gx, gz)
    # Dunes: long crests across the prevailing wind, bent by noise.
    phase = (gx * 0.8 + gz * 0.6) / DUNE_LENGTH * 2 * math.pi + 6.0 * rolling
    dunes = DUNE_AMP * ((0.5 + 0.5 * np.sin(phase)) ** 2 - 0.35)
    delta = (mountain * RIDGE_AMP * (crags - 0.45)
             + (1.0 - mountain) * ((1.0 - sand) * LOW_AMP * (2.0 * rolling - 1.0) + sand * dunes))
    weight = protection(terrain, data, places)
    delta *= weight
    strength = float(terrain.heightmap_strength) * float(terrain.mesh_scale)
    terrain.heightmap_data = (hm + delta / strength).astype(terrain.heightmap_data.dtype)
    terrain.invalidate_height_range()
    return int((weight == 0).sum()), float(np.abs(delta).max())


def footprint_points(data):
    """Where something placed meets the ground: every thing, and a grid over
    every brush's footprint (its corners and edges included)."""
    pts = [(float(t["pos"][0]), float(t["pos"][2])) for t in data["things"] if t.get("pos")]
    for b in data["brushes"]:
        (x, _y, z), (sx, _sy, sz) = b["pos"], b["size"]
        hx, hz = abs(float(sx)) / 2, abs(float(sz)) / 2
        nx, nz = max(2, int(2 * hx // 64) + 2), max(2, int(2 * hz // 64) + 2)
        for u in np.linspace(-hx, hx, nx):
            for v in np.linspace(-hz, hz, nz):
                pts.append((float(x) + u, float(z) + v))
    return np.array(pts, dtype=np.float32)


# -------------------------------------------------------------------- forest
#: What grows in the desert (enliven_world's desert kinds): dead trees and
#: scrub on the sand, palms at an oasis.
DESERT_TREES = ("deadtree01.png", "scrub01.png", "scrub02.png")
OASIS_TREES = ("palm01.png",)


def dry_out_trees(terrain, data, grid):
    """Existing trees now standing in desert become desert kinds.

    Only the canopy texture changes: every brush keeps its place and size."""
    rng = np.random.default_rng(SEED + 47)
    changed = 0
    for b in data["brushes"]:
        if not _is_tree(b):
            continue
        x, _y, z = b["pos"]
        w = float(desert_weight(terrain, [x], [z])[0])
        if w < 0.35 or rng.random() > min(1.0, (w - 0.35) / 0.3):
            continue
        wet = any(grid.water[grid.cell(x + dx, z + dz)]
                  for dx in (-600, 0, 600) for dz in (-600, 0, 600))
        names = OASIS_TREES if wet else DESERT_TREES
        b["textures"] = dict(b["textures"], top=names[int(rng.integers(len(names)))])
        changed += 1
    return changed
def _is_tree(b):
    from game.tools.enliven_world import _is_tree as is_tree
    return is_tree(b)


def plant_forest(terrain, data, places, roads, grid):
    """One dense forest on open green lowland, on the final ground.

    The centre is the candidate with the most free ground round it, away from
    the desert, mountains and settlements. Trees keep clear of roads,
    settlements, water, buildings and existing trees, so nothing is buried
    in foliage and no path is blocked."""
    rng = np.random.default_rng(SEED + 41)
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    road_pts = np.array([p for r in roads for p in resample(r["points"], 120.0)])
    solid = [b for b in data["brushes"] if not _is_tree(b)]
    trees = np.array([(b["pos"][0], b["pos"][2]) for b in data["brushes"] if _is_tree(b)] or [(1e9, 1e9)])
    homes = np.array([(p["x"], p["z"], p.get("radius", 900.0)) for p in places])

    def ok_points(X, Z):
        keep = np.ones(len(X), bool)
        keep &= desert_weight(terrain, X, Z) < 0.05
        for hx, hz, hr in homes:
            keep &= np.hypot(X - hx, Z - hz) > hr + 400.0
        cells = [grid.cell(x, z) for x, z in zip(X, Z)]
        keep &= np.array([not grid.water[c] and grid.high[c] < 1.6 for c in cells])
        return keep

    best = None
    for cx in np.linspace(min_x + 9000, max_x - 9000, 15):
        for cz in np.linspace(min_z + 9000, max_z - 9000, 15):
            a = rng.uniform(0, 2 * math.pi, 160)
            r = FOREST_RADIUS * np.sqrt(rng.uniform(0, 1, 160))
            X, Z = cx + r * np.cos(a), cz + r * np.sin(a)
            score = ok_points(X, Z).mean()
            if best is None or score > best[0]:
                best = (score, cx, cz)
    _score, cx, cz = best
    # A jittered grid inside a noisy blob.
    g = np.arange(-FOREST_RADIUS, FOREST_RADIUS, FOREST_SPACING)
    X, Z = np.meshgrid(cx + g, cz + g)
    X = X.ravel() + rng.uniform(-0.45, 0.45, X.size) * FOREST_SPACING
    Z = Z.ravel() + rng.uniform(-0.45, 0.45, Z.size) * FOREST_SPACING
    # An organic outline: noise decides where the wood ends, and it thins
    # out over its last stretch rather than stopping at a line.
    n = len(g)
    shape = noise_field(n, n, n / 5.0, SEED + 43).T.ravel()
    reach = np.hypot(X - cx, Z - cz) / FOREST_RADIUS
    edge = 0.55 + 0.5 * shape
    density = np.clip((edge - reach) / 0.18, 0.0, 1.0)
    inside = rng.random(X.size) < density
    X, Z = X[inside], Z[inside]
    keep = ok_points(X, Z)
    for i in np.nonzero(keep)[0]:
        x, z = X[i], Z[i]
        if len(road_pts) and np.min(np.hypot(road_pts[:, 0] - x, road_pts[:, 1] - z)) < CLEAR_ROAD:
            keep[i] = False
            continue
        if np.min(np.hypot(trees[:, 0] - x, trees[:, 1] - z)) < 110.0:
            keep[i] = False
    X, Z = X[keep], Z[keep]
    keep = np.ones(len(X), bool)
    for b in solid:
        (bx, _y, bz), (sx, _sy, sz) = b["pos"], b["size"]
        hx, hz = abs(sx) / 2 + CLEAR_BRUSH, abs(sz) / 2 + CLEAR_BRUSH
        if abs(bx - cx) > FOREST_RADIUS + hx or abs(bz - cz) > FOREST_RADIUS + hz:
            continue
        keep &= ~((np.abs(X - bx) < hx) & (np.abs(Z - bz) < hz))
    for t in data["things"]:
        x, _y, z = t["pos"]
        keep &= np.hypot(X - x, Z - z) > CLEAR_BRUSH
    X, Z = X[keep], Z[keep]
    ground = terrain._get_heights_batch(X.astype(np.float32), Z.astype(np.float32))
    proto = next(b for b in data["brushes"] if _is_tree(b))
    counts = {}
    for k in range(len(X)):
        near_water = grid.water[grid.cell(X[k] + 300, Z[k])] or grid.water[grid.cell(X[k] - 300, Z[k])]
        roll = rng.random()
        kind = "willow" if near_water else ("pine" if roll < 0.22 or grid.high[grid.cell(X[k], Z[k])] > 1.15
                                            else "broadleaf")
        names = FOREST_TREES[kind]
        tex = names[int(rng.integers(len(names)))]
        # Mostly mid-sized, a few saplings and a few great old trees.
        size = float(np.clip(rng.lognormal(math.log(190.0), 0.3), *TREE_SIZES))
        data["brushes"].append({
            "pos": [round(float(X[k]), 1), round(float(ground[k]) + TREE_CLEARANCE, 1), round(float(Z[k]), 1)],
            "size": [round(size, 1), TREE_THICKNESS, round(size, 1)],
            "textures": {**{f: "nodraw.jpg" for f in ("north", "south", "east", "west", "down")}, "top": tex},
            "uv_scale": copy.deepcopy(proto.get("uv_scale", {})),
            "id": str(uuid.uuid5(ID_NAMESPACE, f"forest-{k}"))})
        counts[kind] = counts.get(kind, 0) + 1
    return dict(centre=(round(cx), round(cz)), **counts)


def seat_trees(terrain, data):
    """Every tree a flat TREE_THICKNESS canopy, its underside TREE_CLEARANCE
    above the highest ground anywhere beneath it (sampled across the whole
    footprint, so a canopy on a slope still clears whoever walks under its
    uphill edge). Returns how many trees were seated."""
    trees = [b for b in data["brushes"] if _is_tree(b)]
    if not trees:
        return 0
    k = np.linspace(-0.5, 0.5, 9)
    du, dv = (a.ravel() for a in np.meshgrid(k, k))
    X = np.concatenate([b["pos"][0] + du * abs(b["size"][0]) for b in trees]).astype(np.float32)
    Z = np.concatenate([b["pos"][2] + dv * abs(b["size"][2]) for b in trees]).astype(np.float32)
    H = terrain._get_heights_batch(X, Z).reshape(len(trees), len(k), len(k))
    # Between samples the ground can rise by about one step's difference
    # more: add the steepest step, so a canopy on a slope never dips.
    rise = np.maximum(np.abs(np.diff(H, axis=1)).max(axis=(1, 2)),
                      np.abs(np.diff(H, axis=2)).max(axis=(1, 2)))
    top = H.max(axis=(1, 2)) + rise
    for b, ground in zip(trees, top):
        b["size"][1] = TREE_THICKNESS
        b["pos"][1] = round(float(ground) + TREE_CLEARANCE + TREE_THICKNESS / 2, 1)
    return len(trees)


# ------------------------------------------------------------------- routing
def noise_field(nx, nz, scale_cells, seed):
    """Smooth value noise in [0, 1]: two octaves of bilinearly upsampled randoms."""
    rng = np.random.default_rng(seed)
    out = np.zeros((nx, nz))
    for octave, weight in ((1.0, 0.7), (0.5, 0.3)):
        step = max(2.0, scale_cells * octave)
        cx, cz = int(nx / step) + 3, int(nz / step) + 3
        coarse = rng.random((cx, cz))
        fx = np.arange(nx) / step
        fz = np.arange(nz) / step
        x0, z0 = fx.astype(int), fz.astype(int)
        tx = (fx - x0)[:, None]
        tz = (fz - z0)[None, :]
        tx, tz = tx * tx * (3 - 2 * tx), tz * tz * (3 - 2 * tz)
        a = coarse[x0][:, z0]
        b = coarse[x0 + 1][:, z0]
        c = coarse[x0][:, z0 + 1]
        d = coarse[x0 + 1][:, z0 + 1]
        out += weight * ((a * (1 - tx) + b * tx) * (1 - tz) + (c * (1 - tx) + d * tx) * tz)
    return out


class Grid:
    def __init__(self, terrain, water, places=()):
        size = terrain.chunk_size
        self.x0 = terrain.offset_x + terrain.min_chunk_x * size
        self.z0 = terrain.offset_z + terrain.min_chunk_z * size
        self.nx = int((terrain.max_chunk_x + 1 - terrain.min_chunk_x) * size // CELL)
        self.nz = int((terrain.max_chunk_z + 1 - terrain.min_chunk_z) * size // CELL)
        xs = self.x0 + (np.arange(self.nx) + 0.5) * CELL
        zs = self.z0 + (np.arange(self.nz) + 0.5) * CELL
        gx, gz = np.meshgrid(xs, zs, indexing="ij")
        self.h = terrain._get_heights_batch(gx.ravel(), gz.ravel()).reshape(self.nx, self.nz)
        self.water = np.zeros((self.nx, self.nz), bool)
        for x0, z0, x1, z1 in water:
            self.water |= (gx >= x0) & (gx <= x1) & (gz >= z0) & (gz <= z1)
        self.used = np.zeros((self.nx, self.nz), bool)
        # Mountains, relative to where people actually live.
        homes = [float(terrain.get_height_at(p["x"], p["z"])) for p in places] or [float(np.median(self.h))]
        base = float(np.percentile(homes, 80)) + HIGH_ABOVE
        top = max(base + 1.0, float(np.percentile(self.h, 99)))
        self.high = 1.0 + HIGH_COST * np.clip((self.h - base) / (top - base), 0.0, 1.0) ** 1.5
        self.meander = 1.0 + MEANDER_COST * (2.0 * noise_field(self.nx, self.nz, MEANDER_SCALE / CELL, SEED) - 1.0)
        self.floor = float(self.meander.min()) * REUSE      # cheapest possible step factor

    def cell(self, x, z):
        return (min(self.nx - 1, max(0, int((x - self.x0) // CELL))),
                min(self.nz - 1, max(0, int((z - self.z0) // CELL))))

    def centre(self, c):
        return (self.x0 + (c[0] + 0.5) * CELL, self.z0 + (c[1] + 0.5) * CELL)

    def route(self, a, b):
        """A* from cell *a* to cell *b*: gentle, dry, sharing laid road."""
        h, water, used = self.h, self.water, self.used
        high, meander, floor = self.high, self.meander, self.floor
        steps = [(dx, dz, math.hypot(dx, dz) * CELL) for dx in (-1, 0, 1)
                 for dz in (-1, 0, 1) if dx or dz]
        best = {a: 0.0}
        came = {}
        heap = [(0.0, a)]
        bx, bz = b
        while heap:
            _f, c = heapq.heappop(heap)
            if c == b:
                break
            g = best[c]
            cx, cz = c
            for dx, dz, run in steps:
                nx, nz = cx + dx, cz + dz
                if not (0 <= nx < self.nx and 0 <= nz < self.nz):
                    continue
                slope = abs(float(h[nx, nz]) - float(h[cx, cz])) / run
                cost = run * (1.0 + SLOPE_COST * slope * slope) * high[nx, nz] * meander[nx, nz]
                if slope > MAX_SLOPE:
                    cost *= STEEP_COST
                if water[nx, nz]:
                    cost *= WATER_COST
                if used[nx, nz]:
                    cost *= REUSE
                ng = g + cost
                n = (nx, nz)
                if ng < best.get(n, math.inf):
                    best[n] = ng
                    came[n] = c
                    # Admissible: the cheapest a step can be is on laid road.
                    heapq.heappush(heap, (ng + floor * CELL * math.hypot(nx - bx, nz - bz), n))
        path = [b]
        while path[-1] != a:
            path.append(came[path[-1]])
        path.reverse()
        for c in path:
            used[c] = True
        return path


def links(places):
    """Minimum spanning tree over the settlements, plus short loops."""
    keys = list(places)
    pos = {k: (places[k]["x"], places[k]["z"]) for k in keys}
    d = lambda a, b: math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
    joined, edges = {keys[0]}, []
    while len(joined) < len(keys):
        a, b = min(((a, b) for a in joined for b in keys if b not in joined), key=lambda e: d(*e))
        edges.append((a, b))
        joined.add(b)
    have = {frozenset(e) for e in edges}
    for a in keys:
        near = sorted((b for b in keys if b != a), key=lambda b: d(a, b))[:2]
        for b in near:
            if frozenset((a, b)) not in have and d(a, b) <= LOOP_MAX:
                edges.append((a, b))
                have.add(frozenset((a, b)))
                break
    # Shortest first, so long roads find and reuse the short ones.
    return sorted(edges, key=lambda e: d(*e))


def smooth(points, rounds=2):
    """Chaikin corner cutting, keeping the endpoints."""
    for _ in range(rounds):
        if len(points) < 3:
            return points
        out = [points[0]]
        for p, q in zip(points, points[1:]):
            out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
            out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
        out.append(points[-1])
        points = out
    return points


def wander(points, grid, seed):
    """Sway the line gently side to side, easing to nothing at both ends, and
    never onto steeper or higher ground than the route itself chose."""
    pts = resample(points, CELL * 0.5)
    if len(pts) < 4:
        return points
    rng = np.random.default_rng(seed)
    total = (len(pts) - 1) * CELL * 0.5
    knots = max(2, int(total / WANDER_LENGTH) + 2)
    offsets = rng.uniform(-1.0, 1.0, knots)
    out = []
    for i, (x, z) in enumerate(pts):
        s = i * CELL * 0.5
        f = s / WANDER_LENGTH
        k = min(knots - 2, int(f))
        t = f - k
        t = t * t * (3 - 2 * t)
        off = WANDER * (offsets[k] * (1 - t) + offsets[k + 1] * t)
        ease = min(1.0, s / 600.0, (total - s) / 600.0)
        p, q = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        dx, dz = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dz) or 1.0
        nx_, nz_ = -dz / length, dx / length
        cand = (x + nx_ * off * ease, z + nz_ * off * ease)
        here, there = grid.cell(x, z), grid.cell(*cand)
        if grid.high[there] > grid.high[here] * 1.05 or grid.water[there]:
            cand = (x, z)
        out.append(cand)
    return out


def resample(points, spacing):
    """Points along the polyline every *spacing*, endpoints included."""
    out = [points[0]]
    carry = 0.0
    for p, q in zip(points, points[1:]):
        seg = math.hypot(q[0] - p[0], q[1] - p[1])
        s = spacing - carry
        while s < seg:
            t = s / seg
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
            s += spacing
        carry = seg - (s - spacing)
    if math.hypot(out[-1][0] - points[-1][0], out[-1][1] - points[-1][1]) > spacing * 0.3:
        out.append(points[-1])
    else:
        out[-1] = points[-1]
    return out


# ------------------------------------------------------------------- building
def build_roads(places, grid):
    roads = []
    for a, b in links(places):
        pa, pb = places[a], places[b]
        cells = grid.route(grid.cell(pa["x"], pa["z"]), grid.cell(pb["x"], pb["z"]))
        pts = [(pa["x"], pa["z"])] + [grid.centre(c) for c in cells[1:-1]] + [(pb["x"], pb["z"])]
        seed = SEED + sum(map(ord, a + b))
        roads.append(dict(ends=(a, b), points=smooth(wander(smooth(pts, 2), grid, seed), 2)))
    return roads


def stamp_roads(terrain, roads):
    texture = os.path.join(ROOT, ROAD_TEXTURE)
    count = 0
    for road in roads:
        pts = resample(road["points"], STAMP_SPACING)
        for i, (x, z) in enumerate(pts):
            p = pts[max(0, i - 1)]
            q = pts[min(len(pts) - 1, i + 1)]
            angle = math.atan2(q[0] - p[0], q[1] - p[1])
            if terrain.stamp_texture_at(x, z, ROAD_RADIUS, texture, feather=STAMP_FEATHER,
                                        opacity=0.92, angle=angle):
                count += 1
    return count


def place_nodes(terrain, roads):
    """Nodes along every road, merged where roads meet; ``(nodes, edges)``."""
    nodes, edges = [], set()

    def node_at(x, z):
        for i, (nx, nz) in enumerate(nodes):
            if math.hypot(nx - x, nz - z) <= NODE_MERGE:
                return i
        nodes.append((x, z))
        return len(nodes) - 1

    for road in roads:
        prev = None
        for x, z in resample(road["points"], NODE_SPACING):
            i = node_at(x, z)
            if prev is not None and prev != i:
                edges.add((min(prev, i), max(prev, i)))
            prev = i
    return nodes, sorted(edges)


def path_node_things(terrain, nodes, edges):
    names = [f"ROAD_{i + 1:04d}" for i in range(len(nodes))]
    nbrs = {i: [] for i in range(len(nodes))}
    for a, b in edges:
        nbrs[a].append(b)
        nbrs[b].append(a)
    out = []
    for i, (x, z) in enumerate(nodes):
        y = float(terrain.get_height_at(x, z)) + NODE_LIFT
        out.append({
            "type": "path_node", "pos": [round(x, 1), round(y, 1), round(z, 1)],
            "properties": {
                "type": "path_node", "name": names[i],
                "id": str(uuid.uuid5(ID_NAMESPACE, names[i])),
                "radius": 256.0, "show_radius": False, "affects_type": "both",
                "next_node": ",".join(names[j] for j in sorted(nbrs[i])),
                "wait_time": 0.0, "speed": 1.0},
            "io_connections": []})
    return out


# -------------------------------------------------------------------- preview
def render(path, grid, places, roads, nodes, edges, terrain=None, data=None, size=1400):
    from PIL import Image, ImageDraw, ImageFont
    h = grid.h
    lo, hi = np.percentile(h, 1), np.percentile(h, 99.5)
    n = np.clip((h - lo) / max(1e-6, hi - lo), 0, 1)
    # Hill shading from the north-west.
    gx, gz = np.gradient(h, CELL)
    shade = np.clip(0.75 - (gx * -0.7 + gz * -0.7) * 1.2, 0.35, 1.15)
    low = np.array([88, 132, 72]); mid = np.array([150, 160, 100]); top = np.array([235, 235, 235])
    rgb = np.where(n[..., None] < 0.6, low + (mid - low) * (n[..., None] / 0.6),
                   mid + (top - mid) * ((n[..., None] - 0.6) / 0.4))
    if terrain is not None and terrain.biome_map is not None:
        from engine import terrain_biomes as tb
        xs = grid.x0 + (np.arange(grid.nx) + 0.5) * CELL
        zs = grid.z0 + (np.arange(grid.nz) + 0.5) * CELL
        gx, gz = np.meshgrid(xs, zs, indexing="ij")
        w = tb.sample(terrain.biome_map, terrain.get_terrain_bounds(), gx.ravel(), gz.ravel())
        w = w.reshape(grid.nx, grid.nz, 4)
        for ch, colour in ((0, (214, 180, 118)), (1, (238, 242, 250)), (3, (206, 172, 80))):
            a = w[..., ch:ch + 1]
            rgb = rgb * (1 - a) + np.array(colour) * a
    rgb = rgb * shade[..., None]
    rgb[grid.water] = (60, 110, 170)
    # Grid is [x, z]; image rows run north (high z) to south.
    img = Image.fromarray(np.clip(np.transpose(rgb, (1, 0, 2))[::-1], 0, 255).astype(np.uint8))
    img = img.resize((size, size), Image.BILINEAR)
    draw = ImageDraw.Draw(img)
    sx = size / (grid.nx * CELL)
    sz = size / (grid.nz * CELL)
    to = lambda x, z: ((x - grid.x0) * sx, size - (z - grid.z0) * sz)
    if data is not None:
        for b in data["brushes"]:
            if _is_tree(b):
                u, v = to(b["pos"][0], b["pos"][2])
                r = max(1.0, b["size"][0] * sx * 0.5)
                draw.ellipse((u - r, v - r, u + r, v + r), fill=(28, 72, 30))
    for road in roads:
        draw.line([to(*p) for p in road["points"]], fill=(120, 72, 32), width=5, joint="curve")
        draw.line([to(*p) for p in road["points"]], fill=(214, 172, 108), width=3, joint="curve")
    for a, b in edges:
        draw.line([to(*nodes[a]), to(*nodes[b])], fill=(255, 240, 80), width=1)
    for x, z in nodes:
        u, v = to(x, z)
        draw.ellipse((u - 2, v - 2, u + 2, v + 2), fill=(255, 230, 40), outline=(60, 40, 0))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    colour = {"town": (200, 30, 30), "hamlet": (230, 120, 20), "inn": (120, 40, 160), "farm": (30, 110, 30)}
    for p in places.values():
        u, v = to(p["x"], p["z"])
        r = 7 if p["kind"] == "town" else 5
        draw.rectangle((u - r, v - r, u + r, v + r), fill=colour[p["kind"]], outline=(255, 255, 255))
        draw.text((u + r + 3, v - 9), p["name"], fill=(255, 255, 255), font=font,
                  stroke_width=2, stroke_fill=(0, 0, 0))
    legend = [("Town", colour["town"]), ("Hamlet", colour["hamlet"]), ("Inn", colour["inn"]),
              ("Farm", colour["farm"]), ("Road (stamped)", (214, 172, 108)),
              ("Desert", (214, 180, 118)), ("Tree brush", (28, 72, 30)),
              ("ROAD_* path node / link", (255, 230, 40))]
    draw.rectangle((10, 10, 260, 22 + 22 * len(legend)), fill=(0, 0, 0, 160))
    for i, (label, c) in enumerate(legend):
        y = 18 + 22 * i
        draw.rectangle((18, y, 32, y + 14), fill=c)
        draw.text((40, y - 2), label, fill=(255, 255, 255), font=font)
    draw.text((10, size - 26), f"{len(places)} settlements · {len(roads)} roads · "
              f"{len(nodes)} path nodes · {len(edges)} links", fill=(255, 255, 255), font=font,
              stroke_width=2, stroke_fill=(0, 0, 0))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


# ---------------------------------------------------------------------- main
def make(source=SOURCE, out=OUT, preview=PREVIEW):
    data = load(source)
    places = settlements(data)
    terrain = terrain_of(data)
    feet = footprint_points(data)
    before = terrain._get_heights_batch(feet[:, 0], feet[:, 1])
    desert = paint_desert(terrain)
    protected, reshaped = realism(terrain, data, list(places.values()))
    after = terrain._get_heights_batch(feet[:, 0], feet[:, 1])
    moved = float(np.abs(after - before).max()) if len(feet) else 0.0
    # Never let anything end up inside or under the terrain.
    if moved > 0.01:
        raise RuntimeError(f"terrain moved by {moved:.3f} under something placed")
    grid = Grid(terrain, water_rects(data), places.values())
    roads = build_roads(places, grid)
    stamps = stamp_roads(terrain, roads)
    nodes, edges = place_nodes(terrain, roads)
    dried = dry_out_trees(terrain, data, grid)
    forest = plant_forest(terrain, data, list(places.values()), roads, grid)
    seated = seat_trees(terrain, data)
    # Replace any earlier ROAD_* nodes; keep everything else (patrol chains too).
    data["things"] = [t for t in data["things"]
                      if not (t.get("properties", {}).get("type") == "path_node"
                              and str(t["properties"].get("name", "")).upper().startswith("ROAD_"))]
    data["things"] += path_node_things(terrain, nodes, edges)
    terrain_data = terrain.to_dict()
    # Keep every saved terrain field; add the baked road paint.
    data["terrain_data"] = dict(data["terrain_data"], texture_paint=terrain_data["texture_paint"],
                                texture_paint_resolution=terrain_data["texture_paint_resolution"],
                                heightmap_blob=terrain_data["heightmap_blob"],
                                biome_map_blob=terrain_data["biome_map_blob"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f)
    if preview:
        render(preview, grid, places, roads, nodes, edges, terrain, data)
    return dict(settlements=len(places), roads=len(roads), stamps=stamps,
                nodes=len(nodes), links=len(edges), protected_pixels=protected,
                max_reshape=round(reshaped, 1), checked_points=len(feet),
                max_change_under_placed=round(moved, 4), desert_fraction=round(desert, 3),
                forest=forest, desert_trees=dried, trees=seated)


if __name__ == "__main__":
    args = sys.argv[1:]
    print(make(*(args + [SOURCE, OUT, PREVIEW][len(args):])))
