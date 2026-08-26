"""
Generate the **spellbook** world/inventory sprites, matching the Tidy plugin's
book art: a coloured hardcover with a cream label, a centre glyph and a footer
rule on the left, and lined page-edges on the right.

Four covers are produced — maroon, green, brown, indigo — each with its own
centre glyph, into ``assets/sprites/miniwind/spellbook_<cover>.png``. Drawn with
Pillow at 4x and downsampled, like the other MiniWind art generators.

Run from the repo root:  python -m game.tools.make_spellbooks
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4
SIZE = 128
S = SIZE * SS

PAGE = (239, 233, 208)      # cream page edge
PAGE_LINE = (206, 198, 168)

# cover -> (cover fill, accent/label/glyph colour, dark shade, glyph)
COVERS = {
    "red":    ((122, 26, 38), (226, 198, 122), (86, 12, 22), "circle"),
    "green":  ((28, 74, 52), (214, 198, 128), (16, 48, 34), "cross"),
    "brown":  ((74, 48, 30), (232, 224, 196), (48, 30, 18), "circle"),
    "purple": ((58, 44, 96), (206, 190, 236), (36, 26, 66), "diamond"),
}


def _draw_glyph(d, kind, cx, cy, r, col, dark):
    if kind == "circle":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=dark, width=SS)
        d.ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], fill=dark)
    elif kind == "cross":
        w = int(r * 0.5)
        d.line([(cx - r, cy - r), (cx + r, cy + r)], fill=col, width=w)
        d.line([(cx - r, cy + r), (cx + r, cy - r)], fill=col, width=w)
    elif kind == "diamond":
        d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                  outline=col, width=SS * 2)


def render(cover_fill, accent, dark, glyph):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m = int(S * 0.06)                       # outer margin
    x0, y0, x1, y1 = m, m, S - m, S - m
    split = int(x0 + (x1 - x0) * 0.72)      # cover | pages divide

    # Page block (right), with ruled lines.
    d.rectangle([split, y0, x1, y1], fill=PAGE)
    for i in range(1, 13):
        ly = y0 + (y1 - y0) * i / 13
        d.line([(split + SS * 2, ly), (x1 - SS * 2, ly)], fill=PAGE_LINE, width=SS)

    # Cover (left).
    d.rectangle([x0, y0, split, y1], fill=cover_fill)

    # Thin inset border framing the whole book.
    b = int(S * 0.035)
    d.rectangle([x0 + b, y0 + b, x1 - b, y1 - b], outline=accent, width=SS)

    # Cream label near the top of the cover.
    lx0 = x0 + int((split - x0) * 0.12)
    lx1 = split - int((split - x0) * 0.06)
    ly0 = y0 + int((y1 - y0) * 0.12)
    ly1 = y0 + int((y1 - y0) * 0.34)
    d.rounded_rectangle([lx0, ly0, lx1, ly1], radius=int(S * 0.03),
                        fill=accent, outline=dark, width=SS)

    # Centre glyph.
    cx = (x0 + split) // 2
    cy = int(y0 + (y1 - y0) * 0.58)
    _draw_glyph(d, glyph, cx, cy, int((split - x0) * 0.16), accent, dark)

    # Footer rule.
    fx0 = x0 + int((split - x0) * 0.18)
    fx1 = split - int((split - x0) * 0.18)
    fy = y0 + int((y1 - y0) * 0.84)
    d.rounded_rectangle([fx0, fy, fx1, fy + int(S * 0.03)],
                        radius=int(S * 0.012), fill=accent)

    # Soft drop shadow + downsample.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    alpha = img.split()[3]
    ImageDraw.Draw(shadow).bitmap((0, 0), alpha.point(lambda a: 90 if a > 40 else 0),
                                  fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SS * 2))
    out = Image.alpha_composite(shadow, img)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    out_dir = os.path.join(root, "assets", "sprites", "miniwind")
    os.makedirs(out_dir, exist_ok=True)
    for name, (fill, accent, dark, glyph) in COVERS.items():
        render(fill, accent, dark, glyph).save(
            os.path.join(out_dir, f"spellbook_{name}.png"))
    # A generic default (maroon) for a spellbook with no cover chosen.
    fill, accent, dark, glyph = COVERS["red"]
    render(fill, accent, dark, glyph).save(os.path.join(out_dir, "spellbook.png"))
    print(f"Wrote {len(COVERS)} spellbook covers (+ default) to {out_dir}")


if __name__ == "__main__":
    main()
