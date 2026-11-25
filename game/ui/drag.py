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

A *source* is ``(kind, key, item id)`` -- or ``(kind, key, item id, n)``
for *n* of a stack split off with a right click -- and a *target*
``(kind, key)``; the
kinds are ``pack``, ``equip``, ``quick``, ``strip`` and ``container``. A spell
dragged out of the spellbook is ``("spell", None, spell id)``, and it can be
let go on the strip; a strip slot holding one carries ``"spell:<id>"``.

Instead of a drag, a click can pick an item up (:func:`pick`): every slot it
fits lights up, in every window, and a click on one puts it there -- the same
``session.item_drop(source, target)``. A click on the item again, or a right
click, puts it back down.

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
#: What a click (not a drag) has picked up to place with a second click on a
#: slot, or None: ``{"owner": window, "source": (...)}``. Any window can take
#: it: a click on one of its slots that fits is the drop.
picked = None


def set_zones(owner, zones) -> None:
    """*owner*'s drop targets for this frame: ``[(QRect, target)]``."""
    _tick[0] += 1
    _zones[owner] = list(zones)
    _order[owner] = _tick[0]


def forget(owner) -> None:
    """*owner* has closed: it takes no more drops."""
    global current, picked
    _zones.pop(owner, None)
    _order.pop(owner, None)
    if current is not None and current.get("owner") is owner:
        current = None
    if picked is not None and picked.get("owner") is owner:
        picked = None


def pick(owner, source) -> None:
    """A click picked *source* up: the slots it fits light up, and a click on
    one of them puts it there."""
    global picked
    picked = {"owner": owner, "source": tuple(source)}


def split_half(qty) -> int:
    """How many a right click picks up off a stack of *qty* (to split it):
    the larger half -- two of three -- and none from a single thing."""
    qty = int(qty or 0)
    return (qty + 1) // 2 if qty >= 2 else 0


def unpick() -> None:
    global picked
    picked = None


def picked_source():
    """The ``(kind, key, id)`` picked up by a click, or None."""
    return picked["source"] if picked is not None else None


def offered():
    """What is on its way to a slot: the item being dragged, else the one a
    click picked up; None when neither."""
    if current is not None:
        return current["source"]
    return picked_source()


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


def draw_ghost(painter, owner, pointer, size=52, source=None) -> None:
    """The dragged item's icon under the pointer, drawn by the window it was
    picked up in; or, given *source*, that item's (one a click picked up)."""
    if source is None:
        if current is None or current.get("owner") is not owner:
            return
        source = current["source"]
    if pointer is None:
        return
    iid = source[2]
    if str(iid).startswith("spell:"):
        iid = str(iid)[len("spell:"):]          # a spell's strip slot
    if source[0] in ("spell", "spell_hand") or iid != source[2]:
        import game.rpg.magic as magic
        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QColor
        spell = magic.get(iid)
        try:
            import game.item_icons as item_icons
            pm = item_icons.spell_pixmap(iid, size)
        except Exception:
            pm = None
        if pm is not None and not pm.isNull():
            painter.save()
            painter.setOpacity(0.85)
            painter.drawPixmap(int(pointer[0] - pm.width() / 2),
                               int(pointer[1] - pm.height() / 2), pm)
            painter.restore()
        elif spell is not None:
            painter.save()
            painter.setOpacity(0.85)
            painter.setBrush(QColor(*spell.color))
            painter.drawEllipse(QPointF(*pointer), size / 3, size / 3)
            painter.restore()
        return
    try:
        import game.item_icons as item_icons
        pm = item_icons.icon_pixmap(iid, None, size)
    except Exception:
        pm = None
    if pm is None or pm.isNull():
        return
    split = len(source) > 3 and bool(source[3])
    painter.save()
    if split:
        # Half a stack on the pointer sits on a little tile of its own.
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QColor, QPen
        painter.setRenderHint(painter.Antialiasing, True)
        painter.setBrush(QColor(20, 18, 28, 220))
        painter.setPen(QPen(QColor(214, 176, 108), 1.5))
        painter.drawRoundedRect(QRectF(pointer[0] - pm.width() / 2 - 5,
                                       pointer[1] - pm.height() / 2 - 5,
                                       pm.width() + 10, pm.height() + 10), 5, 5)
    painter.setOpacity(1.0 if split else 0.85)
    painter.drawPixmap(int(pointer[0] - pm.width() / 2), int(pointer[1] - pm.height() / 2), pm)
    painter.restore()
    if split:
        _draw_count(painter, pointer, pm.width(), pm.height(), int(source[3]))


def _draw_count(painter, pointer, w, h, n) -> None:
    """How many of a split stack ride on the pointer: "×3" on the icon's
    lower right corner."""
    from PyQt5.QtCore import QRect, QRectF, Qt
    from PyQt5.QtGui import QColor, QFontMetrics, QPen
    import game.ui.fonts as fonts
    text = f"×{n}"
    font = fonts.dialogue_font_px(13)
    tw = QFontMetrics(font).horizontalAdvance(text) + 10
    box = QRect(int(pointer[0] + w / 2 - tw + 12), int(pointer[1] + h / 2 - 6), tw, 18)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setBrush(QColor(14, 13, 20, 230))
    painter.setPen(QPen(QColor(214, 176, 108), 1))
    painter.drawRoundedRect(QRectF(box), 4, 4)
    painter.setFont(font)
    painter.setPen(QColor(255, 236, 170))
    painter.drawText(box, int(Qt.AlignCenter), text)
    painter.restore()


def reset() -> None:
    """Forget every window and drag (a play session ended; tests)."""
    global current, picked
    _zones.clear()
    _order.clear()
    current = None
    picked = None
