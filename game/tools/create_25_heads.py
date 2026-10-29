"""Create 25 new MiniWind head portraits from existing, hand-authored heads.

The existing 512px-style PNGs are the source of truth for the game's look.
Each new character starts from a *different* source face, receives a distinct
costume/colour treatment and a small individually drawn feature. The source art
is never modified. Run from the repo root:

    python -m game.tools.create_25_heads

Requires Pillow and NumPy (already MiniWind dependencies).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "assets" / "sprites" / "heads"
# Diverse source characters, not 25 copies of one underlying face.
SOURCE_IDS = (3, 9, 15, 21, 27, 33, 39, 45, 51, 57, 63, 69, 75,
              81, 87, 93, 99, 105, 111, 117, 123, 129, 135, 145, 155)
FIRST_NEW = 162
assert len(SOURCE_IDS) == 25

# Muted fabric and metal colours to fit the existing fantasy heads.
ACCENTS = (
    (171, 132, 70), (123, 159, 140), (174, 104, 78),
    (91, 129, 167), (154, 125, 155), (180, 160, 105),
    (117, 141, 96), (160, 98, 108), (107, 148, 165),
)


def _hsv_tint(im: Image.Image, index: int) -> Image.Image:
    """Preserve the source linework and shading; tint hair/headwear, not skin."""
    rgba = np.asarray(im.convert("RGBA")).copy()
    pixels = rgba[:, :, :3].astype(np.float32) / 255.0
    maximum = pixels.max(axis=2)
    minimum = pixels.min(axis=2)
    difference = maximum - minimum
    saturation = difference / np.maximum(maximum, .00001)

    # Natural skin tones remain recognisable. Clothing and hair can change.
    r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    skin = ((r > g * 1.05) & (g > b * .95) & (r > .22)
            & (saturation > .12) & (saturation < .66))
    occupied = (rgba[:, :, 3] > 16) & (saturation > .13) & ~skin
    # Channel-mix, rather than flat colour replacement, retains painted details.
    variations = (
        (1.10, .97, .88), (.86, 1.11, 1.01), (1.07, .90, 1.13),
        (.91, 1.01, 1.14), (1.14, 1.03, .87), (.88, 1.13, 1.07),
        (1.09, .88, 1.06), (.93, 1.11, .91), (1.04, .98, 1.14),
    )
    mult = np.array(variations[index % len(variations)], dtype=np.float32)
    changed = np.clip((pixels - .12) * mult + .12, 0.0, 1.0)
    pixels[occupied] = changed[occupied]
    rgba[:, :, :3] = np.rint(pixels * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def _feature(im: Image.Image, index: int) -> Image.Image:
    """Add a restrained period accessory, positioned relative to the actual art."""
    bbox = im.getchannel("A").point(lambda p: 255 if p > 20 else 0).getbbox()
    if not bbox:
        raise ValueError("Head portrait has no opaque subject")
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if w < 24 or h < 24:
        raise ValueError("Head portrait subject is unexpectedly small")
    cx = (x0 + x1) / 2.0
    accent = ACCENTS[index % len(ACCENTS)]
    shadow = tuple(max(0, int(v * .35)) for v in accent)
    shine = tuple(min(255, int(v * 1.18 + 15)) for v in accent)
    # A few small strokes supplement different source faces, rather than
    # replacing the original artist's hair, eyes or silhouette.
    overlay = Image.new("RGBA", im.size)
    d = ImageDraw.Draw(overlay, "RGBA")
    kind = index % 5
    width = max(2, round(w / 85))
    if kind == 0:  # fine woven brow band
        y = y0 + .25 * h
        d.arc((x0+.18*w, y-.045*h, x1-.18*w, y+.09*h),
              182, 358, fill=shadow+(210,), width=width+2)
        d.arc((x0+.18*w, y-.052*h, x1-.18*w, y+.075*h),
              182, 358, fill=accent+(215,), width=width)
        d.ellipse((cx-width*2, y-width*2, cx+width*2, y+width*2),
                  fill=shine+(230,))
    elif kind == 1:  # side hair pin / brass clasp
        x = x0 + .23*w
        y = y0 + .31*h
        d.ellipse((x-3*width, y-3*width, x+3*width, y+3*width),
                  fill=shadow+(225,))
        d.ellipse((x-2*width, y-2*width, x+2*width, y+2*width),
                  fill=accent+(230,))
        d.ellipse((x-width, y-width, x, y), fill=shine+(220,))
    elif kind == 2:  # small stitched cowl seam
        y = y0 + .12*h
        a, b = (cx-.17*w, y), (cx+.17*w, y+.025*h)
        d.line((a, b), fill=shadow+(195,), width=width+2)
        d.line((a, b), fill=accent+(205,), width=width)
        for n in range(4):
            x = a[0]+(n+1)*(b[0]-a[0])/5
            d.line((x, y-.008*h, x-.012*w, y+.019*h),
                   fill=shine+(190,), width=max(1,width//2))
    elif kind == 3:  # one discreet silver earring
        x, y = x1-.23*w, y0+.60*h
        r = .035*w
        d.ellipse((x-r, y-r, x+r, y+r), outline=shadow+(205,), width=width+2)
        d.ellipse((x-r, y-r, x+r, y+r), outline=accent+(230,), width=width)
        d.ellipse((x-r*.4, y+r, x+r*.4, y+r*1.8), fill=shine+(225,))
    else:  # embroidered stripe on the headdress
        y = y0 + .115*h
        d.arc((x0+.25*w, y, x1-.25*w, y+.12*h), 190, 350,
              fill=shadow+(215,), width=width+2)
        d.arc((x0+.25*w, y, x1-.25*w, y+.12*h), 190, 350,
              fill=accent+(225,), width=width)
    return Image.alpha_composite(im, overlay)


def generate() -> list[Path]:
    sources = [DIR / f"head{n:02d}.png" for n in SOURCE_IDS]
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing original MiniWind heads: " + ", ".join(missing))
    files = []
    digests = set()
    for index, src in enumerate(sources):
        dst = DIR / f"head{FIRST_NEW + index}.png"
        with Image.open(src) as source:
            original = source.convert("RGBA")
            image = _feature(_hsv_tint(original, index), index)
            if image.size != original.size or image.getbbox() is None:
                raise AssertionError(f"Invalid head generated: {dst.name}")
            if image.tobytes() == original.tobytes():
                raise AssertionError(f"Head was not changed: {dst.name}")
            digest = hashlib.sha256(image.tobytes()).hexdigest()
            if digest in digests:
                raise AssertionError(f"Repeated visual image: {dst.name}")
            digests.add(digest)
            image.save(dst, format="PNG", optimize=True)
        files.append(dst)
    return files


if __name__ == "__main__":
    outputs = generate()
    for path in outputs:
        print(path.relative_to(ROOT))
    print(f"Created {len(outputs)} distinct, source-matched head PNGs")
