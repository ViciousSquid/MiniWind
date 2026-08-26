"""
Generate a **100x100 placeholder icon** for every spell in the registry, tinted
in a pastel wash by its magic school, so the Player-Spells cards have artwork
until real per-spell icons are dropped in.

Icons land in ``assets/sprites/spells/<spell_id>.png``; per-school fallbacks
(``_<school>.png``) and a generic ``_spell.png`` are written too, so a modded /
custom spell with no bespoke art still gets a sensible placeholder. Drop a real
100x100 PNG at ``assets/sprites/spells/<spell_id>.png`` to override one.

Run from the repo root:  python -m game.tools.make_spell_icons
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4
SIZE = 100
S = SIZE * SS

# Pastel wash + a deeper tone per school (bg, ink).
SCHOOL_PASTEL = {
    "destruction": ((250, 205, 200), (150, 60, 52)),
    "restoration": ((205, 240, 212), (52, 120, 74)),
    "alteration":  ((206, 224, 248), (54, 92, 150)),
    "conjuration": ((224, 210, 246), (98, 66, 150)),
    "illusion":    ((247, 214, 240), (150, 66, 130)),
    "mysticism":   ((205, 238, 236), (46, 118, 116)),
    "default":     ((228, 226, 232), (96, 96, 108)),
}


def pastel(school):
    return SCHOOL_PASTEL.get(str(school or "").lower(), SCHOOL_PASTEL["default"])


def _rune(d, cx, cy, r, ink):
    """A simple arcane emblem: an eight-point star inside a ring."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ink, width=SS * 2)
    for k in range(8):
        a = math.pi * k / 4.0
        rr = r * (0.9 if k % 2 == 0 else 0.5)
        d.line([(cx, cy), (cx + math.cos(a) * rr, cy + math.sin(a) * rr)],
               fill=ink, width=SS * 2)
    d.ellipse([cx - r * 0.18, cy - r * 0.18, cx + r * 0.18, cy + r * 0.18], fill=ink)


def render(school, accent=None):
    bg, ink = pastel(school)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(S * 0.06)
    # Parchment-ish rounded tile.
    d.rounded_rectangle([m, m, S - m, S - m], radius=int(S * 0.10), fill=bg,
                        outline=ink, width=SS * 2)
    # Inner keyline.
    b = int(S * 0.11)
    d.rounded_rectangle([b, b, S - b, S - b], radius=int(S * 0.07),
                        outline=(255, 255, 255, 120), width=SS)
    # Central emblem, in the element accent when given, else the school ink.
    glyph = accent or ink
    _rune(d, S // 2, S // 2, int(S * 0.26), glyph)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    out_dir = os.path.join(root, "assets", "sprites", "spells")
    os.makedirs(out_dir, exist_ok=True)

    from game.rpg import magic
    n = 0
    for sid, sp in magic.SPELLS.items():
        col = sp.color if getattr(sp, "color", None) else None
        render(sp.school, accent=tuple(col) if col else None).save(
            os.path.join(out_dir, f"{sid}.png"))
        n += 1
    for school in SCHOOL_PASTEL:
        tag = "_spell" if school == "default" else f"_{school}"
        render(school).save(os.path.join(out_dir, f"{tag}.png"))
    print(f"Wrote {n} spell placeholder icons (+ {len(SCHOOL_PASTEL)} fallbacks) to {out_dir}")


if __name__ == "__main__":
    main()
