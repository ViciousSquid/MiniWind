"""
The Debug Tools window (console: ``debugtools``): time controls for the
simulation.

* **Rewind** -- step the world back a second at a time through the history
  kept while this window is open (game/rewind.py); the world pauses on the
  moment it lands on.
* **Pause / Play** -- freeze the world or let it run (Play also leaves a
  rewound moment and carries on from it).
* **Speed** -- 0.25×, 0.5×, 1× or 2×: how many seconds the world advances
  per real second (the logic and monster-AI threads both follow it).

Closing the window puts the speed back to 1×, lets the world run and stops
recording.
"""

from __future__ import annotations

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QPen

from engine.floating_windows import FloatingWindow

from .. import fio, rewind
from . import hits

SPEEDS = (0.25, 0.5, 1.0, 2.0)
#: The world-pause request the Pause button holds.
PAUSE_OWNER = "debug_tools"
REWIND_STEP = 1.0

_BG = QColor(28, 30, 36, 235)
_BTN = QColor(52, 56, 66)
_BTN_HOT = QColor(78, 84, 98)
_BTN_ON = QColor(70, 120, 190)
_INK = QColor(225, 228, 235)
_DIM = QColor(150, 156, 168)


class DebugToolsWindow(FloatingWindow):
    wants_cursor = True

    def __init__(self, view, x=20, y=110):
        super().__init__("Debug Tools", x, y, width=330, body_height=150)
        self.view = view
        self.key = "debug:tools"
        self._buttons = []
        self.f_button = QFont("Arial", 10, QFont.Bold)
        self.f_small = QFont("Arial", 9)
        session = self._session()
        if session is not None:
            session.rewind.start()

    # -- the live session ------------------------------------------------
    def _logic(self):
        return getattr(self.view, "logic_thread", None)

    def _session(self):
        return getattr(self._logic(), "_miniwind", None)

    def _paused(self) -> bool:
        logic = self._logic()
        if logic is None:
            return False
        owners = logic.session_runtime.world_pause_owners
        owners = (owners() if callable(owners) else owners) or frozenset()
        return PAUSE_OWNER in owners or rewind.PAUSE_OWNER in owners

    def _speed(self) -> float:
        return float(getattr(self._logic(), "time_scale", 1.0))

    # -- actions -------------------------------------------------------------
    def _rewind(self):
        hits.queue(lambda session: session.rewind.back(REWIND_STEP))

    def _toggle_pause(self):
        logic = self._logic()
        if logic is None:
            return
        if self._paused():
            fio.set_world_paused(logic, PAUSE_OWNER, False)
            fio.set_world_paused(logic, rewind.PAUSE_OWNER, False)
        else:
            fio.set_world_paused(logic, PAUSE_OWNER, True)

    def _set_speed(self, value):
        def act():
            logic = self._logic()
            if logic is not None:
                logic.time_scale = float(value)
        return act

    # -- drawing ---------------------------------------------------------------
    def _button(self, painter, rect, label, action, on=False):
        hot = hits.hovered(rect)
        painter.setBrush(_BTN_ON if on else (_BTN_HOT if hot else _BTN))
        painter.setPen(QPen(QColor(110, 118, 135), 1))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setFont(self.f_button)
        painter.setPen(_INK)
        painter.drawText(rect, Qt.AlignCenter, label)
        self._buttons.append((QRect(rect), action))

    def draw_body(self, painter, x, y, w):
        self._buttons = []
        painter.save()
        painter.fillRect(QRect(x, y, w, self.content_height()), _BG)
        pad = 10
        paused = self._paused()
        bw = (w - 2 * pad - 8) // 2
        self._button(painter, QRect(x + pad, y + pad, bw, 34), "⏪  Rewind 1s", self._rewind)
        self._button(painter, QRect(x + pad + bw + 8, y + pad, bw, 34),
                     "▶  Play" if paused else "⏸  Pause", self._toggle_pause, on=paused)
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        painter.drawText(QRect(x + pad, y + 52, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         "Simulation speed")
        sw = (w - 2 * pad - 3 * 6) // 4
        current = self._speed()
        for k, value in enumerate(SPEEDS):
            r = QRect(x + pad + k * (sw + 6), y + 72, sw, 30)
            label = f"{value:g}×"
            self._button(painter, r, label, self._set_speed(value),
                         on=abs(current - value) < 1e-6)
        session = self._session()
        status = "No game running"
        if session is not None:
            rw = session.rewind
            status = f"History {rw.seconds():.1f} s"
            if rw.behind > 0:
                status += f" · rewound {rw.behind:.1f} s"
            if paused:
                status += " · paused"
        painter.setFont(self.f_small)
        painter.setPen(_DIM)
        painter.drawText(QRect(x + pad, y + 112, w - 2 * pad, 28),
                         Qt.AlignLeft | Qt.AlignVCenter, status)
        painter.restore()

    # -- mouse -------------------------------------------------------------------
    def handle_mouse_press(self, event):
        if not self.active:
            return False
        rect = self._full_rect()
        if not rect.contains(event.pos()):
            return False
        if event.y() < rect.y() + self.HEADER_H or event.button() != Qt.LeftButton:
            return super().handle_mouse_press(event)
        for r, action in self._buttons:
            if r.contains(event.pos()):
                action()
                break
        return True

    def on_close(self):
        """Back to normal: real-time speed, running, not recording."""
        logic = self._logic()
        if logic is not None:
            logic.time_scale = 1.0
            fio.set_world_paused(logic, PAUSE_OWNER, False)
            fio.set_world_paused(logic, rewind.PAUSE_OWNER, False)
        session = self._session()
        if session is not None:
            session.rewind.stop()


def open_debug_tools(view):
    """Open (or bring forward) the Debug Tools window on *view*."""
    manager = getattr(view, "window_manager", None)
    if manager is None:
        return None
    existing = manager.find(lambda w: isinstance(w, DebugToolsWindow))
    if existing is not None and existing.active:
        manager.raise_(existing)
        view.update()
        return existing
    win = DebugToolsWindow(view)
    manager.add(win)
    view.update()
    return win
