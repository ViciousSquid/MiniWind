"""
The sky's clouds, baked once: a seamless 512 x 512 RGBA texture of cloud.

The water shader's sky (engine/shaders.py ``skyColor``) used to make its
clouds from fractal noise per pixel -- some 25 noise evaluations by day and 40
by night on every pixel of water. This bakes the same kind of cloud once, at
the first water draw, into a texture that tiles, and the shader reads it a
few times instead:

* **R** -- cloud: domain-warped fractal noise, 0..1;
* **G** -- the same cloud a little toward the sun (``SUN_DIR``): where R is
  thicker than G the cloud faces the light, where thinner it is in its own
  shadow;
* **B** -- the same toward the moon (``MOON_DIR``), for moonlit clouds;
* **A** -- a second, finer cloud for the moon's grey seas.

Pure numpy: no GL here, so it is tested headless. The renderer uploads it.
Baking takes about 0.2 s, so it is done while the game loads, on a thread of
its own (:func:`prepare`, called as Play starts -- behind the loading and
character creation); the renderer takes it when it is ready (:func:`ready`)
and until then the water's sky simply has no clouds.
"""

from __future__ import annotations

import numpy as np

import threading

_baked = None
_baking = None

SIZE = 512
#: Cells of the coarsest noise across the texture (it tiles at any multiple).
CELLS = 8
OCTAVES = 5
#: How far (in texels) the light-side copies are shifted.
LIGHT_SHIFT = 10.0
#: The shader's SUN_DIR and MOON_DIR, flattened onto the sky (x, z).
SUN_XZ = (0.4767, 0.5859)
MOON_XZ = (-0.17008, -0.17008)


def _tile_noise(rng, size, cells):
    """Smooth value noise that tiles: a random grid, interpolated with
    wrap-around."""
    grid = rng.random((cells, cells)).astype(np.float32)
    t = np.arange(size, dtype=np.float32) * cells / size
    i0 = np.floor(t).astype(int) % cells
    i1 = (i0 + 1) % cells
    f = t - np.floor(t)
    f = f * f * (3.0 - 2.0 * f)
    a = grid[i0][:, i0] * (1 - f)[None, :] + grid[i0][:, i1] * f[None, :]
    b = grid[i1][:, i0] * (1 - f)[None, :] + grid[i1][:, i1] * f[None, :]
    return a * (1 - f)[:, None] + b * f[:, None]


def _fbm(rng, size, cells, octaves):
    total = np.zeros((size, size), np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        total += amp * _tile_noise(rng, size, cells * (2 ** o))
        norm += amp
        amp *= 0.5
    return total / norm


def _sample(field, x, y):
    """Bilinear sample of a tiling field at fractional texel coordinates."""
    n = field.shape[0]
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    x0 %= n
    y0 %= n
    x1, y1 = (x0 + 1) % n, (y0 + 1) % n
    return ((field[y0, x0] * (1 - fx) + field[y0, x1] * fx) * (1 - fy)
            + (field[y1, x0] * (1 - fx) + field[y1, x1] * fx) * fy)


def bake(seed: int = 7, size: int = SIZE) -> np.ndarray:
    """The cloud texture: ``(size, size, 4)`` uint8 (see the module doc)."""
    rng = np.random.default_rng(seed)
    base = _fbm(rng, size, CELLS, OCTAVES)
    warp_x = _fbm(rng, size, CELLS, 4)
    warp_y = _fbm(rng, size, CELLS, 4)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    wx = xx + (warp_x - 0.5) * size * 0.18
    wy = yy + (warp_y - 0.5) * size * 0.18
    cloud = _sample(base, wx, wy)

    def toward(dx, dz):
        n = (dx * dx + dz * dz) ** 0.5 or 1.0
        return _sample(base, wx + dx / n * LIGHT_SHIFT, wy + dz / n * LIGHT_SHIFT)

    sun = toward(*SUN_XZ)
    moon = toward(*MOON_XZ)
    fine = _fbm(rng, size, CELLS * 4, 3)
    out = np.stack([cloud, sun, moon, fine], axis=-1)
    lo, hi = out.min(axis=(0, 1)), out.max(axis=(0, 1))
    out = (out - lo) / np.maximum(hi - lo, 1e-6)
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def prepare() -> None:
    """Start baking the clouds on a thread of their own, if not baked or
    baking already. Call it while the game loads."""
    global _baking
    if _baked is not None or (_baking is not None and _baking.is_alive()):
        return

    def work():
        global _baked
        _baked = bake()

    _baking = threading.Thread(target=work, name="sky-clouds", daemon=True)
    _baking.start()


def ready():
    """The baked clouds, or None while they are still baking (or were never
    asked for: then this starts them)."""
    if _baked is None and _baking is None:
        prepare()
    return _baked
