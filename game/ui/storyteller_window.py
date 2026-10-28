"""Read-only live pacing inspector; console ``storyteller``."""

import json

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics

from engine.floating_windows import FloatingWindow

from ..living.journeys import KINDS
from ..storyteller import TUNING


def _timestamp(hours):
    if hours is None:
        return "not sampled yet"
    day, hour = divmod(float(hours), 24)
    return f"Day {int(day)} {int(hour):02d}:{int((hour % 1) * 60):02d}"


def rows_for(storyteller):
    """Read the sampler's existing data; inspection never triggers a sample."""
    if storyteller is None:
        return [("text", "No active MiniWind storyteller.")]
    levers = storyteller.levers
    rows = [("heading", f"State: {storyteller.state}"),
            ("text", f"Last sampled: {_timestamp(storyteller.last_sample)}. Live, read-only view."),
            ("heading", "Current levers")]
    labels = {"population": "Road population", "hunter_bounty": "Hunter bounty threshold",
              "lair_refill_scale": "New lair refill delay multiplier",
              "market_chance": "Market trip chance", "destination_bias": "Town destination multiplier",
              "vendetta_bias": "Vendetta arrival multiplier"}
    for key, value in levers.items():
        if key not in ("kind_weights", "kind_hours"):
            rows.append(("text", f"{labels.get(key, key)}: {json.dumps(value, ensure_ascii=False)}"))
    rows.append(("heading", "Journey weights and departure hours"))
    for kind, spec in KINDS.items():
        weight = levers["kind_weights"].get(kind, spec["weight"])
        lo, hi = levers["kind_hours"].get(kind, spec["hours"])
        hours = f"{lo:02g}:00–{hi:02g}:00" + (" (overnight)" if lo > hi else "")
        rows.append(("text", f"{kind}: weight {weight:g}; departs {hours}"))
    rows.append(("heading", f"Last {TUNING['observation_cap']} observations · newest first"))
    observations = storyteller.observations
    if not observations:
        rows.append(("text", "No observations yet. Waiting for the next storyteller sample."))
    for observation in observations:
        rows.append(("heading", f"{_timestamp(observation['time'])} · {observation['state']}"))
        rows.append(("text", observation["reason"]))
        law = observation["sensors"].get("law", {})
        if law:
            rows.append(("text", "Regional law: " + "; ".join(
                f"{region}: bounty {row['bounty']}, phase {row['phase']}"
                for region, row in law.items())))
    return rows


class StorytellerWindow(FloatingWindow):
    wants_cursor = True
    WIDTH = 720
    MAX_BODY_H = 560
    FOOTER_H = 30

    def __init__(self, view):
        super().__init__("Storyteller", x=20, y=60, width=self.WIDTH, body_height=self.MAX_BODY_H)
        self.view = view
        self.key = "debug:storyteller"
        self.font = QFont("Arial", 10)
        self.bold = QFont("Arial", 10, QFont.Bold)
        self._scroll = 0
        self._scroll_max = 0
        self._buttons = []

    def _storyteller(self):
        logic = getattr(self.view, "logic_thread", None)
        return getattr(getattr(logic, "_miniwind", None), "storyteller", None)

    def _view_size(self):
        return (getattr(self.view, "width", lambda: 1280)(),
                getattr(self.view, "height", lambda: 720)())

    def content_height(self):
        return max(90, min(self.MAX_BODY_H, self._view_size()[1] - self.window_rect.y() - self.HEADER_H - 10))

    def draw(self, painter, focused=False):
        vw, vh = self._view_size()
        self.width = max(self.MIN_W, min(self.WIDTH, vw - 20))
        self.window_rect.setWidth(self.width)
        self.window_rect.moveTo(max(5, min(self.window_rect.x(), vw - self.width - 5)),
                                max(5, min(self.window_rect.y(), vh - self.HEADER_H - 100)))
        super().draw(painter, focused)

    def draw_body(self, painter, x, y, w):
        rows = rows_for(self._storyteller())
        layout, total = [], 8
        text_w = w - 32
        flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        for kind, text in rows:
            font = self.bold if kind == "heading" else self.font
            fm = QFontMetrics(font)
            height = fm.boundingRect(QRect(0, 0, text_w, 10000), flags, text).height() + 8
            if kind == "heading":
                total += 8
            layout.append((font, text, total, height, kind))
            total += height
        height = self.content_height()
        visible = height - self.FOOTER_H
        self._scroll_max = max(0, total + 8 - visible)
        self._scroll = max(0, min(self._scroll, self._scroll_max))
        painter.save()
        painter.setClipRect(QRect(x, y, w, visible), Qt.IntersectClip)
        for font, text, top, line_height, kind in layout:
            painter.setFont(font)
            painter.setPen(QColor(150, 205, 225) if kind == "heading" else QColor(225, 228, 235))
            painter.drawText(QRect(x + 12, y + top - self._scroll, text_w, line_height), flags, text)
        painter.restore()
        painter.save()
        painter.setFont(self.font)
        painter.setPen(QColor(185, 190, 200))
        painter.drawText(QRect(x + 12, y + visible, w - 130, self.FOOTER_H),
                         Qt.AlignVCenter, "Scroll to read all settings and observations")
        self._buttons = []
        for offset, label, direction in ((112, "Up", -1), (58, "Down", 1)):
            rect = QRect(x + w - offset, y + visible + 3, 50, self.FOOTER_H - 6)
            painter.fillRect(rect, QColor(55, 65, 80))
            painter.drawText(rect, Qt.AlignCenter, label)
            self._buttons.append((rect, direction))
        painter.restore()

    def _scroll_by(self, amount):
        self._scroll = max(0, min(self._scroll + amount, self._scroll_max))
        self.view.update()

    def handle_wheel(self, event):
        self._scroll_by(-event.angleDelta().y())
        return True

    def handle_body_click(self, x, y):
        for rect, direction in self._buttons:
            if rect.contains(x, y):
                self._scroll_by(direction * (self.content_height() - self.FOOTER_H))
                return True
        return False


def open_storyteller(view):
    """Open one live window per view, or bring the existing window forward."""
    manager = getattr(view, "window_manager", None)
    session = getattr(getattr(view, "logic_thread", None), "_miniwind", None)
    if manager is None or getattr(session, "storyteller", None) is None:
        return None
    win = manager.find(lambda w: isinstance(w, StorytellerWindow) and w.active)
    if win is None:
        win = manager.add(StorytellerWindow(view))
    else:
        manager.raise_(win)
    view.update()
    return win
