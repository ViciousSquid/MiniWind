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
padlock is drawn into QRectF(PADLOCK_RECT); its mechanism is turned upright
(the pick enters from below) and its channels are laid out to match.

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
PADLOCK_RECT = (100.0, 104.0, 270.0, 392.0)
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
def padlock_layout():
    """Plate-unit geometry of the padlock, and where the upright mechanism's
    channels land (game/ui/lockpicking.py turns it about (232, 314) by -90
    degrees at 0.8 scale)."""
    c, s = (232.0, 314.0), 0.8
    rows = [c[1] - s * (x - 228) for x in PINS]                # channel centre rows
    return {"centre": c, "scale": s, "rows": rows,
            "chan_x": (c[0] + s * (214 - 300), c[0] + s * (322 - 300)),
            "keyway_x": (c[0] + s * (318 - 300), c[0] + s * (348 - 300))}


def padlock():
    cv = Canvas(PADLOCK_RECT)
    rng = np.random.default_rng(37)
    lay = padlock_layout()
    body, shackle, recess, window = cv.mask(), cv.mask(), cv.mask(), cv.mask()
    cv.rrect(body, 132, 236, 332, 456, 30)
    path = [(176, 246), (176, 182)]
    for i in range(0, 181, 6):
        a = math.radians(180 - i)
        path.append((232 + 56 * math.cos(a), 182 - 64 * math.sin(a)))
    path += [(288, 182), (288, 246)]
    cv.line(shackle, path, 22)
    cv.rrect(window, 152, 252, 312, 380, 10)            # the cutaway into the works
    x0, x1 = lay["chan_x"]
    for row in lay["rows"]:
        cv.rrect(recess, x0, row - 7.4, x1, row + 7.4, 3)
    k0, k1 = lay["keyway_x"]
    cv.rrect(recess, k0, 300, k1, 470, 6)               # the keyway, out through the foot
    b, sh, rc, wn = arr(body), arr(shackle), arr(recess), arr(window)
    shape = b.shape
    h = 0.6 * bevel(b, 10 * SCALE) + 0.5 * bevel(sh, 5 * SCALE) * (1 - b)
    h += 0.5 * sh * 0  # the shackle's roundness comes from its bevel
    h -= 0.35 * blur(wn, 3) * b
    h -= 0.6 * blur(rc * np.maximum(b, wn), 2)
    cast = noise(shape, 70, rng, 6)
    h += 0.035 * (cast - 0.5) * b
    h += 0.03 * blur(dents(shape, rng, 500, 4, 18), 1.2) * b
    scr = scratches(shape, rng, 900, 50)
    h -= 0.02 * scr * (b + sh)
    # A stamped maker's mark on the face, below the cutaway.
    mark = cv.mask()
    cv.rrect(mark, 156, 398, 226, 428, 4)
    inner = cv.mask()
    cv.rrect(inner, 160, 402, 222, 424, 3)
    stamp = arr(mark) - arr(inner)
    border = cv.mask()
    cv.rrect(border, 140, 244, 324, 448, 24)
    border_in = cv.mask()
    cv.rrect(border_in, 143, 247, 321, 445, 21)
    stamp = np.maximum(stamp, (arr(border) - arr(border_in)) * 0.8)
    for k, x in enumerate((168, 180, 192, 204)):
        dot = cv.mask()
        cv.rrect(dot, x - 3, 410, x + 3, 420, 1.5)
        stamp = np.maximum(stamp, arr(dot) * (0.7 + 0.1 * k))
    h -= 0.05 * blur(stamp, 1.0)
    rivet = np.maximum(dome(cv, shape, 176, 252, 6.0), dome(cv, shape, 288, 252, 6.0))
    h += 0.18 * rivet
    alpha = np.clip(b + sh, 0, 1)
    steel = np.array([0.46, 0.48, 0.51])
    brass = np.array([0.62, 0.48, 0.26])
    tone = noise(shape, 220, rng, 5)
    patina = noise(shape, 90, rng, 5)
    body_col = brass * (0.75 + 0.45 * tone[..., None])
    body_col = body_col * (1 - 0.3 * patina[..., None]) + np.array([0.30, 0.30, 0.20]) * 0.3 * patina[..., None]
    steel_col = steel * (0.78 + 0.4 * tone[..., None])
    on_body = b[..., None]
    albedo = body_col * on_body + steel_col * (1 - on_body)
    edge = np.clip(bevel(b, 3 * SCALE) - bevel(b, 12 * SCALE), 0, 1) + np.clip(
        bevel(sh, 2 * SCALE) - bevel(sh, 6 * SCALE), 0, 1)
    shine = np.array([0.92, 0.80, 0.52]) * on_body + np.array([0.80, 0.82, 0.84]) * (1 - on_body)
    albedo = albedo * (1 - 0.35 * edge[..., None]) + shine * 0.35 * edge[..., None]
    grime = blur(np.clip(1 - h * 1.6, 0, 1), 8) * noise(shape, 40, rng, 4)
    albedo *= (1 - 0.35 * grime[..., None])
    albedo += 0.2 * scr[..., None] * alpha[..., None]
    albedo = albedo * (1 - wn[..., None] * 0.75) + np.array([0.05, 0.05, 0.06]) * wn[..., None] * 0.75
    albedo = albedo * (1 - rc[..., None]) + np.array([0.03, 0.03, 0.035]) * rc[..., None]
    rgba = shade(h, albedo, alpha, strength=7.5, spec=0.7, gloss=40.0)
    save(rgba, "padlock.png", shadow_from=alpha)


def main():
    iron_lock()
    rusted_lock()
    padlock()


if __name__ == "__main__":
    main()
