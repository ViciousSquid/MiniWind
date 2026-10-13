"""
Shared drawing helpers and the Miniwind visual theme (Qt).

Only imported on the Qt side (editor/engine host). A dark, gilded fantasy-UI
palette with a few reusable primitives — framed panels, bars and text — so the
HUD and the full-screen menus look like one game rather than a debug overlay.
"""

from __future__ import annotations

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QBrush, QPen, QLinearGradient,
                         QPainter, QPainterPath, QPixmap, QTransform)

from . import fonts

# palette
GOLD = QColor(198, 162, 88)
GOLD_BRIGHT = QColor(255, 214, 130)
GILD = QColor(150, 122, 64)
PARCH = QColor(226, 224, 236)
INK = QColor(232, 228, 240)
DIM = QColor(150, 150, 168)
PANEL_TOP = QColor(30, 28, 40, 244)
PANEL_BOT = QColor(16, 15, 24, 246)
SHADOW = QColor(0, 0, 0, 140)
SELECT = QColor(70, 60, 96, 230)

HEALTH = QColor(196, 62, 54)
MAGICKA = QColor(64, 116, 200)
STAMINA = QColor(96, 168, 84)
XP = QColor(200, 170, 90)

ALIGN_CENTER = int(Qt.AlignCenter)
ALIGN_LEFT = int(Qt.AlignVCenter | Qt.AlignLeft)
ALIGN_RIGHT = int(Qt.AlignVCenter | Qt.AlignRight)
WORD_WRAP = int(Qt.TextWordWrap)


#: ``font()`` arguments -> a built QFont, valid for one installed-font set.
_FONT_CACHE = {}
_font_cache_families = None


def font(size, bold=False, italic=False, family="Georgia"):
    """A UI font. A sans *family* becomes MedievalSharp when that is installed
    (see :func:`game.ui.fonts.game_family`).

    Built once per distinct request and handed out as a copy (QFont copies
    are implicitly shared, so cheap): the HUD asks for the same dozen fonts
    every frame, and resolving the family each time was most of the cost."""
    global _font_cache_families
    key = (size, bold, italic, family)
    if fonts._families is not _font_cache_families or len(_FONT_CACHE) > 512:
        _FONT_CACHE.clear()
        _font_cache_families = fonts._families
    f = _FONT_CACHE.get(key)
    if f is None:
        f = QFont(fonts.game_family(family), size,
                  QFont.Bold if bold else QFont.Normal, italic)
        if fonts._families is not _font_cache_families:
            return f             # the font set changed while resolving
        _FONT_CACHE[key] = f
    return QFont(f)


#: Decorative "old RPG" family stack for titles — the same one the spell cards
#: use. Whatever the OS has first wins (Papyrus/Palatino/Book Antiqua/Georgia…).
FANCY_FAMILIES = ["Papyrus", "Luminari", "Palatino Linotype", "Book Antiqua",
                  "Georgia", "Cambria", "serif"]


def fancy_font(size, bold=False, italic=False):
    f = QFont()
    try:
        f.setFamilies(FANCY_FAMILIES)
    except Exception:
        f.setFamily("Georgia")
    f.setPointSize(int(size))
    f.setBold(bool(bold))
    f.setItalic(bool(italic))
    f.setStyleHint(QFont.Serif)
    return f


# ------------------------------------------------------------------ sprites
_TX_TRANSLATE = QTransform.TxTranslate

#: Pixmaps of HUD pieces that look the same frame after frame, by key.
_SPRITES = {}
_SPRITE_LIMIT = 256


def device_ratio(painter) -> float:
    """The device pixel ratio *painter* draws at (1.0 when it cannot say)."""
    try:
        return float(painter.device().devicePixelRatioF()) or 1.0
    except Exception:
        return 1.0


def sprite(painter, key, w, h, paint):
    """A cached pixmap, *w* x *h* logical pixels, painted by ``paint(p)``.

    For a HUD piece that is redrawn identically frame after frame (a bar at
    the same fill, a panel, the clock at the same minute): it is painted once
    into a transparent pixmap at the screen's pixel ratio and blitted after
    that, rather than rebuilt from paths, gradients and text every frame.
    *key* must capture everything the drawing depends on except position.

    None when *painter* scales or rotates (a blit would resample the
    picture); the caller then draws directly.
    """
    if painter.transform().type() > _TX_TRANSLATE:
        return None
    dpr = device_ratio(painter)
    # Drawn with the hints the caller's painter has (antialiasing above all),
    # so the picture is the one a direct draw would have made.
    hints = painter.renderHints()
    full = (key, int(w), int(h), dpr, int(hints))
    pm = _SPRITES.get(full)
    if pm is None:
        pm = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHints(hints)
            paint(p)
        finally:
            p.end()
        if len(_SPRITES) >= _SPRITE_LIMIT:
            _SPRITES.clear()
        _SPRITES[full] = pm
    return pm


def _paint_panel(painter, x, y, w, h, radius, shadow):
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    if shadow:
        sp = QPainterPath()
        sp.addRoundedRect(QRectF(x + 4, y + 6, w, h), radius, radius)
        painter.fillPath(sp, SHADOW)
    body = QPainterPath()
    body.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    grad = QLinearGradient(0, y, 0, y + h)
    grad.setColorAt(0.0, PANEL_TOP)
    grad.setColorAt(1.0, PANEL_BOT)
    painter.fillPath(body, QBrush(grad))
    painter.setPen(QPen(GILD, 2))
    painter.drawPath(body)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(x + 4, y + 4, w - 8, h - 8), radius - 3, radius - 3)
    painter.setPen(QPen(QColor(90, 74, 44), 1))
    painter.drawPath(inner)
    painter.restore()


def panel(painter, x, y, w, h, radius=12, shadow=True):
    """Draw a framed, gilded, gradient panel and return its inner rect."""
    if x == int(x) and y == int(y):
        # Whole-pixel placement: the same panel every frame, so a blit. The
        # 2 px gilt stroke and the drop shadow reach past the body's rect.
        pad = 2
        pm = sprite(painter, ("panel", float(w), float(h), radius, bool(shadow)),
                    w + pad * 2 + 4, h + pad * 2 + 6,
                    lambda p: _paint_panel(p, pad, pad, w, h, radius, shadow))
    else:
        pm = None
    if pm is not None:
        painter.drawPixmap(int(x) - pad, int(y) - pad, pm)
    else:
        _paint_panel(painter, x, y, w, h, radius, shadow)
    return QRect(int(x + 16), int(y + 16), int(w - 32), int(h - 32))


def _paint_bar(painter, x, y, w, h, fill, color, bg, label, text_color):
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRect(int(x), int(y), int(w), int(h)), 3, 3)
    if fill > 0:
        g = QLinearGradient(x, y, x, y + h)
        g.setColorAt(0.0, color.lighter(125))
        g.setColorAt(1.0, color.darker(115))
        painter.setBrush(QBrush(g))
        painter.drawRoundedRect(QRect(int(x), int(y), fill, int(h)), 3, 3)
    painter.setPen(QPen(GILD, 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRect(int(x), int(y), int(w), int(h)), 3, 3)
    if label:
        painter.setFont(font(max(7, int(h * 0.5)), bold=True, family="Segoe UI"))
        painter.setPen(text_color or QColor(240, 240, 245))
        painter.drawText(QRect(int(x), int(y), int(w), int(h)), ALIGN_CENTER, label)
    painter.restore()


def bar(painter, x, y, w, h, frac, color, bg=QColor(20, 18, 26, 220), label=None,
        text_color=None):
    """A framed stat bar filled to *frac* (0..1)."""
    frac = max(0.0, min(1.0, frac))
    # The drawing only depends on the filled width in whole pixels, so that
    # (not the exact fraction) is what identifies the cached picture.
    fill = int(w * frac)
    key = ("bar", float(w), float(h), fill, color.rgba(), bg.rgba(), label,
           text_color.rgba() if text_color is not None else None)
    pm = sprite(painter, key, int(w) + 2, int(h) + 2,
                lambda p: _paint_bar(p, 1, 1, w, h, fill, color, bg, label,
                                     text_color))
    if pm is not None:
        painter.drawPixmap(int(x) - 1, int(y) - 1, pm)
    else:
        _paint_bar(painter, x, y, w, h, fill, color, bg, label, text_color)


def text(painter, x, y, s, size=11, color=INK, bold=False, italic=False,
         family="Georgia"):
    painter.save()
    painter.setFont(font(size, bold, italic, family))
    painter.setPen(color)
    painter.drawText(int(x), int(y), s)
    painter.restore()


def text_in(painter, rect, s, size=11, color=INK, align=ALIGN_LEFT, bold=False,
            italic=False, family="Georgia"):
    painter.save()
    painter.setFont(font(size, bold, italic, family))
    painter.setPen(color)
    painter.drawText(rect, align, s)
    painter.restore()


def dim_screen(painter, w, h, alpha=170):
    painter.fillRect(QRect(0, 0, int(w), int(h)), QColor(6, 6, 10, alpha))


def heading(painter, rect, title, subtitle=None):
    # Titles are in the game's own medieval face (MedievalSharp, bundled in
    # assets/fonts) rather than whatever display font the OS happens to have,
    # and sized in pixels so they fit the panel at any DPI. The face has one
    # upright weight, so it is never asked for bold or italic.
    from . import fonts
    painter.save()
    painter.setFont(fonts.dialogue_font_px(28))
    painter.setPen(GOLD_BRIGHT)
    fm = painter.fontMetrics()
    painter.drawText(rect.x(), rect.y() + 24,
                     fm.elidedText(str(title), Qt.ElideRight, max(1, rect.width())))
    painter.setPen(QPen(GILD, 1))
    painter.drawLine(rect.x(), rect.y() + 32, rect.right(), rect.y() + 32)
    if subtitle:
        painter.setFont(fonts.dialogue_font_px(13))
        painter.setPen(DIM)
        fm = painter.fontMetrics()
        painter.drawText(rect.x(), rect.y() + 48,
                         fm.elidedText(str(subtitle), Qt.ElideRight, max(1, rect.width())))
    painter.restore()
    return rect.y() + (56 if subtitle else 44)
