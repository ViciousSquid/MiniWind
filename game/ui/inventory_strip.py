"""
The inventory strip: a Minecraft-style bar of item slots along the bottom of
the screen, always shown in free play.

Each slot holds something carried (the slots are kept on the character,
``Character.strip``, and synced by ``MiniwindSession.strip_slots``): its icon,
its count, a gold edge when it is worn or in hand. One slot is *selected* —
raised and lit, its name shown above the bar.

* click a slot (or press its number key) to select it; a weapon in it is
  taken in hand at once -- the main hand, or the off hand when the main hand
  is full -- and clicked again is put away. Double-click anything else to
  use or wear it;
* drag a slot onto another to rearrange (the two swap); out over the world,
  it is dropped on the floor;
* drag between the strip and the character window (C), a chest or a body:
  out of the strip into the pack takes it off the strip, onto the body wears
  it, into a container stores it; from any of them onto a slot puts it there
  (taking it first, from a chest or a body).

Always nine slots, one per number key.

The strip is a :class:`FloatingWindow` without chrome so the view routes the
mouse to it like any window; it does not pause the world. As everywhere in
the game UI, changes are queued through :mod:`game.ui.hits` for the tick.
"""

from __future__ import annotations

import time

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QLinearGradient, QPainterPath, QPen

from engine.floating_windows import FloatingWindow

from . import drag, hits, hud_layout

# Forged iron and old bronze, after the dark ornate action bars of ARPGs: a
# bevelled tile per slot on a riveted backing bar, an ember rim on the one
# selected.
_BAR_TOP = QColor(58, 52, 46, 238)
_BAR_BOT = QColor(24, 21, 19, 245)
_BRONZE = QColor(150, 116, 66)
_BRONZE_HI = QColor(214, 176, 108)
_RIVET = QColor(186, 150, 92)
_TILE_TOP = QColor(44, 42, 40, 250)
_TILE_BOT = QColor(16, 15, 15, 250)
_TILE_EDGE = QColor(8, 7, 7)
_BEVEL_HI = QColor(255, 255, 255, 34)
_BEVEL_LO = QColor(0, 0, 0, 120)
_EMBER = QColor(240, 140, 50)
_EMBER_GLOW = QColor(255, 150, 60, 70)
_WORN = QColor(214, 176, 108)
_OK = QColor(110, 220, 130)
_COUNT = QColor(255, 236, 170)
_NUMBER = QColor(170, 150, 120)

CELL = 58            # a slot's size at full width (px)
MIN_CELL = 30
GAP = 6
PAD = 9              # backing bar around the slots
NUMBERS = 13         # strip under the slots for their numbers
BOTTOM = 4           # gap under the bar
SIDE_CLEAR = 290     # keep clear of the HUD's corners (health bars, loadout)
DOUBLE_CLICK = 0.35
DRAG_START = 5


def layout(n, view_w, view_h):
    """The slot rects of an *n*-slot strip in a view of the given size."""
    n = max(1, int(n))
    room = max(view_w - 2 * SIDE_CLEAR, n * (MIN_CELL + GAP))
    room = min(room, view_w - 20 - 2 * PAD)
    cell = int(max(MIN_CELL, min(CELL, (room + GAP) // n - GAP)))
    total = n * cell + (n - 1) * GAP
    x0 = (view_w - total) // 2
    y = view_h - cell - BOTTOM - PAD - NUMBERS
    return [QRect(x0 + i * (cell + GAP), y, cell, cell) for i in range(n)]


def height_needed() -> int:
    """How much of the bottom of the view the strip and its name plate take."""
    return CELL + 2 * PAD + NUMBERS + BOTTOM + 34


def _is_weapon(iid) -> bool:
    if not iid:
        return False
    try:
        from ..rpg import items
        d = items.get(iid)
    except Exception:
        return False
    return d is not None and d.category == items.WEAPON


def _bar_rect(rects):
    a, b = rects[0], rects[-1]
    return QRect(a.x() - PAD, a.y() - PAD, b.right() - a.x() + 1 + 2 * PAD,
                 a.height() + 2 * PAD + NUMBERS)


class InventoryStrip(FloatingWindow):
    """The strip (see the module docstring)."""

    wants_cursor = True
    HEADER_H = 0

    def __init__(self, session):
        super().__init__("Inventory", 0, 0, 200, body_height=CELL)
        self.window_rect = QRect(0, 0, 0, 0)
        self.session = session
        self.key = "strip"
        self._rects = []           # slot rects, as last laid out
        self._slots = []           # the stacks in them (or None)
        self._view = (0, 0)
        self._press = None         # (QPoint, slot index)
        self._dragging = False
        self._last_click = (0.0, None)
        from . import fonts
        self.f_count = fonts.dialogue_font_px(14)
        self.f_name = fonts.dialogue_font_px(16)
        self.f_number = fonts.dialogue_font_px(11)

    @property
    def selected(self) -> int:
        """The selected slot: kept on the session, so the number keys (read
        on the tick) and a click here pick the same one."""
        return int(getattr(self.session, "strip_selected", 0) or 0)

    @selected.setter
    def selected(self, index) -> None:
        self.session.strip_selected = int(index)

    # ------------------------------------------------------------ geometry
    def place(self, view_w, view_h):
        self._view = (int(view_w), int(view_h))

    def _layout(self):
        n = len(self._slots) or self.session.strip_size()
        vw, vh = self._view
        self._rects = layout(n, vw, vh) if vw and vh else []
        if self._rects:
            # Wherever the player has put it (game/ui/hud_layout.py).
            natural = _bar_rect(self._rects)
            hud_layout.note("strip", natural)
            moved = hud_layout.screen_rect("strip", vw, vh)
            dx, dy = moved.x() - natural.x(), moved.y() - natural.y()
            self._rects = [r.translated(dx, dy) for r in self._rects]
            self.window_rect = _bar_rect(self._rects)
            self.width = self.window_rect.width()

    def _full_rect(self):
        return QRect(self.window_rect)

    def content_height(self):
        return self.window_rect.height()

    # ------------------------------------------------------------- drawing
    def draw(self, painter, focused=False):
        try:
            self._slots = list(self.session.strip_slots())
        except Exception:
            self._slots = []
        if hud_layout.collapsed("strip"):
            self._rects = []          # folded away: nothing drawn, nothing to hit
            return
        self._layout()
        if not self._rects:
            return
        self.selected = max(0, min(self.selected, len(self._rects) - 1))
        worn = set()
        hands = []
        try:
            worn = {v for v in self.session.game.character.equipment.values() if v}
            # A weapon is lit by the copy in hand, not every slot of its kind.
            hands = self.session.strip_hands()
        except Exception:
            pass
        dragged = drag.dragged_id()
        mine = drag.current is not None and drag.current.get("owner") is self
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        self._draw_bar(painter)
        zones = []
        for i, rect in enumerate(self._rects):
            stack = self._slots[i] if i < len(self._slots) else None
            iid = stack.get("id") if stack else None
            sel = i == self.selected
            hot = hits.hovered(rect)
            self._draw_tile(painter, rect, stack, sel, hot, dragged is not None)
            hide = mine and self._press is not None and self._press[1] == i
            if iid and not hide:
                held = (hands[i] is not None if _is_weapon(iid) and i < len(hands)
                        else iid in worn)
                self._draw_item(painter, rect, iid, stack, held)
            painter.setFont(self.f_number)
            painter.setPen(_EMBER if sel else _NUMBER)
            painter.drawText(QRect(rect.x(), rect.bottom() + 2, rect.width(), NUMBERS),
                             Qt.AlignCenter, str(i + 1))
            zones.append((QRect(rect), ("strip", i)))
        drag.set_zones(self, zones)
        # The selected slot's name, above the bar.
        stack = self._slots[self.selected] if self.selected < len(self._slots) else None
        if stack and dragged is None:
            self._draw_name(painter, stack)
        if mine:
            drag.draw_ghost(painter, self, hits.pointer, self._rects[0].width() - 8)
        painter.restore()

    def _draw_bar(self, painter):
        """The riveted iron backing bar with its bronze rim."""
        bar = QRectF(self.window_rect)
        path = QPainterPath()
        path.addRoundedRect(bar, 7, 7)
        g = QLinearGradient(0, bar.top(), 0, bar.bottom())
        g.setColorAt(0.0, _BAR_TOP)
        g.setColorAt(1.0, _BAR_BOT)
        shadow = QPainterPath()
        shadow.addRoundedRect(bar.translated(0, 3), 7, 7)
        painter.fillPath(shadow, QColor(0, 0, 0, 110))
        painter.fillPath(path, QBrush(g))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_BRONZE, 2))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        painter.drawRoundedRect(bar.adjusted(3, 3, -3, -3), 5, 5)
        # A highlight along the top edge, as on worn metal.
        painter.setPen(QPen(QColor(_BRONZE_HI.red(), _BRONZE_HI.green(), _BRONZE_HI.blue(), 90), 1))
        painter.drawLine(int(bar.left() + 8), int(bar.top() + 1), int(bar.right() - 8), int(bar.top() + 1))
        # Rivets in the corners, and end caps.
        painter.setPen(Qt.NoPen)
        for cx, cy in ((bar.left() + 5, bar.top() + 5), (bar.right() - 5, bar.top() + 5),
                       (bar.left() + 5, bar.bottom() - 5), (bar.right() - 5, bar.bottom() - 5)):
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.drawEllipse(QRectF(cx - 2.2, cy - 1.6, 4.4, 4.4))
            painter.setBrush(_RIVET)
            painter.drawEllipse(QRectF(cx - 2, cy - 2, 4, 4))

    def _draw_tile(self, painter, rect, stack, selected, hot, dragging):
        """One bevelled slot tile, tinted by the rarity of what is in it."""
        r = QRectF(rect)
        if selected:
            glow = QPainterPath()
            glow.addRoundedRect(r.adjusted(-4, -4, 4, 4), 5, 5)
            painter.fillPath(glow, _EMBER_GLOW)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        top, bot = _TILE_TOP, _TILE_BOT
        rarity = (stack or {}).get("rarity")
        if rarity and rarity != "common":
            try:
                from ..rpg import items
                rgb = items.RARITY_INFO[items.rarity_of(stack)]["rgb"]
                top = QColor(int(rgb[0] * 0.42), int(rgb[1] * 0.42), int(rgb[2] * 0.42), 250)
                bot = QColor(int(rgb[0] * 0.14), int(rgb[1] * 0.14), int(rgb[2] * 0.14), 250)
            except Exception:
                pass
        g.setColorAt(0.0, top)
        g.setColorAt(1.0, bot)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        painter.fillPath(path, QBrush(g))
        # Bevel: light top-left, dark bottom-right.
        painter.setPen(QPen(_BEVEL_HI, 1))
        painter.drawLine(int(r.left() + 2), int(r.top() + 1), int(r.right() - 2), int(r.top() + 1))
        painter.drawLine(int(r.left() + 1), int(r.top() + 2), int(r.left() + 1), int(r.bottom() - 2))
        painter.setPen(QPen(_BEVEL_LO, 1))
        painter.drawLine(int(r.left() + 2), int(r.bottom() - 1), int(r.right() - 2), int(r.bottom() - 1))
        painter.drawLine(int(r.right() - 1), int(r.top() + 2), int(r.right() - 1), int(r.bottom() - 2))
        edge, width = (_EMBER, 2.2) if selected else (_TILE_EDGE, 1.4)
        if dragging and hot:
            edge, width = _OK, 2.4
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(edge, width))
        painter.drawRoundedRect(r, 3, 3)
        if not selected:
            painter.setPen(QPen(QColor(_BRONZE.red(), _BRONZE.green(), _BRONZE.blue(), 80), 1))
            painter.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 4, 4)
        if hot and not dragging:
            painter.fillRect(rect.adjusted(2, 2, -2, -2), QColor(255, 220, 160, 26))

    def _draw_name(self, painter, stack):
        name = str(stack.get("name") or stack.get("id"))
        try:
            from ..rpg import items
            colour = QColor(*items.RARITY_INFO[items.rarity_of(stack)]["rgb"])
        except Exception:
            colour = QColor(245, 240, 220)
        painter.setFont(self.f_name)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(name) + 24
        top = self.window_rect.y() - 30
        plate = QRect(self.window_rect.center().x() - tw // 2, top, tw, 24)
        painter.setBrush(QColor(14, 12, 11, 200))
        painter.setPen(QPen(QColor(_BRONZE.red(), _BRONZE.green(), _BRONZE.blue(), 150), 1))
        painter.drawRoundedRect(plate, 4, 4)
        painter.setPen(colour)
        painter.drawText(plate, Qt.AlignCenter, name)

    def _draw_item(self, painter, rect, iid, stack, worn):
        pm = None
        try:
            from .. import item_icons
            pm = item_icons.icon_pixmap(iid, stack, rect.width() - 12)
        except Exception:
            pm = None
        if pm is not None and not pm.isNull():
            painter.drawPixmap(rect.x() + (rect.width() - pm.width()) // 2,
                               rect.y() + (rect.height() - pm.height()) // 2, pm)
        else:
            painter.setFont(self.f_number)
            painter.setPen(QColor(232, 226, 210))
            fm = painter.fontMetrics()
            name = fm.elidedText(str(stack.get("name") or iid), Qt.ElideRight, rect.width() - 6)
            painter.drawText(rect.adjusted(3, 3, -3, -3), Qt.AlignCenter, name)
        if worn:
            # Worn or in hand: a bronze corner mark, top left.
            painter.setPen(Qt.NoPen)
            painter.setBrush(_WORN)
            corner = QPainterPath()
            corner.moveTo(rect.x() + 2, rect.y() + 2)
            corner.lineTo(rect.x() + 14, rect.y() + 2)
            corner.lineTo(rect.x() + 2, rect.y() + 14)
            corner.closeSubpath()
            painter.drawPath(corner)
        qty = int(stack.get("qty", 1) or 1)
        if qty > 1:
            painter.setFont(self.f_count)
            painter.setPen(QColor(0, 0, 0, 210))
            painter.drawText(rect.adjusted(0, 0, -3, -1), Qt.AlignRight | Qt.AlignBottom, str(qty))
            painter.setPen(_COUNT)
            painter.drawText(rect.adjusted(0, 0, -4, -2), Qt.AlignRight | Qt.AlignBottom, str(qty))

    # --------------------------------------------------------------- mouse
    def _slot_at(self, p):
        for i, r in enumerate(self._rects):
            # The number under a slot is part of it: clicking it picks the slot.
            if r.adjusted(0, 0, 0, NUMBERS + 2).contains(p):
                return i
        return None

    def hit(self, pos):
        return bool(self._rects) and self.window_rect.contains(pos)

    def handle_mouse_press(self, event):
        if not self.active or not self.hit(event.pos()):
            return False
        i = self._slot_at(event.pos())
        if i is None or event.button() != Qt.LeftButton:
            return True               # the bar itself: swallowed, not a swing
        self.selected = i
        stack = self._slots[i] if i < len(self._slots) else None
        if stack:
            self._press = (QPoint(event.pos()), i)
        return True

    @property
    def mouse_captured(self):
        return self._press is not None

    def handle_mouse_move(self, event, view_w, view_h):
        hits.pointer = (event.x(), event.y())
        if self._press is None:
            return False
        start, i = self._press
        if not self._dragging and (event.pos() - start).manhattanLength() >= DRAG_START:
            stack = self._slots[i] if i < len(self._slots) else None
            if stack:
                self._dragging = True
                drag.start(self, ("strip", i, stack.get("id")))
        return True

    def handle_mouse_release(self, event):
        if self._press is None:
            return False
        _start, i = self._press
        self._press = None
        stack = self._slots[i] if i < len(self._slots) else None
        iid = stack.get("id") if stack else None
        if not self._dragging:
            if _is_weapon(iid):
                # A weapon goes in hand on the click itself.
                hits.queue(lambda session: session.select_strip_slot(i))
                self._last_click = (0.0, None)
                return True
            now = time.monotonic()
            last_t, last_i = self._last_click
            self._last_click = (now, i)
            if iid and last_i == i and now - last_t <= DOUBLE_CLICK:
                hits.queue(lambda session: session.inventory_use(iid))
                self._last_click = (0.0, None)
            return True
        self._dragging = False
        drag.stop(self)
        source = ("strip", i, iid)
        mine = self._slot_at(event.pos())
        target = ("strip", mine) if mine is not None else drag.target_at(
            event.x(), event.y(), exclude=self)
        if target is None and iid and not drag.over_window(event.x(), event.y()):
            # Out over the world: on the floor (one copy of a weapon).
            hits.queue(lambda session: session.drop_item(iid))
            return True
        if target is None or target == ("strip", i) or not iid:
            return True
        if target[0] == "strip":
            self.selected = int(target[1])
        hits.queue(lambda session: session.item_drop(source, target))
        return True

    def handle_body_click(self, x, y):
        return True

    def on_close(self):
        drag.forget(self)
