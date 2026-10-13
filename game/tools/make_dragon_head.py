"""
The dragon's head sprite, ``assets/sprites/heads/dragon01.png``.

Two ways to make it:

* ``python -m game.tools.make_dragon_head`` draws one: a green, scaled face
  in a mane of flame, brown horns, yellow eyes, long whiskers and an open,
  fanged mouth, on a transparent background.
* ``python -m game.tools.make_dragon_head --from picture.png`` uses a picture
  instead (a drawing on a white background): the white around the drawing is
  made transparent -- flooded in from the edges, so white inside it (teeth,
  eyes) stays -- trimmed to the drawing, squared and saved.
"""

from __future__ import annotations

import argparse
import math
import os
from collections import deque

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join("assets", "sprites", "heads", "dragon01.png")
SIZE = 512

OUTLINE = (20, 12, 8, 255)
GREEN = (46, 140, 70, 255)
GREEN_DARK = (28, 96, 48, 255)
GREEN_LIGHT = (84, 176, 96, 255)
RED = (226, 44, 14, 255)
ORANGE = (252, 128, 24, 255)
YELLOW = (255, 196, 40, 255)
HORN = (150, 98, 54, 255)
HORN_LIGHT = (196, 146, 92, 255)


def _flame(d, cx, base_y, height, width, lean, colours):
    """One tongue of the mane: nested pointed flames, outermost first."""
    for k, col in enumerate(colours):
        f = 1.0 - k * 0.28
        h, w = height * f, width * f
        tip = (cx + lean * h, base_y - h)
        d.polygon([(cx - w, base_y), (cx - w * 0.55, base_y - h * 0.45),
                   (tip[0] - w * 0.15, tip[1] + h * 0.25), tip,
                   (tip[0] + w * 0.2, tip[1] + h * 0.3),
                   (cx + w * 0.6, base_y - h * 0.4), (cx + w, base_y)], fill=col)


def _outlined(layer, width=5):
    a = layer.split()[3]
    rim = Image.new("RGBA", layer.size, OUTLINE)
    rim.putalpha(a.filter(ImageFilter.MaxFilter(width * 2 + 1)))
    rim.alpha_composite(layer)
    return rim


def draw():
    S = SIZE
    c = S / 2
    mane = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(mane)
    # The mane: flames fanning up and out behind the face.
    for k in range(-5, 6):
        a = k / 5.0
        _flame(d, c + a * 150, 300 - abs(a) * 40, 230 - abs(a) * 70, 52, a * 0.55,
               (RED, ORANGE, YELLOW))
    for side in (-1, 1):
        for k in range(4):
            y = 250 + k * 45
            _flame(d, c + side * (110 + k * 14), y + 70, 130 - k * 12, 44, side * 0.75,
                   (RED, ORANGE, YELLOW))
    _flame(d, c, 470, 70, 60, 0.0, (RED, ORANGE))          # the beard
    img = _outlined(mane, 4)
    # Horns, swept up and back.
    horns = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    h = ImageDraw.Draw(horns)
    for side in (-1, 1):
        base = (c + side * 62, 236)
        pts = [base]
        for t in range(1, 9):
            f = t / 8.0
            pts.append((base[0] + side * (f * 70 + f * f * 10), base[1] - f * 190))
        left = [(x - side * 14 * (1 - i / 8), y) for i, (x, y) in enumerate(pts)]
        right = [(x + side * 14 * (1 - i / 8), y) for i, (x, y) in enumerate(pts)]
        h.polygon(left + right[::-1], fill=HORN)
        h.line(pts, fill=HORN_LIGHT, width=4)
    img.alpha_composite(_outlined(horns, 3))
    # The face.
    face = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    f = ImageDraw.Draw(face)
    f.ellipse((c - 105, 220, c + 105, 400), fill=GREEN)           # brow and cheeks
    f.rounded_rectangle((c - 62, 300, c + 62, 440), 40, fill=GREEN)  # snout
    f.ellipse((c - 70, 380, c + 70, 470), fill=GREEN)              # jaw
    for row in range(4):                                           # nose ridges
        y = 300 + row * 22
        f.rounded_rectangle((c - 38, y, c + 38, y + 18), 9, fill=GREEN_LIGHT,
                            outline=GREEN_DARK, width=2)
    for side in (-1, 1):                                           # scales
        for r in range(3):
            for k in range(4):
                x = c + side * (62 + k * 11)
                y = 270 + r * 26 + k * 6
                f.arc((x - 9, y - 9, x + 9, y + 9), 0, 180, fill=GREEN_DARK, width=2)
    f.ellipse((c - 56, 392, c - 28, 414), fill=GREEN_DARK)         # nostrils
    f.ellipse((c + 28, 392, c + 56, 414), fill=GREEN_DARK)
    img.alpha_composite(_outlined(face, 4))
    d = ImageDraw.Draw(img)
    # Eyes under angry brows.
    for side in (-1, 1):
        ex = c + side * 66
        d.ellipse((ex - 20, 268, ex + 20, 300), fill=YELLOW, outline=OUTLINE, width=3)
        d.ellipse((ex - 7, 272, ex + 7, 296), fill=OUTLINE)
        d.polygon([(ex - side * 34, 248), (ex + side * 30, 262), (ex + side * 26, 276),
                   (ex - side * 30, 268)], fill=RED, outline=OUTLINE)
    # The mouth: dark, a red tongue, fangs.
    d.rounded_rectangle((c - 50, 422, c + 50, 470), 18, fill=(40, 6, 6, 255),
                        outline=OUTLINE, width=3)
    d.ellipse((c - 36, 446, c + 36, 474), fill=(232, 96, 96, 255))
    for side in (-1, 1):
        d.polygon([(c + side * 44, 424), (c + side * 32, 424), (c + side * 38, 448)],
                  fill=(250, 250, 240, 255), outline=OUTLINE)
        d.polygon([(c + side * 44, 468), (c + side * 32, 468), (c + side * 38, 448)],
                  fill=(250, 250, 240, 255), outline=OUTLINE)
    for k in range(-2, 3):
        d.polygon([(c + k * 12 - 5, 424), (c + k * 12 + 5, 424), (c + k * 12, 434)],
                  fill=(250, 250, 240, 255))
    # Whiskers, long and curling.
    for side in (-1, 1):
        pts = []
        for t in range(0, 30):
            u = t / 29.0
            x = c + side * (50 + u * 190)
            y = 405 + math.sin(u * math.pi) * 22 - max(0.0, u - 0.72) ** 2 * 1400
            pts.append((x, y))
        d.line(pts, fill=OUTLINE, width=11)
        d.line(pts, fill=GREEN, width=6)
    return img


def key_out_white(src, threshold=236):
    """*src* with the white around the drawing made transparent, trimmed and
    squared. White enclosed by the drawing is kept."""
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    px = img.load()

    def whitish(p):
        return p[0] >= threshold and p[1] >= threshold and p[2] >= threshold
    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        p = px[x, y]
        if p[3] and not whitish(p):
            continue
        px[x, y] = (255, 255, 255, 0)
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    # Soften the anti-aliased fringe: near-white pixels touching the cleared
    # area fade out rather than leaving a white halo.
    alpha = img.split()[3]
    edge = alpha.filter(ImageFilter.MinFilter(3))
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if p[3] and edge.getpixel((x, y)) == 0 and min(p[:3]) > 190:
                px[x, y] = (p[0], p[1], p[2], int(255 * (255 - min(p[:3])) / 65))
    box = img.getbbox()
    if box:
        img = img.crop(box)
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", help="a picture on white to use instead")
    ap.add_argument("-o", "--out", default=OUT)
    args = ap.parse_args()
    img = key_out_white(args.source) if args.source else draw()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    img.save(args.out)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
