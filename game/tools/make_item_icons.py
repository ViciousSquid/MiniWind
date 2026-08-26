"""
Generate MiniWind's inventory **item icons** — one clean, recognisable sprite per
item in ``game/data/items.json`` (swords, daggers, axes, bows, armour, potions,
ingredients, books, …).

Like :mod:`game.tools.make_sprites`, everything is drawn with Pillow at 4× and
downsampled for crisp anti-aliased edges — no external art, fully reproducible.
Each item's *shape* is inferred from its id / name / category and each is tinted
by its *material* (iron, steel, silver, elven, wood, leather, …) so a map full of
loot reads at a glance and iron vs. steel vs. elven gear is told apart.

Icons land in ``assets/sprites/items/<id>.png`` (64×64, transparent). A generic
fallback per category is also written (``_weapon.png``, ``_armour.png``, …) so a
modded item with no bespoke icon still gets something sensible.

Run from the repo root:  python -m game.tools.make_item_icons
"""

from __future__ import annotations

import json
import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4            # supersample factor
SIZE = 64         # final icon size (px)
S = SIZE * SS     # working canvas size

# --- material palettes -----------------------------------------------------
# (light, mid, dark) — light = highlight, dark = outline/shadow.
MATERIALS = {
    "iron":    ((176, 178, 188), (128, 130, 140), (70, 72, 82)),
    "steel":   ((196, 210, 230), (150, 166, 190), (86, 100, 124)),
    "silver":  ((228, 232, 240), (188, 194, 206), (130, 138, 152)),
    "elven":   ((208, 224, 150), (150, 180, 96), (92, 120, 60)),
    "silvered":((228, 232, 240), (188, 194, 206), (130, 138, 152)),
    "wood":    ((168, 122, 74), (128, 88, 50), (84, 56, 30)),
    "leather": ((176, 126, 82), (140, 96, 58), (92, 62, 36)),
    "fur":     ((160, 132, 104), (124, 100, 76), (84, 66, 48)),
    "gold":    ((252, 214, 108), (226, 176, 58), (150, 110, 20)),
    "default": ((178, 180, 188), (132, 134, 144), (78, 80, 90)),
}
GRIP = (98, 66, 40)        # leather grip
GRIP_D = (60, 40, 22)
GOLD = MATERIALS["gold"]


def _mat(item):
    m = str(item.get("material") or "").lower()
    return MATERIALS.get(m, MATERIALS["default"])


def _canvas():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _finish(img):
    # Soft drop-shadow so icons sit on any panel colour, then downsample.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    alpha = img.split()[3]
    sd = ImageDraw.Draw(shadow)
    sd.bitmap((0, 0), alpha.point(lambda a: 90 if a > 40 else 0), fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SS * 2))
    out = Image.alpha_composite(shadow, img)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def _poly(d, pts, fill, outline=None, width=SS):
    d.polygon(pts, fill=fill, outline=outline)
    if outline and width > 1:
        # Pillow's polygon outline is 1px; re-stroke the edges for a bolder line.
        d.line(list(pts) + [pts[0]], fill=outline, width=width, joint="curve")


# ---------------------------------------------------------------------------
# Shape painters — each fills the S×S supersampled canvas.
# ---------------------------------------------------------------------------
def draw_sword(d, mat, length=0.78, curve=0.0, blade_w=0.075):
    """A vertical bladed weapon: blade, crossguard, grip, pommel."""
    lo, mid, dk = mat
    cx = S * 0.5
    tip_y = S * (0.5 - length * 0.5)
    guard_y = S * (0.5 + length * 0.16)
    bw = S * blade_w
    cxr = cx + curve * S * 0.12  # tip drift for sabres
    # blade
    _poly(d, [(cxr, tip_y), (cx + bw, guard_y - S * 0.02),
              (cx - bw, guard_y - S * 0.02)], fill=mid, outline=dk, width=SS)
    # highlight edge
    d.line([(cxr, tip_y), (cx - bw * 0.3, guard_y - S * 0.02)], fill=lo, width=SS)
    # crossguard
    d.rounded_rectangle([cx - S * 0.16, guard_y, cx + S * 0.16, guard_y + S * 0.05],
                        radius=S * 0.02, fill=dk)
    # grip
    d.rounded_rectangle([cx - S * 0.035, guard_y + S * 0.05, cx + S * 0.035, guard_y + S * 0.20],
                        radius=S * 0.02, fill=GRIP, outline=GRIP_D, width=SS)
    # pommel
    d.ellipse([cx - S * 0.055, guard_y + S * 0.20, cx + S * 0.055, guard_y + S * 0.30], fill=dk)


def draw_dagger(d, mat):
    draw_sword(d, mat, length=0.5, blade_w=0.06)


def draw_saber(d, mat):
    draw_sword(d, mat, length=0.82, curve=1.0, blade_w=0.07)


def draw_mace(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    # haft
    d.rounded_rectangle([cx - S * 0.03, S * 0.36, cx + S * 0.03, S * 0.86],
                        radius=S * 0.02, fill=GRIP, outline=GRIP_D, width=SS)
    # spiked head
    head_y = S * 0.30
    r = S * 0.15
    for a in range(0, 360, 45):
        rad = math.radians(a)
        d.line([(cx, head_y), (cx + math.cos(rad) * r * 1.5, head_y + math.sin(rad) * r * 1.5)],
               fill=dk, width=SS * 3)
    d.ellipse([cx - r, head_y - r, cx + r, head_y + r], fill=mid, outline=dk, width=SS)
    d.ellipse([cx - r * 0.4, head_y - r * 0.5, cx + r * 0.1, head_y], fill=lo)


def draw_hammer(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.03, S * 0.32, cx + S * 0.03, S * 0.86],
                        radius=S * 0.02, fill=GRIP, outline=GRIP_D, width=SS)
    d.rounded_rectangle([cx - S * 0.20, S * 0.18, cx + S * 0.20, S * 0.36],
                        radius=S * 0.03, fill=mid, outline=dk, width=SS)
    d.rectangle([cx - S * 0.18, S * 0.20, cx - S * 0.02, S * 0.28], fill=lo)


def draw_axe(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.028, S * 0.16, cx + S * 0.028, S * 0.88],
                        radius=S * 0.02, fill=GRIP, outline=GRIP_D, width=SS)
    # double-bit axe head
    _poly(d, [(cx, S * 0.20), (cx + S * 0.26, S * 0.26), (cx + S * 0.20, S * 0.40),
              (cx, S * 0.38)], fill=mid, outline=dk, width=SS)
    _poly(d, [(cx, S * 0.20), (cx - S * 0.26, S * 0.26), (cx - S * 0.20, S * 0.40),
              (cx, S * 0.38)], fill=mid, outline=dk, width=SS)
    d.line([(cx + S * 0.02, S * 0.22), (cx + S * 0.24, S * 0.27)], fill=lo, width=SS)


def draw_club(d, mat):
    _, mid, dk = MATERIALS["wood"]
    cx = S * 0.5
    _poly(d, [(cx - S * 0.05, S * 0.86), (cx + S * 0.05, S * 0.86),
              (cx + S * 0.14, S * 0.20), (cx - S * 0.14, S * 0.20)],
          fill=mid, outline=dk, width=SS)
    for i in range(3):
        y = S * (0.30 + i * 0.16)
        d.ellipse([cx - S * 0.10, y, cx - S * 0.04, y + S * 0.05], fill=dk)


def draw_bow(d, mat):
    lo, mid, dk = mat if mat[0][0] < 200 else MATERIALS["wood"]
    cx, cy = S * 0.52, S * 0.5
    r = S * 0.36
    bbox = [cx - r, cy - r, cx + r, cy + r]
    d.arc(bbox, start=-70, end=70, fill=mid, width=SS * 3)
    d.arc([bbox[0] + SS, bbox[1], bbox[2] + SS, bbox[3]], start=-70, end=70, fill=lo, width=SS)
    # string
    y0 = cy + r * math.sin(math.radians(-70))
    y1 = cy + r * math.sin(math.radians(70))
    x0 = cx + r * math.cos(math.radians(-70))
    d.line([(x0, y0), (x0, y1)], fill=(230, 230, 220), width=max(2, SS))


def draw_staff(d, mat=None):
    _, wmid, wdk = MATERIALS["wood"]
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.03, S * 0.24, cx + S * 0.03, S * 0.9],
                        radius=S * 0.02, fill=wmid, outline=wdk, width=SS)
    # glowing orb
    gem = (110, 170, 240)
    d.ellipse([cx - S * 0.13, S * 0.10, cx + S * 0.13, S * 0.34],
              fill=gem, outline=(40, 70, 130), width=SS)
    d.ellipse([cx - S * 0.06, S * 0.14, cx + S * 0.01, S * 0.21], fill=(210, 230, 255))


def draw_arrow(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    d.line([(cx, S * 0.16), (cx, S * 0.84)], fill=MATERIALS["wood"][1], width=SS * 2)
    # head
    _poly(d, [(cx, S * 0.10), (cx + S * 0.09, S * 0.26), (cx - S * 0.09, S * 0.26)],
          fill=mid, outline=dk, width=SS)
    # fletching
    for sgn in (-1, 1):
        _poly(d, [(cx, S * 0.70), (cx + sgn * S * 0.10, S * 0.78),
                  (cx + sgn * S * 0.02, S * 0.84)], fill=(200, 70, 60), outline=dk, width=SS)


def draw_helmet(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    d.pieslice([cx - S * 0.26, S * 0.24, cx + S * 0.26, S * 0.76], 180, 360,
               fill=mid, outline=dk, width=SS)
    d.rectangle([cx - S * 0.26, S * 0.50, cx + S * 0.26, S * 0.58], fill=mid, outline=dk)
    # nose guard + eye slit
    d.rectangle([cx - S * 0.03, S * 0.34, cx + S * 0.03, S * 0.58], fill=dk)
    d.rectangle([cx - S * 0.22, S * 0.44, cx - S * 0.06, S * 0.50], fill=(30, 30, 36))
    d.rectangle([cx + S * 0.06, S * 0.44, cx + S * 0.22, S * 0.50], fill=(30, 30, 36))
    d.arc([cx - S * 0.20, S * 0.28, cx + S * 0.10, S * 0.5], 190, 250, fill=lo, width=SS)


def draw_cuirass(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    _poly(d, [(cx - S * 0.24, S * 0.22), (cx + S * 0.24, S * 0.22),
              (cx + S * 0.28, S * 0.34), (cx + S * 0.20, S * 0.78),
              (cx - S * 0.20, S * 0.78), (cx - S * 0.28, S * 0.34)],
          fill=mid, outline=dk, width=SS)
    # neckline + pecs
    d.arc([cx - S * 0.12, S * 0.16, cx + S * 0.12, S * 0.34], 0, 180, fill=dk, width=SS * 2)
    d.line([(cx, S * 0.30), (cx, S * 0.74)], fill=dk, width=SS)
    d.arc([cx - S * 0.18, S * 0.30, cx - S * 0.02, S * 0.5], 250, 360, fill=lo, width=SS)


def draw_gauntlet(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.16, S * 0.40, cx + S * 0.16, S * 0.80],
                        radius=S * 0.04, fill=mid, outline=dk, width=SS)
    for i in range(4):
        x = cx - S * 0.15 + i * S * 0.10
        d.rounded_rectangle([x, S * 0.20, x + S * 0.07, S * 0.44],
                            radius=S * 0.03, fill=mid, outline=dk, width=SS)
    d.rounded_rectangle([cx - S * 0.22, S * 0.34, cx - S * 0.10, S * 0.52],
                        radius=S * 0.03, fill=mid, outline=dk, width=SS)  # thumb


def draw_greaves(d, mat):
    lo, mid, dk = mat
    for sgn, cx in ((-1, S * 0.38), (1, S * 0.62)):
        d.rounded_rectangle([cx - S * 0.08, S * 0.16, cx + S * 0.08, S * 0.82],
                            radius=S * 0.04, fill=mid, outline=dk, width=SS)
        d.line([(cx, S * 0.22), (cx, S * 0.76)], fill=lo, width=SS)


def draw_boots(d, mat):
    lo, mid, dk = mat
    for cx in (S * 0.36, S * 0.62):
        _poly(d, [(cx - S * 0.07, S * 0.20), (cx + S * 0.07, S * 0.20),
                  (cx + S * 0.07, S * 0.60), (cx + S * 0.20, S * 0.60),
                  (cx + S * 0.20, S * 0.76), (cx - S * 0.07, S * 0.76)],
              fill=mid, outline=dk, width=SS)


def draw_shield(d, mat):
    lo, mid, dk = mat
    cx = S * 0.5
    _poly(d, [(cx - S * 0.26, S * 0.18), (cx + S * 0.26, S * 0.18),
              (cx + S * 0.26, S * 0.52), (cx, S * 0.84), (cx - S * 0.26, S * 0.52)],
          fill=mid, outline=dk, width=SS * 2)
    d.line([(cx, S * 0.20), (cx, S * 0.80)], fill=dk, width=SS)
    d.line([(cx - S * 0.24, S * 0.40), (cx + S * 0.24, S * 0.40)], fill=dk, width=SS)
    # boss
    d.ellipse([cx - S * 0.07, S * 0.40, cx + S * 0.07, S * 0.54], fill=lo, outline=dk, width=SS)


POTION_COLOURS = {
    "heal": (214, 60, 60), "heal_minor": (230, 120, 120), "magicka": (70, 110, 230),
    "stamina": (90, 200, 100), "shield": (90, 200, 220), "cure": (230, 210, 80),
}


def draw_potion(d, item_id):
    key = item_id.replace("potion_", "")
    liquid = POTION_COLOURS.get(key, (200, 90, 200))
    cx = S * 0.5
    glass = (196, 206, 210)
    # body
    d.ellipse([cx - S * 0.18, S * 0.34, cx + S * 0.18, S * 0.82],
              fill=glass, outline=(90, 100, 110), width=SS)
    # liquid fill
    d.pieslice([cx - S * 0.15, S * 0.40, cx + S * 0.15, S * 0.80], 20, 160, fill=liquid)
    d.ellipse([cx - S * 0.15, S * 0.52, cx + S * 0.15, S * 0.79], fill=liquid)
    # neck + cork
    d.rectangle([cx - S * 0.06, S * 0.22, cx + S * 0.06, S * 0.40], fill=glass,
                outline=(90, 100, 110), width=SS)
    d.rounded_rectangle([cx - S * 0.07, S * 0.16, cx + S * 0.07, S * 0.24],
                        radius=S * 0.02, fill=GRIP)
    # shine
    d.ellipse([cx - S * 0.12, S * 0.44, cx - S * 0.05, S * 0.58], fill=(255, 255, 255, 120))


def draw_bread(d, _id=None):
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.24, S * 0.36, cx + S * 0.24, S * 0.70],
                        radius=S * 0.14, fill=(196, 146, 84), outline=(120, 80, 40), width=SS)
    for i in range(3):
        x = cx - S * 0.14 + i * S * 0.14
        d.line([(x, S * 0.40), (x - S * 0.04, S * 0.66)], fill=(150, 100, 54), width=SS)


def draw_ingredient(d, item_id):
    if "mushroom" in item_id:
        cx = S * 0.5
        d.rectangle([cx - S * 0.05, S * 0.46, cx + S * 0.05, S * 0.78], fill=(224, 214, 190))
        d.pieslice([cx - S * 0.22, S * 0.28, cx + S * 0.22, S * 0.60], 180, 360,
                   fill=(180, 70, 60), outline=(110, 40, 34), width=SS)
        for dx in (-0.10, 0, 0.10):
            d.ellipse([cx + dx * S - S * 0.02, S * 0.36, cx + dx * S + S * 0.02, S * 0.40],
                      fill=(240, 220, 210))
    elif "flax" in item_id or "nightshade" in item_id:
        col = (150, 170, 230) if "flax" in item_id else (150, 80, 170)
        cx = S * 0.5
        d.line([(cx, S * 0.8), (cx, S * 0.4)], fill=(80, 140, 70), width=SS * 2)
        for a in range(0, 360, 72):
            rad = math.radians(a - 90)
            x = cx + math.cos(rad) * S * 0.14
            y = S * 0.34 + math.sin(rad) * S * 0.14
            d.ellipse([x - S * 0.08, y - S * 0.08, x + S * 0.08, y + S * 0.08], fill=col)
        d.ellipse([cx - S * 0.05, S * 0.29, cx + S * 0.05, S * 0.39], fill=(240, 220, 90))
    else:  # bonemeal / pelt / generic pouch
        cx = S * 0.5
        d.rounded_rectangle([cx - S * 0.18, S * 0.40, cx + S * 0.18, S * 0.80],
                            radius=S * 0.10, fill=(150, 116, 80), outline=(90, 66, 40), width=SS)
        d.line([(cx - S * 0.16, S * 0.44), (cx + S * 0.16, S * 0.44)], fill=(90, 66, 40), width=SS * 2)
        d.ellipse([cx - S * 0.04, S * 0.30, cx + S * 0.04, S * 0.40], fill=(90, 66, 40))


def draw_book(d, item_id):
    covers = {"book_blade": (150, 60, 50), "book_marksman": (60, 110, 70),
              "book_lore": (70, 80, 140)}
    col = covers.get(item_id, (110, 80, 140))
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.22, S * 0.22, cx + S * 0.22, S * 0.78],
                        radius=S * 0.02, fill=col, outline=(30, 30, 40), width=SS)
    d.rectangle([cx - S * 0.22, S * 0.22, cx - S * 0.14, S * 0.78], fill=(40, 40, 50))
    d.rectangle([cx + S * 0.14, S * 0.24, cx + S * 0.20, S * 0.76], fill=(235, 228, 208))
    d.line([(cx + S * 0.02, S * 0.30), (cx + S * 0.02, S * 0.70)], fill=GOLD[1], width=SS)


def draw_lockpick(d, _id=None):
    lo, mid, dk = MATERIALS["iron"]
    cx = S * 0.5
    d.line([(cx - S * 0.16, S * 0.72), (cx + S * 0.16, S * 0.28)], fill=mid, width=SS * 2)
    d.line([(cx + S * 0.16, S * 0.28), (cx + S * 0.24, S * 0.22)], fill=mid, width=SS * 2)
    d.line([(cx - S * 0.16, S * 0.72), (cx - S * 0.24, S * 0.78)], fill=GRIP, width=SS * 3)


def draw_torch(d, _id=None):
    cx = S * 0.5
    d.rounded_rectangle([cx - S * 0.04, S * 0.44, cx + S * 0.04, S * 0.86],
                        radius=S * 0.02, fill=MATERIALS["wood"][1], outline=MATERIALS["wood"][2], width=SS)
    # flame
    _poly(d, [(cx, S * 0.12), (cx + S * 0.13, S * 0.40), (cx - S * 0.13, S * 0.40)],
          fill=(240, 150, 40))
    _poly(d, [(cx, S * 0.22), (cx + S * 0.08, S * 0.42), (cx - S * 0.08, S * 0.42)],
          fill=(250, 220, 90))


def draw_amulet(d, _id=None):
    cx = S * 0.5
    d.arc([cx - S * 0.22, S * 0.16, cx + S * 0.22, S * 0.60], 20, 160,
          fill=(210, 210, 220), width=SS * 2)
    d.ellipse([cx - S * 0.11, S * 0.52, cx + S * 0.11, S * 0.76],
              fill=(150, 160, 175), outline=(90, 96, 110), width=SS)
    d.ellipse([cx - S * 0.05, S * 0.58, cx + S * 0.05, S * 0.70], fill=(120, 200, 230))


def draw_repair(d, _id=None):
    draw_hammer(d, MATERIALS["iron"])


def draw_gold(d, _id=None):
    lo, mid, dk = GOLD
    for i, (dx, dy) in enumerate([(-0.10, 0.14), (0.10, 0.10), (0.0, -0.06)]):
        cx = S * (0.5 + dx)
        cy = S * (0.5 + dy)
        d.ellipse([cx - S * 0.17, cy - S * 0.10, cx + S * 0.17, cy + S * 0.10],
                  fill=mid, outline=dk, width=SS)
        d.ellipse([cx - S * 0.17, cy - S * 0.14, cx + S * 0.17, cy + S * 0.06],
                  fill=lo, outline=dk, width=SS)
        d.text((cx - S * 0.03, cy - S * 0.09), "", fill=dk)


# ---------------------------------------------------------------------------
# Item -> shape inference
# ---------------------------------------------------------------------------
def shape_for(item_id, item):
    """Return a zero-extra-arg painter ``fn(draw)`` for this item."""
    iid = item_id.lower()
    name = str(item.get("name", "")).lower()
    cat = str(item.get("category", "")).lower()
    skill = str(item.get("skill", "")).lower()
    mat = _mat(item)

    text = f"{iid} {name}"

    if cat == "gold" or iid == "gold":
        return draw_gold
    if cat == "ammo" or "arrow" in text:
        return lambda d: draw_arrow(d, mat)
    if cat == "potion":
        return (draw_bread if iid == "bread" else (lambda d: draw_potion(d, iid)))
    if cat == "ingredient":
        return lambda d: draw_ingredient(d, iid)
    if cat == "book":
        return lambda d: draw_book(d, iid)
    if cat == "misc":
        if "lockpick" in text:
            return draw_lockpick
        if "torch" in text:
            return draw_torch
        if "amulet" in text or "ring" in text:
            return draw_amulet
        if "hammer" in text or "repair" in text:
            return draw_repair
        return lambda d: draw_book(d, iid)
    if cat == "armour" or cat == "armor":
        if "helm" in text:
            return lambda d: draw_helmet(d, mat)
        if "shield" in text:
            return lambda d: draw_shield(d, mat)
        if "gauntlet" in text or "bracer" in text or "glove" in text:
            return lambda d: draw_gauntlet(d, mat)
        if "greave" in text or "leg" in text:
            return lambda d: draw_greaves(d, mat)
        if "boot" in text:
            return lambda d: draw_boots(d, mat)
        return lambda d: draw_cuirass(d, mat)   # cuirass / armour / fur
    if cat == "weapon":
        if skill == "marksman" or "bow" in text:
            return lambda d: draw_bow(d, mat)
        if skill == "destruction" or "staff" in text:
            return lambda d: draw_staff(d, mat)
        if "warhammer" in text or "hammer" in text:
            return lambda d: draw_hammer(d, mat)
        if "axe" in text:
            return lambda d: draw_axe(d, mat)
        if "mace" in text:
            return lambda d: draw_mace(d, mat)
        if "club" in text:
            return lambda d: draw_club(d, mat)
        if "dagger" in text:
            return lambda d: draw_dagger(d, mat)
        if "saber" in text or "sabre" in text or "scimitar" in text:
            return lambda d: draw_saber(d, mat)
        return lambda d: draw_sword(d, mat)     # sword / longsword / shortsword
    # unknown
    return lambda d: draw_book(d, iid)


# Generic per-category fallbacks (used by the inventory UI for modded items).
CATEGORY_FALLBACK = {
    "weapon": lambda d: draw_sword(d, MATERIALS["iron"]),
    "armour": lambda d: draw_cuirass(d, MATERIALS["iron"]),
    "armor": lambda d: draw_cuirass(d, MATERIALS["iron"]),
    "ammo": lambda d: draw_arrow(d, MATERIALS["iron"]),
    "potion": lambda d: draw_potion(d, "potion_heal"),
    "ingredient": lambda d: draw_ingredient(d, "ingr_generic"),
    "book": lambda d: draw_book(d, "book"),
    "misc": lambda d: draw_book(d, "misc"),
    "gold": draw_gold,
}


def render(painter):
    img, d = _canvas()
    painter(d)
    return _finish(img)


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    items_path = os.path.join(root, "game", "data", "items.json")
    out_dir = os.path.join(root, "assets", "sprites", "items")
    os.makedirs(out_dir, exist_ok=True)

    with open(items_path, encoding="utf-8") as f:
        items = json.load(f)

    n = 0
    for item_id, item in items.items():
        img = render(shape_for(item_id, item))
        img.save(os.path.join(out_dir, f"{item_id}.png"))
        n += 1

    for cat, fn in CATEGORY_FALLBACK.items():
        render(fn).save(os.path.join(out_dir, f"_{cat}.png"))

    print(f"Wrote {n} item icons + {len(CATEGORY_FALLBACK)} category fallbacks to {out_dir}")


if __name__ == "__main__":
    main()
