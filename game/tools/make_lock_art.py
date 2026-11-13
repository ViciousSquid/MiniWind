"""
The lockpicking minigame's plain locks, rendered as the escutcheon is:
``assets/ui/lockpicking/{iron,rusted,padlock}.png``.

The ornate lock is a painted plate (``escutcheon.png``); the others were flat
vector shapes beside it. Here each is *rendered*: a height field (bevelled
plates, recessed pin channels and keyway, domed rivets, a hammered surface,
scratches, pitting) lit from the top left with diffuse, specular and cavity
shading, over a material (forged iron; iron eaten by rust, with flaking scale
and streaks; a cast steel padlock with a stamped mark and worn edges).

The plates share the escutcheon's layout, in the game's "plate" coordinates
(``game/ui/lockpicking.py``: drawn into QRectF(-12, 130, 480, 320), 3.2 px per
unit), so the live pins and pick the game draws sit in their channels: five
channels at x = 173, 200, 228, 255, 282 above a keyway at y ~ 318-346. The
padlock, drawn into QRectF(PADLOCK_RECT), is a cutaway practice lock: its pin
chambers and plug sit in that same place, the pins upright, the pick in from
the left through the keyway.

Deterministic (fixed seeds). Run from the repo root::

    python -m game.tools.make_lock_art
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join("assets", "ui", "lockpicking")
SCALE = 3.2                       # px per plate unit, as escutcheon.png
PLATE_RECT = (-12.0, 130.0, 480.0, 320.0)
PADLOCK_RECT = (96.0, 100.0, 264.0, 330.0)
PINS = (173, 200, 228, 255, 282)
LIGHT = np.array([-0.55, -0.62, 0.56])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


# --------------------------------------------------------------------- tools
class Canvas:
    """Masks drawn in plate units on an image of the rect's size."""

    def __init__(self, rect):
        self.rect = rect
        self.w = int(round(rect[2] * SCALE))
        self.h = int(round(rect[3] * SCALE))

    def px(self, x, y):
        return ((x - self.rect[0]) * SCALE, (y - self.rect[1]) * SCALE)

    def mask(self):
        return Image.new("L", (self.w, self.h), 0)

    def rrect(self, img, x0, y0, x1, y1, r, fill=255):
        a, b = self.px(x0, y0), self.px(x1, y1)
        ImageDraw.Draw(img).rounded_rectangle([a, b], radius=r * SCALE, fill=fill)

    def ellipse(self, img, cx, cy, r, fill=255):
        a, b = self.px(cx - r, cy - r), self.px(cx + r, cy + r)
        ImageDraw.Draw(img).ellipse([a, b], fill=fill)

    def poly(self, img, pts, fill=255):
        ImageDraw.Draw(img).polygon([self.px(x, y) for x, y in pts], fill=fill)

    def line(self, img, pts, width, fill=255):
        ImageDraw.Draw(img).line([self.px(x, y) for x, y in pts], fill=fill,
                                 width=max(1, int(width * SCALE)), joint="curve")


def arr(img):
    return np.asarray(img, dtype=np.float32) / 255.0


def _box(a, r, axis):
    """A box blur of radius *r* along *axis* (edges held), by cumulative sums."""
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def blur(a, radius):
    """A Gaussian blur, near enough: three box passes each way."""
    if radius <= 0:
        return a
    r = max(1, int(round(radius * 0.87)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box(_box(out, r, 0), r, 1)
    return out


def noise(shape, scale, rng, octaves=5, persistence=0.55):
    """Fractal value noise in [0, 1]."""
    h, w = shape
    total = np.zeros(shape, np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        cells = max(2, int(round(max(w, h) / (scale / (2 ** o)))))
        grid = rng.random((max(2, int(cells * h / max(w, h)) + 2), cells + 2)).astype(np.float32)
        img = Image.fromarray((grid * 255).astype(np.uint8), mode="L").resize((w, h), Image.BICUBIC)
        total += amp * np.asarray(img, np.float32) / 255.0
        norm += amp
        amp *= persistence
    total /= norm
    return (total - total.min()) / max(1e-6, total.max() - total.min())


def bevel(mask, width_px):
    """A rounded bevel: 0 outside, rising over *width_px* inside the edge."""
    m = mask.astype(np.float32)
    soft = blur(m, width_px * 0.6)
    return np.clip((soft - 0.5) * 2.0, 0.0, 1.0) ** 0.6 * m


def scratches(shape, rng, count, length, canvas_scale=1.0):
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    for _ in range(count):
        x, y = rng.random() * shape[1], rng.random() * shape[0]
        a = rng.normal(-0.35, 0.6)
        ln = length * (0.3 + rng.random())
        d.line([(x, y), (x + math.cos(a) * ln, y + math.sin(a) * ln)],
               fill=int(90 + rng.random() * 120), width=1)
    return arr(img)


def dents(shape, rng, count, rmin, rmax):
    """Hammer marks: shallow round dimples."""
    out = np.zeros(shape, np.float32)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for _ in range(count):
        cx, cy = rng.random() * shape[1], rng.random() * shape[0]
        r = rmin + rng.random() * (rmax - rmin)
        x0, x1 = int(max(0, cx - r)), int(min(shape[1], cx + r + 1))
        y0, y1 = int(max(0, cy - r)), int(min(shape[0], cy + r + 1))
        if x0 >= x1 or y0 >= y1:
            continue
        d2 = ((xx[y0:y1, x0:x1] - cx) ** 2 + (yy[y0:y1, x0:x1] - cy) ** 2) / (r * r)
        out[y0:y1, x0:x1] -= np.where(d2 < 1, (1 - d2) ** 2, 0) * (0.4 + 0.6 * rng.random())
    return out


def dome(canvas, shape, cx, cy, r):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    px, py = canvas.px(cx, cy)
    rp = r * SCALE
    d2 = ((xx - px) ** 2 + (yy - py) ** 2) / (rp * rp)
    return np.where(d2 < 1, np.sqrt(np.clip(1 - d2, 0, 1)), 0).astype(np.float32)


def shade(height, albedo, alpha, *, strength=6.0, spec=0.6, gloss=24.0, rough=None,
          cavity=0.55):
    """Light a height field from the top left: diffuse, Blinn specular, cavity
    and broad occlusion, and the light falling off across the plate."""
    gy, gx = np.gradient(height * strength)
    n = np.stack([-gx, -gy, np.ones_like(height)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    diff = np.clip(n @ LIGHT, 0, 1)
    half = LIGHT + np.array([0, 0, 1.0])
    half /= np.linalg.norm(half)
    s = np.clip(n @ half, 0, 1) ** gloss
    if rough is not None:
        s *= (1.0 - rough)
    hollow = np.clip(blur(height, 5) - height, 0, None)
    broad = np.clip(blur(height, 28) - height, 0, None)
    occ = np.clip(1.0 - hollow * cavity * 9.0 - broad * 1.6, 0.18, 1.0)
    hgt, wid = height.shape
    yy, xx = np.mgrid[0:hgt, 0:wid].astype(np.float32)
    fall = 1.08 - 0.38 * np.clip((xx / wid * 0.6 + yy / hgt * 0.8), 0, 1.4) / 1.4
    rgb = albedo * (0.16 + 1.0 * diff[..., None]) * (occ * fall)[..., None] + spec * (s * fall)[..., None]
    return np.dstack([np.clip(rgb, 0, 1), alpha])


def save(rgba, name, shadow_from=None):
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), mode="RGBA")
    if shadow_from is not None:
        sh = Image.fromarray((np.clip(blur(shadow_from, 18), 0, 1) * 160).astype(np.uint8), "L")
        base = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dark = Image.new("RGBA", img.size, (0, 0, 0, 255))
        base.paste(dark, (int(4 * SCALE), int(7 * SCALE)), sh)
        base.alpha_composite(img)
        img = base
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    img.save(path, optimize=True)
    print("wrote", path, img.size)


# ---------------------------------------------------------------- box locks
def box_lock_shapes(cv):
    case, housing, recess, bolt = cv.mask(), cv.mask(), cv.mask(), cv.mask()
    cv.poly(case, [(8, 196), (24, 178), (432, 178), (448, 196), (448, 404),
                   (432, 420), (24, 420), (8, 404)])
    cv.rrect(housing, 144, 192, 312, 364, 12)
    for x in PINS:
        cv.rrect(recess, x - 9, 214, x + 9, 322, 4)
    cv.rrect(recess, 26, 318, 306, 348, 7)             # the keyway the pick enters by
    cv.rrect(bolt, 312, 300, 446, 352, 6)
    return arr(case), arr(housing), arr(recess), arr(bolt)


def rivet_points():
    return [(26, 196), (430, 196), (26, 402), (430, 402), (160, 206), (296, 206),
            (160, 350), (296, 350), (90, 384), (366, 384), (228, 398)]


def box_height(cv, rng):
    case, housing, recess, bolt = box_lock_shapes(cv)
    shape = case.shape
    h = 0.55 * bevel(case, 7 * SCALE) + 0.35 * bevel(housing, 5 * SCALE)
    h += 0.18 * bevel(bolt, 3 * SCALE) * case
    for gx in range(326, 440, 12):                      # grooves along the bolt
        g = cv.mask()
        cv.rrect(g, gx, 306, gx + 4, 346, 2)
        h -= 0.06 * blur(arr(g), 2) * bolt
    h -= 0.9 * blur(recess, 2.5)
    hammer = dents(shape, rng, 900, 6, 26) * case
    h += 0.035 * blur(hammer, 1.5)
    grain = noise(shape, 90, rng, 6)
    h += 0.04 * (grain - 0.5) * case
    rivets = np.zeros(shape, np.float32)
    for (x, y) in rivet_points():
        rivets = np.maximum(rivets, dome(cv, shape, x, y, 6.5))
    h += 0.22 * rivets
    return h, case, recess, rivets


def iron_lock():
    cv = Canvas(PLATE_RECT)
    rng = np.random.default_rng(11)
    h, case, recess, rivets = box_height(cv, rng)
    shape = h.shape
    h += 0.05 * blur(dents(shape, rng, 500, 14, 40), 2) * case      # deeper forging
    scr = scratches(shape, rng, 900, 70)
    h -= 0.03 * scr * case
    grain = noise(shape, 6, rng, 3, 0.6)
    h += 0.012 * (grain - 0.5) * case
    tone = noise(shape, 260, rng, 5)
    patina = noise(shape, 120, rng, 5)
    cool = np.array([0.30, 0.33, 0.36])
    warm = np.array([0.34, 0.31, 0.28])
    albedo = cool * (1 - patina[..., None]) + warm * patina[..., None]
    albedo *= (0.7 + 0.55 * tone[..., None]) * (0.9 + 0.2 * grain[..., None])
    worn = np.clip(bevel(case, 2.5 * SCALE) - bevel(case, 10 * SCALE), 0, 1)
    worn = np.maximum(worn, np.clip(bevel(blur(recess, 1) > 0.5, 2 * SCALE), 0, 1) * 0)
    albedo = albedo * (1 - 0.35 * worn[..., None]) + np.array([0.70, 0.72, 0.74]) * 0.35 * worn[..., None]
    grime = np.clip(blur(recess, 10) * 2.0 + (1 - bevel(case, 16 * SCALE)) * 0.6, 0, 1) * case
    grime *= noise(shape, 30, rng, 4)
    albedo *= (1 - 0.45 * grime[..., None])
    albedo += 0.16 * scr[..., None] * case[..., None]
    albedo = albedo * (1 - recess[..., None]) + np.array([0.04, 0.045, 0.05]) * recess[..., None]
    albedo = albedo * (1 - rivets[..., None] * 0.3) + np.array([0.55, 0.56, 0.58]) * rivets[..., None] * 0.3
    rgba = shade(h, albedo, case, strength=8.5, spec=0.6, gloss=34.0)
    save(rgba, "iron.png", shadow_from=case)


def rusted_lock():
    cv = Canvas(PLATE_RECT)
    rng = np.random.default_rng(23)
    h, case, recess, rivets = box_height(cv, rng)
    shape = h.shape
    # Where rust takes hold: the edges, round the rivets, at the keyway and
    # channels -- then wherever the large noise lets it spread.
    edges = np.clip(1.0 - bevel(case, 22 * SCALE), 0, 1) * case
    near = blur(recess, 14) * 2.2
    for (x, y) in rivet_points():
        near = np.maximum(near, blur(dome(cv, shape, x, y, 12.0), 6) * 1.4)
    spread = noise(shape, 220, rng, 6, 0.62)
    hold = np.clip(edges * 0.9 + near + spread * 1.15 - 0.62, 0, 1)
    edge_noise = noise(shape, 26, rng, 4, 0.7)
    rust = np.clip((hold + (edge_noise - 0.5) * 0.55 - 0.18) * 2.6, 0, 1) * case
    grain = noise(shape, 7, rng, 3, 0.6)
    pits = dents(shape, rng, 3200, 1.2, 5.5) * case
    h += 0.06 * pits * (0.4 + rust)
    h += 0.05 * (grain - 0.5) * rust
    # Scale lifting off in flakes: raised crust with a dark rim where it broke.
    flake = noise(shape, 40, rng, 5, 0.66)
    crust = np.clip((flake - 0.6) * 14.0, 0, 1) * rust
    rim = np.clip(blur(crust, 2) - crust, 0, 1) * 3.0
    h += 0.07 * blur(crust, 1.0)
    # Rust runs down from the rivets, the keyway and the channels.
    sources = recess.copy()
    for (x, y) in rivet_points():
        sources = np.maximum(sources, dome(cv, shape, x, y, 8.0))
    acc, streak = sources.copy(), np.zeros(shape, np.float32)
    step = int(3 * SCALE)
    for _ in range(30):
        acc = np.roll(acc, step, axis=0) * 0.9
        acc[:step] = 0
        streak = np.maximum(streak, acc)
    streak = blur(streak * (0.5 + 0.8 * noise(shape, 18, rng, 3)), 2.5) * case
    iron = np.array([0.24, 0.23, 0.22]) * (0.8 + 0.4 * noise(shape, 120, rng, 5)[..., None])
    deep = np.array([0.22, 0.09, 0.03])
    orange = np.array([0.58, 0.25, 0.07])
    ochre = np.array([0.72, 0.44, 0.17])
    hue = noise(shape, 60, rng, 5)[..., None]
    rust_col = deep * (1 - hue) + orange * hue
    rust_col *= (0.75 + 0.5 * grain[..., None])
    r = rust[..., None]
    albedo = iron * (1 - r) + rust_col * r
    albedo = albedo * (1 - crust[..., None] * 0.55) + ochre * crust[..., None] * 0.55
    albedo *= (1 - 0.55 * np.clip(rim, 0, 1)[..., None])
    albedo = albedo * (1 - 0.5 * streak[..., None]) + np.array([0.40, 0.15, 0.05]) * 0.5 * streak[..., None]
    albedo *= (1 - 0.35 * np.clip(pits * -1.5, 0, 1)[..., None])
    albedo = albedo * (1 - recess[..., None]) + np.array([0.05, 0.03, 0.02]) * recess[..., None]
    rough = np.clip(rust * 1.3, 0, 1)
    rgba = shade(h, albedo, case, strength=8.0, spec=0.22, gloss=16.0, rough=rough)
    save(rgba, "rusted.png", shadow_from=case)


# ------------------------------------------------------------------ padlock
def padlock():
    """A laminated steel padlock opened up, as a cutaway practice lock is: the
    shackle above, the body's laminations, and a window into the works -- the
    pin chambers standing upright above a brass plug, its keyway open at the
    body's left side, where the pick comes in. The pins and pick the game
    draws stand in these chambers (the box locks' layout)."""
    cv = Canvas(PADLOCK_RECT)
    rng = np.random.default_rng(37)
    body, shackle, window, plug, recess = (cv.mask() for _ in range(5))
    cv.rrect(body, 118, 196, 338, 412, 16)
    path = [(170, 204), (170, 160)]
    for i in range(0, 181, 6):
        a = math.radians(180 - i)
        path.append((228 + 58 * math.cos(a), 160 - 46 * math.sin(a)))
    path += [(286, 160), (286, 204)]
    cv.line(shackle, path, 24)
    cv.rrect(window, 146, 204, 312, 362, 6)             # the cutaway into the works
    cv.rrect(plug, 134, 310, 312, 356, 10)              # the brass plug, its shear line on top
    for x in PINS:
        cv.rrect(recess, x - 9, 212, x + 9, 324, 4)     # the pin chambers
    cv.rrect(recess, 112, 318, 306, 348, 7)             # the keyway, open at the left side
    b, sh, wn, pg, rc = arr(body), arr(shackle), arr(window), arr(plug), arr(recess)
    shape = b.shape
    h = 0.6 * bevel(b, 8 * SCALE) + 0.55 * bevel(sh, 6 * SCALE) * (1 - b)
    # Laminations: the stacked steel plates a padlock body is riveted from.
    lam = np.zeros(shape, np.float32)
    for y in range(206, 412, 9):
        g = cv.mask()
        cv.rrect(g, 118, y, 338, y + 1.4, 0.6)
        lam = np.maximum(lam, arr(g))
    h -= 0.05 * blur(lam, 1.2) * b * (1 - wn)
    h -= 0.45 * blur(wn, 2.5) * b                       # the window is cut in
    h += 0.42 * bevel(pg, 6 * SCALE) * wn               # the round plug stands proud in it
    h -= 0.7 * blur(rc * np.maximum(b, pg), 1.8)
    h += 0.03 * blur(dents(shape, rng, 600, 3, 14), 1.2) * b
    scr = scratches(shape, rng, 1100, 50)
    h -= 0.02 * scr * (b + sh)
    rivets = np.zeros(shape, np.float32)
    for (x, y) in ((132, 210), (324, 210), (132, 398), (324, 398), (170, 206), (286, 206)):
        rivets = np.maximum(rivets, dome(cv, shape, x, y, 5.5))
    h += 0.2 * rivets
    mark = cv.mask()
    cv.rrect(mark, 184, 374, 272, 400, 4)
    inner = cv.mask()
    cv.rrect(inner, 188, 378, 268, 396, 3)
    stamp = arr(mark) - arr(inner)
    for k, x in enumerate((198, 212, 226, 240, 254)):
        dot = cv.mask()
        cv.rrect(dot, x - 3.5, 382, x + 3.5, 392, 1.5)
        stamp = np.maximum(stamp, arr(dot) * 0.8)
    h -= 0.05 * blur(stamp, 1.0) * b
    alpha = np.clip(b + sh, 0, 1)
    tone = noise(shape, 220, rng, 5)
    steel = np.array([0.50, 0.52, 0.55]) * (0.78 + 0.4 * tone[..., None])
    albedo = steel.copy()
    edge = np.clip(bevel(b, 2.5 * SCALE) - bevel(b, 10 * SCALE), 0, 1) + np.clip(
        bevel(sh, 2 * SCALE) - bevel(sh, 7 * SCALE), 0, 1)
    albedo = albedo * (1 - 0.35 * edge[..., None]) + np.array([0.82, 0.84, 0.86]) * 0.35 * edge[..., None]
    albedo *= (1 - 0.35 * blur(lam, 1.5)[..., None] * (1 - wn[..., None]))
    grime = blur(np.clip(1 - h * 1.6, 0, 1), 8) * noise(shape, 40, rng, 4)
    albedo *= (1 - 0.3 * grime[..., None])
    albedo += 0.18 * scr[..., None] * alpha[..., None]
    inside = np.array([0.20, 0.21, 0.22])              # the body's drilled interior
    albedo = albedo * (1 - wn[..., None]) + inside * (0.7 + 0.5 * tone[..., None]) * wn[..., None]
    brass = np.array([0.66, 0.50, 0.26]) * (0.8 + 0.35 * noise(shape, 60, rng, 4)[..., None])
    on_plug = (pg * wn)[..., None]
    albedo = albedo * (1 - on_plug) + brass * on_plug
    albedo = albedo * (1 - rc[..., None]) + np.array([0.035, 0.035, 0.04]) * rc[..., None]
    rgba = shade(h, albedo, alpha, strength=7.5, spec=0.65, gloss=38.0)
    save(rgba, "padlock.png", shadow_from=alpha)


def main():
    iron_lock()
    rusted_lock()
    padlock()


if __name__ == "__main__":
    main()
