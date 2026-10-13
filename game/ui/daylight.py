"""
Day and night over the world.

The game clock (:class:`game.rpg.gametime.GameClock`) runs a full day in
24 real minutes, one game hour a minute. This module turns its hour into how
the world looks:

* :func:`sky_at` — the colour and depth of the darkness at an hour, eased
  between key moments: full daylight, a warm evening, an amber-to-violet dusk,
  deep blue night, a grey-violet pre-dawn and a golden sunrise.
* :func:`draw` — that darkness laid over the scene (under the HUD), with a
  soft hole around every *local* light — the lamps, hearths and braziers of
  the map and every carried torch — so lit places stay lit at night and the
  rest of the world sinks into the dark. Each light also throws a faint
  glow of its own colour, and the player keeps a little moonlight about
  them, enough to see their own feet.

The 3D renderer's lighting has a fixed sun and an additive ambient term that
can brighten but never darken, so night is painted here, on the game's
overlay, where it can be measured headlessly. The mask is drawn at a quarter
of the view's resolution and scaled up smoothly: it is all soft gradients, so
nothing is lost, and painting it costs a sixteenth as much.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QRadialGradient

#: Key moments of the day: (hour, darkness colour, darkness 0..1).
SKY = (
    (0.0, (8, 12, 38), 0.74),
    (4.5, (8, 12, 38), 0.74),
    (5.5, (58, 42, 92), 0.46),
    (6.3, (255, 168, 92), 0.16),
    (7.3, (255, 200, 120), 0.0),
    (17.0, (255, 182, 96), 0.0),
    (18.5, (255, 128, 60), 0.18),
    (19.5, (118, 58, 108), 0.40),
    (20.5, (24, 24, 70), 0.62),
    (21.5, (8, 12, 38), 0.74),
    (24.0, (8, 12, 38), 0.74),
)

#: Lights larger than this (world units) are a map's fill light — the
#: author's stand-in for daylight over a whole area — not a lamp, so they get
#: no hole in the dark (one would undo the night across the map).
LOCAL_LIGHT_MAX_RADIUS = 1200.0
#: How much of a light's radius reads as lit through the dark.
LIT_FRACTION = 0.8
#: The player's own patch of moonlight: radius (world units) and how much of
#: the dark it lifts.
PLAYER_GLOW_RADIUS = 230.0
PLAYER_GLOW = 0.4
#: The mask is painted at this fraction of the view's size.
MASK_SCALE = 0.25
#: At most this many holes a frame (the nearest to the screen's centre win).
MAX_HOLES = 48

_mask = {"image": None}


def _ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def sky_at(hour: float):
    """``((r, g, b), darkness)`` at *hour* (0..24), eased between :data:`SKY`."""
    h = float(hour) % 24.0
    for (h0, c0, a0), (h1, c1, a1) in zip(SKY, SKY[1:]):
        if h0 <= h <= h1:
            t = _ease((h - h0) / (h1 - h0)) if h1 > h0 else 0.0
            colour = tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(3))
            return colour, a0 + (a1 - a0) * t
    return SKY[0][1], SKY[0][2]


def night_amount(hour: float) -> float:
    """0 in daylight, 1 in the depth of night (for glows and the like)."""
    return min(1.0, sky_at(hour)[1] / SKY[0][2])


def _world_to_screen(glm, proj, view, x, y, z, width, height):
    clip = proj * view * glm.vec4(float(x), float(y), float(z), 1.0)
    w = clip.w
    if w <= 1e-4:
        return None
    nx, ny = clip.x / w, clip.y / w
    return ((nx * 0.5 + 0.5) * width, (1.0 - (ny * 0.5 + 0.5)) * height)


def _local_lights(session):
    """``[(pos, radius, intensity, (r, g, b))]`` of the lit local lights."""
    out = []
    try:
        lights = session._type_buckets().get("light", ())
    except Exception:
        lights = ()
    for t in lights:
        p = t.properties
        state = p.get("state", "on")
        if state is False or str(state).lower() in ("off", "false", "0"):
            continue
        try:
            radius = float(p.get("radius", 512.0))
            intensity = float(p.get("intensity", 1.0))
        except (TypeError, ValueError):
            continue
        if radius <= 0.0 or radius > LOCAL_LIGHT_MAX_RADIUS or intensity <= 0.0:
            continue
        colour = p.get("colour") or p.get("color") or (255, 200, 140)
        try:
            colour = tuple(int(c) for c in list(colour)[:3])
        except (TypeError, ValueError):
            colour = (255, 200, 140)
        out.append((t.pos, radius, intensity, colour))
    return out


def holes(session, viewport, width, height):
    """``[(x, y, radius_px, strength, (r, g, b))]``: where the dark is lifted,
    in view pixels, for what is on screen."""
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return []
    out = []
    margin = 0.25
    sources = list(_local_lights(session))
    try:
        player = session._player_pos()
    except Exception:
        player = None
    if player is not None:
        sources.append((player, PLAYER_GLOW_RADIUS / LIT_FRACTION, None, None))
    for pos, radius, intensity, colour in sources:
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        centre = _world_to_screen(glm, proj, view, x, y, z, width, height)
        edge = _world_to_screen(glm, proj, view, x + radius * LIT_FRACTION, y, z, width, height)
        if centre is None or edge is None:
            continue
        r_px = math.hypot(edge[0] - centre[0], edge[1] - centre[1])
        if r_px < 2.0:
            continue
        if (centre[0] + r_px < -width * margin or centre[0] - r_px > width * (1 + margin)
                or centre[1] + r_px < -height * margin or centre[1] - r_px > height * (1 + margin)):
            continue
        if intensity is None:
            strength = PLAYER_GLOW
        else:
            strength = max(0.0, min(1.0, 0.45 + 0.4 * intensity))
        out.append((centre[0], centre[1], r_px, strength, colour))
    if len(out) > MAX_HOLES:
        cx, cy = width / 2.0, height / 2.0
        out.sort(key=lambda h: (h[0] - cx) ** 2 + (h[1] - cy) ** 2)
        out = out[:MAX_HOLES]
    return out


def paint_mask(width, height, colour, darkness, lifted, night=1.0) -> QImage:
    """The darkness layer at *MASK_SCALE*: *colour* at *darkness*, with each of
    *lifted* (``(x, y, r, strength, rgb)`` in view pixels) cut out softly
    and, after dark, washed faintly with its light's colour."""
    mw = max(1, int(width * MASK_SCALE))
    mh = max(1, int(height * MASK_SCALE))
    img = _mask["image"]
    if img is None or img.width() != mw or img.height() != mh:
        img = _mask["image"] = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    # No antialiasing: every edge here is a gradient already fading to nothing.
    p.fillRect(QRect(0, 0, mw, mh), QColor(colour[0], colour[1], colour[2],
                                           int(255 * max(0.0, min(1.0, darkness)))))
    p.setPen(Qt.NoPen)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    for x, y, r, strength, _rgb in lifted:
        c = QPointF(x * MASK_SCALE, y * MASK_SCALE)
        rr = r * MASK_SCALE
        g = QRadialGradient(c, rr)
        g.setColorAt(0.0, QColor(0, 0, 0, int(255 * strength)))
        g.setColorAt(0.45, QColor(0, 0, 0, int(255 * strength * 0.8)))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(g)
        p.drawEllipse(c, rr, rr)
    if night > 0.05:
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        for x, y, r, strength, rgb in lifted:
            if rgb is None:
                continue
            c = QPointF(x * MASK_SCALE, y * MASK_SCALE)
            rr = r * MASK_SCALE * 0.85
            g = QRadialGradient(c, rr)
            g.setColorAt(0.0, QColor(rgb[0], rgb[1], rgb[2], int(60 * strength * night)))
            g.setColorAt(1.0, QColor(rgb[0], rgb[1], rgb[2], 0))
            p.setBrush(g)
            p.drawEllipse(c, rr, rr)
    p.end()
    return img


def draw(painter, session, viewport, width, height) -> None:
    """Lay the hour's darkness over the scene (call before the HUD)."""
    clock = getattr(session, "clock", None)
    if clock is None or width <= 0 or height <= 0:
        return
    colour, darkness = sky_at(clock.hour)
    if darkness <= 0.004:
        return
    lifted = holes(session, viewport, width, height) if viewport is not None else []
    img = paint_mask(width, height, colour, darkness, lifted, night_amount(clock.hour))
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawImage(QRect(0, 0, int(width), int(height)), img)
    painter.restore()
