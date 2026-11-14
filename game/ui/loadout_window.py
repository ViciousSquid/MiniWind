"""
The player's in-play **loadout** popup — a draggable floating window (SysMon
chrome) with two tabs:

* **Inventory** — the weapons the player carries. Click one to equip it (click
  the equipped one again to go unarmed). The equipped weapon is highlighted and
  drives left-mouse melee / bow attacks.
* **Spells** — the spells the player knows. The two hands are separate
  slots with their own buttons: left-click a spell to ready it in the left
  hand (the left mouse button casts it), right-click to ready it in the right
  hand (the right mouse button casts it); click it again in that hand to put
  it away. Each row is tagged L / R with the hand(s) holding it. While worn
  metal armour stops casting, the spells are greyed out and cannot be readied,
  and hovering one shows why.

Opened with **I** during play and left open while fighting (it doesn't pause the
world). It subclasses the engine's :class:`FloatingWindow` so it lives in the
same :class:`WindowManager` as the NPC inspector and the other popups, and it
draws itself immediate-mode with the live QPainter, reading the session each
frame so equip / selection state is always current.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QColor, QFontMetrics, QPen, QBrush, QPixmap

from engine.floating_windows import FloatingWindow

# Palette echoes engine.sysmon / the other popups.
_BG = QColor(20, 20, 25, 235)
_TEXT = QColor(222, 222, 226)
_MUTED = QColor(150, 150, 160)
_WHITE = QColor(245, 245, 248)
_TAB_BG = QColor(45, 47, 54)
_TAB_ON = QColor(70, 96, 120)
_ROW = QColor(38, 40, 46)
_ROW_HOVER = QColor(52, 55, 63)
_SEL = QColor(61, 95, 93)
_SEL_LINE = QColor(120, 210, 180)
_GOLD = QColor(240, 200, 110)


class LoadoutWindow(FloatingWindow):
    ROW_H = 34
    ICON = 26
    PAD = 10
    TAB_H = 26
    # Tells the view to free the (normally hidden, centre-locked) play-mode
    # cursor while this window is open, so its rows can be clicked.
    wants_cursor = True

    def __init__(self, session, x=60, y=70, width=300):
        super().__init__("Loadout", x, y, width, body_height=300)
        self.session = session
        self.tab = "inventory"          # 'inventory' | 'spells'
        self._tab_rects = []            # [(QRect, tab_name)]
        self._row_rects = []            # [(QRect, kind, id)]
        import game.ui.fonts as fonts
        self.body_font = fonts.dialogue_font(10)
        self.small_font = fonts.dialogue_font(9)
        self.title_font = fonts.dialogue_font(11)
        self._fm = QFontMetrics(self.body_font)
        self._icon_cache = {}

    # ---- data (read live from the session) -------------------------------
    def _character(self):
        try:
            return self.session.game.character
        except Exception:
            return None

    def _weapons(self):
        """Equippable weapons in the inventory: list of (id, name, stack).

        Read straight from :meth:`MiniwindSession.weapon_slots` so the order
        here is the order the number keys use — row 1 is what pressing 1 draws.
        """
        try:
            return [(entry["id"], entry["name"], entry["stack"])
                    for entry in self.session.weapon_slots()]
        except Exception:
            return []

    def _spells(self):
        """Known spells: list of (id, Spell)."""
        c = self._character()
        if c is None:
            return []
        try:
            import game.rpg.magic as magic
        except Exception:
            return []
        out = []
        for sid in getattr(c, "known_spells", []) or []:
            sp = magic.get(sid)
            if sp is not None:
                out.append((sid, sp))
        return out

    def _equipped_weapon(self):
        c = self._character()
        if c is None:
            return None
        try:
            import game.rpg.equipment as eq
            return eq.equipped_id(c, "weapon")
        except Exception:
            return None

    def _active_spell(self):
        c = self._character()
        return getattr(c, "active_spell", None) if c else None

    def _weapon_icon(self, stack):
        iid = stack.get("id")
        if iid in self._icon_cache:
            return self._icon_cache[iid]
        pm = None
        try:
            import game.item_icons as item_icons
            pm = item_icons.icon_pixmap(iid, stack, self.ICON)
        except Exception:
            pm = None
        self._icon_cache[iid] = pm
        return pm

    # ---- sizing ----------------------------------------------------------
    def content_height(self):
        if self.tab == "inventory":
            n = max(1, len(self._weapons()))
        else:
            n = max(1, len(self._spells()))
        return self.TAB_H + self.PAD + n * self.ROW_H + self.PAD + 22

    # ---- drawing ---------------------------------------------------------
    def draw_body(self, painter, x, y, w):
        self._tab_rects = []
        self._row_rects = []
        painter.setFont(self.body_font)

        # --- Tab bar ---
        tabs = [("inventory", "Inventory"), ("spells", "Spells")]
        tw = w // 2
        for i, (key, label) in enumerate(tabs):
            r = QRect(x + i * tw, y, tw if i == 1 else tw, self.TAB_H)
            active = (self.tab == key)
            painter.fillRect(r, _TAB_ON if active else _TAB_BG)
            painter.setPen(QPen(_SEL_LINE if active else QColor(70, 72, 82), 1))
            painter.drawRect(r)
            painter.setPen(_WHITE if active else _MUTED)
            painter.drawText(r, Qt.AlignCenter, label)
            self._tab_rects.append((r, key))

        top = y + self.TAB_H + self.PAD
        if self.tab == "inventory":
            self._draw_weapons(painter, x, top, w)
        else:
            self._draw_spells(painter, x, top, w)

    def _row_rect(self, x, top, w, i):
        return QRect(x + 6, top + i * self.ROW_H, w - 12, self.ROW_H - 4)

    def _draw_weapons(self, painter, x, top, w):
        weapons = self._weapons()
        equipped = self._equipped_weapon()
        if not weapons:
            painter.setPen(_MUTED)
            painter.drawText(x + 10, top + 20, "No weapons in your pack.")
            return
        for i, (iid, name, stack) in enumerate(weapons):
            r = self._row_rect(x, top, w, i)
            sel = (iid == equipped)
            painter.fillRect(r, _SEL if sel else _ROW)
            if sel:
                painter.fillRect(QRect(r.x(), r.y(), 3, r.height()), _SEL_LINE)
            # Slot number: this row's key. Row 1 is what pressing 1 draws.
            painter.setPen(_GOLD if sel else _MUTED)
            painter.setFont(self.small_font)
            painter.drawText(QRect(r.x() + 4, r.y(), 16, r.height()),
                             Qt.AlignVCenter | Qt.AlignHCenter, str(i + 1))
            pm = self._weapon_icon(stack)
            iy = r.y() + (r.height() - self.ICON) // 2
            if pm is not None and not pm.isNull():
                painter.drawPixmap(r.x() + 22, iy, pm)
            painter.setPen(_WHITE if sel else _TEXT)
            painter.setFont(self.body_font)
            painter.drawText(r.x() + 22 + self.ICON + 8, r.y() + r.height() // 2 + 4, name)
            # damage stat, right-aligned
            dmg = stack.get("damage")
            if dmg is None:
                try:
                    import game.rpg.items as itemdb
                    d = itemdb.get(iid)
                    dmg = d.get("damage") if d else None
                except Exception:
                    dmg = None
            painter.setFont(self.small_font)
            painter.setPen(_GOLD if sel else _MUTED)
            label = f"{int(dmg)} dmg" if dmg else ("equipped" if sel else "")
            painter.drawText(QRect(r.right() - 66, r.y(), 60, r.height()),
                             Qt.AlignVCenter | Qt.AlignRight, label)
            self._row_rects.append((r, "weapon", iid))
        painter.setPen(_MUTED)
        painter.setFont(self.small_font)
        painter.drawText(x + 8, top + len(weapons) * self.ROW_H + 14,
                         "Press 1-4 or click to equip • Left-mouse attacks")

    def _draw_spells(self, painter, x, top, w):
        spells = self._spells()
        if not spells:
            painter.setPen(_MUTED)
            painter.drawText(x + 10, top + 20, "You know no spells.")
            return
        import game.ui.spell_lock as spell_lock
        # Worn metal armour greys every spell out: not selectable, and the
        # row's tooltip says why.
        locked = spell_lock.locked(self._character())
        held = self._held_hands()
        for i, (sid, sp) in enumerate(spells):
            r = self._row_rect(x, top, w, i)
            sel = sid in held.values()
            painter.fillRect(r, _SEL if sel else _ROW)
            if sel:
                painter.fillRect(QRect(r.x(), r.y(), 3, r.height()), _SEL_LINE)
            # element colour swatch
            col = QColor(*sp.color) if getattr(sp, "color", None) else QColor(160, 120, 220)
            if locked:
                col = QColor(spell_lock.GREY)
            cy = r.y() + (r.height() - self.ICON) // 2
            painter.setBrush(QBrush(col))
            painter.setPen(QPen(col.darker(150), 1))
            painter.drawEllipse(r.x() + 8, cy, self.ICON, self.ICON)
            painter.setPen(spell_lock.GREY if locked else _WHITE if sel else _TEXT)
            painter.setFont(self.body_font)
            painter.drawText(r.x() + 8 + self.ICON + 8, r.y() + r.height() // 2 + 4, sp.name)
            spell_lock.note(r, locked)
            painter.setFont(self.small_font)
            painter.setPen(_GOLD if sel else _MUTED)
            cost = int(getattr(sp, "base_cost", 0) or 0)
            painter.drawText(QRect(r.right() - 66, r.y(), 60, r.height()),
                             Qt.AlignVCenter | Qt.AlignRight, f"{cost} mp")
            # Which hand(s) hold it: L / R, as the mouse buttons that cast it.
            for k, side in enumerate(s for s in ("left", "right") if held.get(s) == sid):
                tag = QRect(r.right() - 96 + k * 16, r.y() + (r.height() - 14) // 2, 14, 14)
                painter.setBrush(spell_lock.GREY if locked else _GOLD)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(tag, 2, 2)
                painter.setPen(QColor(20, 16, 10))
                painter.drawText(tag, Qt.AlignCenter, "L" if side == "left" else "R")
            self._row_rects.append((r, "spell", sid))
        painter.setPen(_MUTED)
        painter.setFont(self.small_font)
        painter.drawText(x + 8, top + len(spells) * self.ROW_H + 14,
                         "Left-click: left hand (LMB) • Right-click: right hand (RMB)")
        spell_lock.flush(painter)      # a greyed spell's tooltip, on top

    def _held_hands(self):
        """``{"left": spell_id, "right": spell_id}`` for the physical hands
        that hold a spell."""
        c = self._character()
        out = {}
        if c is None:
            return out
        try:
            import game.rpg.equipment as eq
            for side in ("left", "right"):
                spell = eq.hand_spell(c, eq.relative_hand(c, side))
                if spell is not None:
                    out[side] = spell.id
        except Exception:
            pass
        return out

    # ---- interaction -----------------------------------------------------
    def handle_mouse_press(self, event):
        # Which button: the left readies a spell in the left hand, the right
        # in the right hand (see handle_body_click).
        self._press_hand = "right" if event.button() == Qt.RightButton else "left"
        return super().handle_mouse_press(event)

    def handle_body_click(self, x, y):
        from PyQt5.QtCore import QPoint
        p = QPoint(x, y)
        for r, key in self._tab_rects:
            if r.contains(p):
                self.tab = key
                return True
        for r, kind, iid in self._row_rects:
            if r.contains(p):
                if kind == "weapon":
                    self._equip(iid)
                else:
                    self._ready_in_hand(iid, getattr(self, "_press_hand", "left"))
                return True
        return False

    def _equip(self, item_id):
        c = self._character()
        if c is None:
            return
        try:
            import game.rpg.equipment as eq
            if eq.equipped_id(c, "weapon") == item_id:
                eq.unequip(c, "weapon")            # toggle off -> unarmed
                self.session.notify("Unarmed")
            else:
                self.session.game.equip(item_id)
                self.session.notify(f"Equipped {self._name_of(item_id)}")
        except Exception:
            pass

    def _ready_in_hand(self, spell_id, hand):
        """Ready *spell_id* in the physical *hand* ("left" / "right"), or put
        it away if that hand holds it already -- from the game tick, like
        every other change the game UI makes. Worn metal armour refuses it
        (MiniwindSession.equip_hand_spell)."""
        from . import hits
        hits.queue(lambda session, sid=spell_id, h=hand: session.ready_spell(sid, h))

    def _name_of(self, item_id):
        try:
            import game.rpg.items as itemdb
            d = itemdb.get(item_id)
            return d.name if d else item_id
        except Exception:
            return item_id

    def _name_of_spell(self, spell_id):
        try:
            import game.rpg.magic as magic
            sp = magic.get(spell_id)
            return sp.name if sp else spell_id
        except Exception:
            return spell_id
