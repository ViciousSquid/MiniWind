"""
Play-mode pause menu.

Escape during play raises this menu instead of ending the game. It freezes the
world, blurs the frame that was on screen when the player hit Escape, and
paints a ``P A U S E D`` banner over it with one row of options across the
screen, in the manner of a classic RPG title menu:

    RESUME   GAME v   MUSIC: ON   EDITOR   QUIT
                NEW GAME
                LOAD GAME
                SAVE GAME

``GAME`` is a dropdown (its arrow points down while folded, up while open)
holding the three things done to a whole game.

Its ``LOAD GAME`` and ``SAVE GAME`` open a page of three save slots, ``MUSIC``
switches the game's background music on and off on the spot, and anything
destructive (starting over, loading, overwriting an occupied slot, leaving for
the editor, quitting) asks a plain ``SURE?`` before it happens.

The menu is drawn with the same ``QPainter`` pass the HUD uses, so it needs no
widgets and no layout. MiniWind installs one on the 3D view as its
``play_menu`` (see :func:`game.integration._patch_play_menu`); the view feeds
it key and mouse events while it is active and paints it last, so nothing
paints over it. What the options *do* is supplied by an actions object
(:class:`game.ui.pause_actions.PauseActions`), which owns the level, play mode,
the saves and the music.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtGui import QBrush, QColor, QFont, QLinearGradient, QPolygon


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
_CHIP_TEXT = QColor(196, 196, 200)
_CHIP_SEL_TEXT = QColor(255, 255, 255)
_SUBTLE = QColor(160, 160, 168)
_CAPTION = QColor(140, 140, 148)
_CAPTION_SEL = QColor(236, 210, 214)


#: The world-pause owner key the menu holds while it is open.
PAUSE_OWNER = "pause_menu"

#: Keys that move the highlight back / forward along the row of options.
_PREV_KEYS = (Qt.Key_Left, Qt.Key_A)
_NEXT_KEYS = (Qt.Key_Right, Qt.Key_D, Qt.Key_Tab)
#: Keys that move up / down a dropdown list (and open one from its header).
_UP_KEYS = (Qt.Key_Up, Qt.Key_W)
_DOWN_KEYS = (Qt.Key_Down, Qt.Key_S)


class PauseMenu:
    """Escape-menu state machine, renderer and input handler for play mode."""

    #: Top-level options, left to right. ``options`` opens the settings page;
    #: ``game`` is the header of the :data:`GAME_ITEMS` dropdown.
    ROOT_ITEMS = (
        ('resume', 'RESUME'),
        ('map', 'MAP'),
        ('game', 'GAME'),
        ('options', 'OPTIONS'),
        ('editor', 'EDITOR'),
        ('quit', 'QUIT'),
    )

    #: The GAME dropdown, top to bottom.
    GAME_ITEMS = (
        ('new', 'NEW GAME'),
        ('load', 'LOAD GAME'),
        ('save', 'SAVE GAME'),
    )

    def __init__(self, view, actions=None):
        self.view = view
        #: What the options do; defaults to the view's editor window, which
        #: is what the menu talked to before the actions moved into the game.
        self._actions = actions
        self.active = False
        #: 'root' | 'load' | 'save' | 'confirm'
        self.page = 'root'
        self.index = 0
        self._background = None          # blurred QPixmap of the paused frame
        self._hit_rects = []             # [(index, QRect)] for the current page
        self._pending = None             # (callable, prompt, detail) awaiting SURE?
        self._return_state = ('root', 0, False, 0)
        self._slot_cache = None
        from .options_page import OptionsPage
        #: The OPTIONS page (game/ui/options_page.py).
        self.options = OptionsPage(self)
        from .map_page import MapPage
        #: The MAP page (game/ui/map_page.py).
        self.map = MapPage(self)
        #: Whether MAP was opened straight from play (M, Show on map): then
        #: leaving it resumes the game rather than showing the menu.
        self._map_direct = False
        #: Whether the GAME dropdown is open, and its highlighted entry.
        self.expanded = False
        self.sub_index = 0
        self._drop_rects = []            # [(sub index, QRect)] of the dropdown

    # ------------------------------------------------------------------ owner
    @property
    def editor(self):
        return getattr(self.view, 'editor', None)

    @property
    def actions(self):
        return self._actions if self._actions is not None else self.editor

    # --------------------------------------------------------------- lifecycle
    def open(self):
        """Freeze the world and raise the menu over a blurred still of the frame."""
        if self.active:
            return
        self._background = self._grab_blurred_frame()
        self.active = True
        self.page = 'root'
        self.index = 0
        self.expanded = False
        self.sub_index = 0
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
        self.expanded = False
        self._pending = None
        self._background = None
        self._hit_rects = []
        self._drop_rects = []
        self._set_world_paused(False)
        closed = getattr(self.view, 'play_menu_closed', None)
        if closed is not None:
            try:
                closed()
            except Exception:
                pass
        self.view.update()

    def _set_world_paused(self, paused: bool):
        """Freeze / thaw the simulation while the menu is on screen.

        Holds the menu's own world-pause request on the logic thread
        (``LogicThread.set_world_paused``), so the game's screens and the
        actor picker, which hold theirs, can neither thaw the world behind
        the menu nor be thawed by it closing.
        """
        lt = getattr(self.view, 'logic_thread', None)
        set_paused = getattr(lt, 'set_world_paused', None)
        if set_paused is not None:
            set_paused(PAUSE_OWNER, bool(paused))

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
        if self.page == 'options':
            return 'OPTIONS'
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
            reader = getattr(self.actions, 'pause_menu_slot_info', None)
            try:
                self._slot_cache = reader() if reader else [None] * SLOT_COUNT
            except Exception:
                self._slot_cache = [None] * SLOT_COUNT
        return self._slot_cache

    # ------------------------------------------------------------------- input
    def _root_key(self):
        """Key of the highlighted option on the root row."""
        keys = [key for key, _ in self.ROOT_ITEMS]
        return keys[max(0, min(self.index, len(keys) - 1))]

    def _set_index(self, index):
        """Highlight row option *index*; moving off GAME folds its dropdown."""
        self.index = index
        if self.page == 'root' and self._root_key() != 'game':
            self.expanded = False

    def toggle_dropdown(self, open_it=None):
        """Open or fold the GAME dropdown (highlighting GAME as it opens)."""
        keys = [key for key, _ in self.ROOT_ITEMS]
        self.expanded = (not self.expanded) if open_it is None else bool(open_it)
        if self.expanded:
            self.index = keys.index('game')
            self.sub_index = 0
        self.view.update()

    def handle_key(self, event) -> bool:
        """Consume one key press. Returns True when the menu handled it."""
        if not self.active:
            return False
        key = event.key()
        if self.page == 'options':
            self.options.handle_key(key)
            return True
        if self.page == 'map':
            self.map.handle_key(key)
            return True
        items = self._items()
        if self.page == 'root' and self.expanded:
            # The open dropdown takes the keys until it folds.
            if key in _UP_KEYS:
                self.sub_index = (self.sub_index - 1) % len(self.GAME_ITEMS)
            elif key in _DOWN_KEYS:
                self.sub_index = (self.sub_index + 1) % len(self.GAME_ITEMS)
            elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.activate_game_item(self.GAME_ITEMS[self.sub_index][0])
                return True
            elif key == Qt.Key_Escape:
                self.expanded = False
            elif key in _PREV_KEYS or key in _NEXT_KEYS:
                step = -1 if key in _PREV_KEYS else 1
                self._set_index((self.index + step) % len(items))
            self.view.update()
            return True
        if key in _PREV_KEYS or (key in _UP_KEYS and self.page != 'root'):
            if items:
                self._set_index((self.index - 1) % len(items))
            self.view.update()
            return True
        if key in _NEXT_KEYS or (key in _DOWN_KEYS and self.page != 'root'):
            if items:
                self._set_index((self.index + 1) % len(items))
            self.view.update()
            return True
        if key in _DOWN_KEYS and self.page == 'root' and self._root_key() == 'game':
            self.toggle_dropdown(True)
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

    def _dropdown_at(self, pos):
        if not (self.page == 'root' and self.expanded):
            return None
        for sub, rect in self._drop_rects:
            if rect.contains(pos):
                return sub
        return None

    def handle_mouse_move(self, event) -> bool:
        if not self.active:
            return False
        if self.page == 'options':
            self.options.handle_mouse_move(event.pos(), event.buttons())
            return True
        if self.page == 'map':
            self.map.handle_mouse_move(event.pos(), event.buttons())
            return True
        sub = self._dropdown_at(event.pos())
        if sub is not None:
            if sub != self.sub_index:
                self.sub_index = sub
                self.view.update()
            return True
        for idx, rect in self._hit_rects:
            if rect.contains(event.pos()):
                if idx != self.index:
                    self._set_index(idx)
                    self.view.update()
                break
        return True

    def handle_mouse_press(self, event) -> bool:
        if not self.active:
            return False
        if event.button() != Qt.LeftButton:
            return True
        if self.page == 'options':
            self.options.handle_mouse_press(event.pos())
            return True
        if self.page == 'map':
            self.map.handle_mouse_press(event.pos())
            return True
        sub = self._dropdown_at(event.pos())
        if sub is not None:
            self.sub_index = sub
            self.activate_game_item(self.GAME_ITEMS[sub][0])
            return True
        for idx, rect in self._hit_rects:
            if rect.contains(event.pos()):
                self._set_index(idx)
                self.activate()
                return True
        # A click anywhere else folds an open dropdown.
        if self.expanded:
            self.expanded = False
            self.view.update()
        return True

    def handle_mouse_release(self, event=None) -> bool:
        if not self.active:
            return False
        if self.page == 'options':
            self.options.handle_mouse_release()
        elif self.page == 'map':
            self.map.handle_mouse_release()
        return True

    def handle_wheel(self, event) -> bool:
        if not self.active:
            return False
        if self.page == 'map':
            self.map.handle_wheel(event.pos(), event.angleDelta().y())
        return True

    def open_map(self, focus=None):
        """Open straight onto the MAP page (M in play, or a quest's *Show on
        map*), on the player or on *focus* = ``(x, z, label)``."""
        was_open = self.active
        if not was_open:
            self.open()
        self._map_direct = not was_open
        self.page = 'map'
        self.expanded = False
        self.map.open(focus)
        self.view.update()

    def _leave_map(self):
        """Back from MAP: to the game when it was opened from play, else to
        the root row on MAP."""
        if self._map_direct:
            self._map_direct = False
            self.close()
            return
        self.page = 'root'
        keys = [key for key, _ in self.ROOT_ITEMS]
        self.index = keys.index('map')
        self.view.update()

    def _leave_options(self):
        """Back from OPTIONS to the root row, on OPTIONS."""
        self.page = 'root'
        keys = [key for key, _ in self.ROOT_ITEMS]
        self.index = keys.index('options')
        self.view.update()

    def back(self):
        """Escape: fold the dropdown, leave a sub-page, or leave the menu."""
        if self.page == 'options':
            self._leave_options()
            return
        if self.page == 'map':
            self._leave_map()
            return
        if self.page == 'confirm':
            (self.page, self.index, self.expanded,
             self.sub_index) = self._return_state
            self._pending = None
            self.view.update()
            return
        if self.page in ('load', 'save'):
            self._to_game_item(self.page)
            return
        if self.expanded:
            self.expanded = False
            self.view.update()
            return
        self.close()

    def _to_game_item(self, item_key):
        """Back to the root row with the GAME dropdown open on *item_key*."""
        self.page = 'root'
        self.toggle_dropdown(True)
        keys = [key for key, _ in self.GAME_ITEMS]
        self.sub_index = keys.index(item_key) if item_key in keys else 0
        self.view.update()

    def activate_game_item(self, key):
        """Perform an entry of the GAME dropdown."""
        if key in ('load', 'save'):
            self.page = key
            self.index = 0
            self.expanded = False
            self._slot_cache = None
            self.view.update()
        elif key == 'new':
            self._confirm("Start a new game?",
                          "Unsaved progress will be lost.", self._do_new_game)

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
                self._to_game_item(self.page)
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
                                  f"Saved {_when(info)}.",
                                  lambda s=slot: self._do_save(s))
            return

        # Root page. Choosing GAME opens or folds its dropdown; anything else
        # folds it. (Enter inside an open dropdown is handled by handle_key.)
        if key == 'game':
            self.toggle_dropdown()
            return
        self.expanded = False
        if key == 'resume':
            self.close()
        elif key == 'options':
            self.page = 'options'
            self.options.open()
            self.view.update()
        elif key == 'map':
            self._map_direct = False
            self.page = 'map'
            self.map.open()
            self.view.update()
        elif key == 'editor':
            self._confirm("Leave for the editor?",
                          "The game ends and the editor opens this map.",
                          self._do_editor)
        elif key == 'quit':
            self._confirm("Quit to desktop?",
                          "Unsaved progress will be lost.", self._do_quit)

    def _confirm(self, title, detail, action):
        self._return_state = (self.page, self.index, self.expanded,
                              self.sub_index)
        self._pending = (action, title, detail)
        self.page = 'confirm'
        self.expanded = False
        self.index = 1          # default to NO — the safe answer
        self.view.update()

    # ----------------------------------------------------------------- actions
    def _call_action(self, name, *args):
        fn = getattr(self.actions, name, None)
        if fn is None:
            return False
        try:
            fn(*args)
            return True
        except Exception:
            import traceback
            traceback.print_exc()
            try:
                from editor.debug_console import debug_log
                debug_log("Error", f"Pause menu: {name} failed.")
            except Exception:
                pass
            return False

    def _do_save(self, slot):
        self._slot_cache = None
        self._call_action('pause_menu_save_slot', slot)
        self.close()

    def _do_load(self, slot):
        self._slot_cache = None
        # Close first: loading replays the level and re-enters play mode, and the
        # blurred still behind the menu would be of the *old* session.
        self.close()
        self._call_action('pause_menu_load_slot', slot)

    def _do_new_game(self):
        self.close()
        self._call_action('pause_menu_new_game')

    def _do_editor(self):
        self.close()
        self._call_action('pause_menu_to_editor')

    def _do_quit(self):
        self.close()
        self._call_action('pause_menu_quit')

    # ------------------------------------------------------------------- paint
    def draw(self, painter):
        """Paint the whole overlay. Called last in the frame's painter pass.

        Laid out like a classic RPG title menu: the banner above, then one
        horizontal row of plain-text options on a dark ribbon across the
        screen. The highlighted option is bright with a crimson rule under it;
        the rest are muted.
        """
        if not self.active:
            return
        w, h = self.view.width(), self.view.height()
        self._hit_rects = []

        # Blurred still of the frame the player paused on, then a dark scrim so
        # the menu reads at any brightness.
        if self._background is not None:
            painter.drawPixmap(QRect(0, 0, w, h), self._background)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(10, 10, 14, 150)))
        painter.drawRect(0, 0, w, h)

        if self.page == 'map':
            self.map.draw(painter, w, h, _text_font, _display_font)
            return

        # --- banner ---
        title_size = max(24, min(72, w // 20, h // 10))
        painter.setFont(_display_font(title_size))
        fm = painter.fontMetrics()
        title = _shown_title()
        tw = fm.horizontalAdvance(title)
        tx = (w - tw) // 2
        # The options need the room below the banner, so it sits higher there.
        ty = int(h * (0.20 if self.page == 'options' else 0.34))
        painter.setPen(_TITLE_SHADOW)
        painter.drawText(tx + 4, ty + 4, title)
        painter.setPen(_TITLE)
        painter.drawText(tx, ty, title)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_ACCENT))
        painter.drawRect(tx, ty + int(title_size * 0.30), tw, max(2, title_size // 18))

        if self.page == 'options':
            self._hit_rects = []
            heading = _shown(self._heading())
            painter.setFont(_display_font(max(12, min(20, w // 70))))
            fm = painter.fontMetrics()
            hy = ty + int(title_size * 0.30) + fm.height() + 16
            painter.setPen(_SUBTLE)
            painter.drawText((w - fm.horizontalAdvance(heading)) // 2, hy, heading)
            self.options.draw(painter, w, h, hy + 14, _text_font, _display_font)
            painter.setFont(_text_font(max(9, min(12, w // 130))))
            fm = painter.fontMetrics()
            hint = ("\u2191 \u2193  choose      \u2190 \u2192  change      "
                    "Enter  set      Esc  back")
            painter.setPen(_CAPTION)
            painter.drawText((w - fm.horizontalAdvance(hint)) // 2,
                             h - max(18, h // 25), hint)
            return

        row_y = int(h * 0.56)

        # --- page heading (LOAD GAME / SAVE GAME / SURE?) ---
        heading = _shown(self._heading())
        if heading:
            painter.setFont(_display_font(max(12, min(20, w // 70))))
            fm = painter.fontMetrics()
            painter.setPen(_ACCENT if self.page == 'confirm' else _SUBTLE)
            painter.drawText((w - fm.horizontalAdvance(heading)) // 2,
                             row_y - int(h * 0.09), heading)

        # A confirm page explains what it is about to do, between the heading
        # and YES / NO.
        if self.page == 'confirm' and self._pending is not None:
            _, prompt, detail = self._pending
            painter.setFont(_display_font(max(11, min(17, w // 90))))
            fm = painter.fontMetrics()
            painter.setPen(_TITLE)
            py = row_y - int(h * 0.09) + fm.height() + 8
            painter.drawText((w - fm.horizontalAdvance(prompt)) // 2, py, prompt)
            painter.setFont(_text_font(max(9, min(12, w // 130))))
            fm = painter.fontMetrics()
            painter.setPen(_CAPTION)
            painter.drawText((w - fm.horizontalAdvance(detail)) // 2,
                             py + fm.height() + 4, detail)
            row_y = max(row_y, py + fm.height() + 28)

        self._draw_option_row(painter, w, h, row_y)

        # --- key hints ---
        painter.setFont(_text_font(max(9, min(12, w // 130))))
        fm = painter.fontMetrics()
        if self.page == 'root' and self.expanded:
            hint = "\u2191 \u2193  select      Enter  choose      Esc  close"
        else:
            hint = ("\u2190 \u2192  select      Enter  choose      "
                    + ("Esc  back" if self.page != 'root' else "Esc  resume"))
        painter.setPen(_CAPTION)
        painter.drawText((w - fm.horizontalAdvance(hint)) // 2,
                         h - max(18, h // 25), hint)

    def _draw_option_row(self, painter, w, h, row_y):
        """Lay the page's options out as one centred horizontal row of words."""
        items = [(key, _shown(label)) for key, label in self._items()]
        if not items:
            return
        captions = self._slot_captions() if self.page in ('load', 'save') else None

        # Largest type that fits the row in the window, gaps included.
        label_pt = max(10, min(22, w // 60, h // 28))
        while True:
            painter.setFont(_display_font(label_pt))
            fm = painter.fontMetrics()
            gap = max(16, label_pt * 2)
            arrow_w = self._arrow_width(label_pt)
            widths = [fm.horizontalAdvance(label)
                      + (arrow_w if self._has_dropdown(key) else 0)
                      for key, label in items]
            if captions:
                cap_font = _text_font(max(8, label_pt - 7))
                painter.setFont(cap_font)
                cfm = painter.fontMetrics()
                widths = [max([lw] + [cfm.horizontalAdvance(line)
                                      for line in (c or '').split('\n')])
                          for lw, c in zip(widths, captions)]
                painter.setFont(_display_font(label_pt))
            total = sum(widths) + gap * (len(items) - 1)
            if total <= w - 48 or label_pt <= 8:
                break
            label_pt -= 1

        text_h = fm.height()
        cap_h = 0
        if captions:
            painter.setFont(_text_font(max(8, label_pt - 7)))
            lines = max(len((c or '').split('\n')) for c in captions)
            cap_h = painter.fontMetrics().height() * lines + 4
            painter.setFont(_display_font(label_pt))
        pad_y = max(10, label_pt // 2 + 4)
        band_h = text_h + cap_h + pad_y * 2 + 6

        # The ribbon: a dark band across the whole screen, hairlines above and
        # below fading toward the edges.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(8, 8, 12, 190)))
        painter.drawRect(0, row_y, w, band_h)
        line = QLinearGradient(0, 0, w, 0)
        line.setColorAt(0.0, QColor(196, 196, 200, 0))
        line.setColorAt(0.5, QColor(196, 196, 200, 120))
        line.setColorAt(1.0, QColor(196, 196, 200, 0))
        painter.setBrush(QBrush(line))
        painter.drawRect(0, row_y, w, 1)
        painter.drawRect(0, row_y + band_h - 1, w, 1)

        x = (w - total) // 2
        drop_anchor = None
        for i, ((key, label), cw) in enumerate(zip(items, widths)):
            selected = (i == self.index)
            empty = bool(captions and self.page == 'load' and i < SLOT_COUNT
                         and self._slots()[i] is None)
            # The click target is the whole slice of ribbon the word owns.
            hit = QRect(x - gap // 2, row_y, cw + gap, band_h)
            self._hit_rects.append((i, hit))

            painter.setFont(_display_font(label_pt))
            fm = painter.fontMetrics()
            dropdown = self._has_dropdown(key)
            tw = fm.horizontalAdvance(label)
            lw = tw + (arrow_w if dropdown else 0)
            lx = x + (cw - lw) // 2
            base = row_y + pad_y + fm.ascent()
            colour = (_CHIP_SEL_TEXT if selected
                      else (_CAPTION if empty else _CHIP_TEXT))
            if selected:
                painter.setPen(_TITLE_SHADOW)
                painter.drawText(lx + 2, base + 2, label)
            painter.setPen(colour)
            painter.drawText(lx, base, label)
            if dropdown:
                # Down while folded, up while open.
                self._draw_arrow(painter, lx + tw + arrow_w // 2 + 1,
                                 base - fm.ascent() // 2 + 1, label_pt,
                                 up=self.expanded, colour=colour)
                drop_anchor = (x, cw, row_y + band_h, label_pt)
            if selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(_ACCENT))
                painter.drawRect(lx, base + max(4, label_pt // 4), lw,
                                 max(2, label_pt // 8))

            if captions and i < len(captions) and captions[i]:
                painter.setFont(_text_font(max(8, label_pt - 7)))
                cfm = painter.fontMetrics()
                painter.setPen(_CAPTION_SEL if selected else _CAPTION)
                cy = base + fm.descent() + 8 + cfm.ascent()
                for line in captions[i].split('\n'):
                    text = cfm.elidedText(line, Qt.ElideRight, cw + gap - 8)
                    painter.drawText(x + (cw - cfm.horizontalAdvance(text)) // 2,
                                     cy, text)
                    cy += cfm.height()
            x += cw + gap

        self._drop_rects = []
        if self.page == 'root' and self.expanded and drop_anchor is not None:
            self._draw_dropdown(painter, w, h, *drop_anchor)

    def _game_labels(self):
        return [(key, _shown(label)) for key, label in self.GAME_ITEMS]

    def _has_dropdown(self, key):
        return self.page == 'root' and key == 'game'

    @staticmethod
    def _arrow_width(label_pt):
        return max(14, int(label_pt * 1.3))

    @staticmethod
    def _draw_arrow(painter, cx, cy, label_pt, up, colour):
        """A small solid triangle centred on (cx, cy), pointing up or down."""
        half = max(4, int(label_pt * 0.38))
        tall = max(3, int(label_pt * 0.32))
        if up:
            points = [QPoint(cx - half, cy + tall), QPoint(cx + half, cy + tall),
                      QPoint(cx, cy - tall)]
        else:
            points = [QPoint(cx - half, cy - tall), QPoint(cx + half, cy - tall),
                      QPoint(cx, cy + tall)]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawPolygon(QPolygon(points))

    def _draw_dropdown(self, painter, w, h, x, cw, top, label_pt):
        """The GAME list, hanging from the ribbon under its header."""
        painter.setFont(_display_font(max(9, label_pt - 3)))
        fm = painter.fontMetrics()
        pad_x = max(18, label_pt)
        # Rows sized by the capitals, not the face's line height: display
        # faces often carry a tall line gap that would space the list out.
        item_h = max(int(label_pt * 1.8), int(fm.capHeight() * 2.6))
        width = max(cw + pad_x, max(fm.horizontalAdvance(label)
                                    for _, label in self._game_labels()) + pad_x * 2)
        left = max(8, min(w - width - 8, x + (cw - width) // 2))
        height = item_h * len(self.GAME_ITEMS)
        top = min(top, h - height - max(40, h // 12))   # clear of the key hints

        panel = QRect(left, top, width, height)
        painter.setPen(QColor(196, 196, 200, 90))
        painter.setBrush(QBrush(QColor(8, 8, 12, 235)))
        painter.drawRect(panel)
        for i, (_, label) in enumerate(self._game_labels()):
            rect = QRect(left, top + i * item_h, width, item_h)
            self._drop_rects.append((i, rect))
            selected = (i == self.sub_index)
            if selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(196, 30, 58, 70)))
                painter.drawRect(rect.adjusted(1, 1, 0, 0))
                painter.setBrush(QBrush(_ACCENT))
                painter.drawRect(rect.x() + 1, rect.y() + 1, 3, rect.height() - 1)
            painter.setPen(_CHIP_SEL_TEXT if selected else _CHIP_TEXT)
            # Centre on the capitals: the face's own line box may sit off-centre.
            painter.drawText(rect.x() + (width - fm.horizontalAdvance(label)) // 2,
                             rect.y() + (item_h + fm.capHeight()) // 2, label)

    def _slot_captions(self):
        """Per slot: who was saved (or the map) over when, or 'Empty'."""
        out = []
        for info in self._slots():
            if not info:
                out.append("Empty")
                continue
            map_name = os.path.splitext(os.path.basename(
                str(info.get('map', '')) or 'Unknown'))[0]
            out.append(f"{info.get('summary') or map_name}\n{_when(info)}")
        out.append("")   # BACK has no caption
        return out


def _display_font(pt):
    """The face for the banner and the options (see :mod:`game.ui.fonts`).

    Enchanted Land when it is installed, a little larger as its letters are
    small for their size and without a synthetic bold; bold Arial otherwise.
    """
    from . import fonts
    family = fonts.menu_family()
    if family == fonts.FALLBACK_FAMILY:
        return QFont(family, int(pt), QFont.Bold)
    size = max(1, int(round(pt * DISPLAY_SCALE)))
    font = QFont(family, size)
    # Enchanted Land's own space is a hairline: "NEW GAME" read "NEWGAME".
    font.setWordSpacing(size * DISPLAY_WORD_SPACING)
    return font


#: How much larger the installed display face is set than Arial would be,
#: and the extra room given to each space, as a share of its size.
DISPLAY_SCALE = 1.3
DISPLAY_WORD_SPACING = 0.4


def _display_face_installed() -> bool:
    from . import fonts
    return fonts.menu_family() != fonts.FALLBACK_FAMILY


def _text_font(pt):
    """Small print (captions, details, key hints): MedievalSharp, the game's
    reading face, when installed; Arial otherwise."""
    from . import fonts
    family = fonts.dialogue_family()
    if family == fonts.DIALOGUE_FALLBACK:
        return QFont(fonts.FALLBACK_FAMILY, int(pt))
    return QFont(family, int(pt) + 1)


def _shown(label):
    """*label* as drawn: Title Case in the blackletter face, which is hard to
    read in capitals ("New Game"), else as written ("NEW GAME")."""
    if not label or not _display_face_installed():
        return label
    return " ".join(word[:1].upper() + word[1:].lower() for word in label.split(" "))


def _shown_title():
    """The banner: letter-spaced capitals in Arial, plain "Paused" in the
    display face, whose letters already carry the weight."""
    return "Paused" if _display_face_installed() else "P A U S E D"


def _when(info) -> str:
    """A slot's save time as ``YYYY-MM-DD HH:MM``."""
    return str((info or {}).get('saved_at', '') or '?').replace('T', ' ')[:16]
