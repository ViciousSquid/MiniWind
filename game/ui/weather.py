"""Weather over the top-down view, with a fixed amount of local drawing.

Rain falls from the camera towards the ground: foreground drops are longest
at the screen's edges and converge towards the middle as they descend. The
world remains readable through lighter rain over the centre. Tiny rings mark
the final moments of a drop, while snow drifts more slowly in the same view.

All positions are viewport coordinates. No actor, cell, terrain chunk or
off-screen particle is created or visited, so a larger Big World costs exactly
the same as a small map. The host calls this below its HUD for exposed views.
"""

from __future__ import annotations

import math
import random
from typing import NamedTuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QRadialGradient


MAX_RAIN = 500
MAX_SNOW = 300
MAX_SPLASHES = 64


class Streak(NamedTuple):
    tail_x: float
    tail_y: float
    head_x: float
    head_y: float
    opacity: float
    width: float


class Splash(NamedTuple):
    x: float
    y: float
    radius: float
    opacity: float


def _seeds():
    # A private RNG keeps weather decoration independent of gameplay rolls.
    rng = random.Random(71893)
    return tuple((rng.uniform(-.08, 1.08), rng.uniform(-.08, 1.08),
                  rng.random(), rng.random(), rng.random())
                 for _ in range(MAX_RAIN))


_SEEDS = _seeds()


def _unit(value):
    return max(0., min(1., float(value)))


def rain_geometry(snapshot, width, height):
    """Bounded streaks and ground rings for this viewport and weather frame.

    Phase is derived from the simulation's time, so repainting or resizing
    neither advances rain nor consumes random numbers. A paused world stays
    still without a separate UI timer.
    """
    rain = _unit(snapshot.rain)
    if rain <= .002 or width <= 0 or height <= 0:
        return (), ()
    count = min(MAX_RAIN, max(1, int(width * height / 3000.)))
    scale = max(.65, min(2.1, math.sqrt(width * height / (1280. * 720.))))
    cx, cy = width * .5, height * .5
    wind_x = max(-1., min(1., snapshot.wind_x))
    wind_z = max(-1., min(1., snapshot.wind_z))
    streaks, splashes = [], []
    for index, (u, v, offset, speed, depth) in enumerate(_SEEDS[:count]):
        # Keep each drop's identity as strength changes. Bringing its alpha
        # up over a small strength band avoids a bright new streak appearing
        # abruptly whenever an integer particle count would have changed.
        activation = _unit((rain - .92 * (index + .5) / count) / .08)
        if activation <= .002:
            continue
        phase = (snapshot.time / (.48 + speed * .34) + offset) % 1.
        base_x, base_y = u * width, v * height
        altitude = 1. + .42 * (1. - phase)
        x = cx + (base_x - cx) * altitude - wind_x * width * .035 * (1. - phase)
        y = cy + (base_y - cy) * altitude - wind_z * height * .04 * (1. - phase)
        # An orthographic overhead camera still has a small wind-driven fall
        # through the centre, where radial perspective alone would disappear.
        dx = (cx - base_x) * .42 + wind_x * width * .035 + width * .004
        dy = (cy - base_y) * .42 + wind_z * height * .04 + height * .012
        distance = math.hypot(dx, dy) or 1.
        edge = min(1., max(abs(u - .5), abs(v - .5)) * 2.)
        length = (2.5 + edge ** 1.5 * 23. + depth * 5.) * scale
        opacity = rain * activation * (.10 + .90 * edge ** 1.65) * (.48 + .30 * depth)
        thickness = (.55 + .48 * edge + .30 * depth) * scale
        if depth > .78 and edge > .55:
            # Sparse drops close to the lens sweep past the border. Their
            # longer streaks supply the reference's sense of depth without
            # putting thick foreground rain over the player.
            length *= 2.4
            thickness *= 1.4
            opacity = min(1., opacity * 1.3)
        if -length <= x <= width + length and -length <= y <= height + length:
            streaks.append(Streak(x - dx / distance * length,
                                  y - dy / distance * length, x, y, opacity,
                                  thickness))
        if phase >= .87 and len(splashes) < MAX_SPLASHES:
            progress = (phase - .87) / .13
            if 0. <= base_x <= width and 0. <= base_y <= height:
                splashes.append(Splash(base_x, base_y,
                                       (.7 + 3.1 * progress) * scale,
                                       rain * activation * .24 * (1. - progress)))
    return streaks, splashes


def _draw_rain(painter, snapshot, width, height):
    streaks, splashes = rain_geometry(snapshot, width, height)
    for streak in streaks:
        pen = QPen(QColor(181, 207, 224, int(135 * streak.opacity)))
        pen.setWidthF(streak.width)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(streak.tail_x, streak.tail_y),
                         QPointF(streak.head_x, streak.head_y))
        # A short pale tip makes foreground drops read as motion rather than
        # white scratches, without a gradient allocation for every particle.
        pen.setColor(QColor(220, 237, 246, int(160 * streak.opacity)))
        pen.setWidthF(streak.width * .65)
        painter.setPen(pen)
        painter.drawLine(QPointF(streak.tail_x * .30 + streak.head_x * .70,
                                streak.tail_y * .30 + streak.head_y * .70),
                         QPointF(streak.head_x, streak.head_y))
    painter.setBrush(Qt.NoBrush)
    for splash in splashes:
        pen = QPen(QColor(189, 211, 222, int(255 * splash.opacity)))
        pen.setWidthF(.7)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(splash.x, splash.y),
                            splash.radius, splash.radius * .62)


def _draw_snow(painter, snapshot, width, height):
    snow = _unit(snapshot.snow)
    count = min(MAX_SNOW, max(1, int(width * height / 4200.)))
    scale = max(.65, min(2., math.sqrt(width * height / (1280. * 720.))))
    painter.setPen(Qt.NoPen)
    for index, (u, v, offset, speed, depth) in enumerate(_SEEDS[:count]):
        activation = _unit((snow - .92 * (index + .5) / count) / .08)
        if activation <= .002:
            continue
        period = 3.5 + speed * 4.5
        fall = snapshot.time / period + offset
        # Wind bends a bounded drift rather than multiplying absolute time.
        # Otherwise changing a front after a long session teleports flakes.
        gust = snapshot.time * .45 + offset * math.tau
        x = ((u + fall * .07 + snapshot.wind_x * .04 * math.sin(gust)
              + math.sin(snapshot.time * .7 + offset * math.tau) * .012) % 1.) * width
        y = ((v + fall * .22 + snapshot.wind_z * .025 * math.sin(gust)) % 1.) * height
        edge = min(1., max(abs(x / width - .5), abs(y / height - .5)) * 2.)
        alpha = int(snow * activation * (70 + 105 * edge) * (.55 + depth * .45))
        painter.setBrush(QColor(224, 235, 242, alpha))
        radius = (.65 + depth * 1.25) * scale
        painter.drawEllipse(QPointF(x, y), radius, radius)


def draw_weather(painter, session, width, height):
    """Paint local weather beneath the HUD, without touching the world."""
    weather = getattr(session, "weather", None)
    snapshot = getattr(weather, "snapshot", None)
    if snapshot is None or width <= 0 or height <= 0:
        return
    rain, snow = _unit(snapshot.rain), _unit(snapshot.snow)
    overcast, flash = _unit(snapshot.overcast), _unit(snapshot.lightning)
    if max(rain, snow, overcast, flash) <= .002:
        return
    painter.save()
    try:
        rect = QRectF(0., 0., float(width), float(height))
        painter.setClipRect(rect, Qt.IntersectClip)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if overcast > .002:
            painter.fillRect(rect, QColor(22, 32, 47, int(36 * overcast)))
            edge = QRadialGradient(QPointF(width * .5, height * .5),
                                   math.hypot(width, height) * .53)
            edge.setColorAt(.25, QColor(13, 24, 37, 0))
            edge.setColorAt(1., QColor(13, 24, 37, int(29 * overcast)))
            painter.fillRect(rect, edge)
        if rain > .002:
            _draw_rain(painter, snapshot, width, height)
        if snow > .002:
            _draw_snow(painter, snapshot, width, height)
        if flash > .002:
            painter.fillRect(rect, QColor(224, 235, 247, int(48 * flash)))
    finally:
        painter.restore()
