"""
The pause menu's OPTIONS page.

Graphics settings are the launcher's own (:mod:`game.ui.launcher`): the same
:class:`~game.ui.launcher.DisplaySettings`, the same list of window modes and
the same resolutions, read and written through the same code, so the two can
never disagree. A change to the window mode or resolution shows at once in a
game played from the launcher (``MainWindow.apply_kiosk_display_mode``);
vertical sync and high-DPI scaling are fixed when the application starts and
say so. Below them is the music volume, a slider where 0% is off.

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
        self._slider = None       # QRectF of the volume track
        self._dragging = False
        self._next_launch = set() # keys changed that apply next launch

    # -- data -------------------------------------------------------------
    def open(self):
        reader = getattr(self.menu.actions, "pause_menu_display_settings", None)
        try:
            self.settings = reader() if reader is not None else None
        except Exception:
            self.settings = None
        self.index = 0
        self._dragging = False

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

    def rows(self):
        """``[(key, label, value text, enabled)]`` top to bottom."""
        from . import launcher
        s = self.settings
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
        rows.append(("back", "Back", "", True))
        return rows

    def _note(self, key):
        from . import launcher
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
        if key == "volume":
            return "Drag or use ← →.  0% turns the music off."
        return ""

    # -- changes ----------------------------------------------------------
    def _save(self, mode=None, res=None, vsync=None, hidpi=None):
        s = self.settings
        if s is None:
            return
        w, h = res if res is not None else s.resolution
        s.save(mode if mode is not None else s.mode, w, h,
               s.vsync if vsync is None else vsync,
               s.high_dpi if hidpi is None else hidpi)

    def change(self, key, step=1):
        """Move the row *key* one step (left -1, right / Enter +1)."""
        from . import launcher
        s = self.settings
        if key == "volume":
            self._set_volume(self._volume() + step * VOLUME_STEP)
            return
        if key == "back":
            self.menu._leave_options()
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
        self.menu.view.update()

    # -- input ------------------------------------------------------------
    def handle_key(self, key):
        rows = self.rows()
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

    def _slider_value_at(self, x):
        track = self._slider
        if track is None or track.width() <= 0:
            return None
        return max(0.0, min(1.0, (x - track.left()) / track.width()))

    def handle_mouse_press(self, pos):
        point = QPointF(pos)
        if self._slider is not None and self._slider.adjusted(-6, -10, 6, 10).contains(point):
            self._dragging = True
            self._set_volume(self._slider_value_at(point.x()))
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
                    self._set_volume(value)
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
        self._slider = None
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
                self._draw_slider(painter, vrect, value, selected, text_font, label_pt)
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

    def _draw_slider(self, painter, rect, value_text, selected, text_font, pt):
        label_w = rect.width() * 0.22
        track = QRectF(rect.x() + 4, rect.center().y() - 3, rect.width() - label_w - 14, 6)
        self._slider = track
        volume = self._volume()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(60, 60, 70))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRectF(track.x(), track.y(), track.width() * volume, track.height())
        painter.setBrush(_ACCENT)
        painter.drawRoundedRect(fill, 3, 3)
        knob = QPointF(track.x() + track.width() * volume, track.center().y())
        painter.setBrush(QColor(240, 236, 230) if selected else QColor(200, 196, 190))
        painter.setPen(QPen(QColor(20, 20, 24), 1))
        painter.drawEllipse(knob, 8, 8)
        painter.setFont(text_font(pt))
        painter.setPen(_VALUE if volume > 0 else _NOTE)
        painter.drawText(QRectF(track.right() + 10, rect.y(), label_w, rect.height()),
                         int(Qt.AlignVCenter | Qt.AlignLeft), value_text)
