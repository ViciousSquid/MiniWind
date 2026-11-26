"""
Take the mountain wall away from the world's edge, and make an oasis on it.

    python -m game.tools.reshape_edge [map.json]

Works on ``maps/miniwind_world.json`` in place:

* **No mountains round the edge.** ``expand_world`` raised a mountain wall
  round the whole edge of the world (its heightmap overlay) and
  ``make_road_map`` roughened it into crags. Both are worked out again,
  exactly as those tools made them, and taken off the heightmap, and the
  lowland's own surface (dunes in the desert, a gentle roll elsewhere) laid
  where the wall stood. The Emberpeaks, the south-western uplands and the
  pass are not part of the wall and stay. The ground under anything placed
  does not move (each cave mouth keeps a rocky knoll round it), no land is
  lowered into the sea, and every tree is re-seated on the new ground.
* **Sunfall Oasis.** At the south edge of the world (+z: the bottom of the
  world map), towards the west, in the desert: a lake sculpted into the
  sand, its basin open to the world's edge, one water brush over it whose
  southern side lies on the edge -- so the lake spills over the edge in a
  waterfall curtain (TerrainGL.draw_falls). Its water drifts gently towards
  the falls. Palms and a ring of green round it, and a location marker.

The map records what was done (``_miniwind_world``), so the tool refuses to
run twice. Afterwards re-render the overview pictures with
``python -m game.tools.render_maps``; the game repaints its own world map
and minimap from the changed map file by itself (game/ui/worldmap.py).
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
import uuid

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from game.tools import expand_world as ew          # noqa: E402
from game.tools import make_road_map as rm         # noqa: E402

MAP = os.path.join(ROOT, "maps", "miniwind_world.json")

#: Placed things keep the ground under them: unchanged within KEEP_IN of
#: one, eased to the full change by KEEP_OUT. A cave mouth keeps a knoll.
KEEP_IN, KEEP_OUT = 320.0, 1100.0
CAVE_KEEP_IN, CAVE_KEEP_OUT = 900.0, 2600.0
#: Land inside the sea's brush is never lowered below this far above it.
SEA_CLEARANCE = 40.0

#: The oasis: centre (x, z) and half-widths of its lake, which runs out to
#: the world's southern edge (+z).
OASIS_NAME = "Sunfall Oasis"
OASIS_X = -25500.0
OASIS_SHORE_IN = 1250.0          # the lake's centre, in from the edge
OASIS_RX, OASIS_RZ = 2100.0, 1800.0
#: A rocky islet on the brink that forks the falls, off-centre so one fall
#: is wider than the other: where along the lip (-1 west end, 1 east end),
#: its half-width along the edge and how far in it reaches, and how high
#: it stands above the water.
ISLET_AT = -0.3
ISLET_HALF, ISLET_IN = 230.0, 520.0
ISLET_HEIGHT = 80.0
OASIS_DEPTH = 100.0              # deepest below the surface
OASIS_FLOW_SPEED = 4.0
PALMS = 22
ID_NAMESPACE = uuid.UUID("6f3b8f3e-2d0b-4a8c-9e57-0a5e5ad9c0de")


def _uid(name):
    return str(uuid.uuid5(ID_NAMESPACE, name))


# --------------------------------------------------------------- the wall
def wall_fields(xs, zs, bounds):
    """``(with wall, without wall)``: expand_world's mountain overlay over
    the heightmap's pixels, worked out as it built it, with and without its
    wall round the edge (the Emberpeaks, the uplands, the pass and the
    shrine's basin in both)."""
    lo, hi = bounds
    X, Z = np.meshgrid(xs.astype(np.float32), zs.astype(np.float32))
    edge = np.maximum(np.abs(X), np.abs(Z))
    wall = ew._smoothstep(hi - 9000.0, hi - 1500.0, edge) * \
        (1200.0 + 900.0 * ew._ridged(X, Z, 5200.0, 11))
    sx, sz = ew.SHRINE
    d_shrine = np.hypot(X - sx, Z - sz)
    massif = ew._smoothstep(15500.0, 6500.0, d_shrine) * \
        (700.0 + 1500.0 * ew._ridged(X, Z, 3600.0, 23))
    uplands = ew._smoothstep(0.2, 0.75, ew._value_noise(X, Z, 9000.0, 31) * 0.5 + 0.5) * \
        ew._smoothstep(16000.0, 9000.0, np.hypot(X + 20000.0, Z - 18000.0)) * \
        (250.0 + 650.0 * ew._ridged(X, Z, 2600.0, 37))
    d_pass, along = ew._dist_to_polyline(X, Z, ew.PASS)
    road = ew.SHRINE_ELEVATION * ew._smoothstep(0.0, 1.0, along)
    valley = ew._smoothstep(1500.0, 500.0, d_pass)
    basin = ew._smoothstep(1400.0, 700.0, d_shrine)

    def shape(M):
        M = M * (1.0 - valley) + np.minimum(M, road) * valley
        return M * (1.0 - basin) + ew.SHRINE_ELEVATION * basin
    return (shape(np.maximum(np.maximum(wall, massif), uplands)),
            shape(np.maximum(massif, uplands)))


def keep_weight(xs, zs, data):
    """Per pixel 0..1: 0 where moving the ground would move something
    placed (trees aside: they are re-seated, and water: the sea's brush
    covers half the edge)."""
    step = float(xs[1] - xs[0])
    weight = np.ones((len(zs), len(xs)))

    def keep(cx, cz, hx, hz, k_in, k_out):
        c0 = max(0, int((cx - hx - k_out - xs[0]) // step))
        c1 = min(len(xs) - 1, int((cx + hx + k_out - xs[0]) // step) + 1)
        r0 = max(0, int((cz - hz - k_out - zs[0]) // step))
        r1 = min(len(zs) - 1, int((cz + hz + k_out - zs[0]) // step) + 1)
        if c1 < c0 or r1 < r0:
            return
        dx = np.maximum(np.abs(xs[c0:c1 + 1] - cx) - hx, 0.0)[None, :]
        dz = np.maximum(np.abs(zs[r0:r1 + 1] - cz) - hz, 0.0)[:, None]
        t = np.clip((np.sqrt(dx * dx + dz * dz) - k_in) / (k_out - k_in), 0.0, 1.0)
        window = weight[r0:r1 + 1, c0:c1 + 1]
        np.minimum(window, t * t * (3 - 2 * t), out=window)

    for t in data["things"]:
        pos = t.get("pos") or (0, 0, 0)
        props = t.get("properties") or {}
        cave = (props.get("type") or t.get("type")) == "levelchanger"
        keep(float(pos[0]), float(pos[2]), 0.0, 0.0,
             CAVE_KEEP_IN if cave else KEEP_IN, CAVE_KEEP_OUT if cave else KEEP_OUT)
    for b in data["brushes"]:
        if (rm._is_tree(b) or b.get("shader") == "Water" or b.get("water_plane")
                or b.get("is_trigger") or b.get("is_fog") or b.get("hidden")):
            continue                  # (a trigger volume spans the whole world)
        (x, _y, z), (sx, _sy, sz) = b["pos"], b["size"]
        keep(float(x), float(z), abs(float(sx)) / 2, abs(float(sz)) / 2, KEEP_IN, KEEP_OUT)
    return weight


def remove_wall(terrain, data):
    """Take the edge wall (and the crags laid on it) off the heightmap.
    Returns ``(pixels changed, deepest cut)``."""
    hm = terrain.heightmap_data.astype(np.float64)
    xs, zs = rm._pixel_world(terrain)
    (min_x, max_x), _ = terrain.get_terrain_bounds()
    with_wall, without = wall_fields(xs, zs, (min_x, max_x))
    # expand_world kept every site of its day clear of the mountains (it
    # scaled the overlay down round them); the share of the overlay that is
    # wall is the same either way, so that scaling cancels out here.
    share = np.where(with_wall > 1e-3, (with_wall - without) / np.maximum(with_wall, 1e-3), 0.0)
    share = np.clip(share, 0.0, 1.0)
    gx, gz = np.meshgrid(xs, zs)
    ground = terrain._get_raw_heights_batch(gx.ravel().astype(np.float32),
                                            gz.ravel().astype(np.float32)).reshape(hm.shape)
    # The overlay as it stands in the heightmap now -- expand_world's
    # mountains with make_road_map's realism() on them (crags on the
    # mountains, a roll or dunes on the lowland) -- loses its wall share,
    # crags and all, and the lowland's own surface takes its place.
    overlay = (hm - 0.5) * ew.HM_STRENGTH
    rolling = rm.noise_field(hm.shape[1], hm.shape[0], 14.0, rm.SEED + 23).T
    sand = rm.desert_weight(terrain, gx, gz)
    phase = (gx * 0.8 + gz * 0.6) / rm.DUNE_LENGTH * 2 * math.pi + 6.0 * rolling
    dunes = rm.DUNE_AMP * ((0.5 + 0.5 * np.sin(phase)) ** 2 - 0.35)
    lowland = (1.0 - sand) * rm.LOW_AMP * (2.0 * rolling - 1.0) + sand * dunes
    delta = share * (lowland - overlay)
    # Ground the sea's making lowered (a negative overlay) is never raised.
    delta = np.where(overlay < 0.0, np.minimum(delta, 0.0), delta)
    delta *= keep_weight(xs, zs, data)
    # Never lower land in the sea's brush into the sea.
    for x0, z0, x1, z1, surface in rm.water_rects(data):
        if (x1 - x0) * (z1 - z0) < 1.0e8:
            continue                                  # lakes and pools: inland
        tol = float(xs[1] - xs[0])                     # the edge's own pixels too
        inside = (gx >= x0 - tol) & (gx <= x1 + tol) & (gz >= z0 - tol) & (gz <= z1 + tol)
        floor = np.minimum(ground, surface + SEA_CLEARANCE) - ground
        delta = np.where(inside, np.clip(delta, floor, 0.0), delta)
    strength = float(terrain.heightmap_strength) * float(terrain.mesh_scale)
    terrain.heightmap_data = (hm + delta / strength).astype(terrain.heightmap_data.dtype)
    terrain.invalidate_height_range()
    # The snow painted on the wall's heights goes with them.
    bm = terrain.biome_map.astype(np.float32)
    rows, cols = bm.shape[:2]
    (_mx, _Mx), (min_z, max_z) = terrain.get_terrain_bounds()
    bx = min_x + (np.arange(cols) + 0.5) * (max_x - min_x) / cols
    bz = min_z + (np.arange(rows) + 0.5) * (max_z - min_z) / rows
    bw, bwo = wall_fields(bx, bz, (min_x, max_x))
    bshare = np.clip(np.where(bw > 1e-3, (bw - bwo) / np.maximum(bw, 1e-3), 0.0), 0.0, 1.0)
    bm[..., 1] *= (1.0 - bshare)                       # G: snow
    terrain.set_biome_map(np.clip(bm + 0.5, 0, 255).astype(np.uint8))
    return int((np.abs(delta) > 1.0).sum()), float(-delta.min())


# --------------------------------------------------------------- the oasis
def oasis_mask(wx, wz, bounds):
    """True where the oasis's lake is (world points), its shore frayed a
    little; open to the world's southern edge."""
    max_z = bounds[3]
    cx, cz = OASIS_X, max_z - OASIS_SHORE_IN
    ang = np.arctan2(wz - cz, wx - cx)
    wobble = 1.0 + 0.07 * np.sin(ang * 3.0 + 0.7) + 0.04 * np.sin(ang * 7.0 + 2.1)
    q = np.hypot((wx - cx) / OASIS_RX, (wz - cz) / OASIS_RZ) / wobble
    return q < 1.0, q


def make_oasis(terrain, data):
    """Sculpt the lake's basin, fill it with one water brush that reaches
    the world's southern edge, and dress its shore. Returns the surface."""
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    bounds = (min_x, max_x, min_z, max_z)
    res = float(terrain.sculpt_grid_resolution)
    margin = 150.0
    x0, x1 = OASIS_X - OASIS_RX - margin, OASIS_X + OASIS_RX + margin
    z0 = max_z - OASIS_SHORE_IN - OASIS_RZ - margin
    feather = 600.0
    gxs = np.arange(int(math.floor((x0 - feather) / res)), int(math.ceil((x1 + feather) / res)) + 1)
    gzs = np.arange(int(math.floor((z0 - feather) / res)), int(math.floor(max_z / res)) + 1)
    GX, GZ = np.meshgrid(gxs, gzs, indexing="ij")
    WX, WZ = GX * res, GZ * res
    # Grid points on the edge itself are sampled a hair inside it.
    h = terrain._get_heights_batch(
        np.clip(WX, min_x, max_x - 0.01).ravel().astype(np.float32),
        np.clip(WZ, min_z, max_z - 0.01).ravel().astype(np.float32)).reshape(WX.shape)
    water, q = oasis_mask(WX, WZ, bounds)
    shore = ~water & (q < 1.15)
    surface = float(np.percentile(h[shore], 25)) - 30.0
    d_in = ew._dilate_distance(~water, res, int(2400 // res) + 1)
    d_out = ew._dilate_distance(water, res, int(feather // res) + 2)
    bed = surface - 14.0 - np.minimum(d_in * 0.3, OASIS_DEPTH - 14.0)
    want = np.where(water, np.minimum(h, bed), h)
    # The bank inside the brush stays above the water, rising gently off the
    # shore; past the brush it eases back into the sand.
    in_brush = (WX >= x0) & (WX <= x1) & (WZ >= z0)
    bank = surface + 10.0 + d_out * 0.08
    want = np.where(~water & in_brush, np.maximum(h, bank), want)
    # Round the brush the ground is drawn down towards the lake a little,
    # so it sits in a hollow in the dunes rather than a bowl's rim.
    near = ~water & ~in_brush & (d_out < feather)
    hollow = surface + 10.0 + d_out * 0.18
    ease = ew._smoothstep(feather, 0.0, d_out)
    want = np.where(near, h + (np.minimum(h, hollow) - h) * ease, want)
    # The islet on the brink: rock standing out of the water at the very
    # edge, so the water pours past it on both sides.
    lip = OASIS_RX * math.sqrt(max(0.0, 1.0 - (OASIS_SHORE_IN / OASIS_RZ) ** 2))
    ix = OASIS_X + ISLET_AT * lip
    rng_ang = np.arctan2(WZ - max_z, WX - ix)
    wob = 1.0 + 0.12 * np.sin(rng_ang * 5.0 + 1.1) + 0.06 * np.sin(rng_ang * 11.0 + 0.4)
    r = np.hypot((WX - ix) / ISLET_HALF, (WZ - max_z) / ISLET_IN) / wob
    crag = ew._value_noise(WX.astype(np.float32), WZ.astype(np.float32), 140.0, 53)
    rock = surface + ISLET_HEIGHT * (1.0 - r * r) + 30.0 * (crag - 0.5)
    islet = (r < 1.0) & water
    want = np.where(islet, np.maximum(want, np.maximum(rock, surface + 6.0)), want)
    change = want - h
    for a, b, d in zip(GX.ravel().tolist(), GZ.ravel().tolist(), change.ravel().tolist()):
        if math.isfinite(d) and abs(d) >= 0.25:
            key = (int(a), int(b))
            terrain.sculpt_offsets[key] = terrain.sculpt_offsets.get(key, 0.0) + d
    terrain._touch_sculpt()
    terrain.invalidate_height_range()
    floor = float(np.nanmin(terrain._get_heights_batch(
        WX[water].astype(np.float32),
        np.minimum(WZ[water], max_z - 0.01).astype(np.float32)))) - 10.0
    height = max(surface - floor, 40.0)
    brush = {"pos": [round((x0 + x1) / 2.0, 1), round(surface - height / 2.0, 1),
                     round((z0 + max_z) / 2.0, 1)],
             "size": [round(x1 - x0, 1), round(height, 1), round(max_z - z0, 1)],
             "textures": {k: "nodraw.jpg" for k in ("north", "south", "east", "west", "top", "down")},
             "id": _uid("oasis-water"), "name": "sunfall_oasis_water",
             "shader": "Water", "is_fog": False, "is_trigger": False, "water_plane": True,
             # Drifting gently south (+z, "N" in world axes) to the falls.
             "water_flow": "N", "water_flow_speed": OASIS_FLOW_SPEED}
    # The same water as the sea's: one look for the world's water.
    sea = max((b for b in data["brushes"] if b.get("shader") == "Water"),
              key=lambda b: abs(b["size"][0] * b["size"][2]))
    for key in ("water_opacity", "water_reflectivity", "water_tint", "water_wave_enabled",
                "water_wave_height", "water_wave_spread", "water_fresnel", "water_roughness"):
        if key in sea:
            brush[key] = copy.deepcopy(sea[key])
    data["brushes"].append(brush)
    green_ring(terrain, bounds)
    palms = plant_palms(terrain, data, bounds, surface)
    data["things"].append({
        "type": "marker", "pos": [OASIS_X, round(surface + 40.0, 1),
                                  round(z0 + 260.0, 1)],
        "properties": {"type": "marker", "name": "loc_sunfall_oasis", "id": _uid("oasis-marker"),
                       "marker_kind": "location", "place_name": OASIS_NAME,
                       "discover_radius": 1200.0, "io_enabled": True, "stop_on_escape": True,
                       "custom_idle": "assets/sprites/miniwind/marker_location.png"},
        "io_connections": []})
    return surface, palms


def green_ring(terrain, bounds):
    """No desert round the water: a ring of meadow, fading back to sand."""
    bm = terrain.biome_map.astype(np.float32)
    rows, cols = bm.shape[:2]
    min_x, max_x, min_z, max_z = bounds
    bx = min_x + (np.arange(cols) + 0.5) * (max_x - min_x) / cols
    bz = min_z + (np.arange(rows) + 0.5) * (max_z - min_z) / rows
    BX, BZ = np.meshgrid(bx, bz)
    _water, q = oasis_mask(BX, BZ, bounds)
    shore = (q - 1.0) * min(OASIS_RX, OASIS_RZ)          # roughly, units from the water
    green = ew._smoothstep(1100.0, 450.0, shore)
    bm[..., 0] *= (1.0 - green)                     # R: desert
    terrain.set_biome_map(np.clip(bm + 0.5, 0, 255).astype(np.uint8))


def plant_palms(terrain, data, bounds, surface):
    """Palms round the shore, seated on the new ground; desert scrub and
    dead trees that stood in the water or on the green ring go."""
    min_x, max_x, min_z, max_z = bounds
    rng = np.random.default_rng(rm.SEED + 211)
    proto = next(b for b in data["brushes"] if rm._is_tree(b))
    keep = []
    for b in data["brushes"]:
        if rm._is_tree(b):
            _w, q = oasis_mask(np.array([b["pos"][0]]), np.array([b["pos"][2]]), bounds)
            if q[0] < 1.6:
                continue
        keep.append(b)
    data["brushes"] = keep
    planted = []
    tries = 0
    while len(planted) < PALMS and tries < PALMS * 40:
        tries += 1
        ang = rng.uniform(0.0, 2.0 * math.pi)
        r = rng.uniform(1.12, 1.45)
        x = OASIS_X + math.cos(ang) * OASIS_RX * r
        z = max_z - OASIS_SHORE_IN + math.sin(ang) * OASIS_RZ * r
        if z > max_z - 250.0:
            continue
        water, q = oasis_mask(np.array([x]), np.array([z]), bounds)
        if water[0] or any(math.hypot(x - p["pos"][0], z - p["pos"][2]) < 320.0 for p in planted):
            continue
        s = float(rng.uniform(210.0, 300.0))
        b = copy.deepcopy(proto)
        b.update(pos=[round(x, 1), 0.0, round(z, 1)], size=[round(s, 1), rm.TREE_THICKNESS, round(s, 1)],
                 id=_uid(f"oasis-palm-{len(planted)}"))
        # The whole canopy over dry ground, never over the water.
        if over_water(terrain, data, [b])[0]:
            continue
        b["textures"] = dict(b["textures"], top="palm01.png")
        b["uv_angle"] = {"top": round(float(rng.uniform(0.0, 360.0)), 1)}
        planted.append(b)
    data["brushes"].extend(planted)
    rm.seat_trees(terrain, {"brushes": planted})
    return len(planted)


def over_water(terrain, data, trees):
    """Which of *trees* (brushes) have any part of their canopy over water:
    ground below the surface of a water brush covering it, sampled across
    the whole footprint."""
    if not trees:
        return np.zeros(0, bool)
    rects = rm.water_rects(data)
    k = np.linspace(-0.5, 0.5, 7)
    du, dv = (a.ravel() for a in np.meshgrid(k, k))
    X = np.concatenate([b["pos"][0] + du * abs(b["size"][0]) for b in trees])
    Z = np.concatenate([b["pos"][2] + dv * abs(b["size"][2]) for b in trees])
    (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
    G = terrain._get_heights_batch(np.clip(X, min_x, max_x - 0.01).astype(np.float32),
                                   np.clip(Z, min_z, max_z - 0.01).astype(np.float32))
    wet = np.zeros(len(X), bool)
    for x0, z0, x1, z1, surface in rects:
        wet |= (X >= x0) & (X <= x1) & (Z >= z0) & (Z <= z1) & (G < surface + 2.0)
    return wet.reshape(len(trees), -1).any(axis=1)


def fell_trees_over_water(terrain, data):
    """No tree stands in water or over it: every one whose canopy reaches
    over any water goes. Returns how many went."""
    trees = [b for b in data["brushes"] if rm._is_tree(b)]
    wet = over_water(terrain, data, trees)
    gone = {id(b) for b, w in zip(trees, wet) if w}
    data["brushes"] = [b for b in data["brushes"] if id(b) not in gone]
    return len(gone)


# ---------------------------------------------------------------------- main
def reshape(path=MAP):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    done = data.get("_miniwind_world") or {}
    if done.get("edge_wall_removed") or done.get("oasis"):
        raise SystemExit(f"{path} has already been reshaped (no edge wall, Sunfall Oasis).")
    terrain = rm.terrain_of(data)
    solid = [b for b in data["brushes"]
             if not (rm._is_tree(b) or b.get("water_plane") or b.get("shader") == "Water"
                     or b.get("is_trigger") or b.get("is_fog") or b.get("hidden"))]
    feet = rm.footprint_points({"things": data["things"], "brushes": solid})
    trees = [b for b in data["brushes"] if rm._is_tree(b)]
    tree_xz = np.array([(b["pos"][0], b["pos"][2]) for b in trees], np.float32).reshape(-1, 2)
    tree_before = terrain._get_heights_batch(tree_xz[:, 0], tree_xz[:, 1])
    before = terrain._get_heights_batch(feet[:, 0], feet[:, 1])
    changed, deepest = remove_wall(terrain, data)
    after = terrain._get_heights_batch(feet[:, 0], feet[:, 1])
    moved = float(np.abs(after - before).max()) if len(feet) else 0.0
    if moved > 0.01:
        raise RuntimeError(f"the ground moved by {moved:.3f} under something placed")
    # The trees whose ground moved, on the new ground (the oasis's palms are
    # seated as they are planted).
    tree_after = terrain._get_heights_batch(tree_xz[:, 0], tree_xz[:, 1])
    shifted = [b for b, h0, h1 in zip(trees, tree_before, tree_after) if abs(h1 - h0) > 0.5]
    seated = rm.seat_trees(terrain, {"brushes": shifted})
    surface, palms = make_oasis(terrain, data)
    felled = fell_trees_over_water(terrain, data)
    td = terrain.to_dict()
    data["terrain_data"] = dict(
        data["terrain_data"], heightmap_blob=td["heightmap_blob"],
        biome_map_blob=terrain.to_dict().get("biome_map_blob", data["terrain_data"].get("biome_map_blob")),
        sculpt_offsets=[[gx, gz, round(v, 2)] for (gx, gz), v in
                        sorted(terrain.sculpt_offsets.items()) if abs(v) >= 0.25],
        sculpt_grid_resolution=terrain.sculpt_grid_resolution)
    data["terrain_data"].pop("sculpt_tiles", None)
    flags = data.setdefault("_miniwind_world", {})
    flags["edge_wall_removed"] = True
    flags["oasis"] = OASIS_NAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return dict(pixels_changed=changed, deepest_cut=round(deepest, 1),
                trees_seated=seated, oasis_surface=round(surface, 1), palms=palms,
                trees_over_water_felled=felled)


if __name__ == "__main__":
    print(reshape(sys.argv[1] if len(sys.argv) > 1 else MAP))
