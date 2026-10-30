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

import numpy as np
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

_mask = {}
#: key -> what its image in _mask was last painted from.
_mask_signature = {}


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


#: Parsed light settings by their raw values -- see _light_params.
_PARAMS = {}
_OFF_STATES = ("off", "false", "0")
_DEFAULT_RGB = (255, 200, 140)


def _parse_params(state, radius, intensity, colour):
    if state is False or str(state).lower() in _OFF_STATES:
        return None
    try:
        radius = float(radius)
        intensity = float(intensity)
    except (TypeError, ValueError):
        return None
    if radius <= 0.0 or radius > LOCAL_LIGHT_MAX_RADIUS or intensity <= 0.0:
        return None
    try:
        colour = tuple(int(c) for c in list(colour)[:3])
    except (TypeError, ValueError):
        colour = _DEFAULT_RGB
    return radius, intensity, colour


def _light_params(p):
    """``(radius, intensity, rgb)`` of a lit local light, else None.

    Memoised on the raw property values: a map's lamps share a handful of
    settings, and parsing them for every lamp every frame (twice, with the
    minimap) was most of the night overlay's Python time."""
    state = p.get("state", "on")
    radius = p.get("radius", 512.0)
    intensity = p.get("intensity", 1.0)
    colour = p.get("colour") or p.get("color") or _DEFAULT_RGB
    try:
        key = (state, radius, intensity,
               colour if type(colour) is tuple else tuple(colour))
        hit = _PARAMS.get(key, _PARAMS)
    except TypeError:                        # unhashable or not a sequence
        return _parse_params(state, radius, intensity, colour)
    if hit is _PARAMS:
        if len(_PARAMS) > 1024:
            _PARAMS.clear()
        hit = _PARAMS[key] = _parse_params(state, radius, intensity, colour)
    return hit


def _local_lights(session):
    """``[(pos, radius, intensity, (r, g, b))]`` of the lit local lights."""
    out = []
    try:
        lights = session._type_buckets().get("light", ())
    except Exception:
        lights = ()
    for t in lights:
        # A silhouette light casts a shadow in the 3D terrain shader, but is
        # not a lamp and must not punch a bright hole through the night mask.
        mode = t.properties.get("terrain_shadow_only", False)
        if mode is True or (
            isinstance(mode, str)
            and mode.strip().lower() in ("true", "1", "yes", "on")
        ):
            continue
        params = _light_params(t.properties)
        if params is not None:
            out.append((t.pos,) + params)
    return out


def holes(session, viewport, width, height):
    """``[(x, y, radius_px, strength, (r, g, b))]``: where the dark is lifted,
    in view pixels, for what is on screen.

    Every light's centre and rim go through the camera in one NumPy pass,
    rather than two matrix products per light per frame."""
    try:
        proj, view = viewport.projection_matrix, viewport.view_matrix
        m = np.array(proj * view, dtype=np.float64)
    except Exception:
        return []
    margin = 0.25
    sources = list(_local_lights(session))
    try:
        player = session._player_pos()
    except Exception:
        player = None
    if player is not None:
        sources.append((player, PLAYER_GLOW_RADIUS / LIT_FRACTION, None, None))
    if not sources:
        return []
    # Each light's centre (rows :n) and a point on its lit rim (rows n:),
    # through the camera in one product.
    n = len(sources)
    pts = np.ones((2 * n, 4), dtype=np.float64)
    pts[:n, :3] = [src[0][:3] for src in sources]
    pts[n:, :3] = pts[:n, :3]
    pts[n:, 0] += np.fromiter((src[1] for src in sources), dtype=np.float64,
                              count=n) * LIT_FRACTION
    clip = pts @ m.T
    cw = clip[:, 3]
    ahead = cw > 1e-4
    w = np.where(ahead, cw, 1.0)
    sx = (clip[:, 0] / w * 0.5 + 0.5) * width
    sy = (1.0 - (clip[:, 1] / w * 0.5 + 0.5)) * height
    r_px = np.hypot(sx[n:] - sx[:n], sy[n:] - sy[:n])
    sx, sy = sx[:n], sy[:n]
    keep = (ahead[:n] & ahead[n:] & (r_px >= 2.0)
            & (sx + r_px >= -width * margin) & (sx - r_px <= width * (1 + margin))
            & (sy + r_px >= -height * margin) & (sy - r_px <= height * (1 + margin)))
    out = []
    for i in np.flatnonzero(keep).tolist():
        _pos, _radius, intensity, colour = sources[i]
        if intensity is None:
            strength = PLAYER_GLOW
        else:
            strength = max(0.0, min(1.0, 0.45 + 0.4 * intensity))
        out.append((float(sx[i]), float(sy[i]), float(r_px[i]), strength, colour))
    if len(out) > MAX_HOLES:
        cx, cy = width / 2.0, height / 2.0
        out.sort(key=lambda h: (h[0] - cx) ** 2 + (h[1] - cy) ** 2)
        out = out[:MAX_HOLES]
    return out


def paint_mask(width, height, colour, darkness, lifted, night=1.0,
               scale=MASK_SCALE, key="view") -> QImage:
    """The darkness layer at *scale*: *colour* at *darkness*, with each of
    *lifted* (``(x, y, r, strength, rgb)`` in pixels of the area) cut out
    softly and, after dark, washed faintly with its light's colour. Each
    *key* (the view, the map, the minimap) keeps an image of its own."""
    mw = max(1, int(width * scale))
    mh = max(1, int(height * scale))
    # Unchanged since the last frame (a player standing still, the map left
    # open): the last picture is this one.
    signature = (tuple(colour), darkness, night, scale,
                 tuple(tuple(h) for h in lifted))
    img = _mask.get(key)
    if img is None or img.width() != mw or img.height() != mh:
        img = _mask[key] = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
    elif _mask_signature.get(key) == signature:
        return img
    _mask_signature[key] = signature
    img.fill(Qt.transparent)
    p = QPainter(img)
    # No antialiasing: every edge here is a gradient already fading to nothing.
    p.fillRect(QRect(0, 0, mw, mh), QColor(colour[0], colour[1], colour[2],
                                           int(255 * max(0.0, min(1.0, darkness)))))
    p.setPen(Qt.NoPen)
    p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    for x, y, r, strength, _rgb in lifted:
        c = QPointF(x * scale, y * scale)
        rr = r * scale
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
            c = QPointF(x * scale, y * scale)
            rr = r * scale * 0.85
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


# ---------------------------------------------------------------- the maps
#: On a map a lamp is drawn no smaller than this (px), so a lit village still
#: shows as a few lights when the map is zoomed right out.
MAP_MIN_LIGHT_PX = 2.5
#: The maps' masks are finer than the view's: their lights are small.
MAP_MASK_SCALE = 0.5


def map_night(session):
    """What the maps need to show the night: ``{"hour", "lights": [(x, z,
    radius, intensity, rgb)]}``, or None by day."""
    clock = getattr(session, "clock", None)
    if clock is None or sky_at(clock.hour)[1] <= 0.004:
        return None
    lights = [(float(pos[0]), float(pos[2]), radius, intensity, rgb)
              for pos, radius, intensity, rgb in _local_lights(session)]
    return {"hour": float(clock.hour), "lights": lights}


def draw_map_night(painter, rect, night, to_screen, scale, player=None,
                   key="map") -> None:
    """Lay the night over a map drawn in *rect* (a QRectF).

    *night* is :func:`map_night`'s answer; *to_screen(x, z)* places a world
    point on the map (a QPointF) and *scale* is map pixels per world unit;
    *player* is ``(x, z)`` for their moonlight."""
    if not night:
        return
    colour, darkness = sky_at(night["hour"])
    if darkness <= 0.004:
        return
    w, h = int(rect.width()), int(rect.height())
    if w <= 0 or h <= 0:
        return
    ox, oy = rect.left(), rect.top()
    lifted = []
    for x, z, radius, intensity, rgb in night.get("lights", ()):
        c = to_screen(x, z)
        r = max(MAP_MIN_LIGHT_PX, radius * LIT_FRACTION * scale)
        cx, cy = c.x() - ox, c.y() - oy
        if cx + r < 0 or cy + r < 0 or cx - r > w or cy - r > h:
            continue
        lifted.append((cx, cy, r, max(0.0, min(1.0, 0.45 + 0.4 * intensity)), rgb))
    if player is not None:
        c = to_screen(player[0], player[1])
        lifted.append((c.x() - ox, c.y() - oy,
                       max(MAP_MIN_LIGHT_PX, PLAYER_GLOW_RADIUS * scale), PLAYER_GLOW, None))
    img = paint_mask(w, h, colour, darkness, lifted, night_amount(night["hour"]),
                     scale=MAP_MASK_SCALE, key=key)
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawImage(rect, img)
    painter.restore()
