"""
Generate the blood stamps baked into the ground (game/gore_fx.py).

Writes ``assets/sprites/miniwind/blood_stamps/{splash,drop,pool,chunk}_N.png``:
128x128 RGBA blots in dark, wet reds with rough edges and thrown droplets,
seen from above. Replace them with your own art freely (same names).

Run:  python -m game.tools.make_blood_stamps
"""

from __future__ import annotations

import math
import os
import random
import zlib

from PIL import Image, ImageDraw, ImageFilter

SIZE = 128
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "sprites",
                   "miniwind", "blood_stamps")
#: kind -> (variants, core radius as a fraction of the half-size, droplets).
KINDS = {"splash": (4, 0.45, 14), "drop": (4, 0.3, 4), "pool": (3, 0.72, 6),
         "chunk": (3, 0.38, 8)}


def _stamp(kind, seed):
    rng = random.Random(seed)
    _n, core, drops = KINDS[kind]
    big = SIZE * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = big / 2
    r = c * core
    dark = (78, 2, 4) if kind != "chunk" else (52, 6, 6)
    deep = (60, 1, 3)
    # The body of the blot: many overlapping lobes of slightly different reds,
    # so its edge is lumpy and its middle uneven, never a neat disc.
    for _ in range(16 if kind != "drop" else 6):
        a = rng.uniform(0, 2 * math.pi)
        off = r * rng.uniform(0.0, 0.55)
        lr = r * rng.uniform(0.3, 0.7)
        x, y = c + math.cos(a) * off, c + math.sin(a) * off
        tone = dark if rng.random() < 0.6 else deep
        d.ellipse([x - lr, y - lr * rng.uniform(0.7, 1.0), x + lr, y + lr],
                  fill=tone + (rng.randint(200, 240),))
    # Thrown droplets, each with a short tapering fleck behind it.
    for _ in range(drops):
        a = rng.uniform(0, 2 * math.pi)
        dist = r * rng.uniform(1.05, 1.7)
        dr = c * rng.uniform(0.015, 0.05)
        x, y = c + math.cos(a) * dist, c + math.sin(a) * dist
        for k in range(4):
            t = k / 4.0
            fx, fy = x - math.cos(a) * dr * 3 * t, y - math.sin(a) * dr * 3 * t
            fr = dr * (1.0 - t * 0.7)
            d.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=dark + (220,))
    img = img.filter(ImageFilter.GaussianBlur(4))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    n = 0
    for kind, (variants, _core, _drops) in KINDS.items():
        for i in range(variants):
            _stamp(kind, zlib.crc32(f"{kind}{i}".encode())).save(
                os.path.join(OUT, f"{kind}_{i + 1}.png"))
            n += 1
    print(f"Wrote {n} blood stamps to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
