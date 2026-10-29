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

A map may carry a fifth channel (HxWx5):

* **tundra** -- tall, dense autumn shrub-grass: deep green leaves with
  flame-orange, red and gold shoots and the odd purple flower, as on a
  northern heath in autumn. It is grown on the CPU (grass blades carry their
  own colour), so the GPU texture stays the four channels above and a
  four-channel map behaves exactly as before.

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

DESERT, SNOW, SWAMP, WHEAT, TUNDRA = range(5)
NAMES = ("desert", "snow", "swamp", "wheat", "tundra")
#: Channels the GPU biome texture holds (RGBA); later channels are CPU-only.
GPU_CHANNELS = 4

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
WHEAT_SIZE = (11.0, 17.0)
WHEAT_COLOUR = np.array((0.86, 0.70, 0.32), np.float32)
WHEAT_TIP = np.array((0.95, 0.84, 0.52), np.float32)
#: Wheat tufts per chunk at full coverage, stalks per tuft, tuft radius.
WHEAT_MAX_PER_CHUNK = 9000
WHEAT_STALKS_PER_TUFT = 8
WHEAT_TUFT_RADIUS = 9.0

#: Wheat through the year: young blades are this green.
WHEAT_YOUNG = np.array((0.36, 0.55, 0.20), np.float32)
#: Stubble after harvest.
WHEAT_STUBBLE = np.array((0.62, 0.52, 0.30), np.float32)
#: A farming year in game days: four seasons of YEAR_DAYS / 4.
YEAR_DAYS = 28
SEASONS = ("spring", "summer", "autumn", "winter")
#: Late autumn: the fields are cut to stubble.
HARVEST_AT = 0.70


def season_of(year_fraction: float) -> str:
    return SEASONS[int((float(year_fraction) % 1.0) * 4) % 4]


def wheat_stage(year_fraction: float) -> Tuple[float, float, float]:
    """``(height, ripeness, cover)`` of the wheat at a point in the year
    (0 = first day of spring): sprouting green in spring, shooting up very
    tall and turning gold through summer, standing ripe into autumn, cut to
    short stubble at :data:`HARVEST_AT`, bare and sparse through winter."""
    f = float(year_fraction) % 1.0
    ease = lambda t: (lambda c: c * c * (3.0 - 2.0 * c))(min(1.0, max(0.0, t)))
    if f < 0.25:                                   # spring: sprouting
        k = ease(f / 0.25)
        return 0.12 + 0.43 * k, 0.0, 0.55 + 0.45 * k
    if f < 0.5:                                    # summer: tall, ripening
        k = ease((f - 0.25) / 0.25)
        return 0.55 + 0.45 * k, k, 1.0
    if f < HARVEST_AT:                             # autumn: ripe, standing
        return 1.0, 1.0, 1.0
    if f < 0.75:                                   # harvest: stubble
        return 0.1, 1.0, 0.8
    return 0.08, 1.0, 0.35 * (1.0 - ease((f - 0.75) / 0.2))   # winter: bare


#: Tundra: tall leafy shrub-grass. Sizes are multiples of the blade height;
#: tufts per chunk at full coverage, stems per tuft and tuft radius.
TUNDRA_SIZE = (6.0, 11.0)
TUNDRA_MAX_PER_CHUNK = 7000
TUNDRA_STEMS_PER_TUFT = 7
TUNDRA_TUFT_RADIUS = 16.0
#: The heath's colours, and how often each grows (green leaves dominate;
#: flame-orange and red shoots come up in patches; gold and a rare violet).
TUNDRA_PALETTE = np.array((
    (0.20, 0.33, 0.13),     # deep leaf green
    (0.33, 0.42, 0.17),     # olive
    (0.46, 0.44, 0.16),     # dry olive
    (0.90, 0.46, 0.10),     # flame orange
    (0.78, 0.20, 0.07),     # red
    (0.92, 0.70, 0.20),     # gold
    (0.50, 0.30, 0.58),     # fireweed violet
), np.float32)
TUNDRA_GREENS = (0, 1, 2)
TUNDRA_FLAMES = (3, 4, 5)
TUNDRA_FLOWER = 6
#: The ground under the heath: russet-brown leaf litter.
TUNDRA_GROUND = np.array((0.36, 0.30, 0.16), np.float32)

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
    if (not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] not in (4, 5)
            or arr.dtype != np.uint8 or arr.size == 0):
        print("[Terrain] Ignoring biome map that is not an HxWx4 (or x5) uint8 image")
        return None
    return arr


def sample(biome_map: Optional[np.ndarray], bounds, xs, zs) -> np.ndarray:
    """Bilinear biome weights (n x channels, 0..1) at world points *xs*, *zs*:
    four columns for a four-channel map, five with tundra.

    *bounds* is ``((min_x, max_x), (min_z, max_z))``. Outside the bounds,
    and with no map, every weight is zero."""
    xs = np.asarray(xs, np.float32).ravel()
    zs = np.asarray(zs, np.float32).ravel()
    channels = biome_map.shape[2] if biome_map is not None else 4
    out = np.zeros((len(xs), channels), np.float32)
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
    if weights.shape[1] > TUNDRA:
        a = (_coverage(weights[:, TUNDRA]) * 0.85)[:, None]
        out = out * (1 - a) + TUNDRA_GROUND[None, :] * a
    return np.clip(out, 0.0, 1.0)


def grass_keep(weights: np.ndarray) -> np.ndarray:
    """How much ordinary grass survives (0..1): none on sand, snow or in a
    wheat field (which grows its own), thinned in the swamp."""
    bare = np.maximum(weights[:, DESERT], weights[:, SNOW])
    keep = np.clip(1.0 - bare * 1.6, 0.0, 1.0) * np.clip(1.0 - weights[:, WHEAT] * 2.0, 0.0, 1.0)
    if weights.shape[1] > TUNDRA:
        # The heath grows its own (:func:`tundra_colours`); meadow thins under it.
        keep = keep * np.clip(1.0 - weights[:, TUNDRA] * 1.5, 0.0, 1.0)
    return keep


def tundra_colours(rng, count: int, patch: np.ndarray) -> np.ndarray:
    """Colours for *count* tundra stems. *patch* (0..1 per stem, a smooth
    field) sets where flame-coloured shoots crowd in among the green, so the
    heath glows in drifts rather than as confetti."""
    patch = np.asarray(patch, np.float32)
    roll = rng.random(count)
    flame = roll < 0.12 + 0.55 * patch * patch
    flower = (~flame) & (rng.random(count) < 0.025)
    pick = np.where(flame, rng.choice(TUNDRA_FLAMES, count, p=(0.5, 0.3, 0.2)),
                    rng.choice(TUNDRA_GREENS, count, p=(0.5, 0.35, 0.15)))
    pick = np.where(flower, TUNDRA_FLOWER, pick)
    colours = TUNDRA_PALETTE[pick]
    # A little per-stem variation in shade.
    return np.clip(colours * rng.uniform(0.85, 1.12, (count, 1)), 0.0, 1.0).astype(np.float32)
