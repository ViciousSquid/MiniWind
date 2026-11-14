"""
Rain, seen from above (the look of :mod:`game.weather`).

The camera looks down on the Vale, so a falling drop is seen end-on: near
the camera it is big, soft and out of focus, far out toward the edge of the
view; it streaks in toward the middle as it falls away, smaller and sharper,
to the ground -- then splashes, a small ring opening where it lands. The wind leans the
streaks (hard in a storm's gale). Under it the scene is washed cooler and
darker as the cloud thickens, and a storm's lightning (game/lightning.py)
lights everything white -- a strike close enough to see drawn as a jagged
bolt down to where it hits, glowing on the ground there.

Drawn over the world and under the HUD, as flat 2D. Nothing is kept between
frames: every drop is placed from its index and the clock, so it costs one
batched line draw and one batch of rings, however long it rains. A bolt,
for the third of a second it shows, is two more batched line draws and a
glow where it hits.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QLineF, QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QPen

from ..lightning import BOLT_SECONDS, flicker

#: Drops on screen at full rain (the screen's area at 1280 x 720).
DROPS = 260
#: Seconds a drop falls, and how far out it starts near the camera (its
#: distance from the middle of the view grows by up to this much).
FALL_SECONDS = 0.55
NEAR_SPREAD = 2.6
#: The share of its fall a drop's streak covers, by band: short near the
#: camera (a soft smear), longer far below (a fine streak); and the splash.
BAND_STREAK = (0.05, 0.1, 0.18)
#: Each band's line (width px, alpha 0..255, colour): near the camera wide,
#: soft and faint (out of focus); far below fine and bright.
BAND_LOOK = ((11.0, 30, (195, 210, 238)), (3.0, 90, (210, 222, 242)),
             (1.2, 190, (230, 238, 250)))
SPLASH_SECONDS = 0.22
SPLASH_RADIUS = 7.0
#: How far the wind leans a drop (pixels across its fall at full wind; a
#: storm's gale blows past full).
WIND_LEAN = 40.0
#: A bolt: how far up the screen it starts (share of the height), how many
#: times its path is split and jogged, how far a jog goes (share of the
#: segment), and its glow and core (width px, colour).
BOLT_RISE = 0.6
BOLT_SPLITS = 5
BOLT_JAG = 0.35
BOLT_GLOW = (13.0, (140, 165, 255))
BOLT_CORE = (3.0, (250, 252, 255))


def _hash(i, k):
    """A stable pseudo-random 0..1 for drop *i*, stream *k*."""
    x = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return x - math.floor(x)


def draw(painter, weather, wind, width, height, now, lightning=None, to_screen=None) -> None:
    """The rain, the gloom and the lightning for *weather* this instant.
    *lightning* is the storm's strikes (game/lightning.py) and *to_screen*
    ``(x, y, z) -> (px, py) or None`` projects where they hit; without
    them a storm only flashes, now and then."""
    if weather is None:
        return
    gloom = float(getattr(weather, "gloom", 0.0))
    rain = float(getattr(weather, "rain", 0.0))
    if gloom <= 0.01 and rain <= 0.02:
        return
    painter.save()
    if gloom > 0.01:
        painter.fillRect(QRect(0, 0, width, height), QColor(22, 30, 44, int(150 * gloom)))
    if rain > 0.02:
        _drops(painter, rain, wind, width, height, now)
    if lightning is not None:
        flash = lightning.flash()
    else:
        flash = _lightning(now) if getattr(weather, "kind", "") == "storm" else 0.0
    if flash > 0.0:
        painter.fillRect(QRect(0, 0, width, height), QColor(235, 240, 255, int(150 * flash)))
    # The bolt over its own flash, so the wash never dims it.
    if lightning is not None and to_screen is not None:
        for strike, age in lightning.bolts():
            at = to_screen(strike.x, strike.y, strike.z)
            if at is not None:
                _bolt(painter, strike.seed, at, age, width, height)
    painter.restore()


def _drops(painter, rain, wind, width, height, now) -> None:
    """Each drop falls from near the camera -- big, soft, far out from the
    middle of the view -- down to the ground -- small, sharp, near where it
    lands -- streaking outward-in as it goes, then splashes. Drawn in three
    bands by nearness (soft and wide near the camera, fine and bright far
    below), each one batched line draw."""
    n = int(DROPS * rain * (width * height) / (1280.0 * 720.0))
    cx, cy = width * 0.5, height * 0.5
    wx, wz = (wind or (0.0, 0.0))
    lean_x, lean_y = wx * WIND_LEAN, wz * WIND_LEAN
    bands = ([], [], [])          # near, middle, far
    rings = []
    for i in range(n):
        offset = _hash(i, 0)
        t = now / FALL_SECONDS + offset
        cycle = math.floor(t)
        phase = t - cycle
        gx = _hash(i, cycle * 3.1 + 1.0) * width
        gy = _hash(i, cycle * 3.1 + 2.0) * height

        def at(p):
            near = 1.0 - p                       # 1 at the camera .. 0 on the ground
            k = 1.0 + NEAR_SPREAD * near * near   # perspective: near is far out
            return (cx + (gx - cx) * k - lean_x * near, cy + (gy - cy) * k - lean_y * near)

        band = 0 if phase < 0.45 else (1 if phase < 0.8 else 2)
        head = at(phase)
        tail = at(max(0.0, phase - BAND_STREAK[band]))
        if not (-60 <= head[0] <= width + 60 and -60 <= head[1] <= height + 60):
            continue
        bands[band].append(QLineF(tail[0], tail[1], head[0], head[1]))
        if phase < SPLASH_SECONDS / FALL_SECONDS:
            s = phase / (SPLASH_SECONDS / FALL_SECONDS)
            rings.append((_hash(i, (cycle - 1) * 3.1 + 1.0) * width,
                          _hash(i, (cycle - 1) * 3.1 + 2.0) * height, s))
    alpha = 0.55 + 0.45 * rain
    for lines, (width_px, a, rgb) in zip(bands, BAND_LOOK):
        if not lines:
            continue
        pen = QPen(QColor(*rgb, int(a * alpha)), width_px)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLines(lines)
    painter.setBrush(Qt.NoBrush)
    for px, py, s in rings:
        r = 1.5 + SPLASH_RADIUS * s
        painter.setPen(QPen(QColor(215, 228, 245, int(150 * (1.0 - s) * alpha)), 1.0))
        painter.drawEllipse(QRectF(px - r, py - r * 0.6, r * 2, r * 1.2))


def bolt_path(seed, end, width, height):
    """The jagged bolt for strike *seed* coming down to *end* (px), as
    ``(trunk, branches)``: lists of points from the sky to the ground.
    Placed from the seed alone, so a bolt keeps its shape while it shows."""
    ex, ey = end
    sx = ex + (_hash(seed, 1) - 0.5) * width * 0.35
    sy = ey - height * BOLT_RISE * (0.7 + 0.3 * _hash(seed, 2))
    trunk = [(sx, sy), (ex, ey)]
    for level in range(BOLT_SPLITS):
        out = [trunk[0]]
        for i, (a, b) in enumerate(zip(trunk, trunk[1:])):
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            jog = (_hash(seed, 10 + level * 37 + i) - 0.5) * 2.0 * BOLT_JAG * seg
            # Jog across the segment, so the path zigzags rather than bunching.
            nx, ny = (-(b[1] - a[1]) / seg, (b[0] - a[0]) / seg) if seg > 1e-6 else (0.0, 0.0)
            out.append(((a[0] + b[0]) * 0.5 + nx * jog, (a[1] + b[1]) * 0.5 + ny * jog))
            out.append(b)
        trunk = out
    branches = []
    for k in range(1 + int(_hash(seed, 3) * 2.0)):
        i = int(len(trunk) * (0.2 + 0.5 * _hash(seed, 4 + k)))
        bx, by = trunk[i]
        length = height * (0.08 + 0.1 * _hash(seed, 6 + k))
        angle = math.pi * 0.5 + (0.6 + 0.5 * _hash(seed, 8 + k)) * (1 if k % 2 else -1)
        points = [(bx, by)]
        for j in range(1, 5):
            t = j / 4.0
            wob = (_hash(seed, 40 + k * 7 + j) - 0.5) * length * 0.25
            points.append((bx + math.cos(angle) * length * t + wob,
                           by + math.sin(angle) * length * t))
        branches.append(points)
    return trunk, branches


def _bolt(painter, seed, end, age, width, height) -> None:
    """A strike in view: its bolt, a soft glow round it and a white core,
    flickering with the flash, and the ground lit where it hits."""
    # The bolt stays lit through the flash's dark beat (the eye holds it).
    bright = max(flicker(age), 0.6 if age < BOLT_SECONDS else 0.0)
    if bright <= 0.0:
        return
    trunk, branches = bolt_path(seed, end, width, height)
    lines = [QLineF(a[0], a[1], b[0], b[1])
             for path in [trunk, *branches] for a, b in zip(path, path[1:])]
    painter.setRenderHint(painter.Antialiasing, True)
    for (width_px, rgb), alpha in ((BOLT_GLOW, 120), (BOLT_CORE, 255)):
        pen = QPen(QColor(*rgb, int(alpha * bright)), width_px)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLines(lines)
    painter.setPen(Qt.NoPen)
    for radius, alpha in ((34.0, 70), (16.0, 170)):
        painter.setBrush(QColor(225, 232, 255, int(alpha * bright)))
        painter.drawEllipse(QPointF(end[0], end[1]), radius, radius * 0.65)
    painter.setBrush(Qt.NoBrush)


def _lightning(now) -> float:
    """A storm's flash with no strikes to go by (a caller passing no
    lightning): 0 most of the time; now and then a double flicker."""
    slot = math.floor(now / 7.0)
    if _hash(int(slot), 9) > 0.55:
        return 0.0
    t = now - slot * 7.0 - _hash(int(slot), 10) * 5.0
    if 0.0 <= t < 0.08:
        return 1.0 - t / 0.08
    if 0.16 <= t < 0.30:
        return 0.6 * (1.0 - (t - 0.16) / 0.14)
    return 0.0
