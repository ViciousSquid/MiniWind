"""
The top-left status frame: a bronze ring holding the minimap, four small fins
fanned round its lower left, and the name, health and magicka bars running out from
behind the ring to the right.

Everything is drawn with QPainter -- no artwork asset -- in three layers:

.. code-block:: text

    back    the four fins                        cached pixmap
    bars    name, health, magicka (+ stamina)    live, every frame
    map     the minimap, clipped to the circle   game.ui.worldmap
    ring    the bronze ring and its "N"          cached pixmap

The ring goes over the minimap and over the bars' left ends, so the bars read
as coming out from behind it. The two static layers are painted once per size
and kept as pixmaps: a pixmap that lives on keeps its texture on the GL paint
engine, where re-tessellating a dozen gradient paths every frame would not.

:func:`layout` is the single source of the geometry, so the minimap
(:func:`game.ui.worldmap.minimap_rect`) and the frame always agree about
where the circle is.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QConicalGradient, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)

from . import theme as T

#: Gap between the frame and the window's top-left corner.
MARGIN = 14
#: The minimap's radius, as a fraction of the ring's outer radius.
INNER = 0.82

_BRONZE_DARK = QColor(52, 28, 10)
_BRONZE_EDGE = QColor(34, 18, 6)

#: ``(ring radius, device pixel ratio) -> (back, ring)`` pixmaps.
_CACHE = {}


def layout(width, height):
    """The frame's geometry for a ``width`` x ``height`` view.

    ``cx, cy`` is the ring's centre, ``R`` its outer radius, ``r`` the
    minimap's radius; ``bars`` is ``[(name, QRectF)]`` top to bottom; ``text_y``
    is the baseline of the first line written under the bars.
    """
    R = max(70.0, min(118.0, height * 0.13))
    cx = MARGIN + 1.22 * R
    cy = MARGIN + R
    bar_x = cx + 0.55 * R
    bar_w = max(190.0, min(280.0, 2.4 * R))
    gap = 0.07 * R
    y = cy - 0.84 * R
    bars = []
    for name, h in (("name", 0.34 * R), ("health", 0.32 * R),
                    ("magicka", 0.32 * R), ("stamina", 0.13 * R)):
        bars.append((name, QRectF(bar_x, y, bar_w, h)))
        y += h + gap
    return SimpleNamespace(cx=cx, cy=cy, R=R, r=INNER * R, bars=bars,
                           text_y=y + 0.12 * R)


def _bronze_linear(x0, y0, x1, y1):
    g = QLinearGradient(x0, y0, x1, y1)
    g.setColorAt(0.0, QColor(250, 212, 150))
    g.setColorAt(0.3, QColor(196, 128, 64))
    g.setColorAt(0.62, QColor(122, 70, 30))
    g.setColorAt(1.0, QColor(70, 38, 14))
    return g


def _circle(cx, cy, radius):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), radius, radius)
    return path


# ------------------------------------------------------------------ layers

def _paint_back(p, f):
    """Four small fins fanned round the ring's lower left, behind it."""
    cx, cy, R = f.cx, f.cy, f.R
    lean = math.radians(5.0)
    for deg in (128.0, 150.0, 172.0, 194.0):
        a0, a1 = math.radians(deg - 5.0), math.radians(deg + 5.0)
        inner, outer = 0.94 * R, 1.17 * R
        blade = QPainterPath()
        blade.moveTo(cx + math.cos(a0) * inner, cy + math.sin(a0) * inner)
        blade.lineTo(cx + math.cos(a0 + lean) * outer, cy + math.sin(a0 + lean) * outer)
        blade.lineTo(cx + math.cos(a1 + lean) * outer, cy + math.sin(a1 + lean) * outer)
        blade.lineTo(cx + math.cos(a1) * inner, cy + math.sin(a1) * inner)
        blade.closeSubpath()
        p.setBrush(QBrush(_bronze_linear(cx - 1.2 * R, cy - 0.4 * R, cx - 0.6 * R, cy + R)))
        p.setPen(QPen(_BRONZE_EDGE, 1.4))
        p.drawPath(blade)


def _paint_ring(p, f):
    """The bronze ring round the minimap, with a north mark at the top."""
    cx, cy, R, r = f.cx, f.cy, f.R, f.r
    ring = _circle(cx, cy, R).subtracted(_circle(cx, cy, r))
    g = QConicalGradient(QPointF(cx, cy), 135.0)
    for at, rgb in ((0.0, (250, 214, 150)), (0.13, (150, 88, 38)),
                    (0.27, (238, 190, 120)), (0.42, (104, 58, 24)),
                    (0.57, (214, 150, 84)), (0.72, (92, 52, 20)),
                    (0.87, (236, 196, 132)), (1.0, (250, 214, 150))):
        g.setColorAt(at, QColor(*rgb))
    p.setBrush(QBrush(g))
    p.setPen(Qt.NoPen)
    p.drawPath(ring)
    # Bevel: a lit top-left lip, a shadowed lower right, crisp dark edges.
    sheen = QLinearGradient(cx - R, cy - R, cx + R, cy + R)
    sheen.setColorAt(0.0, QColor(255, 240, 210, 120))
    sheen.setColorAt(0.5, QColor(255, 240, 210, 0))
    sheen.setColorAt(1.0, QColor(0, 0, 0, 90))
    p.setBrush(QBrush(sheen))
    p.drawPath(ring)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(_BRONZE_EDGE, 2.0))
    p.drawEllipse(QPointF(cx, cy), R - 1.0, R - 1.0)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor(255, 226, 170, 110), 1.0))
    p.drawEllipse(QPointF(cx, cy), (R + r) / 2.0, (R + r) / 2.0)
    p.setPen(QPen(QColor(0, 0, 0, 120), 3.0))
    p.drawEllipse(QPointF(cx, cy), r + 1.5, r + 1.5)
    # North, set into the ring.
    ny = cy - (R + r) / 2.0
    p.setPen(QPen(_BRONZE_EDGE, 1.2))
    p.setBrush(QBrush(QColor(60, 32, 12)))
    p.drawEllipse(QPointF(cx, ny), 0.085 * R, 0.085 * R)
    p.setPen(T.GOLD_BRIGHT)
    p.setFont(T.font(max(7, int(0.1 * R)), bold=True))
    p.drawText(QRectF(cx - 0.1 * R, ny - 0.1 * R, 0.2 * R, 0.2 * R),
               int(Qt.AlignCenter), "N")


def _layer_pixmap(f, paint, dpr):
    """Paint one static layer into a transparent pixmap covering the frame."""
    w = int(math.ceil(f.cx + 2.0 * f.R)) + 4
    h = int(math.ceil(f.cy + 1.7 * f.R)) + 4
    image = QImage(int(w * dpr), int(h * dpr), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, True)
    paint(p, f)
    p.end()
    return QPixmap.fromImage(image)


def _layers(f, dpr):
    key = (round(f.R, 1), round(dpr, 2))
    layers = _CACHE.get(key)
    if layers is None:
        if len(_CACHE) > 8:            # window resizes: keep only recent sizes
            _CACHE.clear()
        layers = (_layer_pixmap(f, _paint_back, dpr), _layer_pixmap(f, _paint_ring, dpr))
        _CACHE[key] = layers
    return layers


# -------------------------------------------------------------------- bars

#: Fill gradients (top, middle, bottom) per bar.
_FILLS = {
    "health": ((176, 255, 96), (78, 196, 40), (26, 104, 18)),
    "magicka": ((132, 232, 255), (38, 160, 228), (14, 78, 150)),
    "stamina": ((255, 226, 140), (214, 160, 52), (120, 82, 18)),
}


def _bar(p, rect, frac, fill, text="", text_x=None, value=""):
    """One bronze-framed glass bar, *frac* full of the *fill* gradient."""
    rad = rect.height() / 2.4
    p.setPen(QPen(_BRONZE_EDGE, 1.2))
    p.setBrush(QBrush(_bronze_linear(rect.left(), rect.top(), rect.left(), rect.bottom())))
    p.drawRoundedRect(rect, rad, rad)
    inset = max(2.0, rect.height() * 0.13)
    inner = rect.adjusted(inset, inset, -inset, -inset)
    irad = max(1.0, rad - inset)
    well = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    well.setColorAt(0.0, QColor(46, 58, 64))
    well.setColorAt(1.0, QColor(6, 8, 10))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(well))
    p.drawRoundedRect(inner, irad, irad)
    if fill is not None and frac > 0.0:
        level = QRectF(inner.left(), inner.top(),
                       max(irad * 2.0, inner.width() * min(1.0, frac)), inner.height())
        g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        top, mid, bottom = (QColor(*c) for c in fill)
        g.setColorAt(0.0, top)
        g.setColorAt(0.45, mid)
        g.setColorAt(1.0, bottom)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(level, irad, irad)
    # Gloss over the upper half.
    gloss = QLinearGradient(inner.topLeft(), QPointF(inner.left(), inner.center().y()))
    gloss.setColorAt(0.0, QColor(255, 255, 255, 110))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(gloss))
    p.drawRoundedRect(QRectF(inner.left() + 2, inner.top() + 1, inner.width() - 4,
                             inner.height() * 0.5), irad, irad)
    if text or value:
        left = inner.left() + 8 if text_x is None else max(inner.left() + 8, text_x)
        area = QRectF(left, inner.top(), inner.right() - left - 8, inner.height())
        p.setPen(QColor(0, 0, 0, 170))
        if text:
            p.setFont(T.font(max(8, int(rect.height() * 0.46))))
            p.drawText(area.translated(1, 1), int(Qt.AlignVCenter | Qt.AlignLeft), text)
            p.setPen(QColor(244, 242, 236))
            p.drawText(area, int(Qt.AlignVCenter | Qt.AlignLeft), text)
        if value:
            p.setFont(T.font(max(7, int(rect.height() * 0.36)), bold=True, family="Segoe UI"))
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(area.translated(1, 1), int(Qt.AlignVCenter | Qt.AlignRight), value)
            p.setPen(QColor(250, 250, 250))
            p.drawText(area, int(Qt.AlignVCenter | Qt.AlignRight), value)


def _clear_of_ring(f, rect):
    """The x a bar's label starts at so the ring does not cover it."""
    dy = rect.center().y() - f.cy
    return f.cx + math.sqrt(max(0.0, f.R * f.R - dy * dy)) + 6.0


def _draw_bars(p, f, c):
    rects = dict(f.bars)
    name = rects["name"]
    _bar(p, name, 0.0, None, text=c.name, text_x=_clear_of_ring(f, name))
    _bar(p, rects["health"], c.health / c.max_health if c.max_health else 0.0,
         _FILLS["health"], value=f"{int(c.health)} / {int(c.max_health)}")
    # One who works no magic (a Warrior) has stamina in the magicka bar's
    # place, as the old bars did, and no separate stamina strip.
    magical = c.max_magicka > 0 or getattr(c, "can_use_magic", lambda: True)()
    stamina = c.stamina / c.max_stamina if c.max_stamina else 0.0
    if magical:
        _bar(p, rects["magicka"], c.magicka / c.max_magicka if c.max_magicka else 0.0,
             _FILLS["magicka"], value=f"{int(c.magicka)} / {int(c.max_magicka)}")
        _bar(p, rects["stamina"], stamina, _FILLS["stamina"])
    else:
        _bar(p, rects["magicka"], stamina, _FILLS["stamina"],
             value=f"{int(c.stamina)} / {int(c.max_stamina)}")


def _draw_identity(p, f, c):
    """Level, race and class, gold, and the level-up prompt, under the bars."""
    from ..rpg import classes, races
    x = f.bars[0][1].left() + 0.45 * f.R
    y = f.text_y
    sub = (f"Level {c.level}  ·  {races.get(c.race_id).label} "
           f"{classes.get(c.class_id).label}  ·  ⦿ {c.gold} gold")
    T.text(p, x, y, sub, size=9, color=T.PARCH, family="Segoe UI")
    if c.can_level_up:
        T.text(p, x, y + 16, "Level up! (press L)", size=9,
               color=QColor(120, 220, 130), bold=True, family="Segoe UI")


# ------------------------------------------------------------------- entry

def draw(painter, session, c, width, height):
    """Paint the whole frame, the minimap inside its ring included."""
    f = layout(width, height)
    device = painter.device()
    dpr = float(device.devicePixelRatioF()) if device is not None else 1.0
    back, ring = _layers(f, dpr)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(0, 0, back)
    _draw_bars(painter, f, c)
    # The well the map sits in. The bars run in behind the ring, so this is
    # what keeps their ends out of the circle when there is no map to cover
    # them (outside Play, or before the map picture is ready).
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(14, 18, 16))
    painter.drawEllipse(QPointF(f.cx, f.cy), f.r + 1.0, f.r + 1.0)
    painter.restore()

    from . import worldmap
    worldmap.draw_minimap(painter, session, None, width, height)

    painter.save()
    painter.drawPixmap(0, 0, ring)
    _draw_identity(painter, f, c)
    painter.restore()
