"""
Containers as the top-down camera sees them: ``assets/sprites/miniwind/
topdown/<kind>.png`` for every container kind (game/entities.py).

The game is played from above, so a barrel is its round lid and its iron
hoops, a chest its banded lid with the lock plate at the front edge, a crate
its planks and cross-brace, a sack its tied neck, an urn its open mouth. Each
is drawn with the heads' dark outline and lit from the top left, on a soft
shadow, with the container's *front* towards the bottom of the image (the
way it is turned in the world: game/ui/world_objects.py).

Run from the repo root::

    python -m game.tools.make_container_art
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = os.path.join("assets", "sprites", "miniwind", "topdown")
SIZE = 256
SS = 4                                     # drawn this much larger, then reduced
OUTLINE = (38, 24, 14, 255)
IRON = (74, 74, 82, 255)
IRON_HI = (128, 128, 138, 255)
GOLD = (214, 172, 74, 255)


def _canvas():
    return Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))


def _px(v):
    return int(round(v * SIZE * SS))


def _box(x0, y0, x1, y1):
    return [_px(x0), _px(y0), _px(x1), _px(y1)]


def _shade(img, strength=0.22):
    """Light from the top left across what is drawn (alpha untouched)."""
    a = np.asarray(img).astype(np.float32)
    h, w = a.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    k = 1.0 + strength * (0.5 - (xs / w + ys / h) / 2.0) * 2.0
    a[..., :3] = np.clip(a[..., :3] * k[..., None], 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def _grain(img, seed, amount=10):
    """Wood or cloth grain: a little noise in the colour."""
    a = np.asarray(img).astype(np.float32)
    rng = np.random.default_rng(seed)
    n = rng.normal(0, amount, a.shape[:2]).astype(np.float32)
    a[..., :3] = np.clip(a[..., :3] + n[..., None], 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def _finish(img):
    """Shadow under it, reduced to size."""
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    alpha = img.split()[3]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 120), mask=alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (7, 9))
    out.alpha_composite(img)
    return out


def barrel():
    img = _canvas()
    d = ImageDraw.Draw(img)
    c, r = 0.5, 0.36
    d.ellipse(_box(c - r, c - r, c + r, c + r), fill=(132, 88, 48, 255),
              outline=OUTLINE, width=_px(0.018))
    # The lid's staves.
    for k in range(-3, 4):
        x = c + k * r * 0.27
        half = math.sqrt(max(0.0, r * r * 0.86 - (x - c) ** 2))
        d.line([_px(x), _px(c - half), _px(x), _px(c + half)], fill=(92, 58, 30, 255),
               width=_px(0.008))
    img = _grain(img, 1)
    d = ImageDraw.Draw(img)
    # Two iron hoops round the rim, and the bung.
    for rr, col in ((r - 0.012, IRON), (r - 0.05, IRON_HI)):
        d.ellipse(_box(c - rr, c - rr, c + rr, c + rr), outline=col, width=_px(0.022))
    d.ellipse(_box(c + 0.08, c - 0.13, c + 0.14, c - 0.07), fill=(60, 36, 18, 255),
              outline=OUTLINE, width=_px(0.006))
    return _finish(_shade(img))


def chest():
    img = _canvas()
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 0.17, 0.27, 0.83, 0.71
    d.rounded_rectangle(_box(x0, y0, x1, y1), radius=_px(0.03), fill=(140, 86, 42, 255),
                        outline=OUTLINE, width=_px(0.018))
    # Lid boards along its length.
    for k in range(1, 4):
        y = y0 + (y1 - y0) * k / 4
        d.line([_px(x0 + 0.01), _px(y), _px(x1 - 0.01), _px(y)], fill=(96, 56, 26, 255),
               width=_px(0.008))
    img = _grain(img, 2)
    d = ImageDraw.Draw(img)
    # Iron bands across the lid, corner brackets, and the lock at the front.
    for x in (x0 + 0.13, x1 - 0.13):
        d.rectangle(_box(x - 0.025, y0, x + 0.025, y1), fill=IRON, outline=OUTLINE,
                    width=_px(0.006))
        for y in (y0 + 0.06, y1 - 0.06):
            d.ellipse(_box(x - 0.01, y - 0.01, x + 0.01, y + 0.01), fill=IRON_HI)
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        sx = 1 if cx == x0 else -1
        sy = 1 if cy == y0 else -1
        d.polygon([(_px(cx), _px(cy)), (_px(cx + sx * 0.07), _px(cy)),
                   (_px(cx), _px(cy + sy * 0.07))], fill=IRON, outline=OUTLINE)
    d.rounded_rectangle(_box(0.45, y1 - 0.07, 0.55, y1 + 0.03), radius=_px(0.012),
                        fill=GOLD, outline=OUTLINE, width=_px(0.006))
    d.ellipse(_box(0.49, y1 - 0.035, 0.51, y1 - 0.01), fill=OUTLINE)
    return _finish(_shade(img))


def crate():
    img = _canvas()
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 0.19, 0.19, 0.81, 0.81
    d.rectangle(_box(x0, y0, x1, y1), fill=(176, 132, 78, 255), outline=OUTLINE,
                width=_px(0.018))
    for k in range(1, 5):
        y = y0 + (y1 - y0) * k / 5
        d.line([_px(x0), _px(y), _px(x1), _px(y)], fill=(122, 86, 46, 255), width=_px(0.007))
    img = _grain(img, 3, 12)
    d = ImageDraw.Draw(img)
    # The frame and its brace.
    t = 0.05
    frame = (150, 108, 60, 255)
    for box in ((x0, y0, x1, y0 + t), (x0, y1 - t, x1, y1), (x0, y0, x0 + t, y1),
                (x1 - t, y0, x1, y1)):
        d.rectangle(_box(*box), fill=frame, outline=OUTLINE, width=_px(0.006))
    d.line([_px(x0 + t), _px(y1 - t), _px(x1 - t), _px(y0 + t)], fill=OUTLINE,
           width=_px(0.07))
    d.line([_px(x0 + t), _px(y1 - t), _px(x1 - t), _px(y0 + t)], fill=frame,
           width=_px(0.055))
    for cx, cy in ((x0 + t / 2, y0 + t / 2), (x1 - t / 2, y0 + t / 2),
                   (x0 + t / 2, y1 - t / 2), (x1 - t / 2, y1 - t / 2)):
        d.ellipse(_box(cx - 0.009, cy - 0.009, cx + 0.009, cy + 0.009), fill=IRON)
    return _finish(_shade(img))


def sack():
    img = _canvas()
    d = ImageDraw.Draw(img)
    pts = []
    for k in range(48):
        a = k / 48 * math.tau
        r = 0.3 + 0.025 * math.sin(a * 5 + 0.7) + 0.015 * math.sin(a * 9)
        pts.append((_px(0.5 + math.cos(a) * r), _px(0.53 + math.sin(a) * r * 0.92)))
    d.polygon(pts, fill=(176, 150, 104, 255), outline=OUTLINE, width=_px(0.018))
    img = _grain(img, 4, 14)
    d = ImageDraw.Draw(img)
    # Folds gathering to the tied neck, the tie, and the gathered cloth above it.
    for k in range(10):
        a = k / 10 * math.tau
        d.line([_px(0.5 + math.cos(a) * 0.07), _px(0.5 + math.sin(a) * 0.07),
                _px(0.5 + math.cos(a) * 0.24), _px(0.53 + math.sin(a) * 0.22)],
               fill=(132, 108, 70, 255), width=_px(0.007))
    d.ellipse(_box(0.43, 0.43, 0.57, 0.57), fill=(110, 76, 40, 255), outline=OUTLINE,
              width=_px(0.008))
    for k in range(6):
        a = k / 6 * math.tau + 0.3
        d.ellipse(_box(0.5 + math.cos(a) * 0.05 - 0.035, 0.5 + math.sin(a) * 0.05 - 0.035,
                       0.5 + math.cos(a) * 0.05 + 0.035, 0.5 + math.sin(a) * 0.05 + 0.035),
                  fill=(186, 160, 112, 255), outline=OUTLINE, width=_px(0.005))
    return _finish(_shade(img))


def urn():
    img = _canvas()
    d = ImageDraw.Draw(img)
    c = 0.5
    d.ellipse(_box(c - 0.29, c - 0.29, c + 0.29, c + 0.29), fill=(168, 92, 58, 255),
              outline=OUTLINE, width=_px(0.018))
    img = _grain(img, 5, 6)
    d = ImageDraw.Draw(img)
    # Painted band round the shoulder, the neck's rim, and the dark mouth.
    d.ellipse(_box(c - 0.22, c - 0.22, c + 0.22, c + 0.22), outline=(70, 36, 22, 255),
              width=_px(0.02))
    d.ellipse(_box(c - 0.14, c - 0.14, c + 0.14, c + 0.14), fill=(190, 112, 72, 255),
              outline=OUTLINE, width=_px(0.012))
    d.ellipse(_box(c - 0.09, c - 0.09, c + 0.09, c + 0.09), fill=(28, 16, 10, 255),
              outline=OUTLINE, width=_px(0.006))
    return _finish(_shade(img))


KINDS = {"barrel": barrel, "chest": chest, "crate": crate, "sack": sack, "urn": urn}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for kind, draw in KINDS.items():
        draw().save(os.path.join(OUT_DIR, f"{kind}.png"))
    print(f"{len(KINDS)} containers drawn into {OUT_DIR}")


if __name__ == "__main__":
    main()
