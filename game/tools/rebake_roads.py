"""Bake the world's roads again, sharper and in another texture.

    python -m game.tools.rebake_roads [map.json] [texture]

The roads :mod:`game.tools.make_road_map` stamped are kept in the map only as
baked terrain paint (no stamp records), saved at 128 texels a 2048-unit
chunk: sixteen world units a texel, smeared on screen. This bakes them again
at the terrain's current paint resolution (512 a chunk for the world's
chunks, :meth:`engine.terrain.Terrain.paint_resolution_for`) with *texture*
(default ``assets/textures/flagstone.jpg``):

* **Where** a road is stays exactly where it was: the old paint's coverage
  (its alpha), resampled to the new resolution, is the new road's -- the
  same footprint, the same feathered edges, so nothing placed beside a road
  and no ``ROAD_*`` path node (the road as NPCs know it) moves or changes.
* **Its edge is feathered** wider than the stamps left it, and broken up by
  a little world-space noise, so the road fades into the ground irregularly
  -- grass creeping over the stones -- rather than ending on a smooth band
  (:func:`feather`). Across chunk borders too: each chunk is blurred with
  its neighbours' edges beside it.
* **What it looks like** is the texture laid on the world as a stamp lays it
  (tiled at :data:`Terrain.STAMP_TILE_UNITS_PER_PIXEL`, unturned), so a road
  stamped later in the editor with the same texture continues it.

Only ``terrain_data``'s paint changes; it is saved in ``<map>.stamp``
beside the map (:func:`engine.terrain_stamp.write_level`). It bakes from the road paint
make_road_map left; a map it has already baked with these settings is left
alone, and one it baked with others is refused (feathering the feathered
paint again would widen it twice): restore the map's paint first.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import terrain_stamp  # noqa: E402
from engine.terrain import Terrain  # noqa: E402

MAP = os.path.join(ROOT, "maps", "miniwind_world.json")
TEXTURE = "assets/textures/flagstone.jpg"
#: The feather's blur: three box passes this many texels each way (at four
#: world units a texel, a soft edge about forty units wider than before).
FEATHER_TEXELS = 4
#: How far the noise moves the edge (in coverage, 0..1), and the size of
#: its features in world units.
EDGE_NOISE = 0.22
EDGE_NOISE_SCALE = 36.0
SEED = 9127


def _hash(ix, iz, seed):
    h = (ix * 374761393 + iz * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def value_noise(x, z, scale, seed=SEED, octaves=3):
    """Smooth noise in -1..1 over world points (arrays), seamless
    everywhere: it is a function of the world position alone."""
    total = np.zeros(np.broadcast(x, z).shape, np.float64)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        fx, fz = x / scale, z / scale
        ix, iz = np.floor(fx).astype(np.int64), np.floor(fz).astype(np.int64)
        tx, tz = fx - ix, fz - iz
        tx, tz = tx * tx * (3 - 2 * tx), tz * tz * (3 - 2 * tz)
        a = _hash(ix, iz, seed + o)
        b = _hash(ix + 1, iz, seed + o)
        c = _hash(ix, iz + 1, seed + o)
        d = _hash(ix + 1, iz + 1, seed + o)
        total += amp * ((a * (1 - tx) + b * tx) * (1 - tz) + (c * (1 - tx) + d * tx) * tz)
        norm += amp
        amp *= 0.5
        scale *= 0.5
    return (total / norm) * 2.0 - 1.0


def _box(a, r, axis):
    """Box blur of *a* along *axis*, width 2r+1, the ends padded by the edge."""
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / float(2 * r + 1)


def feather(terrain: Terrain, texels: int = FEATHER_TEXELS) -> int:
    """Widen and roughen the edge of every road's coverage (alpha), keeping
    each road's peak; returns the chunks with coverage afterwards (a road at
    a chunk's edge can spill a little into an unpainted neighbour)."""
    maps = terrain.texture_paint_maps
    res = terrain.TERRAIN_PAINT_RESOLUTION
    cell = terrain.chunk_size / float(res)
    pad = 3 * texels + 2
    alphas = {k: v[..., 3].astype(np.float32) / 255.0 for k, v in maps.items() if v[..., 3].any()}
    peak = max((float(a.max()) for a in alphas.values()), default=1.0)
    keys = {(cx + dx, cz + dz) for cx, cz in alphas for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    zero = np.zeros((res, res), np.float32)
    out = {}
    for cx, cz in sorted(keys):
        # The chunk with a border of its neighbours' coverage round it.
        big = np.zeros((res + 2 * pad, res + 2 * pad), np.float32)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                a = alphas.get((cx + dx, cz + dz))
                if a is None:
                    continue
                xs = slice(max(0, res - pad) if dx < 0 else 0, pad if dx > 0 else res)
                zs = slice(max(0, res - pad) if dz < 0 else 0, pad if dz > 0 else res)
                bx = {-1: 0, 0: pad, 1: pad + res}[dx]
                bz = {-1: 0, 0: pad, 1: pad + res}[dz]
                part = a[xs, zs]
                big[bx:bx + part.shape[0], bz:bz + part.shape[1]] = part
        if not big.any():
            continue
        for _ in range(3):
            big = _box(_box(big, texels, 0), texels, 1)
        b = big[pad:pad + res, pad:pad + res] / max(peak, 1e-6)
        if not (b > 1e-3).any():
            continue
        # Noise only where the coverage is part way: the road's middle stays
        # whole, the ground beyond stays bare.
        xs = terrain.offset_x + cx * terrain.chunk_size + (np.arange(res) + 0.5) * cell
        zs = terrain.offset_z + cz * terrain.chunk_size + (np.arange(res) + 0.5) * cell
        n = value_noise(xs[:, None], zs[None, :], EDGE_NOISE_SCALE)
        edge = 4.0 * b * (1.0 - b)
        a = np.clip(b + n * EDGE_NOISE * edge, 0.0, 1.0)
        a = a * a * (3.0 - 2.0 * a) * peak
        alpha = np.clip(a * 255.0 + 0.5, 0, 255).astype(np.uint8)
        if not alpha.any():
            continue
        paint = maps.get((cx, cz))
        new = np.zeros((res, res, 4), np.uint8) if paint is None else paint.copy()
        new[..., 3] = alpha
        out[(cx, cz)] = new
    terrain.texture_paint_maps = out
    return len(out)


def retexture(terrain: Terrain, texture: str) -> int:
    """Recolour every painted texel of *terrain* with *texture*, keeping its
    coverage; returns the chunks painted."""
    tile = terrain._tile_image(texture)
    if tile is None:
        raise SystemExit(f"cannot load {texture}")
    image, per_unit = tile
    res = terrain.TERRAIN_PAINT_RESOLUTION
    cell = terrain.chunk_size / float(res)
    out = {}
    for (cx, cz), paint in terrain.texture_paint_maps.items():
        alpha = paint[..., 3]
        if not alpha.any():
            continue
        xs = terrain.offset_x + cx * terrain.chunk_size + (np.arange(res, dtype=np.float32) + 0.5) * cell
        zs = terrain.offset_z + cz * terrain.chunk_size + (np.arange(res, dtype=np.float32) + 0.5) * cell
        source = terrain._sample_tiled_grid(image, xs * per_unit, -zs * per_unit)
        rgb = np.asarray(source[..., :3], dtype=np.float32)    # 0..255
        new = np.zeros_like(paint)
        new[..., :3] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
        new[..., 3] = alpha
        new[alpha == 0, :3] = 0
        out[(cx, cz)] = new
    terrain.texture_paint_maps = out
    terrain.texture_paint_base = dict(out)
    terrain._paint_serial_cache = {}
    return len(out)


def rebake(path: str = MAP, texture: str = TEXTURE) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = terrain_stamp.merge_level_paint(json.load(fh), path)
    td = data["terrain_data"]
    meta = data.setdefault("_miniwind_world", {})
    terrain = Terrain()
    terrain.from_dict(td)
    res = terrain.TERRAIN_PAINT_RESOLUTION
    settings = {"texture": texture, "resolution": res, "feather": FEATHER_TEXELS,
                "edge_noise": EDGE_NOISE}
    done = meta.get("road_paint")
    if done == settings:
        return dict(changed=False, resolution=res, chunks=len(td.get("texture_paint") or []))
    if done:
        raise SystemExit(f"roads already rebaked with {done}; restore the map's road paint first")
    if td.get("paint_stamps"):
        raise SystemExit("the map has stamp records; rebake those in the editor instead")
    old_res = int(td.get("texture_paint_resolution", Terrain.LEGACY_PAINT_RESOLUTION))
    feathered = feather(terrain)
    chunks = retexture(terrain, texture)
    td["texture_paint"] = terrain._serialize_texture_paint()
    td["texture_paint_resolution"] = res
    td.pop("texture_paint_base", None)
    meta["road_paint"] = settings
    # The map in its own layout; the paint in <map>.stamp beside it.
    terrain_stamp.write_level(path, data, indent=4)
    return dict(changed=True, chunks=chunks, feathered=feathered, resolution=res, was=old_res)


if __name__ == "__main__":
    args = sys.argv[1:]
    print(rebake(*(args[:2] or [])))
