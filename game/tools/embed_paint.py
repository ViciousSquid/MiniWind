"""
Lay a map's paint file into the map itself.

    python -m game.tools.embed_paint [map.json]

A map's terrain paint -- the overworld's roads, and the district borders
baked into them -- can live beside it in ``<map>.paint`` (the editor's save
puts it there), joined in by every load that finds the file. This writes it
into the map's own ``terrain_data`` instead, so the map carries its roads
wherever it is loaded from, and removes the paint file, which a map carrying
its own paint never reads (engine/terrain_stamp.py). The map is written
minified, as large maps always are.

Default map: ``maps/miniwind_world.json``.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MAP = os.path.join(ROOT, "maps", "miniwind_world.json")


def write_map(path, level):
    """Write *level* to *path*, minified."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(level, fh, separators=(",", ":"))


def embed(path=MAP):
    from engine import terrain_stamp
    with open(path, encoding="utf-8") as fh:
        level = json.load(fh)
    paint_path = terrain_stamp.paint_path(path)
    if paint_path is None:
        raise SystemExit(f"{path} has no paint file beside it: nothing to lay in.")
    if not terrain_stamp._wants_paint(level):
        raise SystemExit(f"{path} already carries its own paint.")
    level = terrain_stamp.apply_stamp_delta(level, terrain_stamp.load_stamp_file(paint_path))
    terrain = level[terrain_stamp.TERRAIN_KEY]
    if not terrain.get("texture_paint"):
        raise SystemExit(f"{os.path.basename(paint_path)} holds no paint.")
    write_map(path, level)
    os.remove(paint_path)
    return dict(paint_chunks=len(terrain["texture_paint"]),
                stamps=len(terrain.get(terrain_stamp.STAMPS_KEY) or []),
                removed=os.path.basename(paint_path))


if __name__ == "__main__":
    print(embed(sys.argv[1] if len(sys.argv) > 1 else MAP))
