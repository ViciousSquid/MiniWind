"""Build the oak barrel: the explosive barrel's model (engine.prop_entity).

    python game/tools/make_oak_barrel.py

Writes ``assets/models/Oak_Barrel.obj`` / ``.mtl`` and its texture atlas
``Oak_Barrel_Texture.png``: a low-poly cooper's barrel -- twelve flat oak
staves in four bands that make its bulge, flat twelve-sided heads -- about
120 triangles. The detail is in the texture: each stave its own shade of oak
with grain and a dark seam, four dark iron hoops painted round it, the heads
planked across. It stands on the old oil drum's bounds exactly (45.64
across, 65.18 high, its origin on the floor), so a barrel's collision box,
its toppling and its blast are unchanged. Deterministic: the same files
each run.

Pure Python, numpy and Qt; no third-party meshes or textures.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "assets" / "models"
NAME = "Oak_Barrel"

HEIGHT = 65.181947            # the old oil drum's bounds, exactly: the
BASE_Y = 0.0                  # barrel's collision box and physics are its
R_END = 19.0                  # at the heads
R_BULGE = 22.821355           # at the belly (half the drum's 45.64271)
STAVES = 12                   # a multiple of 4: the box is square
BANDS = 4                     # rows of the bulge (even: one edge at the belly)
#: Painted hoops: (height as a share of the barrel, half-height as a share).
HOOPS = ((0.07, 0.035), (0.30, 0.028), (0.70, 0.028), (0.93, 0.035))
TEX = 256

#: The atlas, in UV (0..1, v up): staves (hoops painted on) on the left 3/4,
#: a head (planks across) in the right quarter.
STAVE_U = (0.0, 0.75)
HEAD_UV = (0.76, 0.38, 1.0, 0.62)


def radius_at(t):
    """The barrel's radius at height share *t* (0 bottom .. 1 top): the
    staves bulge to :data:`R_BULGE` at the middle."""
    return R_END + (R_BULGE - R_END) * math.sin(math.pi * max(0.0, min(1.0, t)))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
class Mesh:
    def __init__(self):
        self.v, self.vt, self.vn, self.f = [], [], [], []

    def vert(self, p):
        self.v.append(tuple(p))
        return len(self.v)

    def uv(self, u, v):
        self.vt.append((u, v))
        return len(self.vt)

    def normal(self, n):
        length = math.sqrt(sum(c * c for c in n)) or 1.0
        self.vn.append(tuple(c / length for c in n))
        return len(self.vn)


def _ring_point(t, angle):
    r = radius_at(t)
    return (r * math.cos(angle), BASE_Y + HEIGHT * t, r * math.sin(angle))


def staves(mesh):
    """The side: each stave a flat strip of :data:`BANDS` flat faces, each
    face its own normal (the low-poly facets), its own column of the atlas."""
    u0, u1 = STAVE_U
    rings = [[mesh.vert(_ring_point(b / BANDS, 2 * math.pi * s / STAVES))
              for s in range(STAVES)] for b in range(BANDS + 1)]
    for s in range(STAVES):
        s1 = (s + 1) % STAVES
        su0 = u0 + (u1 - u0) * s / STAVES
        su1 = u0 + (u1 - u0) * (s + 1) / STAVES
        for b in range(BANDS):
            t0, t1 = b / BANDS, (b + 1) / BANDS
            pa, pb = mesh.v[rings[b][s] - 1], mesh.v[rings[b][s1] - 1]
            pc = mesh.v[rings[b + 1][s1] - 1]
            e1 = [pb[i] - pa[i] for i in range(3)]
            e2 = [pc[i] - pa[i] for i in range(3)]
            n = mesh.normal((e2[1] * e1[2] - e2[2] * e1[1],
                             e2[2] * e1[0] - e2[0] * e1[2],
                             e2[0] * e1[1] - e2[1] * e1[0]))
            a = (rings[b][s], mesh.uv(su0, t0), n)
            bb = (rings[b][s1], mesh.uv(su1, t0), n)
            c = (rings[b + 1][s1], mesh.uv(su1, t1), n)
            d = (rings[b + 1][s], mesh.uv(su0, t1), n)
            mesh.f.append((a, d, c))
            mesh.f.append((a, c, bb))


def heads(mesh):
    """The flat heads, closing the stave ends."""
    hu0, hv0, hu1, hv1 = HEAD_UV
    cu, cv = (hu0 + hu1) / 2, (hv0 + hv1) / 2
    ru, rv = (hu1 - hu0) / 2, (hv1 - hv0) / 2
    for top in (True, False):
        t = 1.0 if top else 0.0
        n = mesh.normal((0.0, 1.0 if top else -1.0, 0.0))
        centre = (mesh.vert((0.0, BASE_Y + HEIGHT * t, 0.0)), mesh.uv(cu, cv), n)
        rim = []
        for s in range(STAVES):
            a = 2 * math.pi * s / STAVES
            rim.append((mesh.vert(_ring_point(t, a)),
                        mesh.uv(cu + ru * math.cos(a), cv + rv * math.sin(a)), n))
        for s in range(STAVES):
            nxt = rim[(s + 1) % STAVES]
            mesh.f.append((centre, nxt, rim[s]) if top else (centre, rim[s], nxt))


def write_obj(mesh, path):
    lines = ["# Oak barrel (low poly) -- game/tools/make_oak_barrel.py.",
             f"mtllib {NAME}.mtl", "g barrel", "usemtl OakBarrel"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in mesh.v]
    lines += [f"vt {u:.5f} {v:.5f}" for u, v in mesh.vt]
    lines += [f"vn {x:.4f} {y:.4f} {z:.4f}" for x, y, z in mesh.vn]
    for face in mesh.f:
        lines.append("f " + " ".join(f"{v}/{t}/{n}" for v, t, n in face))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mtl(path):
    path.write_text(
        "# Oak barrel: oak staves and heads, iron hoops, in one atlas.\n"
        "newmtl OakBarrel\nillum 2\nKa 0.10 0.08 0.06\nKd 1.00 1.00 1.00\n"
        "Ks 0.08 0.07 0.06\nNs 12.0\nd 1.0\n"
        f"map_Kd {NAME}_Texture.png\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Texture
# ---------------------------------------------------------------------------
def texture():
    """The atlas as an RGB array (rows top to bottom)."""
    rng = np.random.default_rng(7)
    img = np.zeros((TEX, TEX, 3), dtype=np.float32)
    ys, xs = np.mgrid[0:TEX, 0:TEX].astype(np.float32)
    oak = np.array([160, 110, 64], dtype=np.float32)

    # Staves: columns, each its own shade, with grain and a dark seam between.
    width = TEX * (STAVE_U[1] - STAVE_U[0])
    stave_w = width / STAVES
    for s in range(STAVES):
        x0, x1 = int(round(s * stave_w)), int(round((s + 1) * stave_w))
        cols = slice(x0, x1)
        shade = 0.82 + 0.3 * rng.random()
        warm = np.array([1.0, 0.95 + 0.07 * rng.random(), 0.88 + 0.14 * rng.random()])
        local = xs[:, cols] - x0
        phase = rng.random() * 50
        grain = 0.5 + 0.5 * np.sin(ys[:, cols] * 0.09 + local * 0.7 + phase
                                   + 2.0 * np.sin(ys[:, cols] * 0.022 + phase))
        tone = shade * (0.8 + 0.2 * grain) - rng.random((TEX, x1 - x0)) * 0.08
        img[:, cols] = oak * warm * tone[..., None]
        edge = np.minimum(local, (x1 - x0 - 1) - local)
        img[:, cols] *= np.clip(0.4 + 0.6 * edge, 0.4, 1.0)[..., None]

    # Hoops: dark iron bands across the staves, a highlight along each, rivets.
    stave_cols = slice(0, int(width))
    t = 1.0 - (ys[:, stave_cols] + 0.5) / TEX          # height share (v up)
    for centre, half in HOOPS:
        inside = np.abs(t - centre) <= half
        across = (t - (centre - half)) / (2 * half)
        iron = 52 + 46 * np.exp(-((across - 0.4) / 0.2) ** 2)
        band = np.stack([iron, iron * 0.97, iron * 0.94], axis=-1)
        img[:, stave_cols] = np.where(inside[..., None], band, img[:, stave_cols])
        edge = np.abs(np.abs(t - centre) - half) < 0.006
        img[:, stave_cols] = np.where(edge[..., None], img[:, stave_cols] * 0.55, img[:, stave_cols])
        row = int(round((1.0 - centre) * TEX))
        for s in range(STAVES):
            cx = (s + 0.5) * stave_w
            d = np.hypot(ys[:, stave_cols] - row, xs[:, stave_cols] - cx)
            img[:, stave_cols] += (60 * np.exp(-(d / 1.6) ** 2) * inside)[..., None]

    # The head: planks across, darker towards the rim, a bung.
    gx0, gx1 = int(HEAD_UV[0] * TEX), int(HEAD_UV[2] * TEX)
    gy0, gy1 = TEX - int(HEAD_UV[3] * TEX), TEX - int(HEAD_UV[1] * TEX)
    region = (slice(gy0, gy1), slice(gx0, gx1))
    hy, hx = ys[region] - gy0, xs[region] - gx0
    h, w = gy1 - gy0, gx1 - gx0
    plank_h = h / 5.0
    plank = np.clip((hy / plank_h).astype(int), 0, 4)
    shades = 0.85 + 0.25 * rng.random(5)
    grain = 0.5 + 0.5 * np.sin(hx * 0.12 + plank * 1.7 + 2.0 * np.sin(hy * 0.1))
    img[region] = oak * 1.12 * (shades[plank] * (0.82 + 0.18 * grain))[..., None]
    seam = (hy % plank_h) < 1.0
    img[region] *= np.where(seam, 0.5, 1.0)[..., None]
    r = np.hypot((hx - w / 2) / (w / 2), (hy - h / 2) / (h / 2))
    img[region] *= np.clip(1.0 - 2.2 * np.clip(r - 0.82, 0, 1), 0.4, 1.0)[..., None]
    bung = np.exp(-(np.hypot(hx - w * 0.68, hy - h * 0.5) / 3.0) ** 2)
    img[region] *= (1.0 - 0.55 * bung)[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def write_png(rgb, path):
    from PyQt5.QtGui import QImage
    h, w, _ = rgb.shape
    data = np.ascontiguousarray(rgb).tobytes()
    image = QImage(data, w, h, w * 3, QImage.Format_RGB888).copy()
    if not image.save(str(path), "PNG"):
        raise OSError(f"could not write {path}")


def build():
    mesh = Mesh()
    staves(mesh)
    heads(mesh)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    write_obj(mesh, MODEL_DIR / f"{NAME}.obj")
    write_mtl(MODEL_DIR / f"{NAME}.mtl")
    write_png(texture(), MODEL_DIR / f"{NAME}_Texture.png")
    return mesh


if __name__ == "__main__":
    mesh = build()
    xs = [p[0] for p in mesh.v]
    ys = [p[1] for p in mesh.v]
    print(f"{NAME}: {len(mesh.v)} vertices, {len(mesh.f)} triangles, "
          f"{max(xs) - min(xs):.2f} wide, {max(ys) - min(ys):.2f} high")
    sys.exit(0)
