"""Resizable live Storyteller Studio; console ``storyteller``."""

import json

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics

from engine.floating_windows import FloatingWindow

from ..living.journeys import KINDS
from ..sim.storyteller import TUNING
from ..storyteller_studio import world_explanations


def _timestamp(hours):
    if hours is None:
        return "not sampled yet"
    day, hour = divmod(float(hours), 24)
    return f"Day {int(day)} {int(hour):02d}:{int((hour % 1) * 60):02d}"


def rows_for(storyteller):
    """Read the sampler's existing data; inspection never triggers a sample."""
    if storyteller is None:
        return [("text", "No active MiniWind storyteller.")]
    levers = storyteller.levers if storyteller.enabled else {"kind_weights": {}, "kind_hours": {}}
    rows = [("heading", f"State: {storyteller.state}"),
            ("text", f"Last sampled: {_timestamp(storyteller.last_sample)}. Live sensor readings; edit data on the Levers tab."),
            ("heading", "Live sensors")]
    for key, value in storyteller.sensors.items():
        if key != "law":
            rows.append(("text", f"{key.replace('_', ' ')}: {json.dumps(value, ensure_ascii=False)}"))
    rows.append(("heading", "Current levers"))
    labels = {"population": "Road population", "hunter_bounty": "Hunter bounty threshold",
              "lair_refill_scale": "New lair refill delay multiplier",
              "market_chance": "Market trip chance", "destination_bias": "Town destination multiplier",
              "vendetta_bias": "Vendetta arrival multiplier"}
    labels["writ_hunter_scale"] = "Old unpaid writ hunter threshold multiplier"
    rows.append(("text", "Pacing enabled." if storyteller.enabled else
                 "Pristine ecology: authored defaults; storyteller sensors idle."))
    for key, value in levers.items():
        if key not in ("kind_weights", "kind_hours"):
            rows.append(("text", f"{labels.get(key, key)}: {json.dumps(value, ensure_ascii=False)}"))
    rows.append(("heading", "Journey weights and departure hours"))
    for kind, spec in KINDS.items():
        weight = levers["kind_weights"].get(kind, spec["weight"])
        lo, hi = levers["kind_hours"].get(kind, spec["hours"])
        hours = f"{lo:02g}:00–{hi:02g}:00" + (" (overnight)" if lo > hi else "")
        rows.append(("text", f"{kind}: weight {weight:g}; departs {hours}"))
    rows.append(("heading", "Decisions and reasons"))
    rows.extend(("text", f"{label}: {reason}") for label, reason in storyteller.inspector_rows()
                if label != "State decision")  # the sample history below already shows it
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
        super().__init__("Storyteller Studio", x=20, y=60, width=self.WIDTH, body_height=self.MAX_BODY_H)
        self.view = view
        self.key = "debug:storyteller"
        self.font = QFont("Arial", 10)
        self.bold = QFont("Arial", 10, QFont.Bold)
        self._scroll = 0
        self._scroll_max = 0
        self._buttons = []
        self._cells = []
        self._tabs = []
        self.tab = "Live"
        self.edit_state = None
        self._edit = None
        self._resize = None
        self._wanted_width = self.WIDTH
        self._wanted_height = self.MAX_BODY_H
        self._message = "Drag the corner to resize."

    def _storyteller(self):
        logic = getattr(self.view, "logic_thread", None)
        return getattr(getattr(logic, "_miniwind", None), "storyteller", None)

    def _view_size(self):
        return (getattr(self.view, "width", lambda: 1280)(),
                getattr(self.view, "height", lambda: 720)())

    def content_height(self):
        return max(90, min(self._wanted_height, self._view_size()[1] - self.window_rect.y() - self.HEADER_H - 10))

    def draw(self, painter, focused=False):
        vw, vh = self._view_size()
        self.width = max(self.MIN_W, min(self._wanted_width, vw - 20))
        self.window_rect.setWidth(self.width)
        self.window_rect.moveTo(max(5, min(self.window_rect.x(), vw - self.width - 5)),
                                max(5, min(self.window_rect.y(), vh - self.HEADER_H - 100)))
        super().draw(painter, focused)

    def draw_body(self, painter, x, y, w):
        story = self._storyteller()
        rows = [(kind, text, None) for kind, text in rows_for(story)]
        if story is not None and self.tab == "World":
            rows = []
            for group, label, reason, events in world_explanations(story):
                rows.extend([("heading", f"{group}: {label}", None), ("text", reason, None)])
        elif story is not None and self.tab == "Levers":
            if self.edit_state is None:
                self.edit_state = story.state
            table = story.state_levers(self.edit_state)
            rows = [("text", "Drag a value left/right. Values apply on ordinary samples; edits are saved with this session.", None)]
            rows.append(("text", "RESPITE hostile weights control local admission; distant ecology uses authored defaults.", None))
            for key, value in table.items():
                if key not in ("kind_weights", "kind_hours"):
                    rows.append(("edit", f"{key.replace('_', ' ')}: {value:g}", ((key,), value)))
            rows.append(("heading", "Journey weights", None))
            for kind, spec in KINDS.items():
                value = table["kind_weights"].get(kind, spec["weight"])
                rows.append(("edit", f"{kind}: weight {value:g}", (("kind_weights", kind), value)))
            rows.append(("heading", "Departure windows", None))
            for kind, spec in KINDS.items():
                for i, value in enumerate(table["kind_hours"].get(kind, spec["hours"])):
                    rows.append(("edit", f"{kind} {'from' if i == 0 else 'until'}: {value:g}", (("kind_hours", kind, i), value)))
        self._tabs = []
        for i, name in enumerate(("Live", "Levers", "World")):
            rect = QRect(x + 8 + i * 88, y + 3, 82, 24)
            painter.fillRect(rect, QColor(65, 95, 125) if self.tab == name else QColor(45, 50, 60))
            painter.setPen(QColor(225, 230, 240))
            painter.drawText(rect, Qt.AlignCenter, name)
            self._tabs.append((rect, "tab", name))
        if story is not None and w >= 460:
            painter.drawText(QRect(x + w - 175, y + 3, 165, 24), Qt.AlignRight | Qt.AlignVCenter,
                             f"Live: {story.state}")
        header = 32
        if story is not None and self.tab == "Levers":
            for i, state in enumerate(TUNING["states"]):
                rect = QRect(x + 8 + i * 78, y + 31, 74, 24)
                painter.fillRect(rect, QColor(65, 95, 125) if self.edit_state == state else QColor(45, 50, 60))
                painter.drawText(rect, Qt.AlignCenter, state)
                self._tabs.append((rect, "state", state))
            rect = QRect(x + 8, y + 58, 146, 24)
            painter.fillRect(rect, QColor(45, 50, 60))
            painter.drawText(rect, Qt.AlignCenter, "Reset state edits")
            self._tabs.append((rect, "reset", None))
            rect = QRect(x + 162, y + 58, 150, 24)
            painter.fillRect(rect, QColor(45, 50, 60))
            painter.drawText(rect, Qt.AlignCenter, "Pacing on" if story.enabled else "Pristine ecology")
            self._tabs.append((rect, "enabled", None))
            header = 88
        y += header
        layout, total = [], 8
        text_w = w - 32
        flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        for kind, text, cell in rows:
            font = self.bold if kind == "heading" else self.font
            fm = QFontMetrics(font)
            height = fm.boundingRect(QRect(0, 0, text_w, 10000), flags, text).height() + 8
            if kind == "heading":
                total += 8
            layout.append((font, text, total, height, kind, cell))
            total += height
        height = self.content_height() - header
        visible = height - self.FOOTER_H
        self._scroll_max = max(0, total + 8 - visible)
        self._scroll = max(0, min(self._scroll, self._scroll_max))
        painter.save()
        painter.setClipRect(QRect(x, y, w, visible), Qt.IntersectClip)
        self._cells = []
        for font, text, top, line_height, kind, cell in layout:
            painter.setFont(font)
            painter.setPen(QColor(150, 205, 225) if kind in ("heading", "edit") else QColor(225, 228, 235))
            rect = QRect(x + 12, y + top - self._scroll, text_w, line_height)
            if cell is not None:
                label = text.rsplit(":", 1)[0]
                painter.drawText(QRect(rect.x(), rect.y(), text_w - 108, line_height), flags, label)
                value_rect = QRect(x + w - 108, rect.y(), 88, min(28, line_height))
                painter.fillRect(value_rect, QColor(45, 66, 84))
                painter.drawText(value_rect, Qt.AlignCenter, f"{cell[1]:g} ↔")
                clipped = value_rect.intersected(QRect(x, y, w, visible))
                if not clipped.isEmpty():
                    self._cells.append((clipped, cell))
            else:
                painter.drawText(rect, flags, text)
        painter.restore()
        painter.save()
        painter.setFont(self.font)
        painter.setPen(QColor(185, 190, 200))
        painter.drawText(QRect(x + 12, y + visible, w - 130, self.FOOTER_H),
                         Qt.AlignVCenter, self._message)
        self._buttons = []
        for offset, label, direction in ((112, "Up", -1), (58, "Down", 1)):
            rect = QRect(x + w - offset, y + visible + 3, 50, self.FOOTER_H - 6)
            painter.fillRect(rect, QColor(55, 65, 80))
            painter.drawText(rect, Qt.AlignCenter, label)
            self._buttons.append((rect, direction))
        self._resize_rect = QRect(x + w - 14, y + height - 14, 14, 14)
        painter.drawText(self._resize_rect, Qt.AlignCenter, "◢")
        painter.restore()

    def _scroll_by(self, amount):
        self._scroll = max(0, min(self._scroll + amount, self._scroll_max))
        self.view.update()

    def handle_wheel(self, event):
        self._scroll_by(-event.angleDelta().y())
        return True

    def handle_body_click(self, x, y):
        story = self._storyteller()
        for rect, action, value in self._tabs:
            if not rect.contains(x, y):
                continue
            if action == "tab":
                self.tab, self._scroll = value, 0
            elif action == "state":
                self.edit_state, self._scroll = value, 0
            elif story is not None and action == "reset":
                story.reset_edits(self.edit_state)
                self._message = f"{self.edit_state} edits reset."
            elif story is not None and action == "enabled":
                story.set_enabled(not story.enabled)
            self.view.update()
            return True
        if story is not None:
            for rect, (path, value) in self._cells:
                if rect.contains(x, y):
                    self._edit = (story, self.edit_state, path, value, x)
                    self.mouse_captured = True
                    return True
        for rect, direction in self._buttons:
            if rect.contains(x, y):
                self._scroll_by(direction * (self.content_height() - self.FOOTER_H))
                return True
        return False

    def handle_mouse_press(self, event):
        if self.expanded and getattr(self, "_resize_rect", QRect()).contains(event.pos()):
            self._resize = (event.x(), event.y(), self.width, self.content_height())
            self.mouse_captured = True
            return True
        return super().handle_mouse_press(event)

    def handle_mouse_move(self, event, view_w, view_h):
        if self._resize is not None:
            x, y, width, height = self._resize
            self._wanted_width = max(360, min(view_w - self.window_rect.x() - 5, width + event.x() - x))
            self._wanted_height = max(160, min(view_h - self.window_rect.y() - self.HEADER_H - 5, height + event.y() - y))
        elif self._edit is not None:
            story, state, path, start, x = self._edit
            if story is not self._storyteller():
                self._edit = None
                self.mouse_captured = False
                return True
            step = 0.01 if path[0] in ("market_chance", "writ_hunter_scale", "lair_refill_scale") else 1.0
            value = start + round((event.x() - x) / 5) * step
            high = 24 if path[0] == "kind_hours" else 1 if path[0] == "market_chance" else 10000
            low = 0.01 if path[0] == "destination_bias" else 0
            story.edit_lever(state, path, max(low, min(high, round(value, 4))), persist=False)
            self._message = f"Editing {state} {' / '.join(map(str, path))}"
        else:
            return super().handle_mouse_move(event, view_w, view_h)
        self.view.update()
        return True

    def handle_mouse_release(self, event):
        if self._edit is not None or self._resize is not None:
            if self._edit is not None:
                self._edit[0].persist()
                self._message = "Edit saved with session."
            self._edit = self._resize = None
            self.mouse_captured = False
            return True
        return super().handle_mouse_release(event)

    def on_close(self):
        if self._edit is not None:
            self._edit[0].persist()
        self._edit = self._resize = None
        self.mouse_captured = False


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
