"""
Generate Miniwind's NPC art: a distinctive **top-down** billboard sprite per
role, plus a matching dialogue **portrait**.

Fio's overhead camera draws characters as camera-facing billboards, so a sprite
seen from directly above reads correctly (§14). Each role gets its own silhouette
and palette so a villager, a guard and a bandit are told apart at a glance from
above — cloak mass, shoulders, a head with a facing nub, hats/hoods and a held
weapon where it suits the role.

Everything is drawn with Pillow (a Fio dependency) at 4× and downsampled for
clean anti-aliased edges — no external image files, fully reproducible. Sprites
land in ``assets/sprites/miniwind/<role>.png`` and portraits in
``assets/portraits/miniwind/<role>.png``; the NPC entity points its
``custom_idle`` at the former and the dialogue box blits the latter.

Run from the repo root:  python -m game.tools.make_sprites
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

SS = 4                    # supersample factor
SPRITE = 128              # final sprite size (px)
PORTRAIT = 128            # final portrait size (px)


# --- role palettes ---------------------------------------------------------
# skin, hair, cloth (primary robe/tunic), cloth2 (trim), accent (metal/weapon)
ROLES = {
    "villager":  dict(skin=(226, 176, 140), hair=(96, 64, 40),
                      cloth=(86, 132, 74),  cloth2=(150, 116, 70), accent=(120, 90, 60)),
    "blacksmith": dict(skin=(214, 158, 120), hair=(40, 32, 28),
                      cloth=(84, 78, 74),   cloth2=(150, 60, 40),  accent=(180, 120, 60)),
    "merchant":  dict(skin=(230, 186, 150), hair=(70, 50, 34),
                      cloth=(122, 74, 140), cloth2=(220, 180, 90), accent=(230, 200, 110)),
    "farmer":    dict(skin=(220, 170, 130), hair=(120, 88, 44),
                      cloth=(150, 120, 70), cloth2=(96, 132, 74),  accent=(200, 180, 110)),
    "beggar":    dict(skin=(200, 160, 130), hair=(80, 70, 60),
                      cloth=(110, 100, 88), cloth2=(80, 72, 62),   accent=(90, 80, 70)),
    "guard":     dict(skin=(222, 172, 138), hair=(50, 44, 40),
                      cloth=(70, 84, 120),  cloth2=(170, 60, 55),  accent=(196, 202, 214)),
    "bandit":    dict(skin=(200, 150, 120), hair=(28, 26, 30),
                      cloth=(60, 52, 58),   cloth2=(150, 50, 46),  accent=(180, 184, 190)),
    "cultist":   dict(skin=(190, 168, 170), hair=(20, 18, 26),
                      cloth=(58, 44, 78),   cloth2=(150, 60, 150), accent=(210, 120, 220)),
    "wolf":      dict(skin=(120, 116, 112), hair=(80, 76, 74),
                      cloth=(120, 116, 112), cloth2=(80, 76, 74),  accent=(230, 230, 235)),
    "monster":   dict(skin=(120, 150, 90),  hair=(70, 96, 54),
                      cloth=(96, 128, 72),  cloth2=(60, 84, 48),   accent=(200, 70, 70)),
}


def _lighten(c, f):
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)


def _darken(c, f):
    return tuple(max(0, int(v * (1 - f))) for v in c)


def _shadow(draw, cx, cy, rx, ry):
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(0, 0, 0, 90))


# ---------------------------------------------------------------------------
# Top-down sprite
# ---------------------------------------------------------------------------
def draw_topdown(role: str) -> Image.Image:
    p = ROLES[role]
    S = SPRITE * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = S // 2
    cy = int(S * 0.54)

    # ground shadow (soft)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(
        [cx - S * 0.30, cy + S * 0.10, cx + S * 0.30, cy + S * 0.30], fill=(0, 0, 0, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(S * 0.02))
    img.alpha_composite(sh)

    if role == "wolf":
        return _draw_wolf(img, d, cx, cy, S, p)

    # --- cloak / body (seen from above), an egg wider at the shoulders ---
    body_r = S * 0.30
    d.ellipse([cx - body_r, cy - body_r * 0.9, cx + body_r, cy + body_r * 1.25],
              fill=p["cloth"], outline=_darken(p["cloth"], 0.45), width=int(S * 0.010))
    # rim light on the cloak
    d.arc([cx - body_r, cy - body_r * 0.9, cx + body_r, cy + body_r * 1.25],
          200, 340, fill=_lighten(p["cloth"], 0.22), width=int(S * 0.020))
    # centre seam / trim
    d.line([cx, cy - body_r * 0.4, cx, cy + body_r * 1.1],
           fill=p["cloth2"], width=int(S * 0.02))

    # --- shoulders ---
    for sgn in (-1, 1):
        sx = cx + sgn * S * 0.20
        sy = cy - S * 0.02
        d.ellipse([sx - S * 0.085, sy - S * 0.085, sx + S * 0.085, sy + S * 0.085],
                  fill=_darken(p["cloth"], 0.10), outline=_darken(p["cloth"], 0.45),
                  width=int(S * 0.008))

    # --- held weapon (behind hands, drawn before head so it tucks under) ---
    if role in ("guard",):
        _spear(d, cx + S * 0.20, cy, S, p)
    elif role in ("bandit", "cultist", "blacksmith"):
        _dagger(d, cx + S * 0.20, cy + S * 0.02, S, p, long_=(role == "blacksmith"))

    # --- head ---
    head_r = S * 0.135
    hy = cy - S * 0.06
    # hair/hood ring (back of head)
    d.ellipse([cx - head_r * 1.18, hy - head_r * 1.18, cx + head_r * 1.18, hy + head_r * 1.18],
              fill=p["hair"])
    # face disc
    d.ellipse([cx - head_r, hy - head_r, cx + head_r, hy + head_r],
              fill=p["skin"], outline=_darken(p["skin"], 0.35), width=int(S * 0.006))
    # facing nub (nose) toward the top = forward
    d.polygon([(cx, hy - head_r * 1.15), (cx - head_r * 0.22, hy - head_r * 0.7),
               (cx + head_r * 0.22, hy - head_r * 0.7)], fill=_darken(p["skin"], 0.12))
    # subtle face shading
    d.ellipse([cx - head_r, hy - head_r * 0.2, cx + head_r, hy + head_r],
              fill=None, outline=_darken(p["skin"], 0.18), width=int(S * 0.005))

    # --- hats / hoods per role ---
    if role == "guard":
        # steel helmet from above
        d.ellipse([cx - head_r * 1.05, hy - head_r * 1.05, cx + head_r * 1.05, hy + head_r * 1.05],
                  fill=p["accent"], outline=_darken(p["accent"], 0.4), width=int(S * 0.008))
        d.line([cx, hy - head_r, cx, hy + head_r], fill=_darken(p["accent"], 0.3),
               width=int(S * 0.014))  # helmet ridge
        d.polygon([(cx - head_r * 0.25, hy - head_r * 1.1), (cx + head_r * 0.25, hy - head_r * 1.1),
                   (cx, hy - head_r * 1.7)], fill=p["cloth2"])  # plume
    elif role in ("bandit", "cultist"):
        # hood: dark cowl covering most of the head, face slot forward
        d.pieslice([cx - head_r * 1.25, hy - head_r * 1.25, cx + head_r * 1.25, hy + head_r * 1.25],
                   30, 330, fill=_darken(p["cloth"], 0.15))
        d.ellipse([cx - head_r * 0.6, hy - head_r * 0.9, cx + head_r * 0.6, hy - head_r * 0.05],
                  fill=p["skin"])  # sliver of face
        if role == "cultist":
            d.ellipse([cx - head_r * 0.16, hy - head_r * 0.55, cx + head_r * 0.16, hy - head_r * 0.23],
                      fill=p["accent"])  # third-eye mark
    elif role == "farmer":
        # wide straw hat brim
        br = head_r * 1.7
        d.ellipse([cx - br, hy - br, cx + br, hy + br], fill=p["accent"],
                  outline=_darken(p["accent"], 0.3), width=int(S * 0.008))
        d.ellipse([cx - head_r * 0.8, hy - head_r * 0.8, cx + head_r * 0.8, hy + head_r * 0.8],
                  fill=_darken(p["accent"], 0.18))
    elif role == "merchant":
        # feathered cap
        d.ellipse([cx - head_r * 1.05, hy - head_r * 1.05, cx + head_r * 1.05, hy + head_r * 1.05],
                  fill=p["cloth"])
        d.polygon([(cx + head_r * 0.6, hy - head_r * 0.6), (cx + head_r * 1.7, hy - head_r * 1.4),
                   (cx + head_r * 0.9, hy - head_r * 0.2)], fill=p["cloth2"])
    elif role == "monster":
        # horns
        for sgn in (-1, 1):
            d.polygon([(cx + sgn * head_r * 0.5, hy - head_r * 0.7),
                       (cx + sgn * head_r * 1.3, hy - head_r * 1.6),
                       (cx + sgn * head_r * 0.9, hy - head_r * 0.4)], fill=p["cloth2"])
        # glowing eyes
        for sgn in (-1, 1):
            d.ellipse([cx + sgn * head_r * 0.45 - head_r * 0.12, hy - head_r * 0.55,
                       cx + sgn * head_r * 0.45 + head_r * 0.12, hy - head_r * 0.3],
                      fill=p["accent"])

    return img.resize((SPRITE, SPRITE), Image.LANCZOS)


def _spear(d, hx, hy, S, p):
    length = S * 0.44
    d.line([hx, hy + S * 0.05, hx, hy - length], fill=_darken(p["accent"], 0.55),
           width=int(S * 0.02))  # shaft
    d.polygon([(hx, hy - length - S * 0.05), (hx - S * 0.03, hy - length + S * 0.03),
               (hx + S * 0.03, hy - length + S * 0.03)], fill=p["accent"])  # head


def _dagger(d, hx, hy, S, p, long_=False):
    length = S * (0.30 if long_ else 0.20)
    d.line([hx, hy, hx, hy - length], fill=p["accent"], width=int(S * 0.018))
    d.line([hx - S * 0.05, hy, hx + S * 0.05, hy], fill=_darken(p["accent"], 0.4),
           width=int(S * 0.014))  # crossguard


def _draw_wolf(img, d, cx, cy, S, p):
    # top-down quadruped: elongated body, head with ears, tail
    body = _darken(p["cloth"], 0.0)
    d.ellipse([cx - S * 0.16, cy - S * 0.28, cx + S * 0.16, cy + S * 0.30],
              fill=body, outline=_darken(body, 0.4), width=int(S * 0.01))
    # back ridge highlight
    d.line([cx, cy - S * 0.24, cx, cy + S * 0.24], fill=_lighten(body, 0.18), width=int(S * 0.02))
    # head
    hy = cy - S * 0.30
    d.ellipse([cx - S * 0.12, hy - S * 0.12, cx + S * 0.12, hy + S * 0.12], fill=_darken(body, 0.1))
    # ears
    for sgn in (-1, 1):
        d.polygon([(cx + sgn * S * 0.09, hy - S * 0.07), (cx + sgn * S * 0.16, hy - S * 0.17),
                   (cx + sgn * S * 0.04, hy - S * 0.10)], fill=_darken(body, 0.2))
    # snout + eyes
    d.polygon([(cx, hy - S * 0.16), (cx - S * 0.05, hy - S * 0.02), (cx + S * 0.05, hy - S * 0.02)],
              fill=_lighten(body, 0.12))
    for sgn in (-1, 1):
        d.ellipse([cx + sgn * S * 0.05 - S * 0.02, hy - S * 0.06, cx + sgn * S * 0.05 + S * 0.02,
                   hy - S * 0.02], fill=p["accent"])
    # tail
    d.line([cx, cy + S * 0.28, cx - S * 0.10, cy + S * 0.40], fill=body, width=int(S * 0.05))
    return img.resize((SPRITE, SPRITE), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Dialogue portrait (front-facing bust in a frame)
# ---------------------------------------------------------------------------
def draw_portrait(role: str) -> Image.Image:
    p = ROLES[role]
    S = PORTRAIT * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # background vignette
    bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(bg).rectangle([0, 0, S, S], fill=(18, 20, 30, 255))
    d2 = ImageDraw.Draw(bg)
    d2.ellipse([S * 0.05, S * 0.02, S * 0.95, S * 1.1], fill=(38, 40, 58, 255))
    img.alpha_composite(bg)

    cx = S // 2
    # shoulders / robe
    d.pieslice([cx - S * 0.44, int(S * 0.62), cx + S * 0.44, int(S * 1.25)], 180, 360,
               fill=p["cloth"], outline=_darken(p["cloth"], 0.4), width=int(S * 0.010))
    d.line([cx, int(S * 0.66), cx, S], fill=p["cloth2"], width=int(S * 0.02))

    # neck
    d.rectangle([cx - S * 0.09, int(S * 0.52), cx + S * 0.09, int(S * 0.70)],
                fill=_darken(p["skin"], 0.12))

    # head
    hr = S * 0.22
    hy = int(S * 0.40)
    d.ellipse([cx - hr, hy - hr * 1.15, cx + hr, hy + hr * 1.15],
              fill=p["skin"], outline=_darken(p["skin"], 0.3), width=int(S * 0.006))
    # cheek shade
    d.ellipse([cx - hr, hy - hr * 0.1, cx + hr, hy + hr * 1.15], fill=None,
              outline=_darken(p["skin"], 0.14), width=int(S * 0.006))
    # hair / headwear
    if role in ("bandit", "cultist"):
        d.pieslice([cx - hr * 1.25, hy - hr * 1.5, cx + hr * 1.25, hy + hr * 1.1], 180, 360,
                   fill=_darken(p["cloth"], 0.1))
        d.pieslice([cx - hr * 1.1, hy - hr * 1.35, cx + hr * 1.1, hy + hr * 0.2], 200, 340,
                   fill=(0, 0, 0, 120))
        if role == "cultist":
            d.ellipse([cx - hr * 0.14, hy - hr * 0.75, cx + hr * 0.14, hy - hr * 0.45],
                      fill=p["accent"])
    elif role == "guard":
        d.pieslice([cx - hr * 1.15, hy - hr * 1.5, cx + hr * 1.15, hy + hr * 0.4], 180, 360,
                   fill=p["accent"], outline=_darken(p["accent"], 0.4), width=int(S * 0.008))
        d.line([cx, hy - hr * 1.45, cx, hy + hr * 0.3], fill=_darken(p["accent"], 0.3),
               width=int(S * 0.02))
        # nose guard
        d.rectangle([cx - hr * 0.08, hy - hr * 0.6, cx + hr * 0.08, hy + hr * 0.5],
                    fill=_darken(p["accent"], 0.2))
    elif role == "farmer":
        d.ellipse([cx - hr * 1.8, hy - hr * 0.9, cx + hr * 1.8, hy - hr * 0.1], fill=p["accent"])
        d.pieslice([cx - hr * 1.1, hy - hr * 1.5, cx + hr * 1.1, hy - hr * 0.1], 180, 360,
                   fill=_darken(p["accent"], 0.15))
    else:
        d.pieslice([cx - hr * 1.12, hy - hr * 1.45, cx + hr * 1.12, hy + hr * 0.5], 180, 360,
                   fill=p["hair"])
        if role == "merchant":
            d.polygon([(cx - hr * 0.9, hy - hr * 0.9), (cx + hr * 0.4, hy - hr * 1.6),
                       (cx + hr * 0.6, hy - hr * 0.7)], fill=p["cloth2"])

    # eyes
    eye_y = hy - hr * 0.05
    for sgn in (-1, 1):
        ex = cx + sgn * hr * 0.42
        eye_col = p["accent"] if role in ("monster", "wolf") else (40, 34, 40)
        d.ellipse([ex - hr * 0.12, eye_y - hr * 0.09, ex + hr * 0.12, eye_y + hr * 0.09],
                  fill=(245, 245, 245) if role not in ("monster", "wolf") else _darken(eye_col, 0.5))
        d.ellipse([ex - hr * 0.05, eye_y - hr * 0.06, ex + hr * 0.06, eye_y + hr * 0.06],
                  fill=eye_col)
    # brow
    d.line([cx - hr * 0.6, hy - hr * 0.28, cx - hr * 0.18, hy - hr * 0.34],
           fill=_darken(p["hair"], 0.1), width=int(S * 0.012))
    d.line([cx + hr * 0.18, hy - hr * 0.34, cx + hr * 0.6, hy - hr * 0.28],
           fill=_darken(p["hair"], 0.1), width=int(S * 0.012))
    # nose + mouth
    d.line([cx, eye_y + hr * 0.05, cx, eye_y + hr * 0.4], fill=_darken(p["skin"], 0.22),
           width=int(S * 0.01))
    d.line([cx - hr * 0.28, eye_y + hr * 0.6, cx + hr * 0.28, eye_y + hr * 0.6],
           fill=_darken(p["skin"], 0.3), width=int(S * 0.012))

    out = img.resize((PORTRAIT, PORTRAIT), Image.LANCZOS)

    # gilded frame
    fr = ImageDraw.Draw(out)
    fr.rectangle([1, 1, PORTRAIT - 2, PORTRAIT - 2], outline=(150, 120, 60), width=3)
    fr.rectangle([4, 4, PORTRAIT - 5, PORTRAIT - 5], outline=(90, 72, 40), width=1)
    return out


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    # MiniWind art is namespaced under the engine's assets/ tree so every Fio
    # sprite loader resolves it (see game/entities.py _SPRITE_DIR).
    sdir = os.path.join(root, "assets", "sprites", "miniwind")
    pdir = os.path.join(root, "assets", "portraits", "miniwind")
    os.makedirs(sdir, exist_ok=True)
    os.makedirs(pdir, exist_ok=True)
    for role in ROLES:
        draw_topdown(role).save(os.path.join(sdir, f"{role}.png"))
        draw_portrait(role).save(os.path.join(pdir, f"{role}.png"))
    draw_magicbolt().save(os.path.join(sdir, "magicbolt.png"))
    for kind in _MARKER_STYLE:
        draw_marker(kind).save(os.path.join(sdir, f"marker_{kind}.png"))
    draw_marker("idle").save(os.path.join(sdir, "marker.png"))   # generic fallback
    print(f"wrote {len(ROLES)} sprites (+ magicbolt, {len(_MARKER_STYLE)} markers) -> {sdir}")
    print(f"wrote {len(ROLES)} portraits -> {pdir}")


# Per-kind marker colour + glyph (keep in sync with entities.MARKER_KINDS).
_MARKER_STYLE = {
    "home":      ((76, 175, 80),  "H"),
    "bed":       ((0, 150, 136),  "Z"),
    "work":      ((255, 152, 0),  "W"),
    "forge":     ((211, 47, 47),  "A"),
    "shop":      ((255, 193, 7),  "$"),
    "farm":      ((139, 195, 74), "F"),
    "guardpost": ((63, 81, 181),  "G"),
    "patrol":    ((0, 188, 212),  "P"),
    "social":    ((156, 39, 176), "O"),
    "idle":      ((120, 120, 130), "•"),
    "location":  ((198, 156, 74),  "★"),
    "prison":    ((96, 108, 120),  "†"),
    "quest":     ((255, 202, 40),  "!"),
}


def draw_marker(kind: str, size: int = 48):
    """A distinct map-pin icon per marker kind (coloured disc + glyph + point)."""
    from PIL import ImageDraw, ImageFont
    color, glyph = _MARKER_STYLE.get(kind, _MARKER_STYLE["idle"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size / 2.0
    r = size * 0.34
    top = size * 0.10
    # downward pin point
    d.polygon([(cx - r * 0.55, top + r * 1.2), (cx + r * 0.55, top + r * 1.2),
               (cx, size - 3)], fill=(0, 0, 0, 90))
    d.polygon([(cx - r * 0.5, top + r * 1.15), (cx + r * 0.5, top + r * 1.15),
               (cx, size - 5)], fill=color + (255,))
    # head disc with a darker rim
    bbox = [cx - r, top, cx + r, top + 2 * r]
    d.ellipse(bbox, fill=color + (255,),
              outline=(max(0, color[0] - 60), max(0, color[1] - 60), max(0, color[2] - 60), 255),
              width=2)
    d.ellipse([cx - r + 3, top + 3, cx + r - 3, top + 2 * r - 3], outline=(255, 255, 255, 90), width=1)
    # glyph
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(r * 1.1))
    except Exception:
        font = ImageFont.load_default()
    try:
        tb = d.textbbox((0, 0), glyph, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        d.text((cx - tw / 2 - tb[0], top + r - th / 2 - tb[1]), glyph,
               fill=(255, 255, 255, 255), font=font)
    except Exception:
        d.text((cx - 4, top + r - 6), glyph, fill=(255, 255, 255, 255))
    return img


#: Per-kind container body colour (keep in sync with entities.CONTAINER_KINDS).
_CONTAINER_STYLE = {
    "chest":  (140, 94, 52),
    "barrel": (120, 82, 46),
    "crate":  (168, 130, 78),
    "sack":   (170, 154, 110),
    "urn":    (150, 120, 96),
}


def draw_container(kind: str = "chest", size: int = 64):
    """A simple top-down-ish container icon (coloured body + lid/bands)."""
    from PIL import ImageDraw
    base = _CONTAINER_STYLE.get(kind, _CONTAINER_STYLE["chest"])
    dark = tuple(max(0, c - 45) for c in base)
    band = tuple(min(255, c + 40) for c in base)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size * 0.16
    body = [m, size * 0.30, size - m, size - m]
    if kind == "urn":
        d.ellipse([m, m, size - m, size - m], fill=base + (255,), outline=dark + (255,), width=3)
        d.ellipse([size * 0.34, m * 0.7, size * 0.66, m * 1.8], fill=dark + (255,))
    elif kind == "sack":
        d.ellipse(body, fill=base + (255,), outline=dark + (255,), width=3)
        d.line([size * 0.34, size * 0.30, size * 0.66, size * 0.30], fill=dark + (255,), width=4)
    else:
        # lid
        d.rounded_rectangle([m, size * 0.20, size - m, size * 0.42], radius=6,
                            fill=band + (255,), outline=dark + (255,), width=3)
        # body
        d.rounded_rectangle(body, radius=6, fill=base + (255,), outline=dark + (255,), width=3)
        # metal bands / staves
        for fx in (0.34, 0.5, 0.66):
            x = size * fx
            d.line([x, size * 0.22, x, size - m], fill=dark + (255,), width=3)
        # clasp
        d.rectangle([size * 0.46, size * 0.36, size * 0.54, size * 0.48], fill=band + (255,),
                    outline=dark + (255,))
    return img


def draw_magicbolt(size: int = 48):
    """A glowing violet-cyan magic bolt used for caster projectiles."""
    import math
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    c = size / 2.0
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c + 0.5, y - c + 0.5) / (size / 2.0)
            if d > 1.0:
                continue
            t = max(0.0, 1.0 - d)
            r = min(255, int(150 + 105 * t))
            g = min(255, int(90 + 120 * t))
            b = min(255, int(220 + 35 * t))
            a = int(255 * (t ** 1.4))
            px[x, y] = (r, g, b, a)
    return img


if __name__ == "__main__":
    main()
