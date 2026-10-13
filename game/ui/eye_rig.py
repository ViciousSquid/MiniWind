"""
Eyes that follow the pointer, for a head sprite.

MiniWind's heads are single images with the eyes painted in. :func:`rig_for`
finds the eyes in one -- the bright, colourless whites, two of them side by
side in the lower half of the face -- and splits the picture into:

* the **head** with the irises and pupils painted out (filled with the white
  of the eye), and
* an **iris layer** holding just the irises and pupils,
* each eye's **shape** (the white plus what it encloses), to clip to.

:func:`draw` paints the head, then the iris layer shifted toward a point
(the mouse) and clipped to the eye shapes, so the pupils look at the pointer
while the lids and the rest of the face stay put. A head whose eyes cannot be
found (a helmet's slit, a beast) just draws as it is.

Pure NumPy over Qt images; results are cached per image and size.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np

_cache: Dict[Tuple[str, int], Optional["EyeRig"]] = {}

#: How far (as a fraction of an eye's height) the irises may travel.
TRAVEL = 0.33
#: Pointer distance (px) at which the eyes are looking fully that way.
FULL_LOOK = 260.0


def _to_array(img):
    from PyQt5.QtGui import QImage
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(h * img.bytesPerLine())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4]
    return arr.reshape(h, w, 4).copy()


def _to_image(arr):
    from PyQt5.QtGui import QImage
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888)
    return img.copy()          # own the pixels


def _components(mask):
    """Label 4-connected components; returns (labels, sizes)."""
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    sizes = [0]
    n = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if labels[y0, x0]:
            continue
        n += 1
        stack = [(y0, x0)]
        labels[y0, x0] = n
        count = 0
        while stack:
            y, x = stack.pop()
            count += 1
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not labels[yy, xx]:
                    labels[yy, xx] = n
                    stack.append((yy, xx))
        sizes.append(count)
    return labels, sizes


class EyeRig:
    def __init__(self, head, irises, shapes, centres, travel):
        self.head = head            # QImage: the face, irises painted out
        self.irises = irises        # QImage: the irises and pupils alone
        self.shapes = shapes        # QImage: alpha = where the eyes are
        self.centres = centres      # [(x, y)] of each eye, in image pixels
        self.travel = travel        # (x, y) px the irises may move


def _grow(mask, rx, ry):
    """*mask* grown by rx pixels sideways and ry up and down."""
    out = mask.copy()
    for d in range(1, rx + 1):
        out[:, d:] |= mask[:, :-d]
        out[:, :-d] |= mask[:, d:]
    grown = out.copy()
    for d in range(1, ry + 1):
        grown[d:] |= out[:-d]
        grown[:-d] |= out[d:]
    return grown


def build(arr) -> Optional[EyeRig]:
    """The rig for an RGBA array, or None if two eyes are not found."""
    h, w = arr.shape[:2]
    rgb = arr[..., :3].astype(np.int32)
    alpha = arr[..., 3]
    hi = rgb.max(-1)
    lo = rgb.min(-1)
    # Whites of the eyes: bright and nearly grey, in the face's lower half.
    white = (lo > 150) & (hi - lo < 60) & (alpha > 200)
    white[:int(h * 0.38)] = False
    white[int(h * 0.9):] = False
    # An iris splits each white in two: join the pieces of one eye -- pieces
    # side by side with a gap no wider than the eye is tall (an iris), not
    # the wider bridge of the nose between two eyes.
    labels, sizes = _components(white)
    frags = []
    for g in range(1, len(sizes)):
        if sizes[g] < 3:
            continue
        ys, xs = np.nonzero(labels == g)
        frags.append([g, ys.min(), ys.max(), xs.min(), xs.max()])
    parent = list(range(len(frags)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(frags):
        for j, b in enumerate(frags):
            if j <= i:
                continue
            overlap = min(a[2], b[2]) - max(a[1], b[1])
            tall = max(a[2] - a[1], b[2] - b[1]) + 1
            gap = max(a[3], b[3]) - min(a[4], b[4])
            if overlap >= -1 and gap <= tall * 1.6:
                parent[find(i)] = find(j)
    groups = {}
    for i, f in enumerate(frags):
        groups.setdefault(find(i), []).append(f[0])
    found = []
    for ids in groups.values():
        member = np.isin(labels, ids)
        n = int(member.sum())
        if n < max(6, (w * h) // 8000):
            continue
        ys, xs = np.nonzero(member)
        bh, bw = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
        # An eye is small and wider than tall: a white hood, a beard or a
        # helmet's shine is not.
        if bh > h * 0.11 or bw > w * 0.32 or bw < w * 0.012 or bw < bh * 0.4:
            continue
        found.append((n, member, ys, xs))
    pairs = []
    for a in range(len(found)):
        for b in range(a + 1, len(found)):
            ya, yb = found[a][2].mean(), found[b][2].mean()
            xa, xb = found[a][3].mean(), found[b][3].mean()
            sa, sb = found[a][0], found[b][0]
            if (abs(ya - yb) < h * 0.07 and abs(xa - xb) > w * 0.14
                    and min(sa, sb) > 0.35 * max(sa, sb)):
                pairs.append((sa + sb, a, b))
    if pairs:
        _, a, b = max(pairs)
        chosen = (a, b)
    else:
        # One eye in the middle of the face: a cyclops.
        middle = [k for k, f in enumerate(found)
                  if abs(f[3].mean() - w / 2.0) < w * 0.12]
        if not middle:
            return None
        chosen = (max(middle, key=lambda k: found[k][0]),)
    shape = np.zeros((h, w), bool)
    iris = np.zeros((h, w), bool)
    centres, heights = [], []
    widths = []
    for k in chosen:
        _n, member, ys, xs = found[k]
        y0, y1 = ys.min(), ys.max()
        eye = np.zeros((h, w), bool)
        # The eye spans from the white's leftmost to rightmost pixel on every
        # row; whatever is not white inside it is the iris and pupil.
        for y in range(y0, y1 + 1):
            row = np.nonzero(member[y])[0]
            if len(row):
                eye[y, row.min():row.max() + 1] = True
        shape |= eye
        iris |= eye & ~white
        centres.append((float(xs.mean()), float(ys.mean())))
        heights.append(float(y1 - y0 + 1))
        widths.append(float(xs.max() - xs.min() + 1))
    if iris.sum() < 4:
        return None
    sclera = rgb[white & shape]
    fill = np.median(sclera, axis=0) if len(sclera) else np.array([235, 235, 235])
    face = arr.copy()
    face[iris, :3] = fill.astype(np.uint8)
    layer = np.zeros_like(arr)
    layer[iris] = arr[iris]
    shapes = np.zeros_like(arr)
    shapes[shape, 3] = 255
    # Wide, narrow eyes: the irises travel further sideways than up and down.
    travel = (max(1.0, 0.22 * float(np.mean(widths))),
              max(1.0, 0.18 * float(np.mean(heights))))
    return EyeRig(_to_image(face), _to_image(layer), _to_image(shapes), centres, travel)


def _scaled(rig, src_w, size):
    """*rig* (built at the image's own size) scaled to *size* px."""
    from PyQt5.QtCore import Qt
    if src_w == size:
        return rig
    k = size / float(src_w)
    sc = lambda im: im.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return EyeRig(sc(rig.head), sc(rig.irises), sc(rig.shapes),
                  [(x * k, y * k) for x, y in rig.centres],
                  (rig.travel[0] * k, rig.travel[1] * k))


def rig_for(path: str, size: int) -> Optional[EyeRig]:
    """The rig for the head image at *path*, scaled to *size* px (cached)."""
    key = (str(path), int(size))
    if key in _cache:
        return _cache[key]
    rig = None
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QImage
        img = QImage(str(path))
        if not img.isNull():
            native = build(_to_array(img))
            if native is not None:
                rig = _scaled(native, img.width(), int(size))
    except Exception as exc:
        print(f"[MiniWind] eye rig for {path} failed: {exc}")
        rig = None
    _cache[key] = rig
    return rig


def look_offset(rig: EyeRig, origin, pointer) -> Tuple[float, float]:
    """How far to shift the irises for a pointer at *pointer* (view px), the
    head's top-left being at *origin*."""
    if pointer is None:
        return 0.0, 0.0
    cx = origin[0] + sum(c[0] for c in rig.centres) / len(rig.centres)
    cy = origin[1] + sum(c[1] for c in rig.centres) / len(rig.centres)
    dx, dy = float(pointer[0]) - cx, float(pointer[1]) - cy
    dist = math.hypot(dx, dy)
    if dist < 1e-3:
        return 0.0, 0.0
    reach = min(1.0, dist / FULL_LOOK)
    return dx / dist * reach * rig.travel[0], dy / dist * reach * rig.travel[1]


def draw(painter, rig: EyeRig, x: int, y: int, pointer) -> None:
    """Paint the head at (x, y) with its eyes on *pointer*."""
    from PyQt5.QtGui import QImage, QPainter
    painter.drawImage(int(x), int(y), rig.head)
    ox, oy = look_offset(rig, (x, y), pointer)
    eyes = QImage(rig.irises.size(), QImage.Format_ARGB32_Premultiplied)
    eyes.fill(0)
    p = QPainter(eyes)
    p.drawImage(int(round(ox)), int(round(oy)), rig.irises)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, rig.shapes)
    p.end()
    painter.drawImage(int(x), int(y), eyes)
