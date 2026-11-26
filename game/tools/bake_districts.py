"""
Bake the district borders into a map's terrain paint, by hand.

    python -m game.tools.bake_districts [map.json]

Draws the borders of ``game/data/districts.json`` (game/districts.py) into
the map's paint as hand-drawn ink and writes it -- into the map itself when
the map carries its own paint (``game/tools/embed_paint.py``), else into its
paint file (``<map>.paint``) -- and the drawing's record (``<map>.districts.npz``: what
each inked texel was before). Run it again after changing the districts: it
first lifts the borders it drew last time (from the record), so the paint is
never inked twice. In play the borders cost nothing -- they are the map's
paint -- unless they are switched off or moved.
Default map: ``maps/miniwind_world.json``.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_painted_terrain(map_path):
    """``(terrain, level)``: the map's terrain with its paint file laid in."""
    from game.tools.district_map import load_terrain
    return load_terrain(map_path)


def bake(map_path, report=print):
    from engine import terrain_stamp
    from game import districts as dd
    terrain, level = load_painted_terrain(map_path)
    found = dd.load(biome_weights=terrain.biome_weights_batch,
                    water=dd.water_boxes(level.get("brushes")),
                    height=lambda xs, zs: terrain._get_heights_batch(
                        np.asarray(xs, np.float32), np.asarray(zs, np.float32)))
    record = dd.record_path(map_path)
    res = int(terrain.TERRAIN_PAINT_RESOLUTION)
    old = dd.Drawing.load(record, res)
    if old is not None:
        old.lift(terrain)
        report(f"lifted the borders drawn before ({len(old.under)} chunks)")
    t = time.perf_counter()
    drawing = found.bake(terrain)
    report(f"drew {len(drawing.under)} chunks of border in {time.perf_counter() - t:.1f} s")
    if terrain_stamp._wants_paint(level):
        # The map keeps its paint in its paint file: write that.
        paint = terrain_stamp.paint_file(terrain.to_dict())
        written = terrain_stamp.write_map_stamps(map_path, paint)
    else:
        # The map carries its own paint (game/tools/embed_paint.py): write it
        # into the map, minified; a paint file beside it would not be read.
        from game.tools.embed_paint import write_map
        baked = terrain.to_dict()
        td = level[terrain_stamp.TERRAIN_KEY]
        for key in terrain_stamp.PAINT_KEYS:
            if baked.get(key):
                td[key] = baked[key]
        write_map(map_path, level)
        written = map_path
    drawing.save(record)
    report(f"wrote {written} and {record}")
    return drawing


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        map_path = argv[0]
    else:
        from game import districts as dd
        map_path = os.path.join(ROOT, dd.load().map or "maps/miniwind_world.json")
    bake(map_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
