"""
The pause menu's MAP page: the whole world, to pan and zoom.

The picture is the minimap's (:data:`game.ui.worldmap.WORLD`), drawn large:
the discovered places by name, every active quest's objective as a yellow
diamond (the tracked one brighter), and the player's arrow. It opens on the
player, or on a quest's objective when the journal's *Show on map* asked for
it, with a ring round that objective.

Driven by the pause menu: drag or the arrow keys to pan, the wheel or + / -
to zoom (about the pointer), Space or Home to come back to the player, Esc or
M to leave. Its data comes through the menu's actions
(``pause_menu_map_data``), so the page itself knows no session.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF

#: The closest the map zooms: world units across the shorter side.
MIN_SPAN = 1200.0
#: The span it opens at on the player or a quest objective.
OPEN_SPAN = 9000.0
#: One wheel notch / key press zooms by this factor.
ZOOM_STEP = 1.25
#: An arrow key pans this fraction of the span.
PAN_STEP = 0.12

_GOLD = QColor(214, 178, 96)
_GOLD_BRIGHT = QColor(250, 214, 120)
_INK = QColor(236, 230, 214)
_QUEST = QColor(250, 214, 70)
_QUEST_DIM = QColor(214, 180, 70)
_CAPTION = QColor(170, 166, 160)


class MapPage:
    """State, input and painting of the full map; owned by a PauseMenu."""

    def __init__(self, menu):
        self.menu = menu
        self.world = None
        self.features = {"player": None, "places": [], "quests": []}
        self.centre = None        # (x, z) world point at the middle
        self.span = OPEN_SPAN     # world units across the shorter side
        self.focus = None         # (x, z, label) ringed on the map
        self._rect = None         # QRectF of the map on screen, last paint
        self._drag = None         # (press pos, centre at press)
        self._opened_at = 0.0

    # -- data -------------------------------------------------------------
    def refresh(self):
        reader = getattr(self.menu.actions, "pause_menu_map_data", None)
        try:
            self.world, self.features = reader() if reader is not None else (None, None)
        except Exception:
            self.world, self.features = None, None
        if not self.features:
            self.features = {"player": None, "places": [], "quests": []}

    def open(self, focus=None):
        """Show the map on the player, or on *focus* = ``(x, z, label)``."""
        self.refresh()
        self.focus = focus
        self._drag = None
        self._opened_at = time.monotonic()
        self.span = min(OPEN_SPAN, self._max_span())
        if focus is not None:
            self.centre = (float(focus[0]), float(focus[1]))
        else:
            self.centre_on_player()

    def centre_on_player(self):
        player = self.features.get("player")
        if player is not None:
            self.centre = (player[0], player[1])
        elif self.centre is None:
            self.centre = self._world_centre()
        self.menu.view.update()

    def _bounds(self):
        world = self.world
        if world is not None and getattr(world, "bounds", None) is not None:
            return world.bounds
        return None

    def _world_centre(self):
        b = self._bounds()
        if b is None:
            return (0.0, 0.0)
        (a, c), (d, e) = b
        return ((a + c) / 2.0, (d + e) / 2.0)

    def _max_span(self):
        b = self._bounds()
        if b is None:
            return 40000.0
        (a, c), (d, e) = b
        return max(MIN_SPAN * 2, abs(c - a), abs(e - d)) * 1.05

    # -- view -------------------------------------------------------------
    def _scale(self, rect):
        return min(rect.width(), rect.height()) / max(1.0, self.span)

    def to_screen(self, rect, x, z):
        s = self._scale(rect)
        cx, cz = self.centre or (0.0, 0.0)
        return QPointF(rect.center().x() + (x - cx) * s, rect.center().y() + (z - cz) * s)

    def to_world(self, rect, point):
        s = self._scale(rect)
        cx, cz = self.centre or (0.0, 0.0)
        return (cx + (point.x() - rect.center().x()) / s,
                cz + (point.y() - rect.center().y()) / s)

    def zoom(self, factor, about=None):
        """Zoom by *factor* (>1 zooms in), keeping the world point under
        *about* (a screen point) where it is."""
        rect = self._rect
        before = self.to_world(rect, about) if (rect is not None and about is not None) else None
        self.span = max(MIN_SPAN, min(self._max_span(), self.span / factor))
        if before is not None:
            after = self.to_world(rect, about)
            cx, cz = self.centre
            self.centre = (cx + before[0] - after[0], cz + before[1] - after[1])
        self.menu.view.update()

    def pan(self, fx, fz):
        cx, cz = self.centre or (0.0, 0.0)
        step = self.span * PAN_STEP
        self.centre = (cx + fx * step, cz + fz * step)
        self.menu.view.update()

    # -- input ------------------------------------------------------------
    def handle_key(self, key):
        if key in (Qt.Key_Left, Qt.Key_A):
            self.pan(-1, 0)
        elif key in (Qt.Key_Right, Qt.Key_D):
            self.pan(1, 0)
        elif key in (Qt.Key_Up, Qt.Key_W):
            self.pan(0, -1)
        elif key in (Qt.Key_Down, Qt.Key_S):
            self.pan(0, 1)
        elif key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_PageUp):
            self.zoom(ZOOM_STEP)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore, Qt.Key_PageDown):
            self.zoom(1.0 / ZOOM_STEP)
        elif key in (Qt.Key_Space, Qt.Key_Home):
            self.centre_on_player()
        elif key in (Qt.Key_Escape, Qt.Key_M, Qt.Key_Backspace):
            self.menu._leave_map()

    def handle_mouse_press(self, pos):
        self._drag = (QPointF(pos), self.centre)

    def handle_mouse_move(self, pos, buttons):
        if self._drag is None or not (buttons & Qt.LeftButton) or self._rect is None:
            self._drag = None
            return
        start, centre = self._drag
        s = self._scale(self._rect)
        point = QPointF(pos)
        self.centre = (centre[0] - (point.x() - start.x()) / s,
                       centre[1] - (point.y() - start.y()) / s)
        self.menu.view.update()

    def handle_mouse_release(self):
        self._drag = None

    def handle_wheel(self, pos, delta):
        if delta:
            self.zoom(ZOOM_STEP ** (delta / 120.0), QPointF(pos))

    # -- painting ---------------------------------------------------------
    def draw(self, painter, w, h, text_font, display_font):
        margin = max(16, w // 40)
        top = max(56, h // 11)
        bottom = max(44, h // 14)
        rect = QRectF(margin, top, w - 2 * margin, h - top - bottom)
        self._rect = rect
        if self.centre is None:
            self.centre = self._world_centre()

        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        painter.setRenderHint(painter.SmoothPixmapTransform, True)

        # Heading.
        painter.setFont(display_font(max(16, min(30, w // 45))))
        painter.setPen(_GOLD_BRIGHT)
        painter.drawText(QRectF(0, 0, w, top - 6), int(Qt.AlignHCenter | Qt.AlignBottom), "Map")

        window = QPainterPath()
        window.addRect(rect)
        painter.fillPath(window, QColor(24, 30, 26))
        painter.setClipPath(window)
        self._draw_terrain(painter, rect, text_font)
        self._draw_places(painter, rect, text_font)
        self._draw_quests(painter, rect, text_font)
        self._draw_focus(painter, rect)
        self._draw_player(painter, rect)
        painter.setClipping(False)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_GOLD, 2.5))
        painter.drawRect(rect)
        painter.setPen(QPen(QColor(90, 74, 44), 1))
        painter.drawRect(rect.adjusted(5, 5, -5, -5))
        painter.setFont(display_font(max(12, min(20, w // 70))))
        painter.setPen(_GOLD_BRIGHT)
        painter.drawText(QRectF(rect.center().x() - 20, rect.top() + 6, 40, 26),
                         int(Qt.AlignCenter), "N")

        painter.setFont(text_font(max(9, min(12, w // 130))))
        painter.setPen(_CAPTION)
        painter.drawText(QRectF(0, rect.bottom() + 4, w, bottom - 4),
                         int(Qt.AlignCenter),
                         "Drag  pan      Wheel  zoom      Space  you      Esc  back")
        painter.restore()

    def _draw_terrain(self, painter, rect, text_font):
        world = self.world
        image = world.image() if (world is not None and world.ready) else None
        if image is None:
            painter.setFont(text_font(14, italic=True) if _takes_italic(text_font)
                            else text_font(14))
            painter.setPen(QColor(210, 204, 190))
            msg = ("The cartographer is still at work…"
                   if world is None or not getattr(world, "error", None) else "No map of this land.")
            painter.drawText(rect, int(Qt.AlignCenter), msg)
            if world is not None and getattr(world, "building", False):
                self.menu.view.update()          # repaint until it is ready
            return
        (min_x, max_x), (min_z, max_z) = world.bounds
        a = self.to_screen(rect, min_x, min_z)
        b = self.to_screen(rect, max_x, max_z)
        target = QRectF(a, b)
        visible = target.intersected(rect)
        if visible.isEmpty():
            return
        # Only the part of the picture on screen, so a deep zoom stays cheap.
        sx = image.width() / target.width()
        sy = image.height() / target.height()
        src = QRectF((visible.left() - target.left()) * sx, (visible.top() - target.top()) * sy,
                     visible.width() * sx, visible.height() * sy)
        painter.drawImage(visible, image, src)

    def _draw_places(self, painter, rect, text_font):
        painter.setFont(text_font(11))
        fm = painter.fontMetrics()
        for name, x, z in self.features.get("places", ()):
            p = self.to_screen(rect, x, z)
            if not rect.adjusted(-80, -20, 80, 20).contains(p):
                continue
            painter.setPen(QPen(QColor(30, 20, 8), 1.2))
            painter.setBrush(_GOLD_BRIGHT)
            painter.drawRect(QRectF(p.x() - 4, p.y() - 4, 8, 8))
            tw = fm.horizontalAdvance(name)
            box = QRectF(p.x() - tw / 2 - 5, p.y() + 7, tw + 10, fm.height() + 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(12, 10, 8, 150))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(_INK)
            painter.drawText(box, int(Qt.AlignCenter), name)

    def _draw_quests(self, painter, rect, text_font):
        painter.setFont(text_font(10))
        fm = painter.fontMetrics()
        for name, x, z, _qid, tracked in self.features.get("quests", ()):
            p = self.to_screen(rect, x, z)
            if not rect.adjusted(-80, -20, 80, 20).contains(p):
                continue
            size = 9 if tracked else 7
            diamond = QPolygonF([p + QPointF(0, -size), p + QPointF(size * 0.85, 0),
                                 p + QPointF(0, size), p + QPointF(-size * 0.85, 0)])
            painter.setBrush(QBrush(_QUEST if tracked else _QUEST_DIM))
            painter.setPen(QPen(QColor(60, 40, 0), 1.4))
            painter.drawPolygon(diamond)
            tw = fm.horizontalAdvance(name)
            box = QRectF(p.x() - tw / 2 - 5, p.y() - size - fm.height() - 6,
                         tw + 10, fm.height() + 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(12, 10, 8, 160))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(_QUEST if tracked else _QUEST_DIM)
            painter.drawText(box, int(Qt.AlignCenter), name)

    def _draw_focus(self, painter, rect):
        if self.focus is None:
            return
        p = self.to_screen(rect, self.focus[0], self.focus[1])
        t = time.monotonic() - self._opened_at
        r = 16 + 6 * (0.5 + 0.5 * math.sin(t * 4.0))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(250, 214, 70, 220), 2.5))
        painter.drawEllipse(p, r, r)
        self.menu.view.update()                  # keep the ring breathing

    def _draw_player(self, painter, rect):
        player = self.features.get("player")
        if player is None:
            return
        x, z, angle = player
        c = self.to_screen(rect, x, z)
        fx, fz = math.sin(angle), math.cos(angle)
        k = 1.4
        tip = QPointF(c.x() + fx * 9 * k, c.y() + fz * 9 * k)
        left = QPointF(c.x() + (-fz * 6 - fx * 6) * k, c.y() + (fx * 6 - fz * 6) * k)
        right = QPointF(c.x() + (fz * 6 - fx * 6) * k, c.y() + (-fx * 6 - fz * 6) * k)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(QPen(QColor(20, 20, 20), 1.6))
        painter.drawPolygon(QPolygonF([tip, left, c, right]))


def _takes_italic(text_font):
    try:
        text_font(10, italic=True)
        return True
    except TypeError:
        return False
