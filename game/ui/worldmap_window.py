"""
The world map in a window of its own, for the editor: the ``worldmap``
console command.

The whole map's picture (:class:`game.ui.worldmap.WorldMap`: terrain, biome
regions, water, woods and buildings, painted once in the background and
cached) with the editor camera on it -- where it is and which way it looks --
refreshed ten times a second as the camera moves. Click anywhere on the
map and the camera jumps there. A plain Qt tool window:
it floats over the editor, opens at 800 x 600 and can be shrunk to 320 x
240 (the map scales to fit), and closing it stops its timer. Only one is
open at a time; the command raises it again.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QSizeGrip, QWidget

from . import worldmap

#: How often the camera's place is redrawn (milliseconds): 10 Hz.
REFRESH_MS = 100
#: The window's largest and smallest sizes; the map scales to fit.
MAX_SIZE = (800, 600)
MIN_SIZE = (320, 240)
CAMERA = QColor(255, 210, 60)
CAMERA_EDGE = QColor(30, 20, 10)
BACKGROUND = QColor(22, 20, 26)
INK = QColor(232, 226, 210)

_OPEN = []


class WorldMapWindow(QWidget):
    def __init__(self, main_window):
        super().__init__(main_window, Qt.Tool)
        self.main_window = main_window
        self.setWindowTitle("World Map")
        self.setToolTip("Click to move the editor camera there")
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        # 800 x 600 at most, and it shrinks (the map scales) to 320 x 240.
        self.setMaximumSize(*MAX_SIZE)
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*MAX_SIZE)
        # A handle in the bottom-right corner to drag it bigger or smaller
        # (the window's edges resize it too).
        self._grip = QSizeGrip(self)
        self._grip.resize(16, 16)
        self._camera = None              # (x, z, yaw degrees)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(REFRESH_MS)
        self._refresh()

    # -- data -------------------------------------------------------------
    def _view(self):
        return getattr(self.main_window, "view_3d", None)

    def _refresh(self):
        view = self._view()
        if view is None:
            return
        logic = getattr(view, "logic_thread", None)
        if logic is not None:
            try:
                worldmap.ensure_for(logic, view)
            except Exception:
                pass
        cam = getattr(view, "camera", None)
        if cam is not None:
            try:
                self._camera = (float(cam.pos.x), float(cam.pos.z), float(cam.yaw))
            except AttributeError:
                self._camera = (float(cam.pos[0]), float(cam.pos[2]), float(cam.yaw))
        self.update()

    def mousePressEvent(self, event):
        """Click anywhere on the map: the editor camera jumps there, at its
        own height and facing the way it was."""
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        world = worldmap.WORLD
        image = world.image()
        view = self._view()
        cam = getattr(view, "camera", None)
        if image is None or cam is None or world.bounds is None:
            return
        rect, scale = self._picture_rect(image)
        pos = event.pos()
        if not rect.contains(QPointF(pos)):
            return
        (min_x, _), (min_z, _) = world.bounds
        x = min_x + (pos.x() - rect.x()) / scale * world.cell
        z = min_z + (pos.y() - rect.y()) / scale * world.cell
        jump_camera(view, x, z)
        self._refresh()

    def resizeEvent(self, event):
        self._grip.move(self.width() - self._grip.width(), self.height() - self._grip.height())
        super().resizeEvent(event)

    def closeEvent(self, event):
        self._timer.stop()
        if self in _OPEN:
            _OPEN.remove(self)
        super().closeEvent(event)

    # -- drawing ----------------------------------------------------------
    def _picture_rect(self, image):
        """Where the picture is drawn: as large as fits, kept square to the
        world."""
        w, h = self.width(), self.height() - 22
        scale = min(w / image.width(), h / image.height())
        dw, dh = image.width() * scale, image.height() * scale
        return QRectF((w - dw) / 2.0, (h - dh) / 2.0, dw, dh), scale

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BACKGROUND)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        world = worldmap.WORLD
        image = world.image()
        p.setFont(QFont("Sans", 9))
        if image is None:
            p.setPen(INK)
            text = ("Painting the map..." if world.building or world.error is None
                    else f"No map: {world.error}")
            p.drawText(self.rect(), int(Qt.AlignCenter), text)
            p.end()
            return
        rect, scale = self._picture_rect(image)
        p.drawImage(rect, image)
        if self._camera is not None:
            x, z, yaw = self._camera
            ix, iz = world.to_image(x, z)
            at = QPointF(rect.x() + ix * scale, rect.y() + iz * scale)
            inside = rect.adjusted(-1, -1, 1, 1).contains(at)
            at = QPointF(min(max(at.x(), rect.left()), rect.right()),
                         min(max(at.y(), rect.top()), rect.bottom()))
            # The camera looks along (cos yaw, sin yaw) on the ground.
            a = math.radians(yaw)
            fx, fz = math.cos(a), math.sin(a)
            size = 11.0
            tip = QPointF(at.x() + fx * size, at.y() + fz * size)
            left = QPointF(at.x() - fx * size * 0.6 - fz * size * 0.6,
                           at.y() - fz * size * 0.6 + fx * size * 0.6)
            right = QPointF(at.x() - fx * size * 0.6 + fz * size * 0.6,
                            at.y() - fz * size * 0.6 - fx * size * 0.6)
            p.setPen(QPen(CAMERA_EDGE, 1.6))
            p.setBrush(CAMERA if inside else QColor(CAMERA.red(), CAMERA.green(),
                                                    CAMERA.blue(), 120))
            p.drawPolygon(QPolygonF([tip, left, right]))
            p.setPen(INK)
            p.drawText(QRectF(6, self.height() - 20, self.width() - 28, 18),
                       int(Qt.AlignLeft | Qt.AlignVCenter),
                       f"Editor camera  x {x:,.0f}   z {z:,.0f}"
                       + ("" if inside else "   (off the map)"))
        p.end()


def jump_camera(view, x, z) -> None:
    """Move the editor camera over world ``(x, z)``, keeping its height above
    the ground there as it was where it stood, and its facing. Through the
    view's ``set_editor_camera``: the logic thread owns the editor camera and
    copies it back every frame, so a move made on the view alone is undone."""
    cam = view.camera
    old = cam.pos
    y = float(old.y)
    terrain = getattr(getattr(view, "logic_thread", None), "world_runtime", None)
    terrain = getattr(terrain, "terrain", None)
    if terrain is not None:
        try:
            here = terrain.get_height_at_safe(float(old.x), float(old.z))
            there = terrain.get_height_at_safe(float(x), float(z))
            if here is not None and there is not None:
                y = float(there) + max(60.0, float(old.y) - float(here))
        except Exception:
            pass
    target = (float(x), y, float(z))
    setter = getattr(view, "set_editor_camera", None)
    if setter is not None:
        setter(target)
    else:
        import glm
        cam.pos = glm.vec3(*target)
    view.update()


def toggle(main_window):
    """Open the world map window, or bring the open one to the front."""
    if _OPEN:
        win = _OPEN[0]
        win.show()
        win.raise_()
        win.activateWindow()
        return win
    win = WorldMapWindow(main_window)
    _OPEN.append(win)
    win.show()
    return win
