"""
Draw the world map with the districts over it, to see and tweak them.

    python -m game.tools.district_map [map.json] [out.png]

Builds the same map the game's world map shows (game/ui/worldmap.py: the
terrain's heights, its painted biome regions, its road paint and brushes),
then draws over it each district's border, its name, its seat (a ring with
its coordinates) and a grid every 10,000 world units, labelled. Defaults:
``maps/miniwind_world.json`` -> ``docs/images/districts_map.png``.

To tweak: move a district's ``seat`` in ``game/data/districts.json`` (or its
``warp``) and run this again. ``--biomes`` also prints how much of each
district is each biome.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BIOMES = ("desert", "snow", "swamp", "wheat", "tundra")


def load_terrain(map_path):
    """``(terrain, level)``: the map's terrain, its paint file laid in (the
    roads, and the districts' borders once baked), as the editor loads it."""
    from engine import terrain_stamp
    from engine.terrain import Terrain
    with open(map_path, "r", encoding="utf-8") as fh:
        level = json.load(fh)
    level = terrain_stamp.join_level(level, map_path)
    terrain = Terrain()
    terrain.from_dict(level["terrain_data"])
    return terrain, level


def world_map_rgb(terrain, map_path):
    """``(rgb, bounds, cell)`` exactly as the game's world map builds it."""
    from game.ui import worldmap
    wm = worldmap.WorldMap()
    wm._key = "district-map"
    wm._build("district-map", terrain, [], brush_source=map_path)
    if wm.rgb is None:
        raise RuntimeError(f"world map failed: {wm.error}")
    return wm.rgb, wm.bounds, wm.cell


def biome_shares(districts, terrain, step=400.0):
    """``{district id: {biome or "grass": share}}`` over a grid of samples."""
    x0, z0, x1, z1 = districts.bounds
    xs = np.arange(x0 + step / 2, x1, step)
    zs = np.arange(z0 + step / 2, z1, step)
    gx, gz = np.meshgrid(xs, zs)
    ids = districts.index_at(gx, gz).ravel()
    w = np.asarray(terrain.biome_weights_batch(gx.ravel(), gz.ravel()), np.float32)
    names = BIOMES[:w.shape[1]]
    grass = np.clip(1.0 - w.sum(axis=1), 0.0, 1.0)
    out = {}
    for i, d in enumerate(districts.districts):
        sel = ids == i
        n = max(1, int(sel.sum()))
        row = {name: float(w[sel, k].sum()) / n for k, name in enumerate(names)}
        row["grass"] = float(grass[sel].sum()) / n
        out[d.id] = row
    return out


def draw(rgb, bounds, districts, out_path, scale=1.0):
    from PIL import Image, ImageDraw, ImageFont
    (mx0, mx1), (mz0, mz1) = bounds
    img = Image.fromarray(np.ascontiguousarray(rgb)).convert("RGB")
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    w, h = img.size
    dr = ImageDraw.Draw(img, "RGBA")

    def px(x, z):
        return ((x - mx0) / (mx1 - mx0) * w, (z - mz0) / (mz1 - mz0) * h)

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(12, int(w / 70)))
        small = ImageFont.truetype("DejaVuSans.ttf", max(10, int(w / 110)))
    except OSError:
        font = small = ImageFont.load_default()
    # The grid, every 10,000 units, labelled along the top and left.
    for v in range(-40000, 40001, 10000):
        gx, _ = px(v, mz0)
        _, gy = px(mx0, v)
        dr.line([(gx, 0), (gx, h)], fill=(255, 255, 255, 60), width=1)
        dr.line([(0, gy), (w, gy)], fill=(255, 255, 255, 60), width=1)
        dr.text((gx + 3, 2), f"x {v:+d}", fill=(255, 255, 255, 200), font=small)
        dr.text((3, gy + 2), f"z {v:+d}", fill=(255, 255, 255, 200), font=small)
    # Borders: a pale halo under a dark line, as the game's map would.
    lines = districts.border_lines()
    for line in lines:
        pts = [px(x, z) for x, z in line]
        dr.line(pts, fill=(255, 255, 255, 110), width=max(5, int(w / 180)), joint="curve")
    for line in lines:
        pts = [px(x, z) for x, z in line]
        dr.line(pts, fill=(20, 18, 24, 235), width=max(2, int(w / 400)), joint="curve")
    # Seats and names (a district's name under its first seat; every seat ringed).
    for d in districts.districts:
        r = max(5, int(w / 160))
        for k, seat in enumerate(d.seats):
            kx, ky = px(*seat)
            dr.ellipse([kx - r, ky - r, kx + r, ky + r], outline=(255, 240, 120, 255), width=3)
            if k:
                extra = f"{d.name} seat {k + 1}: {seat[0]:+.0f}, {seat[1]:+.0f}"
                ew = dr.textlength(extra, font=small)
                dr.text((kx - ew / 2, ky + r + 4), extra, fill=(255, 240, 160, 255), font=small,
                        stroke_width=2, stroke_fill=(0, 0, 0, 200))
        sx, sy = px(*d.seat)
        label = f"{d.name.upper()}  ({d.biome})"
        tw = dr.textlength(label, font=font)
        dr.text((sx - tw / 2, sy + r + 4), label, fill=(255, 255, 255, 255), font=font,
                stroke_width=3, stroke_fill=(0, 0, 0, 220))
        coords = f"seat {d.seat[0]:+.0f}, {d.seat[1]:+.0f}  ({d.id})"
        cw = dr.textlength(coords, font=small)
        dr.text((sx - cw / 2, sy + r + 8 + font.size), coords, fill=(255, 240, 160, 255),
                font=small, stroke_width=2, stroke_fill=(0, 0, 0, 200))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return out_path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    show_biomes = "--biomes" in argv
    argv = [a for a in argv if a != "--biomes"]
    map_path = argv[0] if argv else os.path.join(ROOT, "maps", "miniwind_world.json")
    out_path = argv[1] if len(argv) > 1 else os.path.join(ROOT, "docs", "images", "districts_map.png")
    from game import districts as districts_mod
    terrain, level = load_terrain(map_path)
    districts = districts_mod.load(
        biome_weights=terrain.biome_weights_batch,
        water=districts_mod.water_boxes(level.get("brushes")),
        height=lambda xs, zs: terrain._get_heights_batch(np.asarray(xs, np.float32),
                                                         np.asarray(zs, np.float32)))
    rgb, bounds, _cell = world_map_rgb(terrain, map_path)
    draw(rgb, bounds, districts, out_path, scale=1.5)
    print(f"wrote {out_path}")
    if show_biomes:
        for did, row in biome_shares(districts, terrain).items():
            top = sorted(row.items(), key=lambda kv: -kv[1])
            print(f"{did:14s} " + "  ".join(f"{k} {v:.0%}" for k, v in top if v >= 0.02))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
