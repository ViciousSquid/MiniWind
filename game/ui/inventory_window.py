"""
The character window: a large floating window in the spirit of Baldur's Gate.

Opened with **C**. Three panels side by side:

* **Equipment** — a paperdoll of the player (their own head over a body
  silhouette) ringed by the worn slots: head, amulet, chest, hands, ring,
  shield (or a second one-handed weapon: dual wielding), legs, feet and the
  torch hand; below it the four **Quick Weapons**
  (the one in hand is lit) and the **Quiver**. Keys 1-9 pick the strip.
* **Pack** — everything else carried, as a grid of large icons with the stack
  count in the corner, filtered by category tabs along the top (All, Weapons,
  Armour, Potions, Food & Herbs, Other).
* **Details** — the item under the pointer or last clicked: its name in its
  rarity colour, what it is, what it does, its value and weight, and buttons
  to Use / Equip, Assign it to a quick slot, or leave — or the character sheet.

Everything moves by **drag and drop**. Only what fits goes in a slot: a
weapon in a quick slot, a helmet on the head, arrows in the quiver; anything
else springs back with a word of why. Dragging something worn or slotted back
to the pack takes it off. A double-click uses or equips. Things also drag
to and from the inventory strip (I) and an open chest or body
(:mod:`game.ui.drag`).

Painting and the mouse belong to the UI thread; the character belongs to the
game tick. So every change is *queued* through :mod:`game.ui.hits` and carried
out by the tick, in order with the keys, exactly as a screen's buttons are.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                         QRadialGradient, QPainterPath, QPen, QPixmap)

from engine.floating_windows import FloatingWindow

from . import drag, hits
from . import theme as T

# -- palette: dressed stone and old gilt ------------------------------------
_STONE = QColor(46, 45, 43, 245)
_STONE_DARK = QColor(30, 29, 28, 250)
_STONE_EDGE = QColor(84, 80, 72)
_SLOT = QColor(22, 21, 20, 235)
_SLOT_EDGE = QColor(110, 98, 72)
_SLOT_HOT = QColor(240, 200, 110)
_OK = QColor(110, 220, 130)
_NO = QColor(210, 80, 70)
_INK = QColor(232, 226, 210)
_DIM = QColor(150, 145, 132)
_GOLD = QColor(240, 200, 110)
#: A weapon dragged over the shield slot: the off hand, dual wielding.
_OFF_HAND = QColor(110, 190, 230)
_OFF_HAND_FILL = QColor(44, 70, 86)

#: The worn slots around the paperdoll: (slot id, label, x, y) with x, y the
#: slot's centre as fractions of the paperdoll panel.
PAPERDOLL = (
    ("head", "Head", 0.14, 0.10),
    ("chest", "Chest", 0.14, 0.33),
    ("hands", "Hands", 0.14, 0.56),
    ("legs", "Legs", 0.14, 0.79),
    ("amulet", "Amulet", 0.86, 0.10),
    ("ring", "Ring", 0.86, 0.33),
    ("shield", "Shield", 0.86, 0.56),
    ("light", "Torch", 0.86, 0.79),
    ("weapon", "Weapon", 0.30, 0.93),
    ("feet", "Feet", 0.70, 0.93),
)

#: Pack tabs: (label, categories shown; None = everything).
TABS = (
    ("All", None),
    ("Weapons", ("weapon", "ammo")),
    ("Armour", ("armour", "light")),
    ("Potions", ("potion",)),
    ("Herbs", ("ingredient", "food")),
    ("Other", ("book", "misc", "quest", "key", "gold")),
)
#: The extra tab shown only to a character who knows any spells.
SPELLS_TAB = ("Spells", "spells")

CELL = 58
GAP = 6
GRID_COLS = 6
GRID_ROWS = 4                   # 24 cells: the pack's 20 slots and a satchel's 4
DOUBLE_CLICK = 0.35
DRAG_START = 5


def _fit(painter, rect, flags, text, min_px=8):
    """Draw one line of *text* in *rect* without spilling out of it: the
    painter's font is shrunk until the text fits (no smaller than *min_px*),
    and anything still too wide is elided."""
    text = str(text)
    font = painter.font()
    fm = painter.fontMetrics()
    avail = max(1, rect.width())
    if fm.horizontalAdvance(text) > avail or fm.height() > rect.height() + 4:
        px = font.pixelSize() if font.pixelSize() > 0 else int(round(font.pointSizeF() * 4 / 3))
        small = QFont(font)
        while px > min_px:
            px -= 1
            small.setPixelSize(px)
            m = QFontMetrics(small)
            if m.horizontalAdvance(text) <= avail and m.height() <= rect.height() + 4:
                break
        painter.save()
        painter.setFont(small)
        shown = QFontMetrics(small).elidedText(text, Qt.ElideRight, avail)
        painter.drawText(rect, flags, shown)
        painter.restore()
        return
    painter.drawText(rect, flags, text)


def _item(iid):
    try:
        from ..rpg import items
        return items.get(iid)
    except Exception:
        return None


def slot_of(item_def):
    """The equipment slot an item is worn in, or None (not wearable)."""
    if item_def is None:
        return None
    slot = item_def.get("slot")
    if slot:
        return str(slot)
    cat = item_def.category
    if cat == "ammo":
        return "ammo"
    if cat == "weapon":
        return "weapon"
    return None


def fits(target, item_def) -> bool:
    """Whether an item may be dropped on *target* (``("equip", slot)``,
    ``("quick", i)``, ``("pack", None)``)."""
    kind, key = target
    if kind == "pack":
        return True
    if item_def is None:
        return False
    if kind == "quick":
        return item_def.category == "weapon"
    if kind == "equip":
        if key == "shield" and item_def.category == "weapon":
            # The off hand: a second one-handed weapon is dual wielding.
            from ..rpg import equipment
            return equipment.can_dual_wield(item_def)
        return slot_of(item_def) == key
    return False


def why_not(target, item_def) -> str:
    kind, key = target
    name = item_def.name if item_def is not None else "That"
    if kind == "quick":
        return f"{name} isn't a weapon: only weapons go in a quick slot."
    if kind == "equip" and key == "shield" and item_def is not None \
            and item_def.category == "weapon":
        from ..rpg import equipment
        if equipment.is_two_handed(item_def):
            return f"{name} needs both hands."
        return f"{name} can't be held in the off hand."
    if kind == "equip":
        where = {"ammo": "the quiver"}.get(key, f"the {key} slot")
        return f"{name} doesn't go in {where}."
    return f"{name} can't go there."


def placeable(target, source) -> bool:
    """Whether a click on *target* puts the picked-up *source* there: it fits,
    and it is a move -- not the slot it is already in, nor one pack slot to
    another (the pack keeps its own order)."""
    if target is None or source is None:
        return False
    if tuple(target[:2]) == tuple(source[:2]):
        return False
    if target[0] == "pack" and source[0] == "pack":
        return False
    if target[0] == "strip":
        return True
    return source_fits(target, source)


def source_fits(target, source):
    if source[0] in ("spell", "spell_hand"):
        return (target[0] == "hand" or target in (("equip", "weapon"), ("equip", "shield"))
                or source[0] == "spell_hand" and target[0] in ("pack", "spells"))
    return fits(target, _item(source[2]))


class InventoryWindow(FloatingWindow):
    """The Baldur's Gate-style inventory (see the module docstring)."""

    wants_cursor = True

    #: What the right-hand panel shows: the item under the pointer, or the
    #: character sheet (the C key opens the window on that).
    VIEWS = (("details", "Details"), ("character", "Character"))
    #: Whether the details panel carries its own Equip / Assign / Exit row (a
    #: window with buttons of its own turns it off).
    DETAIL_BUTTONS = True

    def __init__(self, session, x=40, y=40, view="details"):
        width = 1120
        super().__init__("Character", x, y, width, body_height=640)
        self.session = session
        self.key = f"screen:{'inventory' if view == 'details' else 'character'}"
        self.view = view if view in dict(self.VIEWS) else "details"
        self.tab = 0
        self.page = 0
        self.selected = None            # item id shown in Details
        self.selected_spell = None      # or a spell id, from the Spells tab
        self.hover = None               # item id under the pointer
        #: (QRect, source) for every item cell drawn this frame, where source
        #: is ("pack"|"equip"|"quick", key, item id).
        self._cells = []
        #: (QRect, target) for every drop target drawn this frame.
        self._targets = []
        #: (QRect, callable) for buttons and tabs.
        self._buttons = []
        self._press = None              # (QPoint, source) of a pending press
        self._drag = None               # source being dragged
        self._last_click = (0.0, None)
        #: This press put a picked-up item back down (its release is no pick).
        self._unpicked = False
        self._pad_point = None
        self._icons = {}
        self._doll = {}
        from . import fonts
        # One typeface throughout, the conversation's own (MedievalSharp,
        # game/ui/fonts.py): it has a single upright weight, so nothing here
        # asks it for bold or italic.
        # Sized in pixels, as the layout is: point sizes grow with the
        # screen's DPI and would spill out of every box on a high-DPI display.
        self.f_body = fonts.dialogue_font_px(15)
        self.f_small = fonts.dialogue_font_px(12)
        self.f_count = fonts.dialogue_font_px(13)
        self.f_title = fonts.dialogue_font_px(21)
        self.f_name = fonts.dialogue_font_px(20)
        self.f_button = fonts.dialogue_font_px(16)
        # The window's own title bar too, rather than the chrome's Arial.
        self.title_font = fonts.dialogue_font_px(13)

    # ------------------------------------------------------------ the model
    def _character(self):
        try:
            return self.session.game.character
        except Exception:
            return None

    def _equipment(self):
        c = self._character()
        return dict(getattr(c, "equipment", {}) or {}) if c else {}

    def _quick(self):
        try:
            return self.session.quick_weapon_slots()
        except Exception:
            return [None] * 4

    def _pack(self):
        """What the pack holds (each copy of a weapon in a slot of its own,
        nothing worn or in hand), filtered by the open tab."""
        c = self._character()
        if c is None:
            return []
        cats = self._tabs()[min(self.tab, len(self._tabs()) - 1)][1]
        if cats == "spells":
            return []
        try:
            stacks = list(self.session.pack_stacks())
        except Exception:
            stacks = []
        out = []
        for stack in stacks:
            iid = stack.get("id")
            d = _item(iid)
            cat = d.category if d is not None else str(stack.get("type", "misc"))
            if cats is not None and cat not in cats:
                continue
            out.append(stack)
        return out

    def _known_spells(self):
        c = self._character()
        try:
            from ..rpg import magic
        except Exception:
            return []
        return [(sid, magic.get(sid)) for sid in (getattr(c, "known_spells", []) or [])
                if magic.get(sid) is not None] if c else []

    def _tabs(self):
        """The pack's tabs: the item categories, and Spells for a caster."""
        return TABS + ((SPELLS_TAB,) if self._known_spells() else ())

    def _stack(self, iid):
        c = self._character()
        for s in (getattr(c, "inventory", []) or []) if c else []:
            if s.get("id") == iid:
                return s
        return None

    def _icon(self, iid, size):
        key = (iid, size)
        if key not in self._icons:
            pm = None
            try:
                from .. import item_icons
                pm = item_icons.icon_pixmap(iid, self._stack(iid), size)
            except Exception:
                pm = None
            self._icons[key] = pm
        return self._icons[key]

    # ------------------------------------------------------------- drawing
    def content_height(self):
        return self._body_height

    def draw_body(self, painter, x, y, w):
        self._draw_content(painter, x, y, w, self.content_height())

    def _draw_content(self, painter, x, y, w, h):
        """Equipment, pack and sheet within the supplied body rectangle."""
        self._cells, self._targets, self._buttons = [], [], []
        self.hover = None
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        painter.fillRect(QRect(x, y, w, h), _STONE_DARK)
        left = QRect(x + 10, y + 10, 330, h - 20)
        mid = QRect(left.right() + 12, y + 10, GRID_COLS * (CELL + GAP) + 26, h - 20)
        right = QRect(mid.right() + 12, y + 10, x + w - mid.right() - 22, h - 20)
        self._draw_equipment(painter, left)
        self._draw_pack(painter, mid)
        # The right-hand panel is tabbed: the item under the pointer
        # (Details), or the character's health, armour, XP and attributes.
        tab_h = 28
        panel = QRect(right.x(), right.y() + tab_h, right.width(), right.height() - tab_h)
        if self.view == "character":
            self._draw_character_sheet(painter, panel)
        else:
            self._draw_details(painter, panel)
        self._draw_view_tabs(painter, right.x() + 8, right.y(), right.width() - 16, tab_h)
        self._draw_dragged(painter)
        # Its slots and pack take drops from the strip and the container
        # screen too (game/ui/drag.py).
        drag.set_zones(self, self._targets)
        self._draw_pad_focus(painter)
        painter.restore()

    def _draw_view_tabs(self, painter, x, y, w, h):
        """File-folder tabs along the top of the right-hand panel: the one
        open joins the panel below it, the others sit behind."""
        tab_w = (w - 4 * (len(self.VIEWS) - 1)) // len(self.VIEWS)
        for k, (key, label) in enumerate(self.VIEWS):
            r = QRect(x + k * (tab_w + 4), y + (0 if key == self.view else 4),
                      tab_w, h - (0 if key == self.view else 4))
            on = key == self.view
            hot = hits.hovered(r)
            painter.save()
            # Rounded on top only: draw it taller and clip off the bottom.
            painter.setClipRect(QRect(r.x() - 2, r.y() - 2, r.width() + 4,
                                      r.height() + (3 if on else 2)))
            painter.setBrush(QColor(58, 56, 52, 250) if on else
                             QColor(54, 48, 40, 240) if hot else QColor(32, 30, 28, 240))
            painter.setPen(QPen(_GOLD if on else _SLOT_EDGE, 1.2))
            painter.drawRoundedRect(r.adjusted(0, 0, 0, 10), 6, 6)
            painter.restore()
            painter.setFont(self.f_button)
            painter.setPen(_GOLD if on else (_INK if hot else _DIM))
            _fit(painter, r, Qt.AlignCenter, label)
            self._buttons.append((QRect(r), self._set_view(key)))

    def _panel(self, painter, rect, title):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 6, 6)
        g = QLinearGradient(0, rect.y(), 0, rect.bottom())
        g.setColorAt(0.0, QColor(58, 56, 52, 250))
        g.setColorAt(1.0, QColor(38, 37, 35, 250))
        painter.fillPath(path, QBrush(g))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_STONE_EDGE, 2))
        painter.drawPath(path)
        bar = QRect(rect.x() + 2, rect.y() + 2, rect.width() - 4, 28)
        painter.fillRect(bar, QColor(26, 25, 24, 230))
        painter.setPen(QPen(_SLOT_EDGE, 1))
        painter.drawLine(bar.bottomLeft(), bar.bottomRight())
        painter.setFont(self.f_title)
        painter.setPen(_GOLD)
        _fit(painter, bar.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, title)
        return QRect(rect.x() + 10, bar.bottom() + 8, rect.width() - 20,
                     rect.bottom() - bar.bottom() - 16)

    def _locked_cell(self, painter, rect):
        """A pack slot the player does not have: a satchel adds them."""
        painter.setBrush(QColor(14, 13, 12, 200))
        painter.setPen(QPen(QColor(44, 40, 36), 1, Qt.DashLine))
        painter.drawRoundedRect(rect, 4, 4)

    def _slot_box(self, painter, rect, iid, target=None, source=None, label=None,
                  lit=False, number=None, stack=None):
        """One item slot: a sunken frame, its icon and count, its drop state.
        *stack* is what the slot shows when it is not the whole carried stack
        (one copy of a weapon carried twice)."""
        # Dragged, or picked up by a click: the slots it fits light up.
        dragging = self._drag or drag.offered()
        drag_def = _item(dragging[2]) if dragging else None
        border = _SLOT_EDGE
        fill = _SLOT
        if dragging and target is not None:
            ok = source_fits(target, dragging)
            border = _OK if ok else QColor(70, 60, 55)
            if ok and target == ("equip", "shield") and drag_def is not None \
                    and drag_def.category == "weapon":
                # The off hand takes a second weapon (dual wielding): lit as
                # a drop too, in its own tint, so it reads as the other hand.
                border, fill = _OFF_HAND, _OFF_HAND_FILL
        elif lit:
            border = _GOLD
        if iid and (iid == self.selected):
            border = _SLOT_HOT
        painter.setBrush(fill)
        painter.setPen(QPen(border, 2 if (lit or dragging) else 1.4))
        painter.drawRoundedRect(rect, 4, 4)
        if hits.hovered(rect):
            painter.fillRect(rect.adjusted(2, 2, -2, -2), QColor(255, 230, 170, 26))
            if iid:
                self.hover = ("item", iid)
        dragging_this = self._drag is not None and source is not None \
            and self._drag[:2] == source[:2]
        if iid and not dragging_this:
            size = rect.width() - 10
            pm = self._icon(iid, size)
            if pm is not None and not pm.isNull():
                painter.drawPixmap(rect.x() + (rect.width() - pm.width()) // 2,
                                   rect.y() + (rect.height() - pm.height()) // 2, pm)
            else:
                d = _item(iid)
                painter.setFont(self.f_small)
                painter.setPen(_INK)
                painter.drawText(rect.adjusted(3, 3, -3, -3), Qt.AlignCenter | Qt.TextWordWrap,
                                 d.name if d else iid)
            stack = stack if stack is not None else self._stack(iid)
            qty = int(stack.get("qty", 1)) if stack else 1
            if qty > 1:
                painter.setFont(self.f_count)
                painter.setPen(QColor(0, 0, 0, 200))
                painter.drawText(rect.adjusted(0, 0, -3, -1), Qt.AlignRight | Qt.AlignBottom, str(qty))
                painter.setPen(QColor(255, 236, 140))
                painter.drawText(rect.adjusted(0, 0, -4, -2), Qt.AlignRight | Qt.AlignBottom, str(qty))
            rarity = (stack or {}).get("rarity")
            if rarity and rarity != "common":
                try:
                    from ..rpg import items
                    rgb = items.RARITY_INFO[items.rarity_of(stack)]["rgb"]
                    painter.setPen(QPen(QColor(*rgb), 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 3, 3)
                except Exception:
                    pass
        elif label and not iid:
            painter.setFont(self.f_small)
            painter.setPen(QColor(120, 112, 98))
            _fit(painter, rect, Qt.AlignCenter, label)
        if number is not None:
            painter.setFont(self.f_count)
            painter.setPen(_GOLD if lit else _DIM)
            painter.drawText(rect.adjusted(4, 2, 0, 0), Qt.AlignLeft | Qt.AlignTop, str(number))
        if target is not None:
            self._targets.append((QRect(rect), target))
        if iid and source is not None:
            self._cells.append((QRect(rect), source))

    def _draw_paperdoll_figure(self, painter, area):
        """The player as MiniWind draws everyone: a head, and nothing else
        (there are no bodies in MiniWind). Faint spokes run from it to the
        slots round it."""
        cx = area.center().x()
        cy = area.y() + int(area.height() * 0.45)
        size = 150
        painter.setPen(QPen(QColor(90, 84, 72, 110), 1, Qt.DashLine))
        for _slot, _label, fx, fy in PAPERDOLL:
            painter.drawLine(cx, cy, int(area.x() + fx * area.width()),
                             int(area.y() + fy * area.height()))
        # A soft pool of light under the head, so it does not float on stone.
        glow = QRadialGradient(float(cx), float(cy), size * 0.62)
        glow.setColorAt(0.0, QColor(120, 104, 80, 90))
        glow.setColorAt(1.0, QColor(120, 104, 80, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPoint(cx, cy), int(size * 0.62), int(size * 0.62))
        c = self._character()
        head = str(getattr(c, "head", "") or "")
        # The eyes follow the pointer where the head's eyes can be found
        # (game/ui/eye_rig.py); otherwise the head is drawn as it is.
        try:
            from ..rpg import heads
            from . import eye_rig
            import os
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            rig = eye_rig.rig_for(os.path.join(root, heads.any_head_path(head)), size)
        except Exception:
            rig = None
        if rig is not None:
            eye_rig.draw(painter, rig, cx - rig.head.width() // 2,
                         cy - rig.head.height() // 2, hits.pointer)
            return
        pm = self._doll.get(head)
        if pm is None:
            try:
                from ..rpg import heads
                import os
                path = heads.any_head_path(head)
                root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                pm = QPixmap(os.path.join(root, path))
                if not pm.isNull():
                    pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pm = QPixmap()
            self._doll[head] = pm
        if pm is not None and not pm.isNull():
            painter.drawPixmap(cx - pm.width() // 2, cy - pm.height() // 2, pm)

    def _draw_equipment(self, painter, rect):
        c = self._character()
        inner = self._panel(painter, rect, getattr(c, "name", "Adventurer") if c else "Adventurer")
        if c is not None:
            try:
                from ..rpg import classes
                sub = f"Level {c.level} {classes.get(c.class_id).label}"
            except Exception:
                sub = f"Level {getattr(c, 'level', 1)}"
            painter.setFont(self.f_small)
            painter.setPen(_DIM)
            _fit(painter, QRect(inner.x(), inner.y() - 4, inner.width(), 14),
                             Qt.AlignRight | Qt.AlignVCenter, sub)
        doll = QRect(inner.x(), inner.y() + 12, inner.width(), 330)
        self._draw_paperdoll_figure(painter, doll)
        worn = self._equipment()
        s = 50
        for slot, label, fx, fy in PAPERDOLL:
            r = QRect(int(doll.x() + fx * doll.width() - s / 2),
                      int(doll.y() + fy * doll.height() - s / 2), s, s)
            iid = worn.get(slot)
            from ..rpg import equipment as eq
            spell = eq.hand_spell(c, "off" if slot == "shield" else "main") \
                if c is not None and slot in ("weapon", "shield") else None
            self._slot_box(painter, r, iid, target=("equip", slot),
                           source=("equip", slot, iid) if iid else None, label=label)
            if spell is not None:
                self._draw_spell_slot(painter, r, spell,
                                      ("spell_hand", "off" if slot == "shield" else "main", spell.id))
        # Quick weapons and quiver.
        y = doll.bottom() + 22
        painter.setFont(self.f_body)
        painter.setPen(_GOLD)
        painter.drawText(inner.x(), y, "Quick Weapons")
        painter.drawText(inner.x() + 4 * (s + 8) + 14, y, "Quiver")
        in_hand = worn.get("weapon")
        quick = self._quick()
        for i in range(4):
            r = QRect(inner.x() + i * (s + 8), y + 8, s, s)
            entry = quick[i] if i < len(quick) else None
            iid = entry["id"] if entry else None
            self._slot_box(painter, r, iid, target=("quick", i),
                           source=("quick", i, iid) if iid else None,
                           lit=bool(iid) and iid == in_hand, number=i + 1)
        rq = QRect(inner.x() + 4 * (s + 8) + 14, y + 8, s, s)
        ammo = worn.get("ammo")
        self._slot_box(painter, rq, ammo, target=("equip", "ammo"),
                       source=("equip", "ammo", ammo) if ammo else None, label="Arrows")
        # Known spells can be dragged straight onto either hand.
        y2 = y + s + 34
        painter.setFont(self.f_body)
        painter.setPen(_GOLD)
        painter.drawText(inner.x(), y2, "Quick Spells")
        self._draw_spells(painter, inner.x(), y2 + 8, inner.width())
        # Footer: armour, gold, load.
        try:
            from ..rpg import equipment as eq, inventory as inv
            ar = int(eq.armour_class(c))
            weight = eq.armor_class_worn(c)
            load = inv.total_weight(c.inventory)
            cap = c.carry_capacity
            gold = int(c.gold)
        except Exception:
            ar, weight, load, cap, gold = 10, "none", 0.0, 0.0, 0
        foot = QRect(inner.x(), inner.bottom() - 20, inner.width(), 20)
        # Three cells, so the armour, the purse and the load never run together.
        third = foot.width() // 3
        f_left = QRect(foot.x(), foot.y(), third + 16, foot.height())
        f_mid = QRect(foot.x() + third + 16, foot.y(), third - 16, foot.height())
        f_right = QRect(foot.x() + 2 * third, foot.y(), foot.width() - 2 * third, foot.height())
        painter.setFont(self.f_body)
        painter.setPen(_INK)
        _fit(painter, f_left, Qt.AlignLeft | Qt.AlignVCenter,
             "Unarmoured" if weight == "none" else f"{weight.title()} armour")
        self._draw_ac_badge(painter, QPoint(inner.x() + int(inner.width() * 0.31),
                                            inner.y() + 40), ar)
        painter.setPen(_GOLD)
        _fit(painter, f_mid, Qt.AlignHCenter | Qt.AlignVCenter, f"{gold} gold")
        painter.setPen(_NO if cap and load > cap else _INK)
        _fit(painter, f_right, Qt.AlignRight | Qt.AlignVCenter, f"{load:.0f} / {cap:.0f} wt")

    def _draw_ac_badge(self, painter, centre, ac):
        """Armour Class on a little heater shield, top left of the paperdoll."""
        cx, cy = centre.x(), centre.y()
        path = QPainterPath()
        path.moveTo(cx - 20, cy - 22)
        path.lineTo(cx + 20, cy - 22)
        path.lineTo(cx + 20, cy + 2)
        path.quadTo(cx + 18, cy + 18, cx, cy + 26)
        path.quadTo(cx - 18, cy + 18, cx - 20, cy + 2)
        path.closeSubpath()
        painter.setBrush(QColor(52, 46, 36, 245))
        painter.setPen(QPen(_GOLD, 1.6))
        painter.drawPath(path)
        painter.setFont(self.f_title)
        painter.setPen(QColor(255, 236, 170))
        painter.drawText(QRect(cx - 20, cy - 20, 40, 30), Qt.AlignCenter, str(ac))
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        painter.drawText(QRect(cx - 20, cy + 8, 40, 14), Qt.AlignCenter, "AC")

    def _draw_spells(self, painter, x, y, w):
        c = self._character()
        try:
            from ..rpg import magic
            spells = [(sid, magic.get(sid)) for sid in (getattr(c, "known_spells", []) or [])]
        except Exception:
            spells = []
        spells = [(sid, sp) for sid, sp in spells if sp is not None][:6]
        if not spells:
            painter.setFont(self.f_small)
            painter.setPen(_DIM)
            painter.drawText(x, y + 16, "You know no spells.")
            return
        s = 40
        active = getattr(c, "active_spell", None)
        for i, (sid, sp) in enumerate(spells):
            r = QRect(x + i * (s + 8), y, s, s)
            col = QColor(*sp.color)
            painter.setBrush(_SLOT)
            painter.setPen(QPen(_GOLD if sid == active else _SLOT_EDGE, 2 if sid == active else 1))
            painter.drawRoundedRect(r, 4, 4)
            if not self._draw_spell_art(painter, r.adjusted(4, 4, -4, -4), sid):
                painter.setBrush(QBrush(col))
                painter.setPen(QPen(col.darker(160), 1))
                painter.drawEllipse(r.adjusted(9, 9, -9, -9))
            if hits.hovered(r):
                self.hover = ("spell", sid)
            self._cells.append((QRect(r), ("spell", None, sid)))

    def _draw_spell_art(self, painter, rect, spell_id) -> bool:
        """The spell's picture (assets/sprites/spells) centred in *rect*;
        False when it has none, for the caller to draw its orb."""
        try:
            from .. import item_icons
            pm = item_icons.spell_pixmap(spell_id, min(rect.width(), rect.height()))
        except Exception:
            pm = None
        if pm is None or pm.isNull():
            return False
        painter.drawPixmap(rect.x() + (rect.width() - pm.width()) // 2,
                           rect.y() + (rect.height() - pm.height()) // 2, pm)
        return True

    def _draw_spell_slot(self, painter, rect, spell, source):
        painter.fillRect(rect.adjusted(2, 2, -2, -2), _SLOT)
        if not self._draw_spell_art(painter, rect.adjusted(6, 3, -6, -19), spell.id):
            painter.setBrush(QColor(*spell.color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(rect.adjusted(12, 5, -12, -19))
        painter.setFont(self.f_small)
        painter.setPen(_INK)
        _fit(painter, rect.adjusted(3, rect.height() - 18, -3, -2),
             Qt.AlignCenter, spell.name)
        self._cells.append((QRect(rect), source))

    def _draw_pack(self, painter, rect):
        inner = self._panel(painter, rect, "Pack")
        # Category tabs.
        tabs = self._tabs()
        self.tab = min(self.tab, len(tabs) - 1)
        tw = (inner.width()) // len(tabs)
        for i, (label, _cats) in enumerate(tabs):
            r = QRect(inner.x() + i * tw, inner.y(), tw - 4, 26)
            on = i == self.tab
            painter.setBrush(QColor(78, 70, 52, 240) if on else QColor(34, 33, 31, 240))
            painter.setPen(QPen(_GOLD if on else _SLOT_EDGE, 1.2))
            painter.drawRoundedRect(r, 4, 4)
            painter.setFont(self.f_small)
            painter.setPen(_GOLD if on else _DIM)
            _fit(painter, r, Qt.AlignCenter, label)
            self._buttons.append((QRect(r), self._set_tab(i)))
        if tabs[self.tab][1] == "spells":
            self._draw_spell_grid(painter, inner)
            return
        pack = self._pack()
        try:
            cap, used = self.session.pack_capacity(), self.session.pack_used()
        except Exception:
            cap, used = GRID_COLS * GRID_ROWS, len(pack)
        everything = tabs[self.tab][1] is None
        per_page = GRID_COLS * GRID_ROWS
        pages = max(1, int(math.ceil(len(pack) / float(per_page))))
        self.page = min(self.page, pages - 1)
        shown = pack[self.page * per_page:(self.page + 1) * per_page]
        gy = inner.y() + 36
        grid = QRect(inner.x(), gy, GRID_COLS * (CELL + GAP), GRID_ROWS * (CELL + GAP))
        for i in range(per_page):
            col, row = i % GRID_COLS, i // GRID_COLS
            r = QRect(grid.x() + col * (CELL + GAP), gy + row * (CELL + GAP), CELL, CELL)
            iid = shown[i]["id"] if i < len(shown) else None
            if not iid and everything and self.page * per_page + i >= cap:
                self._locked_cell(painter, r)    # a slot only a satchel gives
                continue
            self._slot_box(painter, r, iid, target=("pack", None),
                           source=("pack", None, iid) if iid else None,
                           stack=shown[i] if iid else None)
        # How full the pack is, under the grid.
        painter.setFont(self.f_small)
        painter.setPen(_NO if used >= cap else _DIM)
        _fit(painter, QRect(grid.x(), grid.bottom() + 4, grid.width() - 4, 16),
             Qt.AlignRight | Qt.AlignVCenter, f"{used} / {cap} slots")
        # The whole grid takes a drop, not just its cells.
        self._targets.append((QRect(grid), ("pack", None)))
        # Page arrows.
        if pages > 1:
            for k, (glyph, step) in enumerate((("▲", -1), ("▼", 1))):
                r = QRect(grid.right() + 4, gy + k * 40, 16, 34)
                painter.setFont(self.f_body)
                painter.setPen(_GOLD)
                painter.drawText(r, Qt.AlignCenter, glyph)
                self._buttons.append((QRect(r), self._turn_page(step, pages)))
            painter.setFont(self.f_small)
            painter.setPen(_DIM)
            _fit(painter, QRect(grid.x(), grid.bottom() + 4, grid.width(), 16),
                             Qt.AlignLeft | Qt.AlignVCenter, f"page {self.page + 1} of {pages}")
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        _fit(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
                         Qt.AlignCenter,
                         "Drag to equip  ·  out of the window to drop  ·  double-click to use")

    def _draw_spell_grid(self, painter, inner):
        """The Spells tab: every spell known, as an orb in its colour with its
        magicka cost in the corner. Click to see it, double-click to ready it."""
        c = self._character()
        active = getattr(c, "active_spell", None)
        gy = inner.y() + 36
        for i, (sid, sp) in enumerate(self._known_spells()[:GRID_COLS * GRID_ROWS]):
            col, row = i % GRID_COLS, i // GRID_COLS
            r = QRect(inner.x() + col * (CELL + GAP), gy + row * (CELL + GAP), CELL, CELL)
            chosen = sid == self.selected_spell
            painter.setBrush(_SLOT)
            painter.setPen(QPen(_SLOT_HOT if chosen else _GOLD if sid == active else _SLOT_EDGE,
                                2 if (chosen or sid == active) else 1.4))
            painter.drawRoundedRect(r, 4, 4)
            if not self._draw_spell_art(painter, r.adjusted(6, 6, -6, -6), sid):
                col_ = QColor(*sp.color)
                glow = QColor(col_)
                glow.setAlpha(70)
                painter.setBrush(glow)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(r.adjusted(6, 6, -6, -6))
                painter.setBrush(col_)
                painter.setPen(QPen(col_.darker(160), 1))
                painter.drawEllipse(r.adjusted(15, 15, -15, -15))
            try:
                from ..rpg import magic
                cost = int(round(magic.cast_cost(c, sp)))
            except Exception:
                cost = int(getattr(sp, "base_cost", 0) or 0)
            painter.setFont(self.f_count)
            painter.setPen(QColor(150, 190, 255))
            painter.drawText(r.adjusted(0, 0, -4, -2), Qt.AlignRight | Qt.AlignBottom, str(cost))
            if hits.hovered(r):
                painter.fillRect(r.adjusted(2, 2, -2, -2), QColor(255, 230, 170, 26))
                self.hover = ("spell", sid)
            self._cells.append((QRect(r), ("spell", None, sid)))
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        _fit(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
                         Qt.AlignCenter, "Drag a spell to a hand to equip it  ·  mouse buttons use each hand")

    def _draw_spell_details(self, painter, inner, sid):
        from ..rpg import magic
        sp = magic.get(sid)
        c = self._character()
        painter.setFont(self.f_name)
        painter.setPen(QColor(*sp.color))
        _fit(painter, QRect(inner.x(), inner.y(), inner.width(), 26),
                         Qt.AlignLeft | Qt.AlignVCenter, sp.name)
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        painter.drawText(inner.x(), inner.y() + 40,
                         f"{str(sp.school).title()}  ·  {str(sp.delivery).title()}")
        desc = QRect(inner.x(), inner.y() + 56, inner.width(), 110)
        painter.setBrush(QColor(20, 19, 18, 200))
        painter.setPen(QPen(_SLOT_EDGE, 1))
        painter.drawRect(desc)
        painter.setFont(self.f_body)
        painter.setPen(_INK)
        painter.drawText(desc.adjusted(8, 6, -8, -6), Qt.AlignTop | Qt.TextWordWrap,
                         getattr(sp, "desc", "") or "")
        try:
            cost = magic.cast_cost(c, sp)
            chance = magic.cast_chance(c, sp)
            skill = c.skill(sp.school)
        except Exception:
            cost, chance, skill = sp.base_cost, 1.0, 0
        lines = [f"Magicka {cost:g}",
                 f"{str(sp.school).title()} skill {skill}",
                 f"Chance to cast {int(round(chance * 100))}%"]
        for e in sp.effects or []:
            mag = e.get("magnitude", "")
            lines.append(f"{str(e.get('kind', '')).replace('_', ' ').title()} {mag}")
        for k, line in enumerate(lines[:6]):
            painter.drawText(inner.x(), desc.bottom() + 22 + k * 18, line)

    def _draw_details(self, painter, rect):
        inner = self._panel(painter, rect, "Details")
        spell = (self.hover[1] if (self.hover and self.hover[0] == "spell")
                 else None if (self.hover and self.hover[0] == "item")
                 else self.selected_spell)
        if spell:
            self._draw_spell_details(painter, inner, spell)
            by = inner.bottom() - 34
            bw = (inner.width() - 6) // 2
            for k, (label, action) in enumerate((("Select", self._ready_spell(spell)),
                                                 ("Exit", self._close_action))):
                r = QRect(inner.x() + k * (bw + 6), by, bw, 30)
                hot = hits.hovered(r)
                painter.setBrush(QColor(96, 70, 34, 240) if hot else QColor(40, 37, 33, 240))
                painter.setPen(QPen(_GOLD, 1.4))
                painter.drawRoundedRect(r, 5, 5)
                painter.setFont(self.f_button)
                painter.setPen(_GOLD)
                _fit(painter, r, Qt.AlignCenter, label)
                self._buttons.append((QRect(r), action))
            return
        iid = self.hover[1] if (self.hover and self.hover[0] == "item") else self.selected
        d = _item(iid) if iid else None
        if d is None:
            painter.setFont(self.f_body)
            painter.setPen(_DIM)
            painter.drawText(inner.adjusted(0, 10, 0, 0), Qt.AlignTop | Qt.TextWordWrap,
                             "Point at an item to see what it is.\n\n"
                             "Drag it onto your body to wear it, back to the pack to "
                             "put it away, or out of the window to drop it on the floor."
                             "\n\nThe Character tab shows your health, armour, "
                             "experience and attributes.")
        else:
            stack = self._stack(iid) or {}
            try:
                from ..rpg import items
                rgb = items.RARITY_INFO[items.rarity_of(stack)]["rgb"]
                prefix = items.RARITY_INFO[items.rarity_of(stack)]["prefix"]
            except Exception:
                rgb, prefix = (232, 228, 240), ""
            painter.setFont(self.f_name)
            painter.setPen(QColor(*rgb))
            _fit(painter, QRect(inner.x(), inner.y(), inner.width(), 26),
                             Qt.AlignLeft | Qt.AlignVCenter, prefix + d.name)
            painter.setFont(self.f_small)
            painter.setPen(_DIM)
            painter.drawText(inner.x(), inner.y() + 40, d.category.title()
                             + (f"  ·  {slot_of(d)}" if slot_of(d) else ""))
            pm = self._icon(iid, 96)
            if pm is not None and not pm.isNull():
                painter.drawPixmap(inner.center().x() - pm.width() // 2, inner.y() + 52, pm)
            desc = QRect(inner.x(), inner.y() + 156, inner.width(), 96)
            painter.setBrush(QColor(20, 19, 18, 200))
            painter.setPen(QPen(_SLOT_EDGE, 1))
            painter.drawRect(desc)
            painter.setFont(self.f_body)
            painter.setPen(_INK)
            painter.drawText(desc.adjusted(8, 6, -8, -6), Qt.AlignTop | Qt.TextWordWrap,
                             d.desc or "")
            lines = []
            if d.get("damage"):
                lines.append(f"Damage {d.get('damage')}")
            if d.get("armor_rating"):
                lines.append(f"{str(d.get('armor_class', 'light')).title()} armour"
                             f"  ·  rating {d.get('armor_rating')}")
            if d.get("ac_bonus"):
                lines.append(f"Armour Class +{d.get('ac_bonus')}")
            if d.get("kind"):
                lines.append(f"Kind: {d.get('kind')}")
            for e in d.get("effects", []) or []:
                lines.append(f"{str(e.get('kind', '')).replace('_', ' ').title()} "
                             f"{e.get('magnitude', '')}")
            painter.setFont(self.f_body)
            painter.setPen(_INK)
            for k, line in enumerate(lines[:4]):
                painter.drawText(inner.x(), desc.bottom() + 20 + k * 18, line)
            stats = QRect(inner.x(), desc.bottom() + 96, inner.width(), 26)
            painter.setBrush(QColor(20, 19, 18, 200))
            painter.setPen(QPen(_SLOT_EDGE, 1))
            painter.drawRect(stats)
            painter.setPen(_GOLD)
            _fit(painter, stats.adjusted(8, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                             f"{int(stack.get('value', d.value))} gold")
            painter.setPen(_INK)
            _fit(painter, stats.adjusted(0, 0, -8, 0), Qt.AlignRight | Qt.AlignVCenter,
                             f"{float(d.weight):g} wt")
        if not self.DETAIL_BUTTONS:
            return
        # Buttons.
        by = inner.bottom() - 34
        bw = (inner.width() - 12) // 3
        wearable = d is not None and slot_of(d) is not None
        worn = iid is not None and iid in set(v for v in self._equipment().values() if v)
        use_label = ("Take off" if worn else "Equip") if wearable else "Use"
        for k, (label, action, enabled) in enumerate((
                (use_label, self._use(iid), d is not None),
                ("Assign", self._assign(iid), d is not None and d.category == "weapon"),
                ("Exit", self._close_action, True))):
            r = QRect(inner.x() + k * (bw + 6), by, bw, 30)
            hot = enabled and hits.hovered(r)
            painter.setBrush(QColor(96, 70, 34, 240) if hot else QColor(40, 37, 33, 240))
            painter.setPen(QPen(_GOLD if enabled else QColor(70, 66, 60), 1.4))
            painter.drawRoundedRect(r, 5, 5)
            painter.setFont(self.f_button)
            painter.setPen(_GOLD if enabled else QColor(90, 86, 80))
            _fit(painter, r, Qt.AlignCenter, label)
            if enabled:
                self._buttons.append((QRect(r), action))

    def _draw_dragged(self, painter):
        """The item under the pointer while it is being dragged."""
        if self._drag is None or hits.pointer is None:
            return
        px, py = hits.pointer
        pm = self._icon(self._drag[2], CELL - 6)
        if pm is not None and not pm.isNull():
            painter.setOpacity(0.85)
            painter.drawPixmap(int(px - pm.width() / 2), int(py - pm.height() / 2), pm)
            painter.setOpacity(1.0)

    # ------------------------------------------------------------- actions
    # Each returns a callable(session), queued and run by the game tick.
    def _queue(self, action):
        hits.queue(action)

    def _set_view(self, key):
        def act():
            self.view = key
        return act

    # ------------------------------------------------------- character sheet
    def _draw_character_sheet(self, painter, rect):
        """Who the character is: pools, Armour Class, attributes, skills."""
        inner = self._panel(painter, rect, "Character")
        c = self._character()
        if c is None:
            return
        try:
            from ..rpg import attributes as attr, birthsigns, classes, equipment as eq
            from ..rpg import races, skills as sk
        except Exception:
            return
        x, y, w = inner.x(), inner.y(), inner.width()
        painter.setFont(self.f_name)
        painter.setPen(_GOLD)
        _fit(painter, QRect(x, y, w, 22), Qt.AlignLeft | Qt.AlignVCenter, c.name)
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        try:
            sub = (f"Level {c.level} {races.get(c.race_id).label} "
                   f"{classes.get(c.class_id).label} · {birthsigns.get(c.birthsign_id).label}")
        except Exception:
            sub = f"Level {c.level}"
        _fit(painter, QRect(x, y + 22, w, 16), Qt.AlignLeft | Qt.AlignVCenter, sub)
        rolls = getattr(c, "rolls", None) or {}
        yy = y + 40
        if rolls:
            try:
                from ..rpg import bios
                bio = bios.bio_for(rolls.get("strength", 10), rolls.get("endurance", 10),
                                   rolls.get("personality", 10))
                painter.setPen(_GOLD)
                _fit(painter, QRect(x, yy, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                                 f"{bio['title']} · STR {rolls.get('strength', '?')} "
                                 f"END {rolls.get('endurance', '?')} "
                                 f"CHA {rolls.get('personality', '?')}")
            except Exception:
                pass
            yy += 18
        # Pools.
        for label, cur, top, colour in (
                ("Health", c.health, c.max_health, QColor(200, 70, 60)),
                ("Magicka", c.magicka, c.max_magicka, QColor(80, 120, 220)),
                ("Stamina", c.stamina, c.max_stamina, QColor(90, 170, 90))):
            bar = QRect(x + 64, yy + 3, w - 64, 11)
            painter.setPen(_INK)
            _fit(painter, QRect(x, yy, 62, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setBrush(_SLOT)
            painter.setPen(QPen(_SLOT_EDGE, 1))
            painter.drawRect(bar)
            frac = max(0.0, min(1.0, float(cur) / max(1.0, float(top))))
            painter.fillRect(QRect(bar.x() + 1, bar.y() + 1, int((bar.width() - 1) * frac),
                                   bar.height() - 1), colour)
            painter.setPen(_INK)
            _fit(painter, bar, Qt.AlignCenter, f"{int(cur)} / {int(top)}")
            yy += 18
        # Armour Class, and what kind of armour gives it.
        ac = int(eq.armour_class(c))
        weight = eq.armor_class_worn(c)
        self._draw_ac_badge(painter, QPoint(x + 22, yy + 26), ac)
        painter.setFont(self.f_body)
        painter.setPen(_INK)
        _fit(painter, QRect(x + 52, yy + 8, w - 52, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         f"Armour Class {ac}")
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        _fit(painter, QRect(x + 52, yy + 26, w - 52, 16), Qt.AlignLeft | Qt.AlignVCenter,
                         "Unarmoured" if weight == "none" else f"{weight.title()} armour"
                         f" · deflects {int(round(eq.deflect_chance(c) * 100))}%"
                         if hasattr(eq, "deflect_chance") else "")
        yy += 54
        # Experience: what is earned toward the next level, and what is left.
        # Either track fills a level: experience, or ten major-skill rises.
        from ..rpg import character as rpg_character
        xp = int(getattr(c, "xp", 0) or 0)
        need = int(getattr(c, "xp_needed", 0) or rpg_character.xp_to_next(c.level))
        bar = QRect(x, yy, w, 10)
        painter.setBrush(_SLOT)
        painter.setPen(QPen(_SLOT_EDGE, 1))
        painter.drawRect(bar)
        painter.fillRect(QRect(bar.x() + 1, bar.y() + 1,
                               int((bar.width() - 1) * min(1.0, xp / max(1, need))),
                               bar.height() - 1), QColor(200, 170, 70))
        painter.setFont(self.f_small)
        painter.setPen(_INK)
        left = max(0, need - xp)
        _fit(painter, QRect(x, yy + 11, w, 14), Qt.AlignLeft | Qt.AlignVCenter,
             f"XP {xp} / {need}")
        painter.setPen(_GOLD if left == 0 else _DIM)
        _fit(painter, QRect(x, yy + 11, w, 14), Qt.AlignRight | Qt.AlignVCenter,
             "Ready to level up" if left == 0 else f"{left} to level {c.level + 1}")
        prog = int(getattr(c, "xp_progress", 0) or 0)
        painter.setPen(_DIM)
        _fit(painter, QRect(x, yy + 25, w, 14), Qt.AlignLeft | Qt.AlignVCenter,
             f"Skill rises {prog} / {rpg_character.SKILL_UPS_PER_LEVEL}")
        yy += 44
        # Attributes, two columns.
        painter.setFont(self.f_body)
        painter.setPen(_GOLD)
        painter.drawText(x, yy + 12, "Attributes")
        yy += 18
        painter.setFont(self.f_small)
        half = (w - 10) // 2
        for i, a in enumerate(attr.ATTRIBUTES):
            col, row = i % 2, i // 2
            r = QRect(x + col * (half + 10), yy + row * 15, half, 15)
            painter.setPen(_INK)
            _fit(painter, r.adjusted(0, 0, -26, 0), Qt.AlignLeft | Qt.AlignVCenter, attr.label(a))
            painter.setPen(_GOLD)
            painter.drawText(r, Qt.AlignRight | Qt.AlignVCenter, str(c.attrs.get(a, 0)))
        yy += ((len(attr.ATTRIBUTES) + 1) // 2) * 15 + 8
        # Skills, by specialisation, three columns.
        col_w = (w - 12) // 3
        for ci, spec in enumerate((sk.COMBAT, sk.MAGIC, sk.STEALTH)):
            cx = x + ci * (col_w + 6)
            painter.setFont(self.f_body)
            painter.setPen(_GOLD)
            painter.drawText(cx, yy + 12, spec.title())
            painter.setFont(self.f_small)
            for j, sid in enumerate(sk.BY_SPEC[spec]):
                r = QRect(cx, yy + 18 + j * 14, col_w, 14)
                major = sid in getattr(c, "major_skills", ())
                painter.setPen(_GOLD if major else _INK)
                label = painter.fontMetrics().elidedText(
                    ("★" if major else "") + sk.label(sid), Qt.ElideRight, col_w - 22)
                painter.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, label)
                painter.setPen(_INK)
                painter.drawText(r, Qt.AlignRight | Qt.AlignVCenter, str(c.skill(sid)))
        if getattr(c, "bounty", 0):
            painter.setFont(self.f_body)
            painter.setPen(_NO)
            _fit(painter, QRect(x, inner.bottom() - 18, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                             f"Bounty: {c.bounty} gold")

    def _set_tab(self, i):
        def act():
            self.tab = i
            self.page = 0
        return act

    def _turn_page(self, step, pages):
        def act():
            self.page = max(0, min(pages - 1, self.page + step))
        return act

    def _ready_spell(self, sid):
        def act():
            def run(session):
                c = session.game.character
                c.active_spell = sid
                try:
                    from ..rpg import equipment as eq, magic
                    eq._refresh_weapon_kind(c)
                    session.notify(f"Selected {magic.get(sid).name}", 1.5)
                except Exception:
                    pass
            self._queue(run)
        return act

    def _use(self, iid):
        def act():
            if iid:
                self._queue(lambda session: session.inventory_use(iid))
        return act

    def _assign(self, iid):
        def act():
            if iid:
                self._queue(lambda session: session.inventory_assign_quick(iid))
        return act

    def _close_action(self):
        self._queue(lambda session: setattr(session, "open_screen", None))

    # --------------------------------------------------------------- mouse
    def _pad_nodes(self):
        """The actual painted slots and actions, including empty drop slots."""
        nodes = {}
        def node(rect):
            return nodes.setdefault(rect.getRect(), {"rect": rect})
        for rect, source in self._cells:
            node(rect)["source"] = source
        for rect, target in self._targets:
            # A grid-wide pack drop area duplicates its individual cells.
            if any(rect != cell and rect.contains(cell) for cell, _ in self._cells):
                continue
            node(rect)["target"] = target
        for rect, action in self._buttons:
            node(rect)["action"] = action
        return list(nodes.values())

    def _pad_node(self, nodes):
        if not nodes:
            return None
        if self._pad_point is None:
            return next((n for n in nodes if "source" in n), nodes[0])
        x, y = self._pad_point
        return min(nodes, key=lambda n: (n["rect"].center().x() - x) ** 2
                   + (n["rect"].center().y() - y) ** 2)

    def handle_gamepad(self, key):
        """D-pad spatial focus and A pick/place, without double-click timing."""
        if getattr(self, "screen", "inventory") not in ("inventory", "character", "spells", "skills"):
            return False
        if key == "escape":
            drag.unpick()
            self._close_action()
            return True
        if key not in ("up", "down", "left", "right", "return"):
            return False
        nodes = self._pad_nodes()
        current = self._pad_node(nodes)
        if current is None:
            return True
        if key != "return":
            dx, dy = {"up": (0, -1), "down": (0, 1),
                      "left": (-1, 0), "right": (1, 0)}[key]
            origin = current["rect"].center()
            candidates = []
            for n in nodes:
                point = n["rect"].center() - origin
                ahead = point.x() * dx + point.y() * dy
                across = abs(point.x() * dy - point.y() * dx)
                if ahead > 2:
                    candidates.append((ahead + across * 3, n))
            if candidates:
                current = min(candidates, key=lambda entry: entry[0])[1]
        point = current["rect"].center()
        self._pad_point = (point.x(), point.y())
        hits.pointer = self._pad_point
        source = current.get("source")
        if source:
            if source[0] in ("spell", "spell_hand"):
                self.selected_spell = source[2]
            else:
                self.selected, self.selected_spell = source[2], None
        if key == "return":
            picked = drag.picked_source()
            target = current.get("target")
            if "action" in current:
                drag.unpick()
                current["action"]()
            elif picked is not None:
                if source == picked or (target and target[0] == picked[0] == "pack"):
                    drag.unpick()
                elif target and placeable(target, picked):
                    drag.unpick()
                    self._queue(lambda session: session.item_drop(picked, target))
            elif source:
                drag.pick(self, source)
        return True

    def _draw_pad_focus(self, painter):
        from .. import controls
        if not controls.gamepad():
            return
        node = self._pad_node(self._pad_nodes())
        if node is not None:
            if self._pad_point is None:
                point = node["rect"].center()
                self._pad_point = (point.x(), point.y())
                source = node.get("source")
                if source and source[0] not in ("spell", "spell_hand"):
                    self.selected = source[2]
            painter.save()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_GOLD, 3))
            painter.drawRoundedRect(node["rect"].adjusted(-2, -2, 2, 2), 4, 4)
            painter.restore()

    def _at(self, rects, p):
        for r, what in reversed(rects):
            if r.contains(p):
                return what
        return None

    def handle_mouse_press(self, event):
        if not self.active:
            return False
        rect = self._full_rect()
        if not rect.contains(event.pos()):
            return False
        body_top = rect.y() + self.HEADER_H
        picked = drag.picked_source()
        if picked is not None and event.y() >= body_top and event.button() == Qt.RightButton:
            drag.unpick()                    # a right click puts it back down
            return True
        if event.y() < body_top or event.button() != Qt.LeftButton:
            return super().handle_mouse_press(event)
        p = event.pos()
        button = self._at(self._buttons, p)
        if button is not None:
            button()
            return True
        source = self._at(self._cells, p)
        self._unpicked = False
        if picked is not None:
            if source is not None and tuple(source) == tuple(picked):
                drag.unpick()                # the same item again: put down
                self._unpicked = True
            else:
                target = self._at(self._targets, p)
                if target is not None and placeable(target, picked):
                    # A click on a slot it fits: it goes there.
                    drag.unpick()
                    self._queue(lambda session: session.item_drop(picked, target))
                    return True
        if source is not None:
            self._press = (QPoint(p), source)
            if source[0] in ("spell", "spell_hand"):
                self.selected_spell = source[2]
            else:
                self.selected = source[2]
                self.selected_spell = None
        return True

    @property
    def mouse_captured(self):
        return self._press is not None

    def handle_mouse_move(self, event, view_w, view_h):
        if self.dragging:
            return super().handle_mouse_move(event, view_w, view_h)
        hits.pointer = (event.x(), event.y())
        if self._press is not None and self._drag is None:
            start, source = self._press
            if (event.pos() - start).manhattanLength() >= DRAG_START:
                self._drag = source
                drag.start(self, source)
        return self._press is not None

    def handle_mouse_release(self, event):
        if self.dragging:
            return super().handle_mouse_release(event)
        if self._press is None:
            return False
        _start, source = self._press
        self._press = None
        dragged, self._drag = self._drag, None
        drag.stop(self)
        if dragged is None:
            # A click: a second one on the same item soon after uses it; one
            # on its own picks it up, to be put in a slot with a click there.
            now = time.monotonic()
            last_t, last_src = self._last_click
            self._last_click = (now, source)
            if last_src == source and now - last_t <= DOUBLE_CLICK:
                iid = source[2]
                drag.unpick()
                if source[0] in ("spell", "spell_hand"):
                    self._ready_spell(iid)()
                else:
                    self._queue(lambda session: session.inventory_use(iid))
                self._last_click = (0.0, None)
            elif not self._unpicked:
                drag.pick(self, source)
            return True
        iid = dragged[2]
        target = self._at(self._targets, event.pos())
        if target is None:
            # Let go over another window: the strip, an open chest or body.
            target = drag.target_at(event.x(), event.y(), exclude=self)
            if target is not None:
                self._queue(lambda session: session.item_drop(dragged, target))
            elif dragged[0] not in ("spell", "spell_hand") and not drag.over_window(event.x(), event.y()):
                # Out over the world: on the floor.
                self._queue(lambda session: session.drop_item(iid))
            return True
        if target[:1] == dragged[:1] and target[1] == dragged[1]:
            return True
        self._queue(lambda session: session.inventory_move(dragged, target, iid))
        return True

    def handle_body_click(self, x, y):
        return True

    def on_close(self):
        drag.forget(self)
        self._queue(lambda session: setattr(session, "open_screen", None))

    # the body has a fixed size; keep it inside the view when it opens, and
    # clear of the inventory strip along the bottom edge where there is room
    def place(self, view_w, view_h):
        from .inventory_strip import height_needed
        bw = self.width
        bh = self.HEADER_H + self.content_height()
        y = (view_h - bh) // 2
        y = min(y, view_h - height_needed() - bh)
        self.window_rect.moveTo(max(10, (view_w - bw) // 2), max(10, y))
