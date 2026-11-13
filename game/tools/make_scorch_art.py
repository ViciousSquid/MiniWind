"""
Scorched ground: the charred stamps grass fire leaves behind.

Four seamlessly tiling 128 x 128 images of burnt earth -- soot-black char,
brown where the heat was less, flecks of pale ash and the odd dark stalk --
with a ragged alpha so the edges of a burn are broken, not round. The game
bakes them into the terrain's paint where grass burnt out
(:meth:`game.runtime.MiniwindSession._scorch`), which also clears the grass.
And two of bare, turned earth: a burnt wheat field once the scorch has gone,
until its farmer sows it again (:mod:`game.fire_aftermath`).

Run from the repo root::

    python -m game.tools.make_scorch_art
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

OUT = os.path.join("assets", "sprites", "miniwind", "scorch")
SIZE = 128


def tiling_noise(rng, size, cells, octaves=4, persistence=0.55):
    """Fractal value noise in [0, 1] that wraps at the edges."""
    total = np.zeros((size, size), np.float32)
    amp = norm = 0.0
    amp = 1.0
    for o in range(octaves):
        n = cells * (2 ** o)
        grid = rng.random((n, n)).astype(np.float32)
        # Upsample a 3 x 3 tiling and keep the middle: it wraps.
        big = np.tile(grid, (3, 3))
        img = Image.fromarray((big * 255).astype(np.uint8), "L").resize(
            (size * 3, size * 3), Image.BICUBIC)
        total += amp * np.asarray(img, np.float32)[size:2 * size, size:2 * size] / 255.0
        norm += amp
        amp *= persistence
    total /= norm
    return (total - total.min()) / max(1e-6, total.max() - total.min())


def scorch(seed):
    rng = np.random.default_rng(seed)
    char = tiling_noise(rng, SIZE, 4)
    fine = tiling_noise(rng, SIZE, 16, octaves=3)
    ash = tiling_noise(rng, SIZE, 24, octaves=2)
    black = np.array([0.045, 0.038, 0.034])
    brown = np.array([0.20, 0.13, 0.08])
    pale = np.array([0.52, 0.50, 0.47])
    mix = np.clip((char - 0.35) * 1.6, 0, 1)[..., None]
    rgb = black * (1 - mix) + brown * mix
    rgb = rgb * (0.75 + 0.5 * fine[..., None])
    flecks = np.clip((ash - 0.78) * 7.0, 0, 1)[..., None]
    rgb = rgb * (1 - flecks) + pale * flecks
    # Burnt stalks: short dark strokes.
    stalks = np.zeros((SIZE, SIZE), np.float32)
    for _ in range(40):
        x, y = rng.integers(0, SIZE, 2)
        ang = rng.uniform(0, np.pi)
        for t in range(int(rng.integers(4, 11))):
            px = int(x + np.cos(ang) * t) % SIZE
            py = int(y + np.sin(ang) * t) % SIZE
            stalks[py, px] = 1.0
    rgb = rgb * (1 - 0.6 * stalks[..., None])
    # Opaque: no grass grows through it (thin paint lets meadow blades through).
    alpha = np.ones_like(char)
    out = np.dstack([np.clip(rgb, 0, 1), alpha])
    return Image.fromarray((out * 255).astype(np.uint8), "RGBA")


def earth(seed):
    """Bare earth, turned over: what a burnt wheat field is once the scorch
    has gone and before it is sown -- brown soil in furrows, a little ash."""
    rng = np.random.default_rng(seed)
    clods = tiling_noise(rng, SIZE, 8)
    fine = tiling_noise(rng, SIZE, 24, octaves=3)
    yy = np.arange(SIZE, dtype=np.float32)[:, None] * np.ones((1, SIZE), np.float32)
    furrow = 0.5 + 0.5 * np.cos(yy / SIZE * 2 * np.pi * 8 + (clods - 0.5) * 1.6)
    dark = np.array([0.22, 0.15, 0.09])
    light = np.array([0.42, 0.31, 0.20])
    k = np.clip(furrow * 0.7 + clods * 0.3, 0, 1)[..., None]
    rgb = dark * (1 - k) + light * k
    rgb = rgb * (0.82 + 0.36 * fine[..., None])
    ash = np.clip((tiling_noise(rng, SIZE, 20, octaves=2) - 0.83) * 6.0, 0, 1)[..., None]
    rgb = rgb * (1 - ash) + np.array([0.45, 0.43, 0.40]) * ash
    alpha = np.ones_like(clods)
    out = np.dstack([np.clip(rgb, 0, 1), alpha])
    return Image.fromarray((out * 255).astype(np.uint8), "RGBA")


def main():
    os.makedirs(OUT, exist_ok=True)
    for i in range(4):
        path = os.path.join(OUT, f"scorch_{i}.png")
        scorch(1000 + i).save(path, optimize=True)
        print("wrote", path)
    for i in range(2):
        path = os.path.join(OUT, f"earth_{i}.png")
        earth(2000 + i).save(path, optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
