"""
Item drag and drop *between* MiniWind's item windows.

The character window (C, :mod:`game.ui.inventory_window`), the inventory strip
(I, :mod:`game.ui.inventory_strip`) and the container / corpse screen
(:mod:`game.ui.container_window`) are separate floating windows, so an item
picked up in one must be droppable on another. Each window says, while it
paints, where its drop targets are (:func:`set_zones`); the window an item was
picked up in finds what it was let go over with :func:`target_at`, and queues
``session.item_drop(source, target)`` through :mod:`game.ui.hits` for the game
tick, exactly as its own drops are.

A *source* is ``(kind, key, item id)`` and a *target* ``(kind, key)``; the
kinds are ``pack``, ``equip``, ``quick``, ``strip`` and ``container``.

Everything here runs on the UI thread (painting and the mouse).
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint

#: owner -> [(QRect, target)], replaced by each owner every frame it paints.
_zones = {}
#: owner -> paint order, so the window painted last (topmost) wins.
_order = {}
_tick = [0]

#: What is being dragged, or None: ``{"owner": window, "source": (...)}``.
current = None


def set_zones(owner, zones) -> None:
    """*owner*'s drop targets for this frame: ``[(QRect, target)]``."""
    _tick[0] += 1
    _zones[owner] = list(zones)
    _order[owner] = _tick[0]


def forget(owner) -> None:
    """*owner* has closed: it takes no more drops."""
    global current
    _zones.pop(owner, None)
    _order.pop(owner, None)
    if current is not None and current.get("owner") is owner:
        current = None


def over_window(x, y) -> bool:
    """Whether (x, y) is over any open item window (the strip, the character
    window, a chest): let go anywhere else, a dragged item is dropped on
    the floor."""
    point = QPoint(int(x), int(y))
    for owner in list(_zones):
        if not getattr(owner, "active", True):
            continue
        rect = getattr(owner, "window_rect", None)
        if rect is not None and rect.contains(point):
            return True
    return False


def target_at(x, y, exclude=None):
    """The drop target under (x, y) in any window but *exclude*, or None."""
    point = QPoint(int(x), int(y))
    for owner in [o for o in _zones if not getattr(o, "active", True)]:
        forget(owner)                 # closed windows take no drops
    owners = sorted(_zones, key=lambda o: _order.get(o, 0), reverse=True)
    for owner in owners:
        if owner is exclude:
            continue
        for rect, target in reversed(_zones[owner]):
            if rect.contains(point):
                return target
    return None


def start(owner, source) -> None:
    global current
    current = {"owner": owner, "source": tuple(source)}


def stop(owner=None) -> None:
    global current
    if owner is None or (current is not None and current.get("owner") is owner):
        current = None


def dragged_id():
    """The item id being dragged anywhere, or None."""
    return current["source"][2] if current is not None else None


def draw_ghost(painter, owner, pointer, size=52) -> None:
    """The dragged item's icon under the pointer, drawn by the window it was
    picked up in."""
    if current is None or current.get("owner") is not owner or pointer is None:
        return
    iid = current["source"][2]
    if current["source"][0] in ("spell", "spell_hand"):
        from ..rpg import magic
        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QColor
        spell = magic.get(iid)
        if spell is not None:
            painter.save()
            painter.setOpacity(0.85)
            painter.setBrush(QColor(*spell.color))
            painter.drawEllipse(QPointF(*pointer), size / 3, size / 3)
            painter.restore()
        return
    try:
        from .. import item_icons
        pm = item_icons.icon_pixmap(iid, None, size)
    except Exception:
        pm = None
    if pm is None or pm.isNull():
        return
    painter.save()
    painter.setOpacity(0.85)
    painter.drawPixmap(int(pointer[0] - pm.width() / 2), int(pointer[1] - pm.height() / 2), pm)
    painter.restore()


def reset() -> None:
    """Forget every window and drag (a play session ended; tests)."""
    global current
    _zones.clear()
    _order.clear()
    current = None
