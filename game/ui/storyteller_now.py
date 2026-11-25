"""The "Storyteller — what it's doing" window; console ``storyteller``.

A live, read-only view of :mod:`game.storyteller_report`: a badge with the
pacing state, then labelled rows -- Time, State, Why, Sensing, Roads, Weather,
Recent -- and the Activity feed (state changes, population caps, Studio edits,
biased journeys), newest first. **Open Studio** opens the full Storyteller
Studio for editing. Painting it never samples the storyteller, appraises an
actor or draws a random number.
"""

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics

from engine.floating_windows import FloatingWindow

from .. import storyteller_report as report

TITLE = "Storyteller — what it's doing"


class StorytellerNowWindow(FloatingWindow):
    wants_cursor = True
    WIDTH = 600
    MAX_BODY_H = 520
    BADGE_H = 34
    FOOTER_H = 30
    LABEL_W = 92

    def __init__(self, view):
        super().__init__(TITLE, x=24, y=64, width=self.WIDTH, body_height=self.MAX_BODY_H)
        self.view = view
        self.key = "debug:storyteller_now"
        self.font = QFont("Arial", 10)
        self.bold = QFont("Arial", 10, QFont.Bold)
        self.badge_font = QFont("Arial", 11, QFont.Bold)
        self._scroll = 0
        self._scroll_max = 0
        self._buttons = []
        self._resize = None
        self._resize_rect = QRect()
        self._wanted_width = self.WIDTH
        self._wanted_height = self.MAX_BODY_H

    # -- what it reads -------------------------------------------------------
    def _session(self):
        return getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)

    def _storyteller(self):
        return getattr(self._session(), "storyteller", None)

    def rows(self):
        """``(label, text, heading)`` rows; the Activity feed gets a heading."""
        story, session = self._storyteller(), self._session()
        out = [(label, text, False) for label, text in report.rows(story, session, report.SECTIONS[:-1])]
        if story is not None:
            out.append(("", "Activity · newest first", True))
            out += [(label, text, False) for label, text in report.rows(story, session, "activity")]
        return out

    # -- layout --------------------------------------------------------------
    def _view_size(self):
        return (getattr(self.view, "width", lambda: 1280)(),
                getattr(self.view, "height", lambda: 720)())

    def content_height(self):
        return max(120, min(self._wanted_height,
                            self._view_size()[1] - self.window_rect.y() - self.HEADER_H - 10))

    def draw(self, painter, focused=False):
        vw, vh = self._view_size()
        self.width = max(self.MIN_W, min(self._wanted_width, vw - 20))
        self.window_rect.setWidth(self.width)
        self.window_rect.moveTo(max(5, min(self.window_rect.x(), vw - self.width - 5)),
                                max(5, min(self.window_rect.y(), vh - self.HEADER_H - 120)))
        super().draw(painter, focused)

    def draw_body(self, painter, x, y, w):
        story = self._storyteller()
        height = self.content_height()
        # The badge: which state, and whether pacing is on.
        state = getattr(story, "state", None)
        colour = QColor(*report.STATE_COLOURS.get(state, (120, 125, 135)))
        painter.save()
        painter.setFont(self.badge_font)
        chip = QRect(x + 10, y + 6, 104, self.BADGE_H - 10)
        painter.fillRect(chip, colour)
        painter.setPen(QColor(20, 22, 28))
        painter.drawText(chip, Qt.AlignCenter, state or "—")
        painter.setPen(QColor(235, 238, 245))
        title = "STORYTELLER" if story is None else (
            "STORYTELLER · pacing ON" if story.enabled else "STORYTELLER · pacing OFF (pristine)")
        painter.drawText(QRect(chip.right() + 12, y + 4, w - 140, self.BADGE_H - 6),
                         Qt.AlignVCenter | Qt.AlignLeft, title)
        painter.restore()
        top = y + self.BADGE_H
        visible = height - self.BADGE_H - self.FOOTER_H
        # Rows: a coloured label column, wrapped text beside it.
        flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        text_w = max(80, w - self.LABEL_W - 30)
        fm = QFontMetrics(self.font)
        layout, total = [], 4
        for label, text, heading in self.rows():
            if heading:
                total += 6
                layout.append((label, text, heading, total, 22))
                total += 24
                continue
            h = fm.boundingRect(QRect(0, 0, text_w, 10000), flags, text).height() + 6
            layout.append((label, text, heading, total, h))
            total += h
        self._scroll_max = max(0, total + 6 - visible)
        self._scroll = max(0, min(self._scroll, self._scroll_max))
        painter.save()
        painter.setClipRect(QRect(x, top, w, visible), Qt.IntersectClip)
        for label, text, heading, row_y, h in layout:
            ry = top + row_y - self._scroll
            if ry > top + visible or ry + h < top:
                continue
            if heading:
                painter.fillRect(QRect(x + 8, ry, w - 16, 22), QColor(40, 48, 60))
                painter.setFont(self.bold)
                painter.setPen(QColor(150, 205, 225))
                painter.drawText(QRect(x + 14, ry, w - 28, 22), Qt.AlignVCenter, text)
                continue
            painter.setFont(self.bold)
            painter.setPen(QColor(150, 205, 225) if label[:4] not in ("Day ", "-") else QColor(170, 175, 185))
            painter.drawText(QRect(x + 12, ry, self.LABEL_W - 4, h), flags, label)
            painter.setFont(self.font)
            painter.setPen(QColor(228, 230, 236))
            painter.drawText(QRect(x + 12 + self.LABEL_W, ry, text_w, h), flags, text)
        painter.restore()
        # Footer: Open Studio, scroll buttons, resize grip.
        painter.save()
        painter.setFont(self.font)
        fy = top + visible
        self._buttons = []
        for left, width, label, action in ((x + 10, 110, "Open Studio", "studio"),
                                           (x + w - 126, 52, "Up", -1), (x + w - 70, 52, "Down", 1)):
            rect = QRect(left, fy + 3, width, self.FOOTER_H - 6)
            painter.fillRect(rect, QColor(55, 65, 80))
            painter.setPen(QColor(225, 230, 240))
            painter.drawText(rect, Qt.AlignCenter, label)
            self._buttons.append((rect, action))
        painter.setPen(QColor(170, 175, 185))
        painter.drawText(QRect(x + 130, fy, w - 270, self.FOOTER_H), Qt.AlignVCenter,
                         "Read-only · live")
        self._resize_rect = QRect(x + w - 14, y + height - 14, 14, 14)
        painter.drawText(self._resize_rect, Qt.AlignCenter, "◢")
        painter.restore()

    # -- input ---------------------------------------------------------------
    def _scroll_by(self, amount):
        self._scroll = max(0, min(self._scroll + amount, self._scroll_max))
        self.view.update()

    def handle_wheel(self, event):
        self._scroll_by(-event.angleDelta().y())
        return True

    def handle_body_click(self, x, y):
        for rect, action in self._buttons:
            if not rect.contains(x, y):
                continue
            if action == "studio":
                from . import storyteller_window
                storyteller_window.open_storyteller(self.view)
            else:
                self._scroll_by(action * max(40, self.content_height() - self.BADGE_H - self.FOOTER_H))
            return True
        return False

    def handle_mouse_press(self, event):
        if self.expanded and self._resize_rect.contains(event.pos()):
            self._resize = (event.x(), event.y(), self.width, self.content_height())
            self.mouse_captured = True
            return True
        return super().handle_mouse_press(event)

    def handle_mouse_move(self, event, view_w, view_h):
        if self._resize is None:
            return super().handle_mouse_move(event, view_w, view_h)
        x, y, width, height = self._resize
        self._wanted_width = max(380, min(view_w - self.window_rect.x() - 5, width + event.x() - x))
        self._wanted_height = max(180, min(view_h - self.window_rect.y() - self.HEADER_H - 5,
                                           height + event.y() - y))
        self.view.update()
        return True

    def handle_mouse_release(self, event):
        if self._resize is not None:
            self._resize = None
            self.mouse_captured = False
            return True
        return super().handle_mouse_release(event)

    def on_close(self):
        self._resize = None
        self.mouse_captured = False


def open_now(view):
    """Open the window on *view*, or bring the open one forward."""
    manager = getattr(view, "window_manager", None)
    session = getattr(getattr(view, "logic_thread", None), "_miniwind", None)
    if manager is None or getattr(session, "storyteller", None) is None:
        return None
    win = manager.find(lambda w: isinstance(w, StorytellerNowWindow) and w.active)
    if win is None:
        win = manager.add(StorytellerNowWindow(view))
    else:
        manager.raise_(win)
    view.update()
    return win
