"""Shared witness glyphs and last-sighting circles for both maps."""

import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetricsF, QPainterPath, QPen, QPolygonF, QRadialGradient

from . import fonts

SEARCH_LABEL_PERIOD = 60.0


def draw_witness(painter, point, witness, radius=7.0):
    painter.save()
    x, y = point.x(), point.y()
    identified = witness.get("identified", False)
    color = QColor(240, 100, 64) if witness.get("reporting") else (
        QColor(255, 201, 94) if identified else QColor(206, 211, 220))
    painter.setPen(QPen(QColor(25, 18, 15), 1.5))
    painter.setBrush(QColor(28, 23, 25, 240))
    painter.drawEllipse(point, radius + 2, radius + 2)
    painter.setPen(QPen(color, 1.6))
    if identified:
        eye = QPainterPath(QPointF(x - radius, y))
        eye.quadTo(x, y - radius, x + radius, y)
        eye.quadTo(x, y + radius, x - radius, y)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(eye)
        painter.setBrush(color)
        painter.drawEllipse(point, radius * 0.27, radius * 0.27)
    else:
        painter.setFont(fonts.dialogue_font(10))
        painter.drawText(QRectF(x - radius, y - radius - 1, radius * 2, radius * 2),
                         int(Qt.AlignCenter), "?")
    if witness.get("reporting"):
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([QPointF(x - 3, y + radius + 2),
                                       QPointF(x + 3, y + radius + 2),
                                       QPointF(x, y + radius + 7)]))
    painter.restore()


def draw_search(painter, status, to_screen, scale):
    if (not status or status.get("phase") != "search"
            or not status.get("show_radius", True)):
        return
    centre = status.get("centre")
    if centre is None:
        return
    painter.save()
    radius = status["radius"] * scale
    point = to_screen(centre[0], centre[2])
    wash = QRadialGradient(point, radius)
    wash.setColorAt(0, QColor(140, 30, 28, 35))
    wash.setColorAt(1, QColor(140, 30, 28, 18))
    painter.setPen(QPen(QColor(160, 48, 38, 140), 1.5))
    painter.setBrush(wash)
    painter.drawEllipse(point, radius, radius)
    painter.setPen(QPen(QColor(210, 172, 96, 150), 0.8))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(point, max(0, radius - 2), max(0, radius - 2))
    _search_label(painter, point, radius)
    painter.restore()


def _search_label(painter, centre, radius):
    """Follow the lower rim, keeping the map itself readable through the wash."""
    painter.setFont(fonts.dialogue_font(10))
    metrics = QFontMetricsF(painter.font())
    label = "Searching"
    baseline = max(28.0, radius + metrics.height() * 0.85)
    rotation = (time.monotonic() % SEARCH_LABEL_PERIOD) / SEARCH_LABEL_PERIOD * math.tau
    advances = [metrics.horizontalAdvance(ch) + 0.5 for ch in label]
    cursor = -sum(advances) / 2
    for char, advance in zip(label, advances):
        angle = math.pi / 2 + rotation - (cursor + advance / 2) / baseline
        painter.save()
        painter.translate(centre.x() + math.cos(angle) * baseline,
                          centre.y() + math.sin(angle) * baseline)
        painter.rotate(math.degrees(angle) - 90)
        painter.setPen(QPen(QColor(18, 16, 14, 220), 1))
        painter.drawText(QPointF(-advance / 2 + 1, 1), char)
        painter.setPen(QColor(246, 211, 151))
        painter.drawText(QPointF(-advance / 2, 0), char)
        painter.restore()
        cursor += advance
