"""
Re-render the repository's overview maps from the current world.

    python -m game.tools.render_maps [map.json]

Writes, from ``maps/miniwind_world.json`` by default:

* ``_world_map.png`` -- the world as the game's world map paints it
  (game/ui/worldmap.py: heights, biome regions, road paint, water and
  brushes), every named place marked and labelled, caves in magenta;
* ``_cave_map.jpg`` -- the same map with every cave entrance (the world's
  level changers into ``maps/caveNN.json``) ringed and labelled with the
  cave's name and map, and the count in the corner.

Run it again whenever the world changes; both files are only pictures.
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WORLD_SIZE = 1100
CAVE_SIZE = 1400


def _fonts(width):
    from PIL import ImageFont
    try:
        return (ImageFont.truetype("DejaVuSans-Bold.ttf", max(11, int(width / 92))),
                ImageFont.truetype("DejaVuSans-Bold.ttf", max(14, int(width / 60))))
    except OSError:
        f = ImageFont.load_default()
        return f, f


def _canvas(rgb, size):
    from PIL import Image
    img = Image.fromarray(np.ascontiguousarray(rgb)).convert("RGB")
    return img.resize((size, size), Image.LANCZOS)


def _projector(bounds, size):
    (x0, x1), (z0, z1) = bounds
    return lambda x, z: ((x - x0) / (x1 - x0) * size, (z - z0) / (z1 - z0) * size)


def places(level):
    """``[(name, x, z, cave)]`` for every named location marker."""
    out = []
    for t in level.get("things", []):
        p = t.get("properties") or {}
        if p.get("marker_kind") == "location" and p.get("place_name"):
            name = str(p["place_name"])
            cave = bool(re.match(r"loc_cave\d+$", str(p.get("name", ""))))
            out.append((name, float(t["pos"][0]), float(t["pos"][2]), cave))
    return out


def cave_entrances(level):
    """``[(cave name, map slug, x, z)]`` for each level changer into a cave."""
    names = {}
    for name, x, z, cave in places(level):
        if cave:
            names[(round(x), round(z))] = name
    out = []
    for t in level.get("things", []):
        p = t.get("properties") or {}
        if p.get("type") != "levelchanger":
            continue
        target = str(p.get("target_map", ""))
        m = re.search(r"(cave\d+)\.json$", target)
        if not m:
            continue
        x, z = float(t["pos"][0]), float(t["pos"][2])
        prompt = str(p.get("prompt", ""))
        name = prompt.split("Enter ", 1)[1].strip() if "Enter " in prompt else m.group(1)
        out.append((name, m.group(1), x, z))
    out.sort(key=lambda r: r[1])
    return out


class _Labels:
    """Places labels beside their points, trying right, left, below and
    above, so no label covers another where it can be helped."""

    def __init__(self, dr, font, size):
        self.dr, self.font, self.size = dr, font, size
        self.taken = []

    def add(self, xy, text, colour=(255, 255, 255), gap=9):
        x, y = xy
        w = self.dr.textlength(text, font=self.font)
        h = self.font.size * 1.2
        options = [(x + gap, y - h / 2), (x - gap - w, y - h / 2),
                   (x - w / 2, y + gap), (x - w / 2, y - gap - h)]
        best = None
        for tx, ty in options:
            box = (tx - 1, ty - 1, tx + w + 1, ty + h + 1)
            inside = 0 <= box[0] and box[2] <= self.size and 0 <= box[1] and box[3] <= self.size
            hits = sum(1 for o in self.taken
                       if box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3])
            score = hits * 10 + (0 if inside else 5)
            if best is None or score < best[0]:
                best = (score, tx, ty, box)
            if score == 0:
                break
        _score, tx, ty, box = best
        self.taken.append(box)
        self.dr.text((tx, ty), text, fill=colour, font=self.font,
                     stroke_width=2, stroke_fill=(0, 0, 0))


def world_map(rgb, bounds, level, path, size=WORLD_SIZE):
    from PIL import ImageDraw
    img = _canvas(rgb, size)
    dr = ImageDraw.Draw(img)
    px = _projector(bounds, size)
    font, _big = _fonts(size)
    labels = _Labels(dr, font, size)
    marks = places(level)
    for name, x, z, cave in marks:
        sx, sy = px(x, z)
        r = 4 if cave else 3
        labels.taken.append((sx - r, sy - r, sx + r, sy + r))
        dr.ellipse([sx - r, sy - r, sx + r, sy + r],
                   fill=(230, 40, 210) if cave else (255, 255, 255), outline=(0, 0, 0))
    for name, x, z, _cave in marks:
        labels.add(px(x, z), name)
    img.save(path)
    return path


def cave_map(rgb, bounds, level, path, size=CAVE_SIZE):
    from PIL import ImageDraw
    img = _canvas(rgb, size)
    dr = ImageDraw.Draw(img)
    px = _projector(bounds, size)
    font, big = _fonts(size)
    caves = cave_entrances(level)
    labels = _Labels(dr, font, size)
    for name, slug, x, z in caves:
        sx, sy = px(x, z)
        labels.taken.append((sx - 9, sy - 9, sx + 9, sy + 9))
        dr.ellipse([sx - 9, sy - 9, sx + 9, sy + 9], fill=(30, 20, 0), outline=(255, 196, 40), width=3)
        dr.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(255, 196, 40))
    for name, slug, x, z in caves:
        labels.add(px(x, z), f"{name} ({slug})", gap=12)
    title = f"Cave entrances: {len(caves)}"
    w = dr.textlength(title, font=big)
    labels.taken.append((10, 10, 30 + w, 22 + big.size * 1.2))
    dr.rectangle([10, 10, 30 + w, 22 + big.size * 1.2], fill=(0, 0, 0))
    dr.text((20, 14), title, fill=(255, 196, 40), font=big)
    img.convert("RGB").save(path, quality=90)
    return path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    map_path = argv[0] if argv else os.path.join(ROOT, "maps", "miniwind_world.json")
    from game.tools.district_map import load_terrain, world_map_rgb
    terrain, level = load_terrain(map_path)
    rgb, bounds, _cell = world_map_rgb(terrain, map_path)
    print("wrote", world_map(rgb, bounds, level, os.path.join(ROOT, "_world_map.png")))
    print("wrote", cave_map(rgb, bounds, level, os.path.join(ROOT, "_cave_map.jpg")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
