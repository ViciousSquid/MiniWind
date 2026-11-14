"""
Debug overlays over the world, each off unless asked for: settings.ini
``[developer] view_cones`` / ``show_sound``, or the ``viewcone`` and
``showsound`` console commands (never the game's own settings).

* **View cones** (yellow, semi-transparent): what each head near the player
  can see -- a wedge as wide as its cone along the way it faces (drawn
  short: the direction, not how far it sees). What is not covered is its blind spot, where a blow from
  behind rolls for double damage (game/rpg/combat.py). The player's own
  cone is drawn too.
* **Sound** (light blue, semi-transparent): a circle round the player as far
  as their noise carries (game/noise.py) -- growing with footsteps, blows
  and deeds, shrinking to nothing standing still -- and a fading ring where
  someone shouts or a blow lands nearby.

Drawn with the frame's own projection on the ground under each actor, under
the HUD. Only actors near the player are drawn.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPen, QPolygonF

#: Only those this near the player are drawn (world units).
DRAW_RADIUS = 1800.0
#: How long a cone is drawn: it shows which way a head looks and where its
#: blind spot is, not how far it sees (a sight of 1,000 would cover the
#: screen with overlapping cones).
CONE_MAX = 360.0
#: The player's own cone's length.
PLAYER_CONE = 360.0
CONE_FILL = QColor(255, 214, 64, 40)
CONE_EDGE = QColor(255, 214, 64, 120)
SOUND_FILL = QColor(130, 200, 255, 50)
SOUND_EDGE = QColor(130, 200, 255, 140)
#: How long a shout's or a blow's ring lingers (seconds).
RING_SECONDS = 1.2
_ARC_STEPS = 18
_CIRCLE_STEPS = 40


def _ground_polygon(to_screen, points):
    out = []
    for x, y, z in points:
        p = to_screen(x, y, z)
        if p is None:
            return None
        out.append(QPointF(float(p[0]), float(p[1])))
    return QPolygonF(out)


def cone_points(x, y, z, heading, cone_degrees, length):
    """The wedge's corners on the ground: the apex, then the arc."""
    half = math.radians(cone_degrees) * 0.5
    pts = [(x, y, z)]
    for i in range(_ARC_STEPS + 1):
        a = heading - half + 2.0 * half * i / _ARC_STEPS
        pts.append((x + math.sin(a) * length, y, z + math.cos(a) * length))
    return pts


def circle_points(x, y, z, radius):
    return [(x + math.sin(a) * radius, y, z + math.cos(a) * radius)
            for a in (math.tau * i / _CIRCLE_STEPS for i in range(_CIRCLE_STEPS))]


def _fill(painter, poly, fill, edge):
    painter.setPen(QPen(edge, 1.4))
    painter.setBrush(fill)
    painter.drawPolygon(poly)


def draw(painter, session, viewport, width, height) -> None:
    show_cones = session.debug_overlay("view_cones")
    show_sound = session.debug_overlay("show_sound")
    if not (show_cones or show_sound):
        return
    from . import hud
    to_screen = hud.world_projector(viewport, width, height)
    ppos = session._player_pos()
    if to_screen is None or ppos is None:
        return
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    if show_cones:
        _draw_cones(painter, session, to_screen, ppos)
    if show_sound:
        _draw_sound(painter, session, to_screen, ppos)
    painter.restore()


def _draw_cones(painter, session, to_screen, ppos):
    from engine import monster_facing
    from ..entities import VIEW_CONE_DEGREES
    from ..sim import perception
    from .. import fio
    hour = float(getattr(getattr(session, "clock", None), "hour", 12.0) or 12.0)
    r2 = DRAW_RADIUS * DRAW_RADIUS
    for kind in ("npc", "creature"):
        for t in session._things_of_type(kind):
            p = t.properties
            if p.get("dead") or p.get("hidden") or t.pos is None:
                continue
            cone = monster_facing.view_cone(t)
            if cone is None:
                continue
            dx, dz = t.pos[0] - ppos[0], t.pos[2] - ppos[2]
            if dx * dx + dz * dz > r2:
                continue
            length = min(CONE_MAX, perception.sight_range(p, hour))
            if length <= 0:
                continue
            poly = _ground_polygon(to_screen, cone_points(
                t.pos[0], t.pos[1], t.pos[2], monster_facing.heading(t), cone, length))
            if poly is not None:
                _fill(painter, poly, CONE_FILL, CONE_EDGE)
    player = fio.player(session.logic)
    if player is not None:
        poly = _ground_polygon(to_screen, cone_points(
            ppos[0], ppos[1], ppos[2], float(getattr(player, "angle", 0.0) or 0.0),
            VIEW_CONE_DEGREES, PLAYER_CONE))
        if poly is not None:
            _fill(painter, poly, CONE_FILL, CONE_EDGE)


def _draw_sound(painter, session, to_screen, ppos):
    noise = getattr(session, "player_noise", None)
    level = float(getattr(noise, "level", 0.0) or 0.0)
    if level > 1.0:
        poly = _ground_polygon(to_screen, circle_points(ppos[0], ppos[1], ppos[2], level))
        if poly is not None:
            _fill(painter, poly, SOUND_FILL, SOUND_EDGE)
    now = time.monotonic()
    for (x, y, z), radius, t0 in list(session.__dict__.get("noise_rings", ())):
        age = now - t0
        if age > RING_SECONDS:
            continue
        fade = 1.0 - age / RING_SECONDS
        poly = _ground_polygon(to_screen, circle_points(x, y, z, radius * (0.6 + 0.4 * age / RING_SECONDS)))
        if poly is None:
            continue
        edge = QColor(SOUND_EDGE)
        edge.setAlpha(int(SOUND_EDGE.alpha() * fade))
        painter.setPen(QPen(edge, 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolygon(poly)
