"""
Spells shown greyed out while worn metal armour stops the character casting.

Metal interferes with magic (:func:`game.rpg.magic.metal_blocks`): the armour
can still be worn, but every place that shows a spell -- the shortcut bar, the
character window, the spellbook, the loadout window and the HUD -- draws it
greyed out, and hovering it shows a tooltip, :data:`TIP`.

A greyed spell can still be highlighted -- by the pointer or by gamepad
focus -- but not selected or readied (:func:`refuse`); the tooltip on the
highlighted slot is what says why.

Each of those UIs paints its spells, calls :func:`note` for every greyed spell
it draws (with the spell's rectangle) and :func:`focus` for the one gamepad
focus is on, and calls :func:`flush` once it has painted everything else, so
the tooltip lies on top.
"""

from __future__ import annotations

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainterPath, QPen, QPixmap

from . import hits
from . import theme as T

#: The tooltip on a greyed-out spell.
TIP = "Metal armour prevents this"

#: How a greyed spell's name or orb is coloured.
GREY = QColor(118, 118, 126)

_TIP_BG = QColor(26, 20, 20, 240)
_TIP_EDGE = QColor(200, 90, 70)
_TIP_TEXT = QColor(255, 196, 176)

_grey_cache = {}
_GREY_CACHE_LIMIT = 256
_pending = None


def locked(character) -> bool:
    """Whether *character*'s spells are shown greyed out (worn metal armour)."""
    if character is None:
        return False
    try:
        import game.rpg.magic as magic
        return bool(magic.metal_blocks(character))
    except Exception:
        return False


def colour(rgb, is_locked: bool) -> QColor:
    """A spell's orb colour, or :data:`GREY` when it is locked."""
    return QColor(GREY) if is_locked else QColor(*rgb)


def grey(pm, is_locked: bool = True):
    """*pm* in greyscale (alpha kept) and faded, when *is_locked*; else *pm*."""
    if not is_locked or pm is None or pm.isNull():
        return pm
    key = pm.cacheKey()
    hit = _grey_cache.get(key)
    if hit is not None:
        return hit
    src = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    out = src.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32)
    out.setAlphaChannel(src.convertToFormat(QImage.Format_Alpha8))
    faded = QPixmap.fromImage(out)
    faded.setDevicePixelRatio(pm.devicePixelRatio())
    if len(_grey_cache) >= _GREY_CACHE_LIMIT:
        _grey_cache.clear()
    _grey_cache[key] = faded
    return faded


def veil(painter, rect, radius=3.0) -> None:
    """A dark wash over a greyed spell's slot, so it reads as unusable."""
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect).adjusted(2, 2, -2, -2), radius, radius)
    painter.fillPath(path, QColor(18, 18, 22, 120))


def note(rect, is_locked: bool) -> bool:
    """Say a greyed spell was drawn in *rect*: if the pointer is over it, the
    next :func:`flush` shows the tooltip by the pointer. Returns whether it
    is hovered."""
    global _pending
    if not is_locked or not hits.hovered(rect):
        return False
    _pending = (TIP, hits.pointer)
    return True


def focus(rect, is_locked: bool) -> bool:
    """Say gamepad focus is on a greyed spell in *rect*: the next
    :func:`flush` shows the tooltip by that slot (there is no pointer)."""
    global _pending
    if not is_locked or rect is None:
        return False
    _pending = (TIP, (rect.right() - 10, rect.bottom() - 10))
    return True


def flush(painter) -> None:
    """Draw the tooltip a :func:`note` or :func:`focus` this paint asked for."""
    global _pending
    pending, _pending = _pending, None
    if pending and pending[1] is not None:
        draw_tip(painter, pending[0], pending[1])


def refuse(session, character) -> bool:
    """True when *character* cannot select or ready a spell because worn
    metal armour stops it. Nothing is said: the slot is greyed out, and the
    tooltip on it (hovered, or under gamepad focus) is the explanation."""
    return locked(character)


def draw_tip(painter, text, pos) -> QRect:
    """A tooltip box reading *text* just below and right of *pos*, kept
    inside the painter's window."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setFont(T.font(10, bold=True, family="Segoe UI"))
    fm = painter.fontMetrics()
    w, h = fm.horizontalAdvance(text) + 20, fm.height() + 12
    x, y = int(pos[0]) + 16, int(pos[1]) + 18
    try:
        bounds = painter.window()
        if x + w > bounds.right() - 4:
            x = int(pos[0]) - w - 8
        if y + h > bounds.bottom() - 4:
            y = int(pos[1]) - h - 8
        x, y = max(bounds.left() + 4, x), max(bounds.top() + 4, y)
    except Exception:
        pass
    box = QRect(x, y, w, h)
    painter.setBrush(_TIP_BG)
    painter.setPen(QPen(_TIP_EDGE, 1.5))
    painter.drawRoundedRect(QRectF(box), 4, 4)
    painter.setPen(_TIP_TEXT)
    painter.drawText(box, int(Qt.AlignCenter), text)
    painter.restore()
    return box
