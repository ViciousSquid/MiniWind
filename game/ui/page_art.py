"""
The look of a page: torn scraps, illuminated borders and initials.

Every book and note is read on paper (game/ui/book_window.py); some of them
are dressed up:

* **torn** (notes only): a scrap of brown kraft paper with ragged, fibrous
  torn edges -- the lighter fibres showing where it was ripped -- faint
  lines in the grain and a darker curl along one side;
* **illuminated** (books only): a painted vine climbing the margins -- a
  stem with leaves, little flowers in blue and red, gold dots -- and an
  illuminated initial at the head of the text: a gold letter on a blue
  ground, edged in gold, with red in its corner and white tendrils.

A note is a plain sheet or a torn scrap, never illuminated; a book is plain
or illuminated, never torn. Which one is its item's ``"style"`` when
authored (and allowed), else picked steadily from its id (:func:`style_of`).
A page of the Millbrook Crier is always newsprint.
Every picture is drawn here, procedurally, and cached.
"""

from __future__ import annotations

import math
import random
import zlib

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen)

PLAIN = "plain"
TORN = "torn"
ILLUMINATED = "illuminated"
NEWSPRINT = "newsprint"
STYLES = (PLAIN, TORN, ILLUMINATED)

#: The share of the notes torn and of the books illuminated, when their item
#: does not say.
NOTE_TORN = 0.4
BOOK_ILLUMINATED = 0.4
#: The styles each may have.
NOTE_STYLES = (PLAIN, TORN)
BOOK_STYLES = (PLAIN, ILLUMINATED)

#: Lines of text an illuminated initial stands beside.
CAP_LINES = 3

STEM = QColor(70, 104, 58)
LEAF = QColor(96, 136, 72)
LEAF_DARK = QColor(52, 82, 44)
BLUE = QColor(52, 84, 156)
RED = QColor(168, 54, 38)
GOLD = QColor(196, 152, 58)
GOLD_HI = QColor(236, 204, 120)
INK_EDGE = QColor(60, 40, 24)


def _unit(item_id) -> float:
    return (zlib.crc32(str(item_id).encode("utf-8")) % 10000) / 10000.0


def style_of(item_id, note=False) -> str:
    """How the book or note *item_id* is dressed (module docstring)."""
    from ..rpg import items
    if note and "crier" in str(item_id):
        return NEWSPRINT
    d = items.get(item_id)
    authored = str(d.get("style") or "") if d is not None else ""
    if authored in (NOTE_STYLES if note else BOOK_STYLES):
        return authored
    u = _unit(item_id)
    if note:
        return TORN if u < NOTE_TORN else PLAIN
    return ILLUMINATED if u < BOOK_ILLUMINATED else PLAIN


# --------------------------------------------------------------- torn paper
_torn_cache = {}

#: How far in from the image's edge the ragged edge may wander (fraction).
TORN_INSET = 0.07


def torn_paper(w, h, seed=0):
    """A torn scrap of kraft paper filling a ``w`` x ``h`` image, with its
    shadow; transparent outside the tear (cached)."""
    key = (int(w), int(h), int(seed))
    if key in _torn_cache:
        return _torn_cache[key]
    from PIL import Image, ImageDraw, ImageFilter
    rng = np.random.default_rng(seed)
    inset = min(w, h) * TORN_INSET

    def ragged(n, amp):
        """An edge profile: big lazy rips and small fibrous teeth."""
        t = np.linspace(0.0, 1.0, n)
        big = sum(rng.uniform(0.3, 1.0) * np.sin(t * math.tau * f + rng.uniform(0, math.tau))
                  for f in (1.3, 2.7, 5.1, 9.3))
        # Fine fibrous teeth, smoothed so the tear wavers rather than zigzags.
        teeth = np.convolve(rng.normal(0.0, 1.0, n + 8), np.ones(5) / 5.0, mode="same")[4:-4]
        prof = big / 3.0 + teeth * 0.18
        prof = (prof - prof.min()) / max(1e-6, prof.max() - prof.min())
        return prof * amp
    n_x, n_y = max(80, w // 2), max(80, h // 2)
    top = ragged(n_x, inset * 1.6)
    bottom = ragged(n_x, inset * 1.2)
    left = ragged(n_y, inset * 0.9)
    pts = [(x, top[i] + 4) for i, x in enumerate(np.linspace(inset * 0.4, w - inset * 0.4, n_x))]
    pts += [(w - 6 - left[i] * 0.4, y) for i, y in enumerate(np.linspace(inset, h - inset, n_y))]
    pts += [(x, h - 6 - bottom[i]) for i, x in enumerate(np.linspace(w - inset * 0.4, inset * 0.4, n_x))]
    pts += [(left[i] + 4, y) for i, y in enumerate(np.linspace(h - inset, inset, n_y))]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon([(float(x), float(y)) for x, y in pts], fill=255)
    inner = mask.filter(ImageFilter.MinFilter(5))
    a_mask = np.asarray(mask, np.float32) / 255.0
    a_inner = np.asarray(inner, np.float32) / 255.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    # Kraft: brown, fibrous, a faint ruled grain, darker where it curls.
    base = np.array([196, 158, 108], np.float32)
    grain = (rng.random((h, w)).astype(np.float32) - 0.5) * 14
    lines = 6.0 * np.sin(ys / 9.0 + np.sin(xs / 70.0)) * (rng.random((h, 1)) > 0.5)
    curl = np.clip((xs - w * 0.86) / (w * 0.14), 0.0, 1.0) ** 2
    img = base[None, None, :] + (grain + lines * 0.4)[..., None]
    img *= (1.0 - 0.28 * curl)[..., None]
    # The torn edge shows the paper's pale fibres.
    fibre = np.clip(a_mask - a_inner, 0.0, 1.0)
    img = img * (1 - fibre[..., None]) + np.array([232, 214, 178]) * fibre[..., None]
    rgba = np.dstack([np.clip(img, 0, 255), a_mask * 255]).astype(np.uint8)
    sheet = Image.fromarray(rgba, "RGBA")
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 120), mask=mask.filter(ImageFilter.GaussianBlur(6)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.alpha_composite(shadow, (6, 8))
    out.alpha_composite(sheet)
    data = np.ascontiguousarray(np.asarray(out))
    qimg = QImage(data.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    _torn_cache[key] = qimg
    return qimg


# ------------------------------------------------------------ illumination
def _leaf(painter, at, angle, size):
    """One leaf: a pointed oval along *angle*, with its midrib."""
    painter.save()
    painter.translate(at)
    painter.rotate(math.degrees(angle))
    path = QPainterPath()
    path.moveTo(0, 0)
    path.cubicTo(size * 0.35, -size * 0.32, size * 0.75, -size * 0.25, size, 0)
    path.cubicTo(size * 0.75, size * 0.25, size * 0.35, size * 0.32, 0, 0)
    painter.setPen(QPen(LEAF_DARK, max(1.0, size * 0.07)))
    painter.setBrush(LEAF)
    painter.drawPath(path)
    painter.setPen(QPen(LEAF_DARK, max(0.8, size * 0.04)))
    painter.drawLine(QPointF(size * 0.1, 0), QPointF(size * 0.85, 0))
    painter.restore()


def _flower(painter, at, size, colour):
    """A little five-petalled flower with a gold heart."""
    painter.save()
    painter.setPen(QPen(INK_EDGE, max(0.8, size * 0.06)))
    painter.setBrush(colour)
    for k in range(5):
        a = k / 5 * math.tau - math.pi / 2
        c = QPointF(at.x() + math.cos(a) * size * 0.42, at.y() + math.sin(a) * size * 0.42)
        painter.drawEllipse(c, size * 0.3, size * 0.3)
    painter.setBrush(GOLD)
    painter.drawEllipse(at, size * 0.22, size * 0.22)
    painter.restore()


def _bell(painter, at, angle, size):
    """A hanging blue bell-flower, as on the old borders."""
    painter.save()
    painter.translate(at)
    painter.rotate(math.degrees(angle))
    path = QPainterPath()
    path.moveTo(0, 0)
    path.cubicTo(size * 0.5, -size * 0.45, size * 0.9, -size * 0.35, size, -size * 0.5)
    path.lineTo(size * 0.85, 0)
    path.lineTo(size, size * 0.5)
    path.cubicTo(size * 0.9, size * 0.35, size * 0.5, size * 0.45, 0, 0)
    painter.setPen(QPen(INK_EDGE, max(0.8, size * 0.06)))
    painter.setBrush(BLUE)
    painter.drawPath(path)
    painter.restore()


def draw_vine(painter, points, seed, scale=1.0):
    """A painted vine along *points* (QPointF, in order): a wavering stem,
    leaves either side, flowers, bells and gold dots."""
    if len(points) < 2:
        return
    rng = random.Random(seed)
    path = QPainterPath(points[0])
    for a, b in zip(points, points[1:]):
        mid = QPointF((a.x() + b.x()) / 2 + rng.uniform(-6, 6) * scale,
                      (a.y() + b.y()) / 2 + rng.uniform(-6, 6) * scale)
        path.quadTo(mid, b)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(INK_EDGE, 4.2 * scale, Qt.SolidLine, Qt.RoundCap))
    painter.drawPath(path)
    painter.setPen(QPen(STEM, 2.6 * scale, Qt.SolidLine, Qt.RoundCap))
    painter.drawPath(path)
    length = path.length()
    step = 26.0 * scale
    n = int(length // step)
    for k in range(1, n):
        t = path.percentAtLength(k * step)
        at = path.pointAtPercent(t)
        ang = math.radians(-path.angleAtPercent(t))
        side = 1 if k % 2 else -1
        if k % 7 == 3:
            _flower(painter, at + QPointF(math.cos(ang + side * 1.2) * 9 * scale,
                                          math.sin(ang + side * 1.2) * 9 * scale),
                    11 * scale, RED if rng.random() < 0.5 else BLUE)
        elif k % 9 == 5:
            _bell(painter, at, ang + side * 1.1, 15 * scale)
        else:
            _leaf(painter, at, ang + side * rng.uniform(0.7, 1.1), rng.uniform(9, 13) * scale)
        if k % 4 == 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(GOLD)
            off = ang - side * 1.4
            painter.drawEllipse(QPointF(at.x() + math.cos(off) * 7 * scale,
                                        at.y() + math.sin(off) * 7 * scale),
                                2.2 * scale, 2.2 * scale)
    # A flower at each end.
    _flower(painter, points[-1], 13 * scale, RED)
    _flower(painter, points[0], 10 * scale, BLUE)
    painter.restore()


def border_points(rect, side, margin, seed):
    """An L-shaped run of points down the *side* ("left" or "right") margin of
    *rect* and along its top, a little wavering (QPointF list)."""
    rng = random.Random(seed)
    x_in = rect.left() + margin * 0.5 if side == "left" else rect.right() - margin * 0.5
    top = rect.top() + margin * 0.45
    pts = []
    for k in range(9):
        y = rect.bottom() - margin * 0.6 - (rect.height() - margin * 1.2) * k / 8
        pts.append(QPointF(x_in + rng.uniform(-3, 3), y))
    span = rect.width() * 0.62
    for k in range(1, 6):
        dx = span * k / 5
        x = x_in + dx if side == "left" else x_in - dx
        pts.append(QPointF(x, top + rng.uniform(-3, 3)))
    return pts


def cap_size(line_h) -> int:
    """The side of an illuminated initial standing beside CAP_LINES lines."""
    return int(line_h * CAP_LINES - 4)


def draw_initial(painter, letter, rect, font, seed=0):
    """An illuminated initial in *rect*: a gold letter on a blue ground,
    edged in gold, red in a corner, white tendrils."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    r = QRectF(rect)
    painter.setPen(QPen(INK_EDGE, 1.4))
    painter.setBrush(GOLD)
    painter.drawRect(r)
    inner = r.adjusted(4, 4, -4, -4)
    painter.setBrush(BLUE)
    painter.drawRect(inner)
    corner = QPainterPath()
    corner.moveTo(inner.topLeft())
    corner.lineTo(inner.left() + inner.width() * 0.45, inner.top())
    corner.lineTo(inner.left(), inner.top() + inner.height() * 0.45)
    corner.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(RED)
    painter.drawPath(corner)
    rng = random.Random(seed)
    painter.setPen(QPen(QColor(245, 240, 225, 200), 1.2))
    painter.setBrush(Qt.NoBrush)
    for _ in range(6):
        cx, cy = rng.uniform(inner.left() + 6, inner.right() - 6), rng.uniform(inner.top() + 6, inner.bottom() - 6)
        rad = rng.uniform(3, 6)
        painter.drawArc(QRectF(cx - rad, cy - rad, rad * 2, rad * 2),
                        rng.randrange(0, 360) * 16, 240 * 16)
    text = QPainterPath()
    text.addText(0, 0, font, letter)
    tb = text.boundingRect()
    text.translate(inner.center().x() - tb.center().x(), inner.center().y() - tb.center().y())
    g = QLinearGradient(inner.topLeft(), inner.bottomRight())
    g.setColorAt(0.0, GOLD_HI)
    g.setColorAt(1.0, GOLD)
    painter.setPen(QPen(INK_EDGE, 1.6))
    painter.setBrush(QBrush(g))
    painter.drawPath(text)
    painter.restore()
