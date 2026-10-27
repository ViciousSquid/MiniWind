"""Live pathfinding overlay and controls; console ``paths panel``.

Only consumes diagnostic snapshots. Drawing at the renderer's rate never
requests a route. The same records can be exported for later investigation.
"""

from PyQt5.QtCore import QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QPen

from engine.floating_windows import FloatingWindow
from .. import pathfinding_debug as debug

COLOURS = {"route": QColor(80, 220, 255, 230), "direct": QColor(255, 214, 90, 210),
           "chase": QColor(255, 155, 65, 220), "failed": QColor(255, 90, 80, 230)}
WIDTH = 3.0


def _project(glm, proj, view, x, y, z, width, height):
    clip = proj * view * glm.vec4(float(x), float(y), float(z), 1.0)
    if clip.w <= 1e-4:
        return None
    return QPointF((clip.x / clip.w * 0.5 + 0.5) * width,
                   (1.0 - (clip.y / clip.w * 0.5 + 0.5)) * height)


def draw(painter, session, viewport, width, height):
    if not getattr(session, "show_paths", False) or viewport is None:
        return
    import glm
    proj, view = viewport.projection_matrix, viewport.view_matrix
    config = debug.settings(session)
    painter.save()
    try:
        painter.setRenderHint(painter.Antialiasing, True)
        for actor in debug.actor_records(session):
            x, y, z = actor["pos"]
            goal = actor["goal"]
            corners = actor["points"] or ((goal[0], goal[2]),)
            points = [(x, z), *corners]
            screen = [_project(glm, proj, view, px, y + 8.0, pz, width, height)
                      for px, pz in points]
            colour = COLOURS[actor["state"]]
            if not actor["live_navigation"]:
                colour = QColor(170, 175, 185, 180)
            painter.setPen(QPen(colour, WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            # Preserve adjacency: removing hidden points would join unrelated
            # corners across the back of the camera.
            for a, b in zip(screen, screen[1:]):
                if a is not None and b is not None:
                    painter.drawLine(a, b)
            painter.setBrush(colour)
            for corner in screen[1:]:
                if corner is not None:
                    painter.drawEllipse(corner, 4.0, 4.0)
            # Show a blocked requested goal beyond the safe route endpoint.
            if corners[-1] != (goal[0], goal[2]):
                end = _project(glm, proj, view, goal[0], y + 8.0, goal[2], width, height)
                painter.setPen(QPen(COLOURS["failed"], 1.5, Qt.DashLine))
                if screen[-1] is not None and end is not None:
                    painter.drawLine(screen[-1], end)
            if config.labels and screen[0] is not None:
                painter.setPen(colour)
                label = (f"{actor['name']} · {actor['tier']} · {actor['decision']} · "
                         f"{actor.get('searches', 0)} A* · "
                         f"{actor.get('searches_per_second', 0.0):.2f}/s")
                painter.drawText(screen[0] + QPointF(6, -10), label)
            painter.setBrush(Qt.NoBrush)
    finally:
        painter.restore()


class PathfindingWindow(FloatingWindow):
    wants_cursor = True

    def __init__(self, view):
        super().__init__("Pathfinding Debug", x=20, y=110, width=400, body_height=330)
        self.view = view
        self.key = "debug:pathfinding"
        self._buttons = []

    def _session(self):
        return getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)

    def _button(self, painter, rect, label, action, on=False):
        painter.setPen(QColor(220, 225, 235))
        painter.setBrush(QColor(65, 115, 170) if on else QColor(50, 55, 65))
        painter.drawRoundedRect(rect, 3, 3)
        painter.drawText(rect, Qt.AlignCenter, label)
        self._buttons.append((rect, action))

    def draw_body(self, painter, x, y, w):
        self._buttons = []
        session = self._session()
        if session is None:
            painter.drawText(x + 10, y + 20, "No active play session")
            return
        config = debug.settings(session)
        enabled = bool(getattr(session, "show_paths", False))
        painter.save()
        painter.setFont(self.font)
        self._button(painter, QRect(x + 10, y + 10, 180, 28),
                     "Paths on" if enabled else "Paths off",
                     lambda: debug.configure(session, enabled=not enabled), enabled)
        self._button(painter, QRect(x + 200, y + 10, 190, 28),
                     "Labels on" if config.labels else "Labels off",
                     lambda: debug.configure(session, labels=not config.labels), config.labels)
        painter.drawText(x + 10, y + 60, "Show route state")
        for i, state in enumerate(debug.STATES):
            self._button(painter, QRect(x + 10 + i * 77, y + 70, 72, 28), state.title(),
                         lambda state=state: debug.configure(session, state=state), config.state == state)
        painter.drawText(x + 10, y + 120, "BigWorld simulation layer (authoritative)")
        for i, tier in enumerate(debug.TIERS):
            self._button(painter, QRect(x + 10 + i * 77, y + 130, 72, 28), tier.title(),
                         lambda tier=tier: debug.configure(session, tier=tier), config.tier == tier)
        painter.drawText(x + 10, y + 180, "Display distance from player")
        for i, radius in enumerate((800.0, 1600.0, 3200.0)):
            self._button(painter, QRect(x + 10 + i * 128, y + 190, 120, 28), f"{radius:g}",
                         lambda radius=radius: debug.configure(session, radius=radius), config.radius == radius)
        painter.drawText(x + 10, y + 240, f"Actor: {config.actor or 'all'}")
        self._button(painter, QRect(x + 10, y + 250, 180, 28), "All actors",
                     lambda: debug.configure(session, actor=""))
        self._button(painter, QRect(x + 200, y + 250, 190, 28), "Reset counters",
                     session.nav.reset_search_stats)
        painter.drawText(x + 10, y + 300, 'Console: paths actor "Name" / paths export')
        painter.drawText(x + 10, y + 318, "Cyan route · red failed · grey BigWorld coarse")
        painter.restore()

    def handle_body_click(self, x, y):
        for rect, action in self._buttons:
            if rect.contains(x, y):
                action()
                return True
        return False


def open_panel(view):
    manager = getattr(view, "window_manager", None)
    if manager is None:
        return None
    win = manager.find(lambda w: isinstance(w, PathfindingWindow) and w.active)
    if win is None:
        win = PathfindingWindow(view)
        manager.add(win)
    else:
        manager.raise_(win)
    view.update()
    return win
