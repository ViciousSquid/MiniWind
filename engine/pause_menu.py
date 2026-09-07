"""
Play-mode pause menu.

Pressing Escape in a *standalone* play session (the game launched straight from
the launcher, or from an imported ``.fiopak`` package) used to end the game
outright. That is fine when play mode is a preview started from the editor —
Escape means "back to what I was doing" — but for someone actually playing the
game it is a one-key quit with no way back.

This module is that missing menu. It freezes the world, blurs the frame that was
on screen when the player hit Escape, and paints a ``P A U S E D`` banner over it
with a horizontal row of options:

    NEW GAME   LOAD   SAVE   EDITOR   QUIT

``LOAD`` and ``SAVE`` open a second row of three save slots (the engine already
knows how to serialise a whole play session — see :mod:`engine.savegame`), and
anything destructive — starting over, loading, overwriting an occupied slot,
leaving for the editor, quitting — asks a plain ``SURE?`` before it happens.

The menu is drawn with the same ``QPainter`` pass the HUD and the level-complete
overlay use, so it needs no widgets and no layout: the viewport owns one
:class:`PauseMenu`, feeds it key and mouse events while it is active, and calls
:meth:`draw` last so nothing paints over it. Actions are performed through the
editor window (:mod:`editor.main_window`), which owns the level, play mode and
the kiosk presentation.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QBrush, QColor, QFont, QPen


#: How many save slots the menu offers. The slots are ordinary ``.fiosave``
#: files (``slot1``/``slot2``/``slot3``) in the saves directory, so the console
#: ``load slot2`` and the menu are looking at exactly the same thing.
SLOT_COUNT = 3

#: Basename (no extension) of save slot *n* (1-based).
def slot_name(index: int) -> str:
    return f"slot{int(index)}"


# --- palette -----------------------------------------------------------------
_TITLE = QColor(240, 236, 230)
_TITLE_SHADOW = QColor(0, 0, 0, 200)
_ACCENT = QColor(196, 30, 58)          # the editor's crimson
_CHIP_BG = QColor(24, 24, 28, 210)
_CHIP_BORDER = QColor(110, 110, 118)
_CHIP_TEXT = QColor(196, 196, 200)
_CHIP_SEL_TEXT = QColor(255, 255, 255)
_SUBTLE = QColor(160, 160, 168)
_CAPTION = QColor(140, 140, 148)


class PauseMenu:
    """Escape-menu state machine, renderer and input handler for play mode."""

    #: Top-level options, in the order they are laid out left to right.
    ROOT_ITEMS = (
        ('new', 'NEW GAME'),
        ('load', 'LOAD'),
        ('save', 'SAVE'),
        ('editor', 'EDITOR'),
        ('quit', 'QUIT'),
    )

    def __init__(self, view):
        self.view = view
        self.active = False
        #: 'root' | 'load' | 'save' | 'confirm'
        self.page = 'root'
        self.index = 0
        self._background = None          # blurred QPixmap of the paused frame
        self._hit_rects = []             # [(index, QRect)] for the current page
        self._pending = None             # (callable, prompt) awaiting SURE?
        self._return_page = 'root'
        self._return_index = 0
        self._slot_cache = None

    # ------------------------------------------------------------------ owner
    @property
    def editor(self):
        return getattr(self.view, 'editor', None)

    # --------------------------------------------------------------- lifecycle
    def open(self):
        """Freeze the world and raise the menu over a blurred still of the frame."""
        if self.active:
            return
        self._background = self._grab_blurred_frame()
        self.active = True
        self.page = 'root'
        self.index = 0
        self._pending = None
        self._slot_cache = None
        self._set_world_paused(True)
        # Drop any key still held when Escape was pressed, so the player is not
        # walking into a wall the moment the menu closes.
        editor = self.editor
        if editor is not None and hasattr(editor, 'keys_pressed'):
            editor.keys_pressed.clear()
        self.view.update()

    def close(self):
        """Resume play. Safe to call when the menu is not open."""
        if not self.active:
            return
        self.active = False
        self.page = 'root'
        self._pending = None
        self._background = None
        self._hit_rects = []
        self._set_world_paused(False)
        self.view.update()

    def _set_world_paused(self, paused: bool):
        """Freeze / thaw the simulation.

        Set two ways, exactly like the ``inspect`` console command: the engine's
        ``gameplay_paused`` stops the base logic thread and the monster AI, and
        the sticky ``_menu_paused`` request is OR-ed back in by any game host
        that recomputes the pause flag from its own state every tick (see
        ``game/host.py``), so a host cannot thaw the world behind the menu.
        """
        lt = getattr(self.view, 'logic_thread', None)
        if lt is None:
            return
        try:
            if paused:
                self._prev_pause = bool(getattr(lt, 'gameplay_paused', False))
                lt._menu_paused = True
                lt.gameplay_paused = True
            else:
                lt._menu_paused = False
                lt.gameplay_paused = bool(getattr(self, '_prev_pause', False))
        except Exception:
            pass

    def _grab_blurred_frame(self):
        """A cheap blur of the current frame: shrink it hard, then grow it back.

        The world is frozen while the menu is up, so this is captured once on
        open rather than per frame. Downsampling to a fraction of the width and
        smooth-scaling back is a box blur for free, and costs one grab.
        """
        try:
            image = self.view.grabFramebuffer()
        except Exception:
            return None
        if image is None or image.isNull():
            return None
        try:
            w = max(1, image.width())
            small = image.scaledToWidth(max(24, w // 22), Qt.SmoothTransformation)
            small = small.scaledToWidth(max(48, w // 8), Qt.SmoothTransformation)
            from PyQt5.QtGui import QPixmap
            return QPixmap.fromImage(small)
        except Exception:
            return None

    # ------------------------------------------------------------------- pages
    def _items(self):
        """(key, label) pairs for the page currently on screen."""
        if self.page == 'root':
            return list(self.ROOT_ITEMS)
        if self.page in ('load', 'save'):
            items = [(f'slot{i}', f'SLOT {i}') for i in range(1, SLOT_COUNT + 1)]
            items.append(('back', 'BACK'))
            return items
        if self.page == 'confirm':
            return [('yes', 'YES'), ('no', 'NO')]
        return []

    def _heading(self):
        if self.page == 'load':
            return 'LOAD GAME'
        if self.page == 'save':
            return 'SAVE GAME'
        if self.page == 'confirm':
            return 'SURE?'
        return ''

    def _slots(self):
        """Metadata for each save slot, newest read cached until the page changes."""
        if self._slot_cache is None:
            editor = self.editor
            reader = getattr(editor, 'pause_menu_slot_info', None)
            try:
                self._slot_cache = reader() if reader else [None] * SLOT_COUNT
            except Exception:
                self._slot_cache = [None] * SLOT_COUNT
        return self._slot_cache

    # ------------------------------------------------------------------- input
    def handle_key(self, event) -> bool:
        """Consume one key press. Returns True when the menu handled it."""
        if not self.active:
            return False
        key = event.key()
        items = self._items()
        if key in (Qt.Key_Left, Qt.Key_A):
            if items:
                self.index = (self.index - 1) % len(items)
            self.view.update()
            return True
        if key in (Qt.Key_Right, Qt.Key_D):
            if items:
                self.index = (self.index + 1) % len(items)
            self.view.update()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activate()
            return True
        if key == Qt.Key_Escape:
            self.back()
            return True
        # Number keys jump straight to a slot on the save/load pages.
        if self.page in ('load', 'save') and Qt.Key_1 <= key <= Qt.Key_9:
            n = key - Qt.Key_1
            if n < SLOT_COUNT:
                self.index = n
                self.activate()
            return True
        return True  # the menu swallows everything else while it is up

    def handle_mouse_move(self, event) -> bool:
        if not self.active:
            return False
        for idx, rect in self._hit_rects:
            if rect.contains(event.pos()):
                if idx != self.index:
                    self.index = idx
                    self.view.update()
                break
        return True

    def handle_mouse_press(self, event) -> bool:
        if not self.active:
            return False
        if event.button() != Qt.LeftButton:
            return True
        for idx, rect in self._hit_rects:
            if rect.contains(event.pos()):
                self.index = idx
                self.activate()
                break
        return True

    def back(self):
        """Escape: out of a sub-page, or out of the menu entirely."""
        if self.page == 'confirm':
            self.page = self._return_page
            self.index = self._return_index
            self._pending = None
            self.view.update()
            return
        if self.page in ('load', 'save'):
            self.page = 'root'
            self.index = 0
            self.view.update()
            return
        self.close()

    def activate(self):
        """Perform whatever the highlighted option means on this page."""
        items = self._items()
        if not items:
            return
        key = items[max(0, min(self.index, len(items) - 1))][0]

        if self.page == 'confirm':
            if key == 'yes':
                action, self._pending = self._pending[0], None
                self.page = 'root'
                self.index = 0
                action()
            else:
                self.back()
            return

        if self.page in ('load', 'save'):
            if key == 'back':
                self.page = 'root'
                self.index = 0
                self.view.update()
                return
            slot = int(key[-1])
            info = self._slots()[slot - 1]
            if self.page == 'load':
                if info is None:
                    return          # empty slot: nothing to load
                self._confirm(f"Load slot {slot}?",
                              "Progress since your last save will be lost.",
                              lambda s=slot: self._do_load(s))
            else:
                if info is None:
                    self._do_save(slot)
                else:
                    self._confirm(f"Overwrite slot {slot}?",
                                  f"Saved {info.get('saved_at', '?')}.",
                                  lambda s=slot: self._do_save(s))
            return

        # Root page
        if key == 'load':
            self.page = 'load'
            self.index = 0
            self._slot_cache = None
            self.view.update()
        elif key == 'save':
            self.page = 'save'
            self.index = 0
            self._slot_cache = None
            self.view.update()
        elif key == 'new':
            self._confirm("Start a new game?",
                          "Unsaved progress will be lost.", self._do_new_game)
        elif key == 'editor':
            self._confirm("Leave for the editor?",
                          "The game ends and the editor opens this map.",
                          self._do_editor)
        elif key == 'quit':
            self._confirm("Quit to desktop?",
                          "Unsaved progress will be lost.", self._do_quit)

    def _confirm(self, title, detail, action):
        self._return_page = self.page
        self._return_index = self.index
        self._pending = (action, title, detail)
        self.page = 'confirm'
        self.index = 1          # default to NO — the safe answer
        self.view.update()

    # ----------------------------------------------------------------- actions
    def _call_editor(self, name, *args):
        editor = self.editor
        fn = getattr(editor, name, None) if editor is not None else None
        if fn is None:
            return False
        try:
            fn(*args)
            return True
        except Exception:
            from editor.debug_console import debug_log
            debug_log("Error", f"Pause menu: {name} failed.")
            return False

    def _do_save(self, slot):
        self._slot_cache = None
        self._call_editor('pause_menu_save_slot', slot)
        self.close()

    def _do_load(self, slot):
        self._slot_cache = None
        # Close first: loading replays the level and re-enters play mode, and the
        # blurred still behind the menu would be of the *old* session.
        self.close()
        self._call_editor('pause_menu_load_slot', slot)

    def _do_new_game(self):
        self.close()
        self._call_editor('pause_menu_new_game')

    def _do_editor(self):
        self.close()
        self._call_editor('pause_menu_to_editor')

    def _do_quit(self):
        self.close()
        self._call_editor('pause_menu_quit')

    # ------------------------------------------------------------------- paint
    def draw(self, painter):
        """Paint the whole overlay. Called last in the frame's painter pass."""
        if not self.active:
            return
        w, h = self.view.width(), self.view.height()
        self._hit_rects = []

        # Blurred still of the frame the player paused on, then a dark scrim so
        # the menu reads at any brightness.
        if self._background is not None:
            painter.drawPixmap(QRect(0, 0, w, h), self._background)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(10, 10, 14, 170)))
        painter.drawRect(0, 0, w, h)

        # --- banner ---
        title_size = max(28, min(72, w // 20))
        painter.setFont(QFont("Arial", title_size, QFont.Bold))
        fm = painter.fontMetrics()
        title = "P A U S E D"
        tw = fm.horizontalAdvance(title)
        tx = (w - tw) // 2
        ty = int(h * 0.34)
        painter.setPen(_TITLE_SHADOW)
        painter.drawText(tx + 4, ty + 4, title)
        painter.setPen(_TITLE)
        painter.drawText(tx, ty, title)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_ACCENT))
        painter.drawRect(tx, ty + int(title_size * 0.30), tw, max(2, title_size // 18))

        # --- page heading (LOAD GAME / SAVE GAME / SURE?) ---
        row_y = int(h * 0.52)
        heading = self._heading()
        if heading:
            painter.setFont(QFont("Arial", max(12, min(22, w // 70)), QFont.Bold))
            fm = painter.fontMetrics()
            hw = fm.horizontalAdvance(heading)
            painter.setPen(_ACCENT if self.page == 'confirm' else _SUBTLE)
            painter.drawText((w - hw) // 2, row_y - 34, heading)

        # A confirm page explains what it is about to do, above the chips.
        if self.page == 'confirm' and self._pending is not None:
            _, prompt, detail = self._pending
            painter.setFont(QFont("Arial", max(11, min(17, w // 90)), QFont.Bold))
            fm = painter.fontMetrics()
            painter.setPen(_TITLE)
            painter.drawText((w - fm.horizontalAdvance(prompt)) // 2, row_y - 8, prompt)
            painter.setFont(QFont("Arial", max(9, min(12, w // 130))))
            fm = painter.fontMetrics()
            painter.setPen(_CAPTION)
            painter.drawText((w - fm.horizontalAdvance(detail)) // 2, row_y + 12, detail)
            row_y += 44

        self._draw_option_row(painter, w, row_y)

        # --- key hints ---
        painter.setFont(QFont("Arial", max(9, min(12, w // 130))))
        fm = painter.fontMetrics()
        hint = ("← →  select      Enter  choose      "
                + ("Esc  back" if self.page != 'root' else "Esc  resume"))
        painter.setPen(_CAPTION)
        painter.drawText((w - fm.horizontalAdvance(hint)) // 2, int(h * 0.86), hint)

    def _draw_option_row(self, painter, w, row_y):
        """Lay the page's options out as one centred horizontal row of chips."""
        items = self._items()
        if not items:
            return
        label_pt = max(11, min(18, w // 85))
        painter.setFont(QFont("Arial", label_pt, QFont.Bold))
        fm = painter.fontMetrics()
        pad_x = max(14, label_pt * 2)
        gap = max(8, label_pt)
        chip_h = int(label_pt * 3.0)

        captions = self._slot_captions() if self.page in ('load', 'save') else None

        widths = [fm.horizontalAdvance(label) + pad_x * 2 for _, label in items]
        if captions is not None:
            # A slot chip is at least as wide as the line describing what is in
            # it, so "village_walled_source 2026-09-07" reads rather than elides.
            painter.setFont(QFont("Arial", max(8, label_pt - 5)))
            cfm = painter.fontMetrics()
            for i, caption in enumerate(captions[:len(widths)]):
                if caption:
                    widths[i] = max(widths[i], cfm.horizontalAdvance(caption) + 12)
            painter.setFont(QFont("Arial", label_pt, QFont.Bold))
        total = sum(widths) + gap * (len(items) - 1)
        x = (w - total) // 2

        for i, ((key, label), cw) in enumerate(zip(items, widths)):
            rect = QRect(x, row_y, cw, chip_h)
            self._hit_rects.append((i, rect))
            selected = (i == self.index)
            empty = bool(captions and i < SLOT_COUNT
                         and self._slots()[i] is None and self.page == 'load')

            painter.setPen(QPen(_ACCENT if selected else _CHIP_BORDER, 2))
            painter.setBrush(QBrush(_ACCENT if selected else _CHIP_BG))
            painter.drawRoundedRect(rect, 6, 6)

            painter.setFont(QFont("Arial", label_pt, QFont.Bold))
            painter.setPen(_CHIP_SEL_TEXT if selected
                           else (_CAPTION if empty else _CHIP_TEXT))
            painter.drawText(rect, Qt.AlignCenter, label)

            # Slot pages caption each chip with what is actually in the slot.
            if captions is not None and i < len(captions) and captions[i]:
                painter.setFont(QFont("Arial", max(8, label_pt - 5)))
                cfm = painter.fontMetrics()
                text = cfm.elidedText(captions[i], Qt.ElideRight, cw + gap)
                painter.setPen(_CAPTION)
                painter.drawText(x + (cw - cfm.horizontalAdvance(text)) // 2,
                                 row_y + chip_h + max(14, label_pt), text)
            x += cw + gap

    def _slot_captions(self):
        """One short line per slot: the map and when it was saved, or 'Empty'."""
        out = []
        for info in self._slots():
            if not info:
                out.append("Empty")
                continue
            map_name = os.path.splitext(os.path.basename(
                str(info.get('map', '')) or 'Unknown'))[0]
            when = str(info.get('saved_at', '')).replace('T', ' ')[:16]
            out.append(f"{map_name}  {when}".strip())
        out.append("")   # BACK has no caption
        return out
