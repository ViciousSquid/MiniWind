"""
The top-left status frame: a bronze ring holding the minimap, set in the
window's top-left corner, and the health and magicka bars running out from
behind the ring to the right: health always, with stamina a thin line along its
bottom edge, and magicka under them for anyone who works magic.

Everything is drawn with QPainter -- no artwork asset -- in layers:

.. code-block:: text

    bars    health (stamina a line beneath), magicka   live, every frame
    map     the minimap, clipped to the circle   game.ui.worldmap
    ring    the bronze ring                     cached pixmap
    north   a gently damped, upright "N"        live, every frame

The ring goes over the minimap and over the bars' left ends, so the bars read
as coming out from behind it. The static ring is painted once per size
and kept as a pixmap: a pixmap that lives on keeps its texture on the GL paint
engine, where re-tessellating a dozen gradient paths every frame would not.

:func:`layout` is the single source of the geometry, so the minimap
(:func:`game.ui.worldmap.minimap_rect`) and the frame always agree about
where the circle is.
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QConicalGradient, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)

from . import theme as T
from ..compass import CompassNeedle
from ..rpg.character import whole_health

#: Gap between the ring and the window's top and left edges (the clock keeps
#: the same gap from the top right).
MARGIN = 14
#: The minimap's radius, as a fraction of the ring's outer radius.
INNER = 0.82
#: The stamina line's thickness (px), on the bottom edge of the health bar.
STAMINA_LINE = 2.0

_BRONZE_DARK = QColor(52, 28, 10)
_BRONZE_EDGE = QColor(34, 18, 6)

#: ``(ring radius, device pixel ratio) -> ring`` pixmaps.
_CACHE = {}


def layout(width, height, magical=True):
    """The frame's geometry for a ``width`` x ``height`` view.

    Health and stamina are always the first two bars; magicka comes under
    them, and a character who works no magic (a Warrior) has no magicka bar at
    all, so with *magical* False there are only the two.

    ``cx, cy`` is the ring's centre, ``R`` its outer radius, ``r`` the
    minimap's radius; ``bars`` is ``[(name, QRectF)]`` top to bottom; ``text_y``
    is the baseline of the first line written under the bars.
    """
    R = max(70.0, min(118.0, height * 0.13))
    cx = MARGIN + R
    cy = MARGIN + R
    bar_x = cx + 0.55 * R
    bar_w = max(190.0, min(280.0, 2.4 * R))
    gap = 0.07 * R
    y = cy - 0.70 * R
    health_h = 0.22 * R
    # Stamina is a thin line on the bottom edge of the health bar; magicka
    # a slim strip a little below them.
    bars = [("health", QRectF(bar_x, y, bar_w, health_h)),
            ("stamina", QRectF(bar_x, y + health_h, bar_w, STAMINA_LINE))]
    y += health_h + STAMINA_LINE + gap
    if magical:
        bars.append(("magicka", QRectF(bar_x, y, bar_w, 0.09 * R)))
        y += 0.09 * R + gap
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

def _paint_ring(p, f):
    """The static bronze ring round the minimap."""
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


def _north_rotation(session, target, now=None):
    needle = getattr(session, "_minimap_compass", None)
    if needle is None:
        needle = session._minimap_compass = CompassNeedle()
    return needle.update(target, time.monotonic() if now is None else now)


def _paint_north(p, f, rotation=0.0):
    """North trails a turn gently; its letter stays upright and readable."""
    R, r = f.R, f.r
    reach = (R + r) / 2.0
    cx = f.cx + math.sin(rotation) * reach
    ny = f.cy - math.cos(rotation) * reach
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
        layers = _layer_pixmap(f, _paint_ring, dpr)
        _CACHE[key] = layers
    return layers


# -------------------------------------------------------------------- bars

#: Fill gradients (top, middle, bottom) per bar.
_FILLS = {
    "health": ((255, 128, 112), (210, 42, 34), (112, 12, 10)),
    "magicka": ((176, 255, 96), (78, 196, 40), (26, 104, 18)),
    "stamina": ((132, 232, 255), (38, 160, 228), (14, 78, 150)),
}


def _bar(p, rect, frac, fill, value=""):
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
    if value:
        area = inner.adjusted(8, 0, -8, 0)
        p.setFont(T.font(max(7, int(rect.height() * 0.36)), bold=True, family="Segoe UI"))
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(area.translated(1, 1), int(Qt.AlignVCenter | Qt.AlignRight), value)
        p.setPen(QColor(250, 250, 250))
        p.drawText(area, int(Qt.AlignVCenter | Qt.AlignRight), value)


def _stamina_line(p, rect, health, frac):
    """Stamina: a flat line under the straight run of the health bar, so it
    reads as part of that bar rather than a bar of its own."""
    inset = health.height() / 2.4          # clear of the health bar's rounded ends
    track = QRectF(rect.left() + inset, rect.top(), rect.width() - 2 * inset, rect.height())
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(6, 8, 10))
    p.drawRect(track)
    if frac > 0.0:
        p.setBrush(QColor(*_FILLS["stamina"][1]))
        p.drawRect(QRectF(track.left(), track.top(),
                          track.width() * min(1.0, frac), track.height()))


def _magical(c):
    """Whether *c* works magic: a Warrior has no magicka and no bar for it."""
    can = getattr(c, "can_use_magic", None)
    return bool(can()) if callable(can) else c.max_magicka > 0


def _draw_bars(p, f, c):
    # Each fill from its whole-pixel width (:func:`_fill_px`), the value the
    # frame's cache is keyed on, so a cached frame is the one a fresh paint gives.
    rects = dict(f.bars)

    def shown(name, value, maximum):
        rect = rects[name]
        return _fill_px(rect, value, maximum) / rect.width() if rect.width() else 0.0

    _bar(p, rects["health"], shown("health", c.health, c.max_health),
         _FILLS["health"], value=f"{whole_health(c.health)} / {int(c.max_health)}")
    _stamina_line(p, rects["stamina"], rects["health"],
                  shown("stamina", c.stamina, c.max_stamina))
    if "magicka" in rects:
        # Too slim for numbers; the fill says it.
        _bar(p, rects["magicka"], shown("magicka", c.magicka, c.max_magicka),
             _FILLS["magicka"])


def _draw_identity(p, f, c):
    """Level, race and class, gold, and the level-up prompt, under the bars."""
    import game.rpg.classes as classes
    import game.rpg.races as races
    y = f.text_y
    # Clear of the ring at this height: without a magicka bar the text sits
    # higher, where the ring reaches further right.
    top, bottom = y - 12.0, y + 36.0          # every line of text
    dy = 0.0 if top <= f.cy <= bottom else min(abs(top - f.cy), abs(bottom - f.cy))
    x = max(f.bars[0][1].left() + 0.45 * f.R,
            f.cx + math.sqrt(max(0.0, f.R * f.R - dy * dy)) + 8.0)
    sub = (f"Level {c.level}  ·  {races.get(c.race_id).label} "
           f"{classes.get(c.class_id).label}")
    T.text(p, x, y, sub, size=9, color=T.PARCH, family="Segoe UI")
    T.text(p, x, y + 16, f"⦿ {c.gold} gold", size=9, color=T.PARCH, family="Segoe UI")
    if c.can_level_up:
        T.text(p, x, y + 32, "Level up! (press L)", size=9,
               color=QColor(120, 220, 130), bold=True, family="Segoe UI")


# ------------------------------------------------------------------- entry

#: The frame's two cached pictures (game/ui/paint_cache.py): what lies under
#: the minimap (the bars, the map's well) and what lies over it (the
#: ring, the identity text). Only the map and the north marker are live.
_UNDER = None
_OVER = None


def _fill_px(rect, value, maximum):
    """A bar's fill as it shows: whole pixels of its width."""
    frac = value / maximum if maximum else 0.0
    return int(round(max(0.0, min(1.0, frac)) * rect.width()))


def draw(painter, session, c, width, height):
    """Paint the whole frame, the minimap inside its ring included."""
    global _UNDER, _OVER
    from .paint_cache import PaintCache
    if _UNDER is None:
        _UNDER, _OVER = PaintCache(), PaintCache()
    f = layout(width, height, magical=_magical(c))
    device = painter.device()
    dpr = float(device.devicePixelRatioF()) if device is not None else 1.0
    rects = dict(f.bars)
    # Room for the ring, the bars, and the identity lines beside
    # the ring (level, race and class, gold, the level-up prompt).
    right = max([f.cx + 2.0 * f.R] + [r.right() for r in rects.values()])
    region = QRect(0, 0, int(math.ceil(right)) + 280,
                   int(math.ceil(max(f.cy + 1.7 * f.R, f.text_y + 48.0))) + 4)
    under_key = (round(f.R, 1), "magicka" in rects,
                 _fill_px(rects["health"], c.health, c.max_health),
                 whole_health(c.health), int(c.max_health),
                 _fill_px(rects["stamina"], c.stamina, c.max_stamina),
                 _fill_px(rects["magicka"], c.magicka, c.max_magicka)
                 if "magicka" in rects else None)

    def paint_under(p):
        _draw_bars(p, f, c)
        # The well the map sits in. The bars run in behind the ring, so this
        # is what keeps their ends out of the circle when there is no map to
        # cover them (outside Play, or before the map picture is ready).
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(14, 18, 16))
        p.drawEllipse(QPointF(f.cx, f.cy), f.r + 1.0, f.r + 1.0)

    _UNDER.draw(painter, under_key, region, paint_under)

    import game.ui.worldmap as worldmap
    worldmap.draw_minimap(painter, session, None, width, height)

    over_key = (round(f.R, 1), "magicka" in rects, c.level, c.race_id, c.class_id,
                c.gold, bool(c.can_level_up))

    def paint_over(p):
        p.drawPixmap(0, 0, _layers(f, dpr))
        _draw_identity(p, f, c)

    _OVER.draw(painter, over_key, region, paint_over)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    _paint_north(painter, f, _north_rotation(session, worldmap.minimap_rotation(session)))
    painter.restore()
