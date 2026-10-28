"""
Icons for the books and notes that have none (assets/sprites/items/<id>.png).

* A **book** gets the red-bound book's art (``book_blade.png``) with its
  cover recoloured -- the gold trim and the pages untouched -- each title in
  a colour of its own, picked stably from its id.
* A **note** gets a sheet of paper drawn here: a little turned, a folded
  corner, lines of writing; a page of the Millbrook Crier is printed, with a
  headline.

Existing icons are left alone. Run from the repo root::

    python -m game.tools.make_book_icons
"""

from __future__ import annotations

import colorsys
import os
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ICON_DIR = os.path.join("assets", "sprites", "items")
BASE_BOOK = os.path.join(ICON_DIR, "book_blade.png")
SIZE = 256

#: Cover colours (hue 0..1, saturation, value scale) a book may be bound in.
COVERS = ((0.58, 0.55, 0.85), (0.33, 0.45, 0.70), (0.08, 0.60, 0.80), (0.75, 0.40, 0.70),
          (0.12, 0.35, 0.60), (0.50, 0.40, 0.65), (0.95, 0.55, 0.60), (0.00, 0.00, 0.35),
          (0.15, 0.50, 0.90), (0.62, 0.30, 0.45))


def _stable(item_id) -> int:
    return zlib.crc32(str(item_id).encode("utf-8"))


def book_icon(item_id) -> Image.Image:
    """The red book, rebound in *item_id*'s own colour."""
    img = np.asarray(Image.open(BASE_BOOK).convert("RGBA")).astype(np.float32) / 255.0
    rgb = img[..., :3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # The red leather: red well above green, unlike the gold (red ~ green).
    cover = (r > g * 1.6) & (sat > 0.3) & (img[..., 3] > 0.05)
    hue, s_new, v_scale = COVERS[_stable(item_id) % len(COVERS)]
    out = img.copy()
    ys, xs = np.nonzero(cover)
    for y, x in zip(ys, xs):
        h, s, v = colorsys.rgb_to_hsv(*rgb[y, x])
        out[y, x, :3] = colorsys.hsv_to_rgb(hue, min(1.0, s * s_new / 0.6), v * v_scale)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGBA")


def note_icon(item_id) -> Image.Image:
    """A sheet of paper; a printed page for the Crier."""
    seed = _stable(item_id)
    printed = "crier" in item_id
    big = Image.new("RGBA", (SIZE * 2, SIZE * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    w, h = 250, 320
    x0, y0 = (SIZE * 2 - w) // 2, (SIZE * 2 - h) // 2
    paper = (236, 226, 198, 255) if not printed else (228, 224, 210, 255)
    fold = 46
    d.polygon([(x0, y0), (x0 + w - fold, y0), (x0 + w, y0 + fold), (x0 + w, y0 + h),
               (x0, y0 + h)], fill=paper, outline=(120, 100, 70, 255))
    d.polygon([(x0 + w - fold, y0), (x0 + w - fold, y0 + fold), (x0 + w, y0 + fold)],
              fill=(205, 190, 155, 255), outline=(120, 100, 70, 255))
    ink = (60, 45, 35, 255)
    rng = np.random.default_rng(seed)
    y = y0 + 40
    if printed:
        d.rectangle([x0 + 24, y, x0 + w - fold - 6, y + 26], fill=(45, 40, 38, 255))
        y += 44
        for col in (0, 1):
            cx = x0 + 24 + col * (w - 48) // 2
            for k in range(9):
                d.line([cx, y + k * 20, cx + (w - 48) // 2 - 14, y + k * 20], fill=ink, width=5)
    else:
        while y < y0 + h - 30:
            length = int(rng.uniform(0.45, 0.95) * (w - 48))
            d.line([x0 + 24, y, x0 + 24 + length, y], fill=ink, width=6)
            y += int(rng.uniform(24, 32))
    angle = float(rng.uniform(-14, 14))
    big = big.rotate(angle, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 90), mask=big.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    canvas = Image.new("RGBA", big.size, (0, 0, 0, 0))
    canvas.alpha_composite(shadow, (8, 10))
    canvas.alpha_composite(big)
    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    import sys
    sys.path.insert(0, os.getcwd())
    from game.rpg import items
    made = 0
    for d in items.items_by_category(items.BOOK):
        path = os.path.join(ICON_DIR, f"{d.id}.png")
        if os.path.isfile(path):
            continue
        (note_icon(d.id) if d.get("note") else book_icon(d.id)).save(path)
        made += 1
    print(f"{made} icons made")


if __name__ == "__main__":
    main()
