"""A HUD picture painted once and reused until what it shows changes.

The HUD is drawn with QPainter over the GL view every frame. Most of it --
the inventory strip, the bars, the frame's text -- is the same picture frame
after frame, and redrawing it was milliseconds of the UI thread each frame:
every rounded rect, gradient and text run tessellated and sent to GL again.

:class:`PaintCache` paints a region into an image when its *key* (the values
the picture is drawn from) changes, and otherwise draws that same image: one
textured quad, and the same image object, so Qt's GL paint engine keeps its
texture. A key names what is visible -- a bar's fill in whole pixels, the
number written on it -- so a change too small to see does not repaint.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap


class PaintCache:
    __slots__ = ("key", "pixmap", "origin", "paints", "painted_at", "urgent")

    def __init__(self):
        self.key = None
        self.pixmap = None
        self.origin = None
        #: How many times the picture was painted (tests, diagnostics).
        self.paints = 0
        self.painted_at = 0.0
        self.urgent = None

    def draw(self, painter, key, rect, paint, interval=None, urgent=None):
        """Draw ``paint(p)`` -- which paints in *painter*'s coordinates,
        inside *rect* -- from the cached picture while *key* is unchanged.

        With an *interval* (seconds) a changed key repaints at most that
        often: in between, the last picture stands. A change of place or
        size, or of *urgent* (the part of what it shows that must never lag,
        such as which way it faces), always repaints."""
        rect = QRect(rect)
        if rect.isEmpty():
            return
        device = painter.device()
        dpr = float(device.devicePixelRatioF()) if device is not None else 1.0
        full = (key, rect.x(), rect.y(), rect.width(), rect.height(), round(dpr, 3))
        if (full != self.key and interval and self.pixmap is not None
                and full[1:] == self.key[1:] and urgent == self.urgent
                and time.perf_counter() - self.painted_at < interval):
            full = self.key                      # held until the interval is up
        if full != self.key or self.pixmap is None:
            image = QImage(int(math.ceil(rect.width() * dpr)),
                           int(math.ceil(rect.height() * dpr)),
                           QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.transparent)
            p = QPainter(image)
            try:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setRenderHint(QPainter.TextAntialiasing, True)
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.translate(-rect.x(), -rect.y())
                paint(p)
            finally:
                p.end()
            self.pixmap = QPixmap.fromImage(image)
            self.origin = rect.topLeft()
            self.key = full
            self.paints += 1
            self.painted_at = time.perf_counter()
            self.urgent = urgent
        painter.drawPixmap(self.origin, self.pixmap)

    def clear(self):
        self.key = self.pixmap = self.origin = None
