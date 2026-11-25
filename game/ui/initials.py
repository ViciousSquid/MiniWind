"""Illuminated initials in the style of a printer's decorated capitals: a
dark square block, rough at its edges, overgrown with green leafy vines and
golden flowers, the capital in a bright pigment over them -- outlined in
black so the foliage stops short of it, with round knobs on its strokes.

Drawn procedurally (no artwork is copied), deterministic per letter and
pigment, and cached as an image per size, so a journal page or a line of a
conversation costs a picture blit after the first frame.

* :func:`draw` -- one initial filling a box (the journal's big drop caps,
  a conversation's inline capital at the size of its text).
"""

from __future__ import annotations

import math
import random

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QImage, QPainter, QPainterPath, QPen,
                         QPolygonF, QTransform)

from . import fonts

#: The block, the foliage and the flowers.
BLOCK = QColor(24, 26, 22)
LEAF_DARK = QColor(36, 104, 72)
LEAF_LIGHT = QColor(66, 146, 104)
STEM = QColor(44, 118, 82)
FLOWER = QColor(226, 176, 58)
FLOWER_HEART = QColor(170, 96, 30)
#: The capital's pigments (main colour); the journal cycles them down the
#: page. Red-orange is the classic; Fio's own orange and green are among them.
PIGMENTS = {
    "red": QColor(222, 72, 34),
    "orange": QColor(240, 128, 0),          # Fio orange
    "blue": QColor(62, 104, 196),
    "green": QColor(34, 177, 76),           # Fio green
}
#: Where the capital is green, the foliage turns teal so the letter stands out.
LEAF_TEAL_DARK = QColor(30, 86, 104)
LEAF_TEAL_LIGHT = QColor(58, 128, 150)

_CACHE: dict = {}
#: Below this many image pixels across (a conversation's capital at the size
#: of its text), an initial is drawn simplified so the letter still reads.
SMALL_PX = 100


def _rough_square(rng, s):
    """A square a little ragged at its edges, as a worn printing block."""
    pts = []
    m = s * 0.012
    n = 10
    for side in range(4):
        for k in range(n):
            t = k / n
            j = rng.uniform(-m, m)
            if side == 0:
                pts.append(QPointF(t * s, m + j))
            elif side == 1:
                pts.append(QPointF(s - m + j, t * s))
            elif side == 2:
                pts.append(QPointF(s - t * s, s - m + j))
            else:
                pts.append(QPointF(m + j, s - t * s))
    return QPolygonF(pts)


def _leaf(p, x, y, length, angle, colour):
    p.save()
    p.translate(x, y)
    p.rotate(math.degrees(angle))
    path = QPainterPath()
    path.moveTo(0, 0)
    path.quadTo(length * 0.5, -length * 0.32, length, 0)
    path.quadTo(length * 0.5, length * 0.32, 0, 0)
    p.setPen(Qt.NoPen)
    p.setBrush(colour)
    p.drawPath(path)
    p.restore()


def _flower(p, x, y, r):
    p.setPen(Qt.NoPen)
    p.setBrush(FLOWER)
    for k in range(5):
        a = k * math.tau / 5
        p.drawEllipse(QPointF(x + math.cos(a) * r * 0.62, y + math.sin(a) * r * 0.62),
                      r * 0.5, r * 0.5)
    p.setBrush(FLOWER_HEART)
    p.drawEllipse(QPointF(x, y), r * 0.32, r * 0.32)


def _foliage(p, rng, s, dark, light, small=False):
    """Vines curling in from the block's edges, leaves along them, a few
    golden flowers and a speckle of red (sparser when *small*)."""
    for _ in range(3 if small else 9):
        side = rng.randrange(4)
        t = rng.uniform(0.1, 0.9)
        start = [(t * s, 0), (s, t * s), (t * s, s), (0, t * s)][side]
        end = (rng.uniform(0.2, 0.8) * s, rng.uniform(0.2, 0.8) * s)
        c1 = (rng.uniform(0, s), rng.uniform(0, s))
        stem = QPainterPath()
        stem.moveTo(*start)
        stem.quadTo(QPointF(*c1), QPointF(*end))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(STEM if dark is LEAF_DARK else dark, max(1.0, s * 0.03),
                      Qt.SolidLine, Qt.RoundCap))
        p.drawPath(stem)
        for k in range(1, 7):
            f = k / 7.0
            pt = stem.pointAtPercent(f)
            ang = math.radians(-stem.angleAtPercent(f))
            side_sign = 1 if k % 2 else -1
            _leaf(p, pt.x(), pt.y(), s * rng.uniform(0.11, 0.16),
                  ang + side_sign * rng.uniform(0.6, 1.1),
                  light if rng.random() < 0.5 else dark)
    for _ in range(0 if small else 3):
        _flower(p, rng.uniform(0.15, 0.85) * s, rng.uniform(0.15, 0.85) * s, s * 0.07)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(200, 70, 40))
    for _ in range(14):
        p.drawEllipse(QPointF(rng.uniform(0, s), rng.uniform(0, s)), s * 0.008, s * 0.008)


def _capital_path(letter, s, room_share=0.70):
    """The capital, chunky: the medieval face's letter thickened by a stroke
    of its own outline, as a printer's capitals are cut heavy."""
    from PyQt5.QtGui import QPainterPathStroker
    path = _thin_capital(letter, s, room_share)
    stroker = QPainterPathStroker()
    stroker.setWidth(s * 0.055)
    stroker.setJoinStyle(Qt.RoundJoin)
    stroker.setCapStyle(Qt.RoundCap)
    return stroker.createStroke(path).united(path).simplified()


def _thin_capital(letter, s, room_share=0.70):
    font = QFont(fonts.dialogue_family())
    font.setPixelSize(400)
    glyph = QPainterPath()
    glyph.addText(0, 0, font, letter)
    b = glyph.boundingRect()
    if b.width() <= 0 or b.height() <= 0:
        return glyph
    room = s * room_share
    k = min(room / b.width(), room / b.height())
    t = QTransform()
    t.translate(s / 2 - b.center().x() * k, s / 2 - b.center().y() * k)
    t.scale(k, k)
    return t.map(glyph)


def _knobs(p, path, rng, s, colour):
    """Round knobs on the capital's strokes: a ring of its colour with a dark
    pip, at a few points well inside the letter."""
    pts = []
    for _ in range(400):
        x, y = rng.uniform(0.15, 0.85) * s, rng.uniform(0.15, 0.85) * s
        r = s * 0.035
        if all(path.contains(QPointF(x + dx, y + dy))
               for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r))):
            if all(math.hypot(x - a, y - b) > s * 0.22 for a, b in pts):
                pts.append((x, y))
        if len(pts) >= 3:
            break
    for x, y in pts:
        p.setPen(QPen(BLOCK, max(1.0, s * 0.012)))
        p.setBrush(colour.lighter(112))
        p.drawEllipse(QPointF(x, y), s * 0.04, s * 0.04)
        p.setPen(Qt.NoPen)
        p.setBrush(BLOCK)
        p.drawEllipse(QPointF(x, y), s * 0.014, s * 0.014)


def _render(letter, pigment, grey, px):
    s = float(px)
    img = QImage(int(px), int(px), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    rng = random.Random(f"{letter}-{pigment}")
    main = QColor(PIGMENTS.get(pigment, PIGMENTS["red"]))
    green_letter = pigment == "green"
    dark = LEAF_TEAL_DARK if green_letter else LEAF_DARK
    light = LEAF_TEAL_LIGHT if green_letter else LEAF_LIGHT
    block = _rough_square(rng, s)
    clip = QPainterPath()
    clip.addPolygon(block)
    p.setPen(Qt.NoPen)
    p.setBrush(BLOCK)
    p.drawPolygon(block)
    p.save()
    p.setClipPath(clip)
    small = px < SMALL_PX
    _foliage(p, rng, s, dark, light, small)
    path = _capital_path(letter, s, 0.88 if small else 0.70)
    # A black halo round the capital, so the foliage stops short of it.
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(BLOCK, s * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(main)
    p.drawPath(path)
    _knobs(p, path, rng, s, main)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(BLOCK, max(1.0, s * 0.012)))
    p.drawPath(path)
    p.restore()
    # The block's worn rim.
    p.setPen(QPen(QColor(10, 10, 9), max(1.0, s * 0.02)))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(block)
    p.end()
    if grey:
        g = img.convertToFormat(QImage.Format_Grayscale8)
        img = g.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        # The block's transparent margin turns black in grey: mask it again.
        mask = QImage(int(px), int(px), QImage.Format_ARGB32_Premultiplied)
        mask.fill(Qt.transparent)
        mp = QPainter(mask)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.setPen(Qt.NoPen)
        mp.setBrush(Qt.white)
        mp.drawPolygon(block)
        mp.setCompositionMode(QPainter.CompositionMode_SourceIn)
        mp.drawImage(0, 0, img)
        mp.end()
        img = mask
    return img


# ---------------------------------------------------------------------------
# Style 1: the manuscript initial -- the letter in pigment, pearls of a second
# pigment inside it, an ink outline and a hairline flourish.
# ---------------------------------------------------------------------------
_MS_PIGMENTS = {"blue": (QColor(38, 68, 150), QColor(196, 96, 84)),
                "red": (QColor(172, 60, 44), QColor(52, 80, 160)),
                "green": (QColor(34, 177, 76), QColor(196, 70, 44)),
                "orange": (QColor(240, 128, 0), QColor(38, 68, 150))}
_VELLUM = QColor(236, 224, 196)
_INK = QColor(52, 36, 24)


def _render_manuscript(letter, pigment, grey, px):
    s = float(px)
    img = QImage(int(px), int(px), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    main, orn = _MS_PIGMENTS.get(pigment, _MS_PIGMENTS["blue"])
    font = QFont(fonts.menu_family())
    font.setPixelSize(400)
    glyph = QPainterPath()
    glyph.addText(0, 0, font, letter)
    b = glyph.boundingRect()
    if b.width() > 0 and b.height() > 0:
        room = s * 0.84
        k = min(room / b.width(), room / b.height())
        t = QTransform()
        t.translate(s * 0.56 - b.center().x() * k, s / 2 - b.center().y() * k)
        t.scale(k, k)
        path = t.map(glyph)
        pb = path.boundingRect()
        flour = QPainterPath()
        flour.moveTo(pb.left() + pb.width() * 0.25, pb.bottom() - 1)
        flour.cubicTo(pb.left() - pb.width() * 0.35, pb.bottom() + pb.height() * 0.05,
                      pb.left() - pb.width() * 0.25, pb.top() + pb.height() * 0.55,
                      pb.left() - pb.width() * 0.05, pb.top() + pb.height() * 0.35)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(main, max(1.0, pb.height() * 0.018), Qt.SolidLine, Qt.RoundCap))
        p.drawPath(flour)
        p.setPen(Qt.NoPen)
        p.setBrush(main)
        p.drawPath(path)
        p.save()
        p.setClipPath(path)
        step = max(4.0, pb.height() / 6.0)
        rr = step * 0.26
        row, y = 0, pb.top() + step * 0.5
        while y < pb.bottom():
            x = pb.left() + (step * 0.5 if row % 2 else 0.0)
            while x < pb.right() + step:
                p.setBrush(orn)
                p.drawEllipse(QRectF(x - rr, y - rr, 2 * rr, 2 * rr))
                p.setBrush(_VELLUM)
                p.drawEllipse(QRectF(x - rr * 0.38, y - rr * 0.38, rr * 0.76, rr * 0.76))
                x += step
            y += step * 0.86
            row += 1
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_INK, max(0.8, pb.height() * 0.012)))
        p.drawPath(path)
    p.end()
    return _greyed(img) if grey else img


# ---------------------------------------------------------------------------
# Style 3: the foliate initial -- a bold serif capital with a dark extruded
# shadow, inked; curling vines of acanthus leaves and berry clusters wound
# round it, some behind the letter and some in front.
# ---------------------------------------------------------------------------
_FOLIATE_PIGMENTS = {"blue": QColor(44, 112, 116),        # teal
                     "red": QColor(196, 70, 52),
                     "green": QColor(34, 177, 76),          # Fio green
                     "orange": QColor(240, 128, 0)}         # Fio orange
_ACANTHUS = QColor(200, 214, 140)
_ACANTHUS_INK = QColor(46, 70, 40)
_BERRY = QColor(232, 116, 78)
_BERRY_PURPLE = QColor(118, 64, 132)
_OUTLINE = QColor(28, 28, 26)


def _acanthus(p, x, y, length, angle, flip, ink_w):
    """A lobed acanthus leaf: three lobes a side, a midrib, inked."""
    p.save()
    p.translate(x, y)
    p.rotate(math.degrees(angle))
    if flip:
        p.scale(1, -1)
    L, W = length, length * 0.42
    path = QPainterPath()
    path.moveTo(0, 0)
    for k, w in enumerate((0.55, 0.85, 0.6)):
        x0, x1 = L * k / 3.0, L * (k + 1) / 3.0
        path.quadTo((x0 + x1) / 2, -W * w * 1.25, x1, -W * w * 0.35)
    path.quadTo(L * 1.05, 0, L, W * 0.1)
    for k, w in enumerate((0.6, 0.85, 0.55)):
        x0, x1 = L * (3 - k) / 3.0, L * (2 - k) / 3.0
        path.quadTo((x0 + x1) / 2, W * w * 1.1, x1, W * w * 0.3)
    path.closeSubpath()
    p.setBrush(_ACANTHUS)
    p.setPen(QPen(_ACANTHUS_INK, ink_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)
    vein = QPainterPath()
    vein.moveTo(0, 0)
    vein.quadTo(L * 0.5, -W * 0.15, L * 0.9, 0)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_ACANTHUS_INK, ink_w * 0.8, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(vein)
    p.restore()


def _berry(p, rng, x, y, r, colour, ink_w):
    """A bramble berry: a cluster of round drupelets, each inked, with a
    glint, under a little calyx leaf."""
    p.setPen(QPen(_OUTLINE, ink_w))
    drupe = r * 0.3
    spots = []
    for ring, count in ((0.0, 1), (0.42, 6), (0.78, 9)):
        for k in range(count):
            a = k * math.tau / max(1, count) + ring
            spots.append((x + math.cos(a) * r * ring, y + math.sin(a) * r * ring * 1.08))
    spots.sort(key=lambda q: q[1])
    for sx, sy in spots:
        p.setBrush(colour)
        p.drawEllipse(QPointF(sx, sy), drupe, drupe)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 150))
    for sx, sy in spots:
        p.drawEllipse(QPointF(sx - drupe * 0.35, sy - drupe * 0.35), drupe * 0.22, drupe * 0.22)


def _render_foliate(letter, pigment, grey, px, block=False):
    s = float(px)
    img = QImage(int(px), int(px), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    rng = random.Random(f"foliate-{letter}")
    rim = None
    if block:
        # Style 4: the dark printing block of style 2 under it all.
        rim = _rough_square(random.Random(f"block-{letter}"), s)
        clip = QPainterPath()
        clip.addPolygon(rim)
        p.setPen(Qt.NoPen)
        p.setBrush(BLOCK)
        p.drawPolygon(rim)
        p.setClipPath(clip)
    main = QColor(_FOLIATE_PIGMENTS.get(pigment, _FOLIATE_PIGMENTS["blue"]))
    berry = _BERRY_PURPLE if pigment in ("red", "orange") else _BERRY
    ink = max(1.0, s * 0.012)
    # Small (a conversation's capital at the size of its text): the letter
    # fills it and only a hint of the ornament is kept, so it still reads.
    small = px < SMALL_PX
    # The capital: a bold serif, centred a touch left and up (room for its shadow).
    font = QFont("DejaVu Serif")
    font.setBold(True)
    font.setPixelSize(400)
    glyph = QPainterPath()
    glyph.addText(0, 0, font, letter)
    b = glyph.boundingRect()
    path = QPainterPath()
    if b.width() > 0 and b.height() > 0:
        room = s * (0.86 if small else 0.66)
        k = min(room / b.width(), room / b.height())
        t = QTransform()
        t.translate(s * 0.48 - b.center().x() * k, s * 0.47 - b.center().y() * k)
        t.scale(k, k)
        path = t.map(glyph)
    # The vine: an S-curve rising through the letter, with two branches.
    stems = []
    main_stem = QPainterPath()
    main_stem.moveTo(s * 0.12, s * 0.92)
    main_stem.cubicTo(s * 0.55, s * 0.95, s * 0.2, s * 0.45, s * 0.55, s * 0.4)
    main_stem.cubicTo(s * 0.85, s * 0.36, s * 0.7, s * 0.12, s * 0.9, s * 0.08)
    stems.append(main_stem)
    for (x0, y0, cx, cy, x1, y1) in ((s * 0.4, s * 0.62, s * 0.05, s * 0.6, s * 0.08, s * 0.38),
                                     (s * 0.62, s * 0.38, s * 0.95, s * 0.5, s * 0.9, s * 0.7)):
        br = QPainterPath()
        br.moveTo(x0, y0)
        br.quadTo(cx, cy, x1, y1)
        stems.append(br)

    def draw_stems(paths):
        for st in paths:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_ACANTHUS_INK, s * 0.03, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(st)
            p.setPen(QPen(_ACANTHUS, s * 0.016, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(st)

    # Behind the letter: the stems and most of the leaves.
    if small:
        stems = []
    draw_stems(stems)
    for st in stems:
        for f in (0.3, 0.75):
            pt = st.pointAtPercent(f)
            ang = math.radians(-st.angleAtPercent(f))
            _acanthus(p, pt.x(), pt.y(), s * rng.uniform(0.22, 0.28),
                      ang + rng.choice((-1, 1)) * rng.uniform(0.7, 1.2),
                      rng.random() < 0.5, ink)
    # The letter: its dark extruded side, then its face, inked.
    if not path.isEmpty():
        side = QColor(main).darker(320)
        steps = 3 if small else 6
        for k in range(steps, 0, -1):
            d = s * 0.006 * k
            p.setPen(Qt.NoPen)
            p.setBrush(side)
            p.drawPath(path.translated(d, d * 0.8))
        p.setBrush(main)
        p.setPen(QPen(_OUTLINE, ink, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 60), ink * 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path.translated(-ink, -ink))
    if small:
        _berry(p, rng, s * 0.86, s * 0.16, s * 0.12, berry, ink * 0.8)
        if rim is not None:
            p.setClipping(False)
            p.setPen(QPen(QColor(10, 10, 9), max(1.0, s * 0.03)))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(rim)
        p.end()
        return _greyed(img) if grey else img
    # In front: a stretch of vine, two leaves and the berries.
    front = QPainterPath()
    front.moveTo(s * 0.3, s * 0.55)
    front.quadTo(s * 0.5, s * 0.5, s * 0.66, s * 0.6)
    draw_stems([front])
    _acanthus(p, s * 0.66, s * 0.6, s * 0.24, 0.6, False, ink)
    _acanthus(p, s * 0.3, s * 0.55, s * 0.2, 3.6, True, ink)
    for (bx, by) in ((0.22, 0.3), (0.8, 0.32), (0.74, 0.74)):
        _berry(p, rng, s * bx, s * by, s * 0.1, berry, ink * 0.8)
    if rim is not None:
        p.setClipping(False)
        p.setPen(QPen(QColor(10, 10, 9), max(1.0, s * 0.02)))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(rim)
    p.end()
    return _greyed(img) if grey else img


def _render_foliate_block(letter, pigment, grey, px):
    return _render_foliate(letter, pigment, grey, px, block=True)


def _greyed(img):
    """*img* in greyscale, keeping its transparency."""
    out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    g = img.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.drawImage(0, 0, g)
    p.end()
    return out


#: The initials' style: "manuscript" (1), "block" (2), "foliate" (3) or
#: "foliate_block" (4: the foliate initial on the dark block).
STYLE = "block"
_RENDERERS = {"manuscript": _render_manuscript, "foliate": _render_foliate,
              "foliate_block": _render_foliate_block}


def image(letter, pigment="red", grey=False, px=64, style=None):
    """The initial for *letter* as a square QImage *px* across (cached)."""
    style = style or STYLE
    key = (style, letter, pigment, bool(grey), int(px))
    img = _CACHE.get(key)
    if img is None:
        if len(_CACHE) > 256:
            _CACHE.clear()
        render = _RENDERERS.get(style, _render)
        img = _CACHE[key] = render(letter, pigment, grey, max(8, int(px)))
    return img


def draw(painter, box: QRectF, letter: str, pigment: str = "red", grey: bool = False,
         opacity: float = 1.0, style=None) -> QRectF:
    """Draw the initial for *letter* as the largest square in *box* (centred
    across it, at its top). Returns the square drawn."""
    side = min(box.width(), box.height())
    if side <= 1 or not letter:
        return QRectF()
    sq = QRectF(box.left() + (box.width() - side) / 2.0, box.top(), side, side)
    dpr = 2                                  # sharp on high-DPI screens
    img = image(letter.upper(), pigment, grey, int(math.ceil(side * dpr)), style)
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setOpacity(painter.opacity() * max(0.0, min(1.0, opacity)))
    painter.drawImage(sq, img)
    painter.restore()
    return sq
