"""Statistics: one floating window for the pack, character, journal, spells
and map. I and C select their respective tabs; the window keeps its position
and item selection as the player moves between them.

Inventory retains its large cells and Equip / Use / Drop actions. Character
uses InventoryWindow's equipment, pack and sheet, including drag and drop.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QBrush, QPen

from .inventory_window import InventoryWindow, _fit, _item
from . import drag, fonts, hits, screens

#: The big cells of the pack grid, and its shape.
CELL = 96
GAP = 6
COLS = 5
ROWS = 4
#: The screens along the top: (label, open_screen).
TABS = screens.STATISTICS_TABS
PAGES = ("inventory", "skills", "fortune", "alignment")

_STEEL_TOP = QColor(64, 66, 70, 245)
_STEEL_BOT = QColor(30, 31, 34, 245)
_EDGE = QColor(120, 124, 130)
_EDGE_HI = QColor(190, 194, 200)
_TEXT = QColor(226, 228, 232)
_DIM = QColor(130, 134, 140)
_ON = QColor(240, 242, 246)


class PackWindow(InventoryWindow):
    """Shared Statistics window, with a persistent row of top tabs."""

    #: Equip / Use / Drop sit under the grid and Exit along the top.
    DETAIL_BUTTONS = False

    def __init__(self, session, x=40, y=40, viewport=None):
        super().__init__(session, x, y, view="details")
        self.title = "Statistics"
        self.key = "screen:statistics"
        self._body_height = 640
        self.selected_skill = None
        self._skill_nodes = []
        self.screen = None
        self.viewport = viewport
        self.map = None
        self._map_revision = -1
        self.set_screen(getattr(session, "open_screen", "inventory"))

    def set_screen(self, screen):
        if screen not in screens.STATISTICS_SCREENS:
            screen = "inventory"
        changed = screen != self.screen
        self.screen = screen
        self.showing = screen
        if changed:
            self._cells, self._targets, self._buttons = [], [], []
            self._press = self._drag = None
            drag.forget(self)
            if screen == "character":
                self.view = "character"
        if screen != "map":
            if self.map is not None:
                self.map.handle_mouse_release()
            return
        if self.map is None:
            from .map_page import MapPage
            self.map = MapPage(read_data=self._map_data, update=self._update,
                               on_close=self._close_action,
                               on_waypoint=lambda x, z, pick: self._queue(
                                   lambda session: session.toggle_waypoint(x, z, pick)))
        revision = getattr(self.session, "_statistics_map_revision", 0)
        if changed or revision != self._map_revision:
            self.map.open(getattr(self.session, "_statistics_map_focus", None))
            self._map_revision = revision

    def _update(self):
        if self.viewport is not None:
            self.viewport.update()

    def _map_data(self):
        from . import worldmap
        world = worldmap.WORLD
        if not world.ready and not world.building:
            worldmap.ensure_for(self.session.logic, self.viewport)
        return world, worldmap.map_features(self.session)

    # ------------------------------------------------------------- drawing
    def draw_body(self, painter, x, y, w):
        self._cells, self._targets, self._buttons = [], [], []
        self.hover = None
        h = self.content_height()
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        painter.fillRect(QRect(x, y, w, h), QColor(14, 15, 17, 235))
        body = QRect(x, y + 52, w, h - 52)
        if self.screen in ("skills", "fortune", "alignment"):
            page = QRect(x + 10, y + 52, w - 20, h - 62)
            {"skills": self._draw_skills, "fortune": self._draw_fortune,
             "alignment": self._draw_alignment}[self.screen](painter, page)
        elif self.screen == "character":
            self._draw_content(painter, body.x(), body.y(), body.width(), body.height())
        elif self.screen in ("journal", "spells"):
            screens.draw_in_rect(painter, self.session, body.x() + 10, body.y(),
                                 body.width() - 20, body.height() - 10)
            if self.screen == "spells":
                self._cells.extend(screens._SPELL_HITS["cells"])
                self._targets.extend(screens._SPELL_HITS["targets"])
        elif self.screen == "map":
            self._draw_map(painter, body)
        else:
            self._draw_inventory(painter, x, y, w, h)
        self._draw_tabs(painter, QRect(x + 10, y + 8, w - 20, 34))
        self._draw_dragged(painter)
        drag.set_zones(self, self._targets)
        painter.restore()

    def _draw_inventory(self, painter, x, y, w, h):
        grid_w = COLS * (CELL + GAP) + 24
        left = QRect(x + 10, y + 52, grid_w, h - 62)
        right = QRect(left.right() + 12, y + 52, x + w - left.right() - 22, h - 62)
        self._draw_grid(painter, left)
        boxes_h = 110
        details = QRect(right.x(), right.y(), right.width(), right.height() - boxes_h - 10)
        self._draw_details(painter, details)
        self._draw_carried(painter, QRect(right.x(), details.bottom() + 10,
                                          right.width(), boxes_h))

    def _draw_map(self, painter, body):
        keys = getattr(self.session, "sel", {}).get("map", {}).get("keys")
        while keys:
            key = keys.popleft()
            code = {"up": Qt.Key_Up, "down": Qt.Key_Down,
                    "left": Qt.Key_Left, "right": Qt.Key_Right,
                    "pageup": Qt.Key_PageUp, "pagedown": Qt.Key_PageDown,
                    "space": Qt.Key_Space, "home": Qt.Key_Home,
                    "+": Qt.Key_Plus, "=": Qt.Key_Equal,
                    "-": Qt.Key_Minus}.get(key)
            if code is None and len(key) == 1:
                code = ord(key.upper())
            if code is not None:
                self.map.handle_key(code)
        # Re-read features without resetting the player's pan/zoom.
        self.map.refresh()
        self.map.draw(painter, body.width(), body.height(), fonts.dialogue_font_px,
                      fonts.dialogue_font_px, body.x(), body.y())

    def _bevel(self, painter, rect, on=False, enabled=True):
        """A Deus Ex button: a steel plate with a light top edge."""
        g = QLinearGradient(0, rect.y(), 0, rect.bottom())
        g.setColorAt(0.0, QColor(92, 96, 104, 245) if on else _STEEL_TOP)
        g.setColorAt(1.0, _STEEL_BOT)
        painter.setBrush(QBrush(g))
        painter.setPen(QPen(_EDGE_HI if on else _EDGE, 1.4))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QPen(QColor(255, 255, 255, 40 if enabled else 15), 1))
        painter.drawLine(rect.x() + 6, rect.y() + 2, rect.right() - 6, rect.y() + 2)

    def _draw_tabs(self, painter, bar):
        exit_w = 90
        tab_w = (bar.width() - exit_w - 16) // len(TABS)
        painter.setFont(self.f_button)
        for i, (label, screen) in enumerate(TABS):
            r = QRect(bar.x() + i * tab_w, bar.y(), tab_w - 6, bar.height())
            on = screen == self.screen
            self._bevel(painter, r, on)
            painter.setPen(_ON if on else _TEXT)
            _fit(painter, r, Qt.AlignCenter, label)
            if not on:
                self._buttons.append((QRect(r), self._set_page(screen) if screen in PAGES
                                      else self._open(screen)))
        r = QRect(bar.right() - exit_w, bar.y(), exit_w, bar.height())
        self._bevel(painter, r)
        painter.setPen(_TEXT)
        _fit(painter, r, Qt.AlignCenter, "Exit")
        self._buttons.append((QRect(r), self._close_action))

    def _set_page(self, page):
        def act():
            self.set_screen(page)
            self._queue(lambda session: setattr(session, "open_screen", page))
        return act

    def _draw_skills(self, painter, rect):
        from . import hits, skill_tree
        inner = self._panel(painter, rect, "Skills")
        c = self._character()
        if c is None:
            return
        self._skill_nodes = skill_tree.draw(
            painter, inner, c, (self.f_name, self.f_body, self.f_small),
            selected=self.selected_skill, pointer=hits.pointer)
        for r, sid in self._skill_nodes:
            self._buttons.append((QRect(r), self._pick_skill(sid)))

    def _draw_fortune(self, painter, rect):
        """Everything Charisma and Luck are doing for the character, with the
        number and the reason (game.rpg.fortune.benefits)."""
        from ..rpg import fortune
        inner = self._panel(painter, rect, "Fortune")
        c = self._character()
        if c is None:
            return
        painter.setFont(self.f_body)
        painter.setPen(_TEXT)
        _fit(painter, QRect(inner.x(), inner.y(), inner.width(), 24),
             Qt.AlignLeft | Qt.AlignVCenter,
             f"Fortune {fortune.score(c)}  =  (Charisma {c.attrs.get('personality', 40)}"
             f" + Luck {c.attrs.get('luck', 40)}) / 2   ·   the fair of face and the "
             "lucky have an easier road, and here is exactly how.")
        y = inner.y() + 34
        row_h = 40
        for name, value, why, good in fortune.benefits(c):
            if y + row_h > inner.bottom():
                break
            band = QRect(inner.x(), y, inner.width(), row_h - 6)
            painter.fillRect(band, QColor(26, 25, 24, 230))
            mark = (QColor(110, 210, 120) if good else QColor(225, 105, 95)
                    if good is False else _DIM)
            painter.fillRect(QRect(band.x(), band.y(), 5, band.height()), mark)
            painter.setFont(self.f_body)
            painter.setPen(_TEXT)
            _fit(painter, QRect(band.x() + 16, band.y(), int(band.width() * 0.4), band.height()),
                 Qt.AlignLeft | Qt.AlignVCenter, name)
            painter.setPen(mark if good is not None else _TEXT)
            _fit(painter, QRect(band.x() + int(band.width() * 0.4), band.y(),
                                int(band.width() * 0.25), band.height()),
                 Qt.AlignLeft | Qt.AlignVCenter, value)
            painter.setFont(self.f_small)
            painter.setPen(_DIM)
            _fit(painter, QRect(band.x() + int(band.width() * 0.65), band.y(),
                                int(band.width() * 0.35) - 10, band.height()),
                 Qt.AlignLeft | Qt.AlignVCenter, why)
            y += row_h

    def _draw_alignment(self, painter, rect):
        """Where the character stands from Villainous to Saintly, what it is
        doing for and against them, and the deeds that put them there."""
        from ..rpg import alignment
        inner = self._panel(painter, rect, "Alignment")
        c = self._character()
        if c is None:
            return
        value = float(getattr(c, "alignment", 0.0))
        # The scale: red through grey to gold, the tiers marked, you on it.
        bar = QRect(inner.x() + 20, inner.y() + 30, inner.width() - 40, 18)
        g = QLinearGradient(bar.x(), 0, bar.right(), 0)
        g.setColorAt(0.0, QColor(170, 40, 36))
        g.setColorAt(0.5, QColor(96, 96, 100))
        g.setColorAt(1.0, QColor(236, 196, 96))
        painter.setPen(QPen(_EDGE, 1))
        painter.setBrush(QBrush(g))
        painter.drawRoundedRect(bar, 6, 6)
        painter.setFont(self.f_small)
        for lo, name in alignment.TIERS:
            mid = {"Saintly": 87, "Good": 52, "Neutral": 0, "Evil": -52,
                   "Villainous": -87}[name]
            tx = bar.x() + int((mid + 100) / 200.0 * bar.width())
            painter.setPen(_DIM)
            _fit(painter, QRect(tx - 60, bar.y() - 22, 120, 18), Qt.AlignCenter, name)
        mx = bar.x() + int((value + 100) / 200.0 * bar.width())
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QColor(20, 20, 24))
        painter.drawEllipse(mx - 9, bar.center().y() - 9, 18, 18)
        painter.setFont(self.f_name)
        painter.setPen(_ON)
        _fit(painter, QRect(inner.x(), bar.bottom() + 8, inner.width(), 28), Qt.AlignCenter,
             f"{alignment.tier(value)}   ({value:+.0f})")

        # Left: what it means now.  Right: the deeds behind it.
        top = bar.bottom() + 46
        half = (inner.width() - 20) // 2
        for col, (title, lines) in enumerate((
                ("What it means now", [(t, None) for t in alignment.consequences(value)]),
                ("Your deeds", [(f"{e.get('delta', 0):+.1f}   you {e.get('text', '')}",
                                 e.get("delta", 0) >= 0)
                                for e in reversed(getattr(c, "alignment_log", [])[-12:])]
                 or [("Nothing yet. The Vale is watching.", None)]))):
            cx = inner.x() + col * (half + 20)
            painter.setFont(self.f_body)
            painter.setPen(_ON)
            _fit(painter, QRect(cx, top, half, 24), Qt.AlignLeft | Qt.AlignVCenter, title)
            y = top + 30
            painter.setFont(self.f_small)
            for text, good in lines:
                if y + 20 > inner.bottom():
                    break
                painter.setPen(_TEXT if good is None else
                               QColor(120, 210, 130) if good else QColor(230, 110, 100))
                box = QRect(cx, y, half, 40)
                painter.drawText(box, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), text)
                used = painter.fontMetrics().boundingRect(
                    box, int(Qt.AlignLeft | Qt.TextWordWrap), text).height()
                y += max(20, used + 6)

    def _pick_skill(self, sid):
        def act():
            self.selected_skill = sid
        return act

    def _open(self, screen):
        def act():
            self._queue(lambda session, s=screen: setattr(session, "open_screen", s))
        return act

    def handle_mouse_press(self, event):
        if self.active and self.expanded and self._full_rect().contains(event.pos()):
            if event.y() >= self.window_rect.y() + self.HEADER_H:
                button = self._at(self._buttons, event.pos())
                if button is not None and event.button() == Qt.LeftButton:
                    button()
                    return True
                if self.screen == "spells" and self._at(self._cells, event.pos()) is not None:
                    hits.click(event.x(), event.y())
                    return super().handle_mouse_press(event)
                if self.screen in ("journal", "spells"):
                    hits.click(event.x(), event.y())
                    return True
                if self.screen == "map":
                    if (event.button() == Qt.LeftButton and self.map._rect is not None
                            and self.map._rect.contains(event.pos())):
                        self.map.handle_mouse_press(event.pos())
                    return True
        return super().handle_mouse_press(event)

    def handle_body_click(self, x, y):
        from PyQt5.QtCore import QPoint
        button = self._at(self._buttons, QPoint(int(x), int(y)))
        if button is not None:
            button()
        elif self.screen in ("journal", "spells"):
            hits.click(x, y)
        return True

    @property
    def mouse_captured(self):
        return super().mouse_captured or (self.map is not None and self.map._drag is not None)

    def handle_mouse_move(self, event, view_w, view_h):
        if self.screen == "map" and self.map._drag is not None and not self.dragging:
            self.map.handle_mouse_move(event.pos(), event.buttons())
            return True
        return super().handle_mouse_move(event, view_w, view_h)

    def handle_mouse_release(self, event):
        if self.map is not None and self.map._drag is not None:
            self.map.handle_mouse_release()
            return True
        return super().handle_mouse_release(event)

    def handle_wheel(self, event):
        if (self.screen == "map" and self.expanded and self.map._rect is not None
                and self.map._rect.contains(event.pos())):
            self.map.handle_wheel(event.pos(), event.angleDelta().y())

    def _draw_grid(self, painter, rect):
        inner = self._panel(painter, rect, "Inventory")
        c = self._character()
        painter.setFont(self.f_title)
        painter.setPen(_TEXT)
        _fit(painter, QRect(rect.x(), rect.y() + 2, rect.width() - 14, 28),
             Qt.AlignRight | Qt.AlignVCenter, f"Gold   {int(getattr(c, 'gold', 0) or 0)}")
        try:
            stacks = list(self.session.pack_stacks())
        except Exception:
            stacks = []
        per_page = COLS * ROWS
        pages = max(1, int(math.ceil(len(stacks) / float(per_page))))
        self.page = min(self.page, pages - 1)
        shown = stacks[self.page * per_page:(self.page + 1) * per_page]
        gy = inner.y() + 4
        for i in range(per_page):
            col, row = i % COLS, i // COLS
            r = QRect(inner.x() + col * (CELL + GAP), gy + row * (CELL + GAP), CELL, CELL)
            stack = shown[i] if i < len(shown) else None
            iid = stack.get("id") if stack else None
            self._slot_box(painter, QRect(r.x(), r.y(), r.width(), r.height() - 18), iid,
                           target=("pack", None),
                           source=("pack", None, iid) if iid else None, stack=stack)
            # The name along the bottom of the cell, as Deus Ex labels its own.
            label = QRect(r.x(), r.bottom() - 17, r.width(), 17)
            painter.fillRect(label, QColor(20, 21, 23, 230))
            if iid:
                d = _item(iid)
                painter.setFont(self.f_small)
                painter.setPen(_ON if iid == self.selected else _DIM)
                _fit(painter, label.adjusted(3, 0, -3, 0), Qt.AlignCenter,
                     (d.name if d else iid).upper())
        grid = QRect(inner.x(), gy, COLS * (CELL + GAP), ROWS * (CELL + GAP))
        self._targets.append((QRect(grid), ("pack", None)))
        if pages > 1:
            for k, (glyph, step) in enumerate((("▲", -1), ("▼", 1))):
                r = QRect(grid.right() + 2, gy + k * 40, 16, 34)
                painter.setFont(self.f_body)
                painter.setPen(_TEXT)
                painter.drawText(r, Qt.AlignCenter, glyph)
                self._buttons.append((QRect(r), self._turn_page(step, pages)))
        self._draw_actions(painter, QRect(inner.x(), grid.bottom() + 10, grid.width(), 34))

    def _draw_actions(self, painter, row):
        """Equip / Use / Drop, for the item picked (greyed when they do not apply)."""
        d = _item(self.selected) if self.selected else None
        worn = self.selected in set(self._equipment().values()) if self.selected else False
        wearable = d is not None and (bool(d.get("slot")) or d.category == "weapon")
        usable = d is not None and not wearable and d.category in (
            "potion", "ingredient", "book", "scroll", "misc")
        actions = (("Unequip" if worn else "Equip", wearable, self._use(self.selected)),
                   ("Use", usable, self._use(self.selected)),
                   ("Drop", d is not None, self._drop(self.selected)))
        bw = (row.width() - 2 * 8) // 3
        painter.setFont(self.f_button)
        for i, (label, enabled, act) in enumerate(actions):
            r = QRect(row.x() + i * (bw + 8), row.y(), bw, row.height())
            self._bevel(painter, r, enabled=enabled)
            painter.setPen(_TEXT if enabled else QColor(80, 82, 86))
            _fit(painter, r, Qt.AlignCenter, label)
            if enabled:
                self._buttons.append((QRect(r), act))

    def _drop(self, iid):
        def act():
            if iid:
                self._queue(lambda session: session.drop_item(iid))
                self.selected = None
        return act

    def _draw_carried(self, painter, rect):
        """Two small boxes: the keys carried, and the ammunition, counted."""
        c = self._character()
        keys, ammo = 0, []
        for s in (getattr(c, "inventory", []) or []) if c else []:
            d = _item(s.get("id"))
            if d is None:
                continue
            if d.category == "key":
                keys += int(s.get("qty", 1) or 1)
            elif d.category == "ammo":
                ammo.append(f"{d.name}: {int(s.get('qty', 1) or 1)}")
        half = (rect.width() - 10) // 2
        for k, (title, body) in enumerate((("Keys", f"{keys} carried"),
                                           ("Ammunition", "\n".join(ammo) or "None"))):
            r = QRect(rect.x() + k * (half + 10), rect.y(), half, rect.height())
            self._bevel(painter, r)
            painter.setFont(self.f_body)
            painter.setPen(_ON)
            _fit(painter, QRect(r.x() + 10, r.y() + 6, r.width() - 20, 22),
                 Qt.AlignLeft | Qt.AlignVCenter, title)
            painter.setFont(self.f_small)
            painter.setPen(_TEXT)
            painter.drawText(QRect(r.x() + 10, r.y() + 30, r.width() - 20, r.height() - 36),
                             int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), body)
