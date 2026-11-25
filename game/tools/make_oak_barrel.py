"""Build the oak barrel: the explosive barrel's model (engine.prop_entity).

    python game/tools/make_oak_barrel.py

Writes ``assets/models/Oak_Barrel.obj`` / ``.mtl`` and its texture atlas
``Oak_Barrel_Texture.png``: a cooper's barrel of bulging oak staves -- each
stave its own shade of oak, with grain, knots and a dark seam -- bound by
three dark iron hoops, its heads planked across. It stands on the oil drum's
footprint and height (45.6 across, 65.2 high, its origin on the floor), so a barrel's collision box, its
toppling and its blast are unchanged. Deterministic: the same file each run.

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
R_END = 19.6                  # at the heads
R_BULGE = 22.821355           # at the belly (half the drum's 45.64271)
STAVES = 20
RINGS = 12                    # rows of the staves' bulge
HEAD_INSET = 1.6              # the heads sit inside the stave ends (the chime)
#: Hoops: (height as a share of the barrel, half-width, how far they stand out).
HOOPS = ((0.10, 1.9, 0.5), (0.27, 1.5, 0.45), (0.73, 1.5, 0.45), (0.90, 1.9, 0.5))
TEX = 512

#: The atlas, in UV (0..1, v up): staves on the left 3/4, the hoop iron in a
#: strip on the right, a head (planks across) in the top-right square.
STAVE_U = (0.0, 0.75)
HOOP_UV = (0.77, 0.0, 0.99, 0.45)
HEAD_UV = (0.76, 0.52, 1.0, 1.0)


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
        self.v.append(p)
        return len(self.v)

    def uv(self, u, v):
        self.vt.append((u, v))
        return len(self.vt)

    def normal(self, n):
        length = math.sqrt(sum(c * c for c in n)) or 1.0
        self.vn.append(tuple(c / length for c in n))
        return len(self.vn)

    def quad(self, a, b, c, d):
        """Faces (v, vt, vn) tuples, counter-clockwise seen from outside."""
        self.f.append((a, b, c))
        self.f.append((a, c, d))


def staves(mesh):
    """The bulging side: each stave a flat strip of :data:`RINGS` rows, its own
    column of the atlas (so the texture's staves line up with the geometry)."""
    u0, u1 = STAVE_U
    for s in range(STAVES):
        a0 = 2 * math.pi * s / STAVES
        a1 = 2 * math.pi * (s + 1) / STAVES
        su0 = u0 + (u1 - u0) * s / STAVES
        su1 = u0 + (u1 - u0) * (s + 1) / STAVES
        mid = (a0 + a1) / 2
        rows = []
        for r in range(RINGS + 1):
            t = r / RINGS
            rad = radius_at(t)
            y = BASE_Y + HEIGHT * t
            # The normal leans with the bulge's slope.
            slope = (R_BULGE - R_END) * math.pi * math.cos(math.pi * t) / HEIGHT
            row = []
            for a, u in ((a0, su0), (a1, su1)):
                p = (rad * math.cos(a), y, rad * math.sin(a))
                n = (math.cos(mid), -slope, math.sin(mid))
                row.append((mesh.vert(p), mesh.uv(u, t), mesh.normal(n)))
            rows.append(row)
        for r in range(RINGS):
            (a, b), (d, c) = rows[r], rows[r + 1]
            # Outward-facing winding (the angle runs anticlockwise from above).
            mesh.quad(a, d, c, b)


def hoops(mesh):
    """Iron bands round the staves, standing proud of them."""
    hu0, hv0, hu1, hv1 = HOOP_UV
    segments = STAVES * 2
    for t, half, proud in HOOPS:
        lo_t, hi_t = t - half / HEIGHT, t + half / HEIGHT
        ring = []
        for k in range(segments + 1):
            a = 2 * math.pi * k / segments
            u = hu0 + (hu1 - hu0) * k / segments
            col = []
            for tt, v in ((lo_t, hv0), (hi_t, hv1)):
                rad = radius_at(tt) + proud
                p = (rad * math.cos(a), BASE_Y + HEIGHT * tt, rad * math.sin(a))
                col.append((mesh.vert(p), mesh.uv(u, v), mesh.normal((math.cos(a), 0.0, math.sin(a)))))
            ring.append(col)
        for k in range(segments):
            (a, d), (b, c) = ring[k], ring[k + 1]
            mesh.quad(a, d, c, b)
        # The hoop's top and bottom lips, so it reads as a band, not a decal.
        for tt, up in ((hi_t, 1.0), (lo_t, -1.0)):
            for k in range(segments):
                a0 = 2 * math.pi * k / segments
                a1 = 2 * math.pi * (k + 1) / segments
                y = BASE_Y + HEIGHT * tt
                ri, ro = radius_at(tt), radius_at(tt) + proud
                pts = [(ri * math.cos(a0), y, ri * math.sin(a0)), (ro * math.cos(a0), y, ro * math.sin(a0)),
                       (ro * math.cos(a1), y, ro * math.sin(a1)), (ri * math.cos(a1), y, ri * math.sin(a1))]
                n = mesh.normal((0.0, up, 0.0))
                ids = [(mesh.vert(p), mesh.uv(hu0, hv0), n) for p in pts]
                if up > 0:
                    mesh.quad(ids[0], ids[3], ids[2], ids[1])
                else:
                    mesh.quad(ids[0], ids[1], ids[2], ids[3])


def heads(mesh):
    """The planked heads, set into the staves' ends; and the chime -- the
    stave ends' inner faces down to them."""
    hu0, hv0, hu1, hv1 = HEAD_UV
    cu, cv = (hu0 + hu1) / 2, (hv0 + hv1) / 2
    ru, rv = (hu1 - hu0) / 2, (hv1 - hv0) / 2
    segments = STAVES * 2
    for top in (True, False):
        y_end = BASE_Y + (HEIGHT if top else 0.0)
        y = y_end - HEAD_INSET if top else y_end + HEAD_INSET
        r = R_END - 0.9
        up = 1.0 if top else -1.0
        n = mesh.normal((0.0, up, 0.0))
        centre = (mesh.vert((0.0, y, 0.0)), mesh.uv(cu, cv), n)
        rim = []
        for k in range(segments + 1):
            a = 2 * math.pi * k / segments
            rim.append((mesh.vert((r * math.cos(a), y, r * math.sin(a))),
                        mesh.uv(cu + ru * 0.96 * math.cos(a), cv + rv * 0.96 * math.sin(a)), n))
        for k in range(segments):
            if top:
                mesh.f.append((centre, rim[k + 1], rim[k]))
            else:
                mesh.f.append((centre, rim[k], rim[k + 1]))
        # The chime: the inside of the stave ends, from their rim down to the head.
        su = STAVE_U[0] + 0.004
        for k in range(segments):
            a0 = 2 * math.pi * k / segments
            a1 = 2 * math.pi * (k + 1) / segments
            pts = [(R_END * math.cos(a0), y_end, R_END * math.sin(a0)),
                   (R_END * math.cos(a1), y_end, R_END * math.sin(a1)),
                   (r * math.cos(a1), y, r * math.sin(a1)),
                   (r * math.cos(a0), y, r * math.sin(a0))]
            nn = mesh.normal((-math.cos((a0 + a1) / 2), 0.0, -math.sin((a0 + a1) / 2)))
            ids = [(mesh.vert(p), mesh.uv(su, 0.98 if top else 0.02), nn) for p in pts]
            if top:
                mesh.quad(ids[0], ids[3], ids[2], ids[1])
            else:
                mesh.quad(ids[0], ids[1], ids[2], ids[3])
            # The stave ends' rim, end grain, facing out of the barrel.
            rim_pts = [(R_END * math.cos(a0), y_end, R_END * math.sin(a0)),
                       (R_END * math.cos(a1), y_end, R_END * math.sin(a1)),
                       ((R_END + 1.2) * math.cos(a1), y_end, (R_END + 1.2) * math.sin(a1)),
                       ((R_END + 1.2) * math.cos(a0), y_end, (R_END + 1.2) * math.sin(a0))]
            ids = [(mesh.vert(p), mesh.uv(su, 0.99 if top else 0.01), mesh.normal((0, up, 0))) for p in rim_pts]
            if top:
                mesh.quad(ids[0], ids[1], ids[2], ids[3])
            else:
                mesh.quad(ids[0], ids[3], ids[2], ids[1])


def write_obj(mesh, path):
    lines = ["# Oak barrel -- game/tools/make_oak_barrel.py (Fio units: the oil drum's).",
             f"mtllib {NAME}.mtl", "g barrel", "usemtl OakBarrel"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in mesh.v]
    lines += [f"vt {u:.5f} {v:.5f}" for u, v in mesh.vt]
    lines += [f"vn {x:.4f} {y:.4f} {z:.4f}" for x, y, z in mesh.vn]
    for face in mesh.f:
        lines.append("f " + " ".join(f"{v}/{t}/{n}" for v, t, n in face))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mtl(path):
    path.write_text(
        "# Oak barrel: oak staves and heads, dark iron hoops, in one atlas.\n"
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
    oak = np.array([150, 104, 62], dtype=np.float32)

    # Staves: columns, each its own shade, with grain and a dark seam between.
    width = TEX * (STAVE_U[1] - STAVE_U[0])
    stave_w = width / STAVES
    for s in range(STAVES):
        x0, x1 = int(s * stave_w), int((s + 1) * stave_w)
        shade = 0.80 + 0.32 * rng.random()
        warm = np.array([1.0, 0.96 + 0.06 * rng.random(), 0.9 + 0.12 * rng.random()])
        cols = slice(x0, x1)
        local = xs[:, cols] - x0
        phase = rng.random() * 50
        grain = (0.5 + 0.5 * np.sin((ys[:, cols] * 0.045 + local * 0.9 + phase)
                                     + 2.2 * np.sin(ys[:, cols] * 0.011 + phase)))
        fine = rng.random((TEX, x1 - x0)) * 0.12
        tone = shade * (0.78 + 0.22 * grain) - fine
        img[:, cols] = oak * warm * tone[..., None]
        # A knot or two.
        for _ in range(rng.integers(0, 3)):
            ky, kx = rng.integers(20, TEX - 20), rng.integers(x0 + 4, max(x0 + 5, x1 - 4))
            d = np.hypot(ys[:, cols] - ky, (xs[:, cols] - kx) * 1.8)
            img[:, cols] *= (1.0 - 0.45 * np.exp(-(d / 5.0) ** 2))[..., None]
        # The seam: dark at the stave's edges.
        edge = np.minimum(local, (x1 - x0 - 1) - local)
        img[:, cols] *= np.clip(0.35 + 0.65 * (edge / 2.0), 0.35, 1.0)[..., None]

    # Hoop iron: dark, a little mottled, a highlight along its middle.
    hx0, hy1 = int(HOOP_UV[0] * TEX), TEX - int(HOOP_UV[1] * TEX)
    hx1, hy0 = int(HOOP_UV[2] * TEX), TEX - int(HOOP_UV[3] * TEX)
    region = (slice(hy0, hy1), slice(hx0, hx1))
    across = (ys[region] - hy0) / max(1, hy1 - hy0)
    iron = 48 + 40 * np.exp(-((across - 0.45) / 0.18) ** 2) + rng.random(across.shape) * 14
    img[region] = np.stack([iron * 1.0, iron * 0.97, iron * 0.95], axis=-1)
    for k in range(6):          # rivets
        ry = int(hy0 + (hy1 - hy0) * (0.1 + 0.16 * k))
        rx = int((hx0 + hx1) / 2)
        d = np.hypot(ys[region] - ry, xs[region] - rx)
        img[region] += (70 * np.exp(-(d / 2.2) ** 2))[..., None]

    # The head: planks across, a dark ring at the edge, a bung.
    gx0, gx1 = int(HEAD_UV[0] * TEX), int(HEAD_UV[2] * TEX)
    gy0, gy1 = TEX - int(HEAD_UV[3] * TEX), TEX - int(HEAD_UV[1] * TEX)
    region = (slice(gy0, gy1), slice(gx0, gx1))
    hy, hx = ys[region] - gy0, xs[region] - gx0
    h, w = gy1 - gy0, gx1 - gx0
    plank = (hy / (h / 5.0)).astype(int)
    shades = 0.78 + 0.28 * rng.random(6)
    grain = 0.5 + 0.5 * np.sin(hx * 0.07 + plank * 1.7 + 2.0 * np.sin(hy * 0.05))
    tone = shades[np.clip(plank, 0, 5)] * (0.8 + 0.2 * grain)
    img[region] = oak * 0.92 * tone[..., None]
    seam = np.abs((hy % (h / 5.0)) - 0.0) < 1.2
    img[region] *= np.where(seam, 0.45, 1.0)[..., None]
    r = np.hypot(hx - w / 2, hy - h / 2) / (min(w, h) / 2)
    img[region] *= np.clip(1.25 - 0.6 * np.clip(r - 0.78, 0, 1) * 4, 0.35, 1.0)[..., None]
    bung = np.exp(-(np.hypot(hx - w * 0.68, hy - h * 0.5) / 5.0) ** 2)
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
    hoops(mesh)
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
          f"{max(xs) - min(xs):.1f} wide, {max(ys) - min(ys):.1f} high")
    sys.exit(0)
