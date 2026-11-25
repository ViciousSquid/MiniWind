"""
Windows as parchment scrolls (``theme.STYLE == "scroll"``).

When the scroll style is on, every game window is the scroll itself: no
title bar and no dark frame, only the parchment floating over the world on a
soft shadow, its title lettered in rubric at the top, a wax seal to close it.
Wide windows (Statistics, loot, trade) are unrolled sideways between two
upright rolls ending in turned wooden knobs; narrower ones (level-up,
character creation, a tutor) hang between a roll across the top and one
across the bottom. A conversation keeps its own window (:data:`UNDRESSED`).
Inside, the body is drawn with the ink palette (:class:`theme.parchment`):
dark words on the light page.

Everything is drawn procedurally with QPainter -- gradients for the
cylinders, a mottled page from numpy noise, deckled edges from a jittered
path -- and the dressed-up window (everything but its title and the body) is
cached as one picture per size, so a scroll costs a blit a frame.

:func:`dress` turns a window the host has just made into its scroll; with the
classic style it leaves the window as it is.
"""

from __future__ import annotations

import os
import random

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)

from engine.floating_windows import FloatingWindow

from . import fonts
from . import theme as T

#: Parchment, light and dark (#ecd6a8 .. #d9b77f), and its foxing.
PAPER_LIGHT = (240, 222, 178)
PAPER_DARK = (217, 183, 127)
PAPER_STAIN = (178, 136, 82)
PAPER_EDGE = (150, 104, 56)
#: Rubric red, for titles.
RUBRIC = QColor(150, 36, 22)

#: The title band at the top of the page, by shape.
HEADER = {"wide": 30, "tall": 42}
#: How far a shape's rolls, knobs and shadow reach beyond the window's rect:
#: (left, top, right, bottom).
REACH = {"wide": (26, 22, 26, 22), "tall": (16, 22, 16, 26)}
_ROLL_W = 34          # an upright roll's thickness (wide scrolls)
_ROLL_H = 30          # a lying roll's thickness (tall scrolls)
_SHADOW = 14          # how far the soft shadow spreads


def configured_style(session=None) -> str:
    """The window style asked for: ``MINIWIND_UI_STYLE`` in the environment,
    else ``[GAME] window_style`` in settings.ini, else classic."""
    env = os.environ.get("MINIWIND_UI_STYLE", "").strip().lower()
    if env in T.STYLES:
        return env
    try:
        config = session._editor_config() if session is not None else None
        if config is not None:
            style = config.get("GAME", "window_style", fallback="").strip().lower()
            if style in T.STYLES:
                return style
    except Exception:
        pass
    return T.STYLE


# ------------------------------------------------------------------ texture
_PAPER_CACHE = {}


def _smooth_noise(rng, h, w, cell):
    """Value noise: random values on a grid every *cell* px, smoothly
    interpolated to h x w."""
    import numpy as np
    gh, gw = h // cell + 3, w // cell + 3
    grid = rng.random((gh, gw), dtype=np.float32)
    ys = np.arange(h, dtype=np.float32) / cell
    xs = np.arange(w, dtype=np.float32) / cell
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = ys - y0, xs - x0
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a = grid[y0][:, x0]
    b = grid[y0][:, x0 + 1]
    c = grid[y0 + 1][:, x0]
    d = grid[y0 + 1][:, x0 + 1]
    top = a + (b - a) * fx[None, :]
    bot = c + (d - c) * fx[None, :]
    return top + (bot - top) * fy[:, None]


def paper(w, h, seed=7) -> QImage:
    """A *w* x *h* mottled parchment: warm tan, faint darker blotches and
    fibres, darkening towards its edges. Cached by size."""
    key = (int(w), int(h), seed)
    img = _PAPER_CACHE.get(key)
    if img is not None:
        return img
    import numpy as np
    w, h = max(2, int(w)), max(2, int(h))
    rng = np.random.default_rng(seed)
    base = (_smooth_noise(rng, h, w, 180) * 0.45 + _smooth_noise(rng, h, w, 70) * 0.3
            + _smooth_noise(rng, h, w, 22) * 0.17 + _smooth_noise(rng, h, w, 6) * 0.08)
    # Blotches: where a slow noise peaks, a darker stain.
    stain = np.clip((_smooth_noise(rng, h, w, 110) - 0.62) * 3.2, 0, 1) ** 1.5
    stain += np.clip((_smooth_noise(rng, h, w, 40) - 0.72) * 3.0, 0, 1) ** 2 * 0.6
    # Fibres: noise stretched along the page.
    fib = _smooth_noise(rng, h, w, 3) * 0.5 + rng.random((h, w), dtype=np.float32) * 0.5
    # Edges darken (the page is handled there).
    yy = np.minimum(np.arange(h), np.arange(h)[::-1]).astype(np.float32)
    xx = np.minimum(np.arange(w), np.arange(w)[::-1]).astype(np.float32)
    edge = np.exp(-np.minimum(yy[:, None], xx[None, :]) / 22.0)
    light, dark = np.array(PAPER_LIGHT, np.float32), np.array(PAPER_DARK, np.float32)
    t = np.clip((base - 0.25) * 1.5, 0, 1)[..., None] * 0.75
    rgb = light + (dark - light) * t
    rgb = rgb + (np.array(PAPER_STAIN, np.float32) - rgb) * (stain[..., None] * 0.35)
    rgb = rgb * (0.965 + fib[..., None] * 0.05)
    rgb = rgb + (np.array(PAPER_EDGE, np.float32) - rgb) * (edge[..., None] * 0.55)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[..., 3] = 255
    img = QImage(out.tobytes(), w, h, 4 * w, QImage.Format_RGBA8888).copy()
    if len(_PAPER_CACHE) > 24:
        _PAPER_CACHE.clear()
    _PAPER_CACHE[key] = img
    return img


# --------------------------------------------------------------------- paths
def _deckle(rng, x0, y0, x1, y1, inward, step=7.0, depth=3.2):
    """Points along a torn edge from (x0, y0) to (x1, y1), each pushed up to
    *depth* px towards *inward* (a unit (dx, dy)), with an occasional nick."""
    import math
    length = math.hypot(x1 - x0, y1 - y0)
    n = max(2, int(length / step))
    pts = []
    for i in range(n + 1):
        t = i / n
        d = rng.random() * depth
        if rng.random() < 0.06:
            d += depth * (0.8 + rng.random())
        if i in (0, n):
            d = 0.0
        pts.append(QPointF(x0 + (x1 - x0) * t + inward[0] * d,
                           y0 + (y1 - y0) * t + inward[1] * d))
    return pts


def page_path(kind, w, h, seed=11) -> QPainterPath:
    """The sheet's outline in a (0, 0, w, h) box: its free edges deckled
    (top and bottom of a wide scroll, the sides of a tall one); the edges
    that run into the rolls straight."""
    rng = random.Random(seed * 7919 + int(w) * 31 + int(h))
    path = QPainterPath()
    if kind == "wide":
        top = _deckle(rng, 0, 0, w, 0, (0, 1))
        bottom = _deckle(rng, w, h, 0, h, (0, -1))
        pts = top + bottom
    else:
        right = _deckle(rng, w, 0, w, h, (-1, 0))
        left = _deckle(rng, 0, h, 0, 0, (1, 0))
        pts = right + left
    path.moveTo(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    return path


# ------------------------------------------------------------------ pieces
def _grad_stops(g, stops):
    for t, c in stops:
        g.setColorAt(t, QColor(*c))
    return g


#: Across a roll of parchment: dark underside, the light catching it.
_ROLL_STOPS = ((0.0, (104, 72, 40)), (0.14, (176, 138, 88)), (0.34, (236, 214, 170)),
               (0.44, (250, 236, 200)), (0.62, (214, 180, 124)), (0.86, (150, 108, 62)),
               (1.0, (88, 58, 32)))
#: Across turned wood.
_WOOD_STOPS = ((0.0, (40, 22, 10)), (0.22, (104, 62, 30)), (0.4, (168, 112, 62)),
               (0.5, (192, 138, 84)), (0.66, (110, 66, 32)), (1.0, (34, 18, 8)))


def _cap(p, cx, cy, rx, ry):
    """The end of a roll seen from the side: an ellipse with its rolled-up
    layers as a spiral."""
    p.setPen(QPen(QColor(92, 60, 32), 1.1))
    g = QRadialGradient(QPointF(cx, cy), max(rx, ry))
    g.setColorAt(0.0, QColor(150, 112, 66))
    g.setColorAt(1.0, QColor(214, 184, 132))
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(cx, cy), rx, ry)
    p.setBrush(Qt.NoBrush)
    for k in range(1, 4):
        f = 1.0 - k * 0.24
        p.setPen(QPen(QColor(110, 74, 40, 200), 0.9))
        p.drawArc(QRectF(cx - rx * f, cy - ry * f, 2 * rx * f, 2 * ry * f),
                  (40 + k * 70) * 16, 250 * 16)


def _upright_roll(p, x, top, bottom, rw):
    """An upright roll of parchment from *top* to *bottom*, *rw* thick,
    with a wooden rod through it ending in a turned knob at either end."""
    # The rod and knobs first, so the roll sits over the rod's ends.
    cx = x + rw / 2.0
    wood = _grad_stops(QLinearGradient(x, 0, x + rw, 0), _WOOD_STOPS)
    p.setPen(QPen(QColor(30, 16, 6), 1.0))
    p.setBrush(QBrush(wood))
    for sign, end in ((-1, top), (1, bottom)):
        rod_w = rw * 0.38
        p.drawRect(QRectF(cx - rod_w / 2, min(end, end + sign * 5), rod_w, 5))
        # A bead, then the finial: a rounded, slightly pear-shaped knob.
        bead_y = end + sign * 5
        p.drawEllipse(QPointF(cx, bead_y), rw * 0.42, 3.2)
        k = QPainterPath()
        kw = rw * 0.34
        base = bead_y + sign * 2
        tip = base + sign * 10
        k.moveTo(cx - kw * 0.55, base)
        k.cubicTo(cx - kw * 1.25, base + sign * 5, cx - kw * 0.9, tip,
                  cx, tip)
        k.cubicTo(cx + kw * 0.9, tip, cx + kw * 1.25, base + sign * 5,
                  cx + kw * 0.55, base)
        k.closeSubpath()
        p.drawPath(k)
        # A highlight down the knob.
        p.save()
        p.setPen(QPen(QColor(236, 196, 140, 150), 1.4))
        p.drawLine(QPointF(cx - kw * 0.35, base + sign * 3), QPointF(cx - kw * 0.3, tip - sign * 3))
        p.restore()
    # The roll itself.
    body = QPainterPath()
    body.addRoundedRect(QRectF(x, top, rw, bottom - top), 3, 3)
    p.setPen(Qt.NoPen)
    p.fillPath(body, QBrush(_grad_stops(QLinearGradient(x, 0, x + rw, 0), _ROLL_STOPS)))
    # The edge of the outermost turn, a faint line down the roll.
    p.setPen(QPen(QColor(120, 84, 46, 150), 1.0))
    p.drawLine(QPointF(x + rw * 0.72, top + 6), QPointF(x + rw * 0.72, bottom - 6))
    p.setPen(QPen(QColor(80, 52, 28), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(body)
    _cap(p, cx, top, rw / 2.0, 4.5)
    _cap(p, cx, bottom, rw / 2.0, 4.5)


def _lying_roll(p, left, right, y, rh):
    """A roll of parchment lying across from *left* to *right*, its top at
    *y*, *rh* thick, the rolled-up layers showing at its ends."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(left, y, right - left, rh), rh * 0.35, rh * 0.35)
    p.setPen(Qt.NoPen)
    p.fillPath(body, QBrush(_grad_stops(QLinearGradient(0, y, 0, y + rh), _ROLL_STOPS)))
    p.setPen(QPen(QColor(120, 84, 46, 140), 1.0))
    p.drawLine(QPointF(left + 10, y + rh * 0.74), QPointF(right - 10, y + rh * 0.74))
    p.setPen(QPen(QColor(80, 52, 28), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawPath(body)
    _cap(p, left + 4, y + rh / 2.0, 5.0, rh / 2.0)
    _cap(p, right - 4, y + rh / 2.0, 5.0, rh / 2.0)


def _soft_shadow(p, path, dx, dy, spread, alpha=120):
    """*path*'s shadow, blurred, offset by (dx, dy): drawn small and scaled
    up smoothly (a cheap blur)."""
    box = path.boundingRect().adjusted(-spread * 2, -spread * 2, spread * 2, spread * 2)
    k = 6.0
    small = QImage(max(1, int(box.width() / k)), max(1, int(box.height() / k)),
                   QImage.Format_ARGB32_Premultiplied)
    small.fill(Qt.transparent)
    q = QPainter(small)
    q.setRenderHint(QPainter.Antialiasing, True)
    q.scale(1 / k, 1 / k)
    q.translate(-box.x(), -box.y())
    q.setPen(QPen(QColor(0, 0, 0, alpha), spread))
    q.setBrush(QColor(0, 0, 0, alpha))
    q.drawPath(path)
    q.end()
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawImage(box.translated(dx, dy), small)
    p.restore()


# ------------------------------------------------------------------- scroll
_SCROLL_CACHE = {}


def _paint_scroll(p, kind, w, h, header, ox, oy):
    """The whole scroll for a w x h window whose top-left is at (ox, oy)."""
    p.setRenderHint(QPainter.Antialiasing, True)
    sheet = page_path(kind, w, h).translated(ox, oy)
    if kind == "wide":
        rw = _ROLL_W
        lx, rx = ox - rw + 8, ox + w - 8
        top, bottom = oy - 3, oy + h + 3
        shadow = QPainterPath(sheet)
        shadow.addRect(QRectF(lx, top - 18, rw, bottom - top + 36))
        shadow.addRect(QRectF(rx, top - 18, rw, bottom - top + 36))
    else:
        rh = _ROLL_H
        top_y, bot_y = oy - rh + 8, oy + h - 6
        shadow = QPainterPath(sheet)
        shadow.addRect(QRectF(ox - 12, top_y, w + 24, rh))
        shadow.addRect(QRectF(ox - 12, bot_y, w + 24, rh))
    _soft_shadow(p, shadow.simplified(), 7, 10, _SHADOW)
    # The page.
    p.save()
    p.setClipPath(sheet)
    p.drawImage(QPointF(ox, oy), paper(w, h))
    # Where the page curves into a roll it darkens.
    if kind == "wide":
        for x0, x1 in ((ox, ox + 40), (ox + w, ox + w - 40)):
            g = QLinearGradient(x0, 0, x1, 0)
            g.setColorAt(0.0, QColor(90, 56, 24, 110))
            g.setColorAt(1.0, QColor(90, 56, 24, 0))
            p.fillRect(QRectF(min(x0, x1), oy, 40, h), QBrush(g))
    else:
        for y0, y1 in ((oy, oy + 34), (oy + h, oy + h - 30)):
            g = QLinearGradient(0, y0, 0, y1)
            g.setColorAt(0.0, QColor(90, 56, 24, 120))
            g.setColorAt(1.0, QColor(90, 56, 24, 0))
            p.fillRect(QRectF(ox, min(y0, y1), w, 34), QBrush(g))
    p.restore()
    # Its torn edge, a little darker.
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(120, 80, 40, 150), 1.2))
    p.drawPath(sheet)
    # A faint ruling under the title band.
    if header:
        y = oy + header - 3.5
        p.setPen(QPen(QColor(150, 36, 22, 90), 1.0))
        p.drawLine(QPointF(ox + 40, y), QPointF(ox + w - 40, y))
        p.setPen(QPen(QColor(120, 84, 42, 70), 1.0))
        p.drawLine(QPointF(ox + 40, y + 3), QPointF(ox + w - 40, y + 3))
    # The rolls.
    if kind == "wide":
        _upright_roll(p, lx, top, bottom, rw)
        _upright_roll(p, rx, top, bottom, rw)
    else:
        _lying_roll(p, ox - 12, ox + w + 12, top_y, rh)
        _lying_roll(p, ox - 12, ox + w + 12, bot_y, rh)


def paint(painter, rect: QRect, kind="wide", header=0):
    """The scroll for a window filling *rect* (its rolls and shadow reach
    past it, by :data:`REACH`), from a cached picture."""
    l, t, r, b = REACH[kind]
    pad = _SHADOW + 12
    w, h = rect.width(), rect.height()
    dpr = T.device_ratio(painter)
    key = (kind, w, h, header, dpr)
    pm = _SCROLL_CACHE.get(key)
    if pm is None:
        pw, ph = w + l + r + 2 * pad, h + t + b + 2 * pad
        pm = QPixmap(max(1, int(pw * dpr)), max(1, int(ph * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        try:
            _paint_scroll(q, kind, w, h, header, l + pad, t + pad)
        finally:
            q.end()
        if len(_SCROLL_CACHE) > 16:
            _SCROLL_CACHE.clear()
        _SCROLL_CACHE[key] = pm
    painter.drawPixmap(rect.x() - l - pad, rect.y() - t - pad, pm)


def _seal(p, cx, cy, r, glyph="✕"):
    """A blob of red sealing wax with *glyph* pressed into it."""
    rng = random.Random(5)
    import math
    path = QPainterPath()
    n = 16
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        rr = r * (0.9 + 0.14 * rng.random()) if i < n else None
        if i == 0:
            first = rr
        rr = first if i == n else rr
        pt = QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.fillPath(path.translated(1.2, 1.8), QColor(60, 20, 10, 90))
    g = QRadialGradient(QPointF(cx - r * 0.35, cy - r * 0.4), r * 1.4)
    g.setColorAt(0.0, QColor(210, 70, 52))
    g.setColorAt(0.55, QColor(158, 30, 22))
    g.setColorAt(1.0, QColor(96, 14, 10))
    p.fillPath(path, QBrush(g))
    p.setPen(QPen(QColor(110, 18, 12), 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r * 0.66, r * 0.66)
    f = fonts.dialogue_font_px(max(9, int(r * 1.05)))
    p.setFont(f)
    p.setPen(QColor(248, 214, 190))
    p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(Qt.AlignCenter), glyph)
    p.restore()


def draw_title(painter, rect: QRect, title, header, expanded=True, closable=True):
    """The window's title lettered at the top of the page, the wax seal that
    closes it (where the chrome's [X] was) and the fold mark beside it."""
    if header <= 0:
        return
    band = QRect(rect.x() + 60, rect.y() + (header - 34 if header > 34 else 0),
                 rect.width() - 120, 32)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    f = fonts.dialogue_font_px(24)
    painter.setFont(f)
    fm = painter.fontMetrics()
    text = fm.elidedText(str(title), Qt.ElideRight, band.width() - 80)
    tw = fm.horizontalAdvance(text)
    painter.setPen(RUBRIC)
    painter.drawText(band, int(Qt.AlignCenter), text)
    # A flourish either side: a line ending in a lozenge.
    cy = band.center().y() + 2
    for sign in (-1, 1):
        x0 = band.center().x() + sign * (tw / 2 + 12)
        x1 = x0 + sign * 46
        painter.setPen(QPen(QColor(120, 84, 42, 200), 1.2))
        painter.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        d = QPainterPath()
        d.moveTo(x1 + sign * 5, cy)
        d.lineTo(x1, cy - 3.5)
        d.lineTo(x1 - sign * 5, cy)
        d.lineTo(x1, cy + 3.5)
        d.closeSubpath()
        painter.fillPath(d, RUBRIC)
    if closable:
        mid = rect.y() + header / 2.0 + (4 if header > 34 else 0)
        _seal(painter, rect.right() - 13, mid, 10.5)
        painter.setFont(fonts.dialogue_font_px(14))
        painter.setPen(QColor(104, 70, 40))
        painter.drawText(QRectF(rect.right() - 50, mid - 12, 25, 24), int(Qt.AlignCenter),
                         "▾" if expanded else "▸")
    painter.restore()


def plaque(painter, rect, on=False, enabled=True):
    """A button on a scroll: a pale, ink-outlined plaque (warm wash when
    pressed in or chosen, faded when it does nothing)."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    r = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
    g = QLinearGradient(0, r.top(), 0, r.bottom())
    if on:
        g.setColorAt(0.0, QColor(236, 196, 128, 230))
        g.setColorAt(1.0, QColor(214, 164, 92, 230))
    else:
        g.setColorAt(0.0, QColor(250, 238, 208, 200 if enabled else 110))
        g.setColorAt(1.0, QColor(228, 206, 160, 200 if enabled else 110))
    painter.setBrush(QBrush(g))
    painter.setPen(QPen(QColor(140, 30, 18) if on else
                        QColor(96, 64, 36, 230 if enabled else 110), 1.4))
    painter.drawRoundedRect(r, 4, 4)
    painter.setPen(QPen(QColor(96, 64, 36, 70 if enabled else 30), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(r.adjusted(3, 3, -3, -3), 2, 2)
    painter.restore()



# ------------------------------------------------------------------ windows
class ScrollChrome(FloatingWindow):
    """Draws a window as its scroll: put between a window's own class and
    :class:`FloatingWindow` (see :func:`dress`), so a subclass's ``draw``
    that calls ``super().draw`` still gets it."""

    scroll_kind = "wide"
    scroll_closable = True

    def draw(self, painter, focused=False):
        rect = self._full_rect()
        self.window_rect.setHeight(rect.height())
        header = self.HEADER_H
        paint(painter, rect, self.scroll_kind, header)
        draw_title(painter, rect, self.title, header, self.expanded,
                   self.scroll_closable)
        if self.expanded:
            with T.parchment():
                self.draw_body(painter, rect.x(), rect.y() + header, rect.width())


_TYPES = {}
#: Windows that keep their own look with the scroll style on: a
#: conversation stays a conversation window.
UNDRESSED = ("dialogue",)


def _kind_for(win) -> str:
    key = str(getattr(win, "key", ""))
    if key in ("screen:statistics", "screen:container", "screen:trade",
               "screen:inventory", "screen:character", "screen:quest"):
        return "wide"
    return "tall"


def _draws_alone(cls) -> bool:
    """Whether *cls* (or a class between it and FloatingWindow) has a
    ``draw`` of its own that never hands on to ``super().draw``."""
    import inspect
    for k in cls.__mro__:
        if k is FloatingWindow:
            return False
        fn = k.__dict__.get("draw")
        if fn is not None:
            try:
                return "super().draw" not in inspect.getsource(fn)
            except (OSError, TypeError):
                return True
    return False


def dress(win, view_w=None, view_h=None, kind=None):
    """Make *win* its scroll, when the scroll style is on (else leave it).
    Re-centres it in the view so its rolls and knobs stay on screen."""
    if not T.scroll_on() or isinstance(win, ScrollChrome):
        return win
    if str(getattr(win, "key", "")) in UNDRESSED:
        return win
    cls = type(win)
    kind = kind or _kind_for(win)
    # A window whose own draw paints everything (no super().draw) is wrapped
    # from the front; any other gets the scroll where the chrome was.
    front = _draws_alone(cls)
    tkey = (cls, kind, front)
    new = _TYPES.get(tkey)
    if new is None:
        bases = (ScrollChrome, cls) if front else (cls, ScrollChrome)
        new = type("Scroll" + cls.__name__, bases, {"scroll_kind": kind})
        _TYPES[tkey] = new
    win.__class__ = new
    if cls.HEADER_H > 0:
        win.HEADER_H = HEADER[kind]
    else:
        new.scroll_closable = False
    if view_w and view_h:
        place(win, view_w, view_h)
    return win


def place(win, view_w, view_h):
    """Centre *win* with its scroll's reach inside the view."""
    l, t, r, b = REACH[getattr(win, "scroll_kind", "wide")]
    w = win.width
    h = win.HEADER_H + win.content_height()
    x = (view_w - (w + l + r)) // 2 + l
    y = (view_h - (h + t + b)) // 2 + t
    win.window_rect.moveTo(max(l + 2, x), max(t + 2, y))
