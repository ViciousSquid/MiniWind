"""
The pause menu's OPTIONS page.

Graphics settings are the launcher's own (:mod:`game.ui.launcher`): the same
:class:`~game.ui.launcher.DisplaySettings`, the same list of window modes and
the same resolutions, read and written through the same code, so the two can
never disagree. A change to the window mode or resolution shows at once in a
game played from the launcher (``MainWindow.apply_kiosk_display_mode``);
vertical sync and high-DPI scaling are fixed when the application starts and
say so. Below them is the music volume, a slider where 0% is off.

ADVANCED ▸ GRAPHICS holds the grass: a slider of four stops (Off, Low, Medium,
High -- the launcher's choices too) that changes the game at once, while it is
dragged: the renderer is told, and the terrain regrows its grass.

The page is painted with QPainter inside the pause menu and driven by it: the
arrow keys (up / down a row, left / right to change it), Enter, Esc, and the
mouse (the ◀ ▶ arrows, a click on a value, a click or drag on the slider).
"""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPen

#: How far one step of the volume slider moves (Left / Right).
VOLUME_STEP = 0.05

_ACCENT = QColor(196, 30, 58)
_TEXT = QColor(220, 216, 210)
_VALUE = QColor(240, 236, 230)
_DIM = QColor(130, 130, 138)
_NOTE = QColor(200, 170, 90)
_PANEL = QColor(8, 8, 12, 205)
_ROW_SEL = QColor(196, 30, 58, 60)


class OptionsPage:
    """State, input and painting of the options; owned by a PauseMenu."""

    def __init__(self, menu):
        self.menu = menu
        self.index = 0
        self.settings = None
        self._hits = []           # [(QRectF, action)] of the last paint
        self._sliders = {}        # {row key: QRectF} of the slider tracks
        self._dragging = False
        self._next_launch = set() # keys changed that apply next launch
        #: The key bindings list is showing, and the action waiting for its
        #: new key (None when none is).
        self.keys_mode = False
        self.capture = None
        #: The action waiting for its new gamepad button (None when none is):
        #: game.gamepad hands the next button pressed to capture_pad.
        self.capture_pad = None
        #: The sub-page showing: None (the options), "advanced" or "graphics".
        self.section = None

    # -- data -------------------------------------------------------------
    def open(self):
        reader = getattr(self.menu.actions, "pause_menu_display_settings", None)
        try:
            self.settings = reader() if reader is not None else None
        except Exception:
            self.settings = None
        self.index = 0
        self._dragging = False
        self.section = None

    def _volume(self) -> float:
        reader = getattr(self.menu.actions, "pause_menu_music_volume", None)
        try:
            return float(reader()) if reader is not None else 0.0
        except Exception:
            return 0.0

    def _set_volume(self, value):
        value = max(0.0, min(1.0, round(float(value) / VOLUME_STEP) * VOLUME_STEP))
        self.menu._call_action("pause_menu_set_music_volume", value)
        self.menu.view.update()

    def _config(self):
        reader = getattr(self.menu.actions, "pause_menu_config", None)
        try:
            return reader() if reader is not None else (None, None)
        except Exception:
            return None, None

    def _key_rows(self):
        import game.keybinds as keybinds
        config, _save = self._config()
        keys = keybinds.current(config)
        rows = []
        for action, label, _const, _default in keybinds.ACTIONS:
            value = "Press a key…" if self.capture == action else keybinds.label(keys[action])
            rows.append(("bind:" + action, label, value, True))
        rows.append(("pad_header", "Gamepad buttons", "", False))
        import game.controls as controls
        buttons = keybinds.current_pad(config)
        pad_actions = [(a, lab) for a, lab, _c, _d in keybinds.ACTIONS]
        pad_actions += [(a, lab) for a, lab, _b in keybinds.PAD_ONLY]
        for action, label in pad_actions:
            button = buttons.get(action, "")
            value = ("Press a button…" if self.capture_pad == action
                     else controls.PAD_LABELS.get(button, "—") if button else "—")
            rows.append(("pad:" + action, label, value, True))
        rows.append(("pad_hands", "Left / right hand", "LT / RT", False))
        rows.append(("keys_reset", "Reset to defaults", "", True))
        rows.append(("keys_back", "Back", "", True))
        return rows

    def capture_pad_button(self, button) -> None:
        """The gamepad button pressed while an action waited for one: bound
        to it (an action already on it swaps over); B or Start cancels."""
        action, self.capture_pad = self.capture_pad, None
        if action is not None and button not in ("start",):
            import game.keybinds as keybinds
            config, save = self._config()
            if button in keybinds.PAD_BUTTONS:
                keybinds.bind_pad(config, action, button, save)
        self.menu.view.update()

    def rows(self):
        """``[(key, label, value text, enabled)]`` top to bottom."""
        if self.keys_mode:
            return self._key_rows()
        import game.ui.launcher as launcher
        s = self.settings
        if self.section == "advanced":
            return [("graphics", "Graphics", "▸", True),
                    ("advanced_back", "Back", "", True)]
        if self.section == "graphics":
            rows = []
            if s is not None:
                rows.append(("grass", "Grass", launcher.grass_label(s.grass), True))
            rows.append(("graphics_back", "Back", "", True))
            return rows
        rows = []
        if s is not None:
            mode = s.mode
            w, h = s.resolution
            rows.append(("mode", "Display", launcher.mode_label(mode), True))
            rows.append(("res", "Resolution", f"{w} × {h}", mode == "Windowed"))
            rows.append(("vsync", "Vertical sync", "On" if s.vsync else "Off", True))
            rows.append(("hidpi", "High DPI scaling", "On" if s.high_dpi else "Off", True))
        volume = self._volume()
        rows.append(("volume", "Music volume",
                     "OFF" if volume <= 0.0 else f"{int(round(volume * 100))}%", True))
        rows.append(("keys", "Key bindings", "▸", True))
        rows.append(("hud", "Rearrange HUD", "▸", True))
        rows.append(("advanced", "Advanced", "▸", True))
        rows.append(("back", "Back", "", True))
        return rows

    def _note(self, key):
        import game.ui.launcher as launcher
        s = self.settings
        if key == "mode" and s is not None:
            return launcher.mode_help(s.mode)
        if key == "res":
            if s is not None and s.mode != "Windowed":
                return "The resolution is for Windowed mode."
            return "The size of the game's window."
        if key in ("vsync", "hidpi"):
            text = ("Matches the display's refresh rate." if key == "vsync"
                    else "Scales the interface for a high-resolution screen.")
            return text + "  Takes effect next launch."
        if key == "grass" and s is not None:
            return launcher.grass_help(s.grass) + "  Drag or use ← →."
        if key == "advanced":
            return "Graphics: how much grass the world grows."
        if key == "graphics":
            return "Grass, changed while you play."
        if key == "volume":
            return "Drag or use ← →.  0% turns the music off."
        if key == "keys":
            return "Choose the key and the gamepad button for each action."
        if key == "hud":
            return "Drag the HUD's panels where you want them; ▼ hides one."
        if key.startswith("bind:"):
            return ("Press the new key (Esc cancels). A key already in use swaps over."
                    if self.capture else "Enter or click, then press the new key.")
        if key.startswith("pad:"):
            return ("Press the new button on the gamepad (Start or Esc cancels). "
                    "A button already in use swaps over."
                    if self.capture_pad else "A, Enter or click, then press the new button.")
        if key == "pad_hands":
            return "The triggers are always the left- and right-hand attack."
        if key == "keys_reset":
            return "Every action back on its usual key."
        return ""

    # -- changes ----------------------------------------------------------
    def _save(self, mode=None, res=None, vsync=None, hidpi=None, grass=None):
        s = self.settings
        if s is None:
            return
        w, h = res if res is not None else s.resolution
        s.save(mode if mode is not None else s.mode, w, h,
               s.vsync if vsync is None else vsync,
               s.high_dpi if hidpi is None else hidpi, grass)

    def change(self, key, step=1):
        """Move the row *key* one step (left -1, right / Enter +1)."""
        import game.ui.launcher as launcher
        s = self.settings
        if key == "volume":
            self._set_volume(self._volume() + step * VOLUME_STEP)
            return
        if key == "back":
            self.menu._leave_options()
            return
        if key == "keys":
            self.keys_mode, self.capture, self.index = True, None, 0
            self.menu.view.update()
            return
        if key == "hud":
            # Back to the game, in rearrange mode (game/ui/hud_layout.py).
            if self.menu._call_action("pause_menu_rearrange_hud"):
                self.menu.close()
            return
        if key in ("advanced", "graphics", "advanced_back", "graphics_back"):
            self.section = {"advanced": "advanced", "graphics": "graphics",
                            "advanced_back": None, "graphics_back": "advanced"}[key]
            self.index = 0
            self.menu.view.update()
            return
        if key == "keys_back":
            self.keys_mode, self.capture, self.index = False, None, 0
            self.menu.view.update()
            return
        if key == "keys_reset":
            import game.keybinds as keybinds
            config, save = self._config()
            keybinds.reset(config, save)
            self.menu.view.update()
            return
        if key.startswith("bind:"):
            self.capture = key[5:]
            self.menu.view.update()
            return
        if key.startswith("pad:"):
            self.capture_pad = key[4:]
            self.menu.view.update()
            return
        if key in ("pad_header", "pad_hands"):
            return
        if s is None:
            return
        if key == "mode":
            values = [v for v, _l, _h in launcher.MODES]
            i = values.index(s.mode) if s.mode in values else 0
            self._save(mode=values[(i + step) % len(values)])
            self.menu._call_action("pause_menu_apply_display")
        elif key == "res":
            if s.mode != "Windowed":
                return
            choices = [(w, h) for w, h, _l in launcher.resolution_choices(s.resolution)]
            i = choices.index(tuple(s.resolution)) if tuple(s.resolution) in choices else 0
            self._save(res=choices[(i + step) % len(choices)])
            self.menu._call_action("pause_menu_apply_display")
        elif key == "vsync":
            self._save(vsync=not s.vsync)
        elif key == "hidpi":
            self._save(hidpi=not s.high_dpi)
        elif key == "grass":
            stops = self._grass_stops()
            i = stops.index(s.grass) if s.grass in stops else len(stops) - 1
            self._set_grass(stops[max(0, min(len(stops) - 1, i + step))])
        self.menu.view.update()

    @staticmethod
    def _grass_stops():
        """The grass slider's stops, left to right: Off … High."""
        import game.ui.launcher as launcher
        return [v for v, _l, _h in reversed(launcher.GRASS)]

    def _grass_fraction(self) -> float:
        stops = self._grass_stops()
        s = self.settings
        grass = s.grass if s is not None else stops[-1]
        return (stops.index(grass) if grass in stops else len(stops) - 1) / (len(stops) - 1)

    def _set_grass(self, grass):
        """Grass to *grass* now (and in settings.ini), if it is a change."""
        s = self.settings
        if s is None or grass == s.grass:
            return
        self._save(grass=grass)
        self.menu._call_action("pause_menu_apply_grass", grass)
        self.menu.view.update()

    def _slide(self, key, fraction):
        """A slider moved to *fraction* (0..1) of its track."""
        if key == "volume":
            self._set_volume(fraction)
        elif key == "grass":
            stops = self._grass_stops()
            self._set_grass(stops[int(round(fraction * (len(stops) - 1)))])

    # -- input ------------------------------------------------------------
    def handle_key(self, key):
        if self.capture_pad is not None:
            if key == Qt.Key_Escape:             # the keyboard can cancel it too
                self.capture_pad = None
                self.menu.view.update()
            return
        if self.capture is not None:
            # Waiting for the new key: Esc cancels, anything bindable binds.
            if key != Qt.Key_Escape:
                import game.keybinds as keybinds
                name = keybinds.key_name(key)
                if not name or name in keybinds.RESERVED:
                    return
                config, save = self._config()
                keybinds.bind(config, self.capture, name, save)
            self.capture = None
            self.menu.view.update()
            return
        rows = self.rows()
        if self.keys_mode and key == Qt.Key_Escape:
            self.change("keys_back")
            return
        if self.section is not None and key == Qt.Key_Escape:
            self.change(self.section + "_back")
            return
        if key in (Qt.Key_Up, Qt.Key_W):
            self.index = (self.index - 1) % len(rows)
        elif key in (Qt.Key_Down, Qt.Key_S, Qt.Key_Tab):
            self.index = (self.index + 1) % len(rows)
        elif key in (Qt.Key_Left, Qt.Key_A):
            self.change(rows[self.index][0], -1)
        elif key in (Qt.Key_Right, Qt.Key_D):
            self.change(rows[self.index][0], +1)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.change(rows[self.index][0], +1)
        elif key == Qt.Key_Escape:
            self.menu._leave_options()
            return
        self.menu.view.update()

    def _slider_value_at(self, x, key=None):
        track = self._sliders.get(key or self._dragging)
        if track is None or track.width() <= 0:
            return None
        return max(0.0, min(1.0, (x - track.left()) / track.width()))

    def handle_mouse_press(self, pos):
        point = QPointF(pos)
        for key, track in self._sliders.items():
            if track.adjusted(-6, -10, 6, 10).contains(point):
                self._dragging = key
                self._slide(key, self._slider_value_at(point.x(), key))
                return
        for rect, action in reversed(self._hits):
            if rect.contains(point):
                action()
                return

    def handle_mouse_move(self, pos, buttons):
        point = QPointF(pos)
        if self._dragging:
            if buttons & Qt.LeftButton:
                value = self._slider_value_at(point.x())
                if value is not None:
                    self._slide(self._dragging, value)
                return
            self._dragging = False
        for i, rect in enumerate(self._row_rects):
            if rect.contains(point) and i != self.index:
                self.index = i
                self.menu.view.update()
                break

    def handle_mouse_release(self):
        self._dragging = False

    # -- painting ---------------------------------------------------------
    _row_rects = ()

    def draw(self, painter, w, h, top, text_font, display_font):
        rows = self.rows()
        self.index = max(0, min(self.index, len(rows) - 1))
        self._hits = []
        self._sliders = {}
        row_rects = []
        label_pt = max(10, min(17, w // 90))
        row_h = int(label_pt * 2.6)
        panel_w = min(640, w - 64)
        x0 = (w - panel_w) // 2
        bottom_room = max(70, h // 9)
        avail = max(row_h * len(rows), h - top - bottom_room)
        row_h = min(row_h, max(20, avail // (len(rows) + 1)))
        panel = QRectF(x0, top, panel_w, row_h * len(rows) + row_h)

        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        painter.setPen(QPen(QColor(196, 196, 200, 70), 1))
        painter.setBrush(QBrush(_PANEL))
        painter.drawRoundedRect(panel, 6, 6)

        value_x = x0 + panel_w * 0.48
        value_w = panel_w * 0.48
        y = top + row_h * 0.25
        for i, (key, label, value, enabled) in enumerate(rows):
            rect = QRectF(x0 + 6, y, panel_w - 12, row_h)
            row_rects.append(rect)
            selected = i == self.index
            if selected:
                painter.fillRect(rect, _ROW_SEL)
                painter.fillRect(QRectF(rect.x(), rect.y(), 3, rect.height()), _ACCENT)
            painter.setFont(display_font(label_pt))
            painter.setPen(_VALUE if selected else (_TEXT if enabled else _DIM))
            painter.drawText(QRectF(rect.x() + 16, rect.y(), panel_w * 0.45, row_h),
                             int(Qt.AlignVCenter | Qt.AlignLeft), label)
            vrect = QRectF(value_x, rect.y(), value_w, row_h)
            if key == "volume":
                self._draw_slider(painter, key, vrect, self._volume(), value,
                                  self._volume() > 0, selected, text_font, label_pt)
            elif key == "grass":
                self._draw_slider(painter, key, vrect, self._grass_fraction(), value,
                                  True, selected, text_font, label_pt,
                                  stops=len(self._grass_stops()))
            elif key == "back":
                self._hits.append((rect, lambda: self.change("back")))
            else:
                self._draw_value(painter, key, vrect, value, enabled, selected,
                                 text_font, label_pt)
            y += row_h
        self._row_rects = row_rects

        # What the highlighted row does, under the panel.
        note = self._note(rows[self.index][0])
        if note:
            painter.setFont(text_font(max(9, label_pt - 3)))
            painter.setPen(_NOTE)
            painter.drawText(QRectF(x0, panel.bottom() + 8, panel_w, row_h),
                             int(Qt.AlignHCenter | Qt.AlignTop), note)
        painter.restore()

    def _draw_value(self, painter, key, rect, value, enabled, selected, text_font, pt):
        painter.setFont(text_font(pt))
        colour = _VALUE if enabled else _DIM
        arrow_w = rect.height() * 0.9
        left = QRectF(rect.x(), rect.y(), arrow_w, rect.height())
        right = QRectF(rect.right() - arrow_w, rect.y(), arrow_w, rect.height())
        middle = QRectF(left.right(), rect.y(), rect.width() - 2 * arrow_w, rect.height())
        painter.setPen(colour if selected else (_TEXT if enabled else _DIM))
        painter.drawText(middle, int(Qt.AlignCenter), value)
        if key in ("mode", "res"):
            painter.setPen(_ACCENT if (selected and enabled) else colour)
            painter.drawText(left, int(Qt.AlignCenter), "◀")
            painter.drawText(right, int(Qt.AlignCenter), "▶")
            if enabled:
                self._hits.append((left, lambda k=key: self.change(k, -1)))
                self._hits.append((right, lambda k=key: self.change(k, +1)))
                self._hits.append((middle, lambda k=key: self.change(k, +1)))
        elif enabled:
            self._hits.append((rect, lambda k=key: self.change(k, +1)))

    def _draw_slider(self, painter, key, rect, value, value_text, lit, selected,
                     text_font, pt, stops=None):
        """A slider at *value* (0..1); *stops* marks that many detents."""
        label_w = max(rect.width() * 0.22, rect.height() * 3.2)   # room for "Medium"
        track = QRectF(rect.x() + 4, rect.center().y() - 3, rect.width() - label_w - 14, 6)
        self._sliders[key] = track
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(60, 60, 70))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRectF(track.x(), track.y(), track.width() * value, track.height())
        painter.setBrush(_ACCENT)
        painter.drawRoundedRect(fill, 3, 3)
        if stops and stops > 1:
            painter.setBrush(QColor(150, 150, 160))
            for i in range(stops):
                painter.drawEllipse(QPointF(track.x() + track.width() * i / (stops - 1),
                                            track.center().y()), 2.5, 2.5)
        knob = QPointF(track.x() + track.width() * value, track.center().y())
        painter.setBrush(QColor(240, 236, 230) if selected else QColor(200, 196, 190))
        painter.setPen(QPen(QColor(20, 20, 24), 1))
        painter.drawEllipse(knob, 8, 8)
        painter.setFont(text_font(pt))
        painter.setPen(_VALUE if lit else _NOTE)
        painter.drawText(QRectF(track.right() + 10, rect.y(), label_w, rect.height()),
                         int(Qt.AlignVCenter | Qt.AlignLeft), value_text)
