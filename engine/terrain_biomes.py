"""
Regional biomes painted over a terrain: desert, snow, swamp and wheat.

A terrain has one height-driven colour gradient (its ``BiomeConfig``). On a
big world that makes every region look the same, so a map can also carry a
**biome map**: one low-resolution RGBA8 image stretched over the terrain's
bounds (rows run along z, columns along x, like the heightmap), whose
channels are how much of each regional biome covers that spot:

* **R desert** -- sand and dunes, red rock on steep ground, no grass.
* **G snow** -- snowfields, rock showing on the steepest slopes, no grass.
* **B swamp** -- dark moss and mud with standing water, tall reeds.
* **A wheat** -- golden fields in furrows, dense waist-high wheat.

Where all four are zero the terrain looks exactly as it did. Partial weights
blend, so a desert fades through dry steppe into meadow. The fragment shader
(``terrain.frag``) does the full-detail blend; :func:`blend_colors` is its
CPU twin for grass that matches the ground and for pictures of the map.

Pure NumPy: built, saved and sampled headless.
"""

from __future__ import annotations

import base64
import binascii
import io
import zlib
from typing import Optional, Tuple

import numpy as np

DESERT, SNOW, SWAMP, WHEAT = range(4)
NAMES = ("desert", "snow", "swamp", "wheat")

#: Base colours (the shader adds grain, dunes, furrows and puddles).
SAND = np.array((0.84, 0.70, 0.46), np.float32)
SANDSTONE = np.array((0.62, 0.38, 0.24), np.float32)
SNOWFIELD = np.array((0.92, 0.94, 0.98), np.float32)
MOSS = np.array((0.24, 0.29, 0.14), np.float32)
WHEAT_GOLD = np.array((0.82, 0.67, 0.30), np.float32)

#: Grass per biome. Desert and snow carry none; swamp grows reeds; wheat
#: grows a dense field of tall stalks with its own tuft budget per chunk.
REED_SIZE = (2.2, 3.4)
REED_COLOUR = np.array((0.36, 0.42, 0.20), np.float32)
WHEAT_SIZE = (7.0, 10.0)
WHEAT_COLOUR = np.array((0.86, 0.70, 0.32), np.float32)
WHEAT_TIP = np.array((0.95, 0.84, 0.52), np.float32)
#: Wheat tufts per chunk at full coverage, stalks per tuft, tuft radius.
WHEAT_MAX_PER_CHUNK = 9000
WHEAT_STALKS_PER_TUFT = 8
WHEAT_TUFT_RADIUS = 9.0


def encode(biome_map: np.ndarray) -> str:
    """The map as text for a map file: zlib-compressed ``.npy``, base64."""
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(biome_map, dtype=np.uint8))
    return base64.b64encode(zlib.compress(buf.getvalue(), 9)).decode("ascii")


def decode(blob) -> Optional[np.ndarray]:
    """The map from :func:`encode`'s text, or None if it is unusable (never
    unpickled; anything but an HxWx4 uint8 array is dropped)."""
    try:
        raw = zlib.decompress(base64.b64decode(blob))
        arr = np.load(io.BytesIO(raw), allow_pickle=False)
    except (TypeError, ValueError, EOFError, OSError, MemoryError,
            binascii.Error, zlib.error) as exc:
        print(f"[Terrain] Ignoring unreadable biome map: {exc}")
        return None
    if (not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] != 4
            or arr.dtype != np.uint8 or arr.size == 0):
        print("[Terrain] Ignoring biome map that is not an HxWx4 uint8 image")
        return None
    return arr


def sample(biome_map: Optional[np.ndarray], bounds, xs, zs) -> np.ndarray:
    """Bilinear biome weights (n x 4, 0..1) at world points *xs*, *zs*.

    *bounds* is ``((min_x, max_x), (min_z, max_z))``. Outside the bounds,
    and with no map, every weight is zero."""
    xs = np.asarray(xs, np.float32).ravel()
    zs = np.asarray(zs, np.float32).ravel()
    out = np.zeros((len(xs), 4), np.float32)
    if biome_map is None or len(xs) == 0:
        return out
    (x0, x1), (z0, z1) = bounds
    if x1 <= x0 or z1 <= z0:
        return out
    h, w = biome_map.shape[:2]
    u = (xs - x0) / (x1 - x0)
    v = (zs - z0) / (z1 - z0)
    inside = (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    if not np.any(inside):
        return out
    # Texel centres, as GL_LINEAR samples them.
    fx = np.clip(u[inside] * w - 0.5, 0.0, w - 1.0)
    fz = np.clip(v[inside] * h - 0.5, 0.0, h - 1.0)
    ix0 = np.floor(fx).astype(np.int64)
    iz0 = np.floor(fz).astype(np.int64)
    ix1 = np.minimum(ix0 + 1, w - 1)
    iz1 = np.minimum(iz0 + 1, h - 1)
    tx = (fx - ix0)[:, None]
    tz = (fz - iz0)[:, None]
    m = biome_map.astype(np.float32) / 255.0
    top = m[iz0, ix0] * (1 - tx) + m[iz0, ix1] * tx
    bot = m[iz1, ix0] * (1 - tx) + m[iz1, ix1] * tx
    out[inside] = top * (1 - tz) + bot * tz
    return out


def _coverage(w, sharp: Tuple[float, float] = (0.0, 1.0)):
    lo, hi = sharp
    t = np.clip((w - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def blend_colors(colors: np.ndarray, weights: np.ndarray,
                 slope: Optional[np.ndarray] = None) -> np.ndarray:
    """*colors* (n x 3 ground albedo) with the biomes painted over them, as
    ``terrain.frag`` does (without its fine noise)."""
    out = np.asarray(colors, np.float32).copy()
    if weights is None or not np.any(weights):
        return out
    s = np.zeros(len(out), np.float32) if slope is None else np.asarray(slope, np.float32)
    steep = _coverage(s, (0.3, 0.55))[:, None]
    sand = SAND[None, :] * (1 - steep) + SANDSTONE[None, :] * steep
    a = _coverage(weights[:, DESERT])[:, None]
    out = out * (1 - a) + sand * a
    a = _coverage(weights[:, WHEAT], (0.35, 0.6))[:, None]
    out = out * (1 - a) + WHEAT_GOLD[None, :] * a
    a = _coverage(weights[:, SWAMP])[:, None]
    out = out * (1 - a) + MOSS[None, :] * a
    a = (_coverage(weights[:, SNOW]) * (1.0 - 0.7 * _coverage(s, (0.45, 0.7))))[:, None]
    out = out * (1 - a) + SNOWFIELD[None, :] * a
    return np.clip(out, 0.0, 1.0)


def grass_keep(weights: np.ndarray) -> np.ndarray:
    """How much ordinary grass survives (0..1): none on sand, snow or in a
    wheat field (which grows its own), thinned in the swamp."""
    bare = np.maximum(weights[:, DESERT], weights[:, SNOW])
    return np.clip(1.0 - bare * 1.6, 0.0, 1.0) * np.clip(1.0 - weights[:, WHEAT] * 2.0, 0.0, 1.0)
