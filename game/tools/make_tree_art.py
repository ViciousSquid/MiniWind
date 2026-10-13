"""
Top-down tree art for the biomes, in the style of ``tree01..07.png``: a
canopy seen from above with a dark outline, on a transparent background.

* ``pine01/02.png`` -- conifers: star-shaped tiers of needles.
* ``snowpine01/02.png`` -- the same, snow lying on the boughs.
* ``palm01.png`` -- an oasis palm: radiating fronds.
* ``deadtree01.png`` -- a bare, grey-brown tree for the desert's edge.
* ``scrub01/02.png`` -- dry desert brush.
* ``willow01.png`` -- a swamp willow: drooping strands, olive.

Run from the repo root::

    python -m game.tools.make_tree_art
"""

from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join("assets", "textures")
SIZE = 256


def _canvas():
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def _outline(img, colour=(14, 34, 14, 255), width=3):
    """A dark rim around the canopy, as the hand-drawn trees have."""
    a = img.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(width * 2 + 1))
    rim = Image.new("RGBA", img.size, colour)
    rim.putalpha(grown)
    rim.alpha_composite(img)
    return rim


def pine(seed, snow=False):
    rng = random.Random(seed)
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = SIZE / 2
    tiers = 5
    for t in range(tiers):
        r = SIZE * 0.47 * (1.0 - t / (tiers + 0.6))
        points = 11 + t
        shade = 40 + t * 14
        col = (18 + t * 6, shade + 30, 28 + t * 5, 255)
        poly = []
        rot = rng.uniform(0, math.pi)
        for k in range(points * 2):
            a = rot + math.pi * k / points
            rr = r * (1.0 if k % 2 == 0 else rng.uniform(0.55, 0.7))
            poly.append((c + math.cos(a) * rr, c + math.sin(a) * rr))
        d.polygon(poly, fill=col)
        if snow:
            for k in range(points):
                a = rot + 2 * math.pi * k / points + rng.uniform(-0.15, 0.15)
                rr = r * rng.uniform(0.45, 0.85)
                x, y = c + math.cos(a) * rr, c + math.sin(a) * rr
                s = rng.uniform(4, 9) * (1.0 - t * 0.1)
                d.ellipse((x - s, y - s * 0.7, x + s, y + s * 0.7), fill=(236, 242, 250, 255))
    d.ellipse((c - 5, c - 5, c + 5, c + 5), fill=(70, 50, 30, 255))
    return _outline(img)


def palm(seed):
    rng = random.Random(seed)
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = SIZE / 2
    fronds = 9
    for k in range(fronds):
        a = 2 * math.pi * k / fronds + rng.uniform(-0.15, 0.15)
        length = SIZE * rng.uniform(0.38, 0.47)
        bend = rng.uniform(-0.25, 0.25)
        pts = []
        for s in range(13):
            f = s / 12.0
            aa = a + bend * f * f
            pts.append((c + math.cos(aa) * length * f, c + math.sin(aa) * length * f))
        for i, (x, y) in enumerate(pts[1:], 1):
            f = i / 12.0
            w = 16 * math.sin(math.pi * min(1.0, f * 1.1))
            nx, ny = -math.sin(a), math.cos(a)
            d.polygon([pts[i - 1], (x + nx * w, y + ny * w), (x, y), (x - nx * w, y - ny * w)],
                      fill=(60 + i * 3, 128 + i * 4, 40, 255))
        d.line(pts, fill=(46, 84, 26, 255), width=2)
    d.ellipse((c - 9, c - 9, c + 9, c + 9), fill=(110, 80, 40, 255))
    return _outline(img, (24, 44, 14, 255), 2)


def dead_tree(seed):
    rng = random.Random(seed)
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = SIZE / 2

    def branch(x, y, a, length, width, depth):
        if depth == 0 or length < 8:
            return
        x2, y2 = x + math.cos(a) * length, y + math.sin(a) * length
        d.line((x, y, x2, y2), fill=(104, 88, 70, 255), width=int(width))
        for _ in range(2):
            branch(x2, y2, a + rng.uniform(-0.7, 0.7), length * rng.uniform(0.55, 0.75),
                   max(1, width * 0.65), depth - 1)
    for k in range(6):
        a = 2 * math.pi * k / 6 + rng.uniform(-0.3, 0.3)
        branch(c, c, a, SIZE * 0.17, 9, 4)
    d.ellipse((c - 10, c - 10, c + 10, c + 10), fill=(96, 78, 60, 255))
    return _outline(img, (40, 32, 24, 255), 2)


def scrub(seed):
    rng = random.Random(seed)
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = SIZE / 2
    for _ in range(70):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, SIZE * 0.33)
        x, y = c + math.cos(a) * r, c + math.sin(a) * r
        s = rng.uniform(8, 20)
        tone = rng.uniform(0.8, 1.15)
        d.ellipse((x - s, y - s, x + s, y + s),
                  fill=(int(128 * tone), int(124 * tone), int(70 * tone), 255))
    return _outline(img, (70, 60, 34, 255), 2)


def willow(seed):
    rng = random.Random(seed)
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = SIZE / 2
    d.ellipse((c - SIZE * 0.36, c - SIZE * 0.36, c + SIZE * 0.36, c + SIZE * 0.36),
              fill=(70, 88, 40, 255))
    for _ in range(260):
        a = rng.uniform(0, 2 * math.pi)
        r0 = rng.uniform(0, SIZE * 0.2)
        r1 = rng.uniform(SIZE * 0.3, SIZE * 0.46)
        x0, y0 = c + math.cos(a) * r0, c + math.sin(a) * r0
        x1, y1 = c + math.cos(a) * r1, c + math.sin(a) * r1
        tone = rng.uniform(0.75, 1.2)
        d.line((x0, y0, x1, y1), fill=(int(96 * tone), int(118 * tone), int(52 * tone), 255),
               width=2)
    return _outline(img, (28, 38, 16, 255), 2)


ART = {
    "pine01.png": lambda: pine(1),
    "pine02.png": lambda: pine(7),
    "snowpine01.png": lambda: pine(3, snow=True),
    "snowpine02.png": lambda: pine(11, snow=True),
    "palm01.png": lambda: palm(5),
    "deadtree01.png": lambda: dead_tree(9),
    "scrub01.png": lambda: scrub(13),
    "scrub02.png": lambda: scrub(17),
    "willow01.png": lambda: willow(19),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, make in ART.items():
        make().save(os.path.join(OUT, name))
        print("wrote", os.path.join(OUT, name))


if __name__ == "__main__":
    main()
