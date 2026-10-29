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

It also renders a top-down preview of the result (``docs/screenshots/``).
Deterministic: the same source always gives the same map, ids included.
"""

from __future__ import annotations

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
def render(path, grid, places, roads, nodes, edges, size=1400):
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
    rgb = rgb * shade[..., None]
    rgb[grid.water] = (60, 110, 170)
    # Grid is [x, z]; image rows run north (high z) to south.
    img = Image.fromarray(np.clip(np.transpose(rgb, (1, 0, 2))[::-1], 0, 255).astype(np.uint8))
    img = img.resize((size, size), Image.BILINEAR)
    draw = ImageDraw.Draw(img)
    sx = size / (grid.nx * CELL)
    sz = size / (grid.nz * CELL)
    to = lambda x, z: ((x - grid.x0) * sx, size - (z - grid.z0) * sz)
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
    grid = Grid(terrain, water_rects(data), places.values())
    roads = build_roads(places, grid)
    stamps = stamp_roads(terrain, roads)
    nodes, edges = place_nodes(terrain, roads)
    # Replace any earlier ROAD_* nodes; keep everything else (patrol chains too).
    data["things"] = [t for t in data["things"]
                      if not (t.get("properties", {}).get("type") == "path_node"
                              and str(t["properties"].get("name", "")).upper().startswith("ROAD_"))]
    data["things"] += path_node_things(terrain, nodes, edges)
    terrain_data = terrain.to_dict()
    # Keep every saved terrain field; add the baked road paint.
    data["terrain_data"] = dict(data["terrain_data"], texture_paint=terrain_data["texture_paint"],
                                texture_paint_resolution=terrain_data["texture_paint_resolution"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f)
    if preview:
        render(preview, grid, places, roads, nodes, edges)
    return dict(settlements=len(places), roads=len(roads), stamps=stamps,
                nodes=len(nodes), links=len(edges))


if __name__ == "__main__":
    args = sys.argv[1:]
    print(make(*(args + [SOURCE, OUT, PREVIEW][len(args):])))
