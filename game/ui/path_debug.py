"""
Seeing where everyone is going (console ``paths``).

With it on, every walking actor near the player draws its way on the
world, over the scene and under the HUD:

* **cyan** -- a route round walls (game/navigation.py): the actor, each
  corner still ahead, then the goal;
* **yellow** -- a straight walk to a schedule destination (``_dest``) with
  nothing in the way;
* **red** -- a fight: a straight line to whatever it is chasing.

A dot marks the goal. Off by default; costs nothing while off.
"""

from __future__ import annotations

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QPen

from .. import fio

ROUTE = QColor(80, 220, 255, 230)
STRAIGHT = QColor(255, 214, 90, 210)
CHASE = QColor(255, 90, 80, 220)
#: Only actors this near the player draw (world units).
REACH = 3200.0
WIDTH = 3.0


def _project(glm, proj, view, x, y, z, width, height):
    clip = proj * view * glm.vec4(float(x), float(y), float(z), 1.0)
    if clip.w <= 1e-4:
        return None
    return QPointF((clip.x / clip.w * 0.5 + 0.5) * width,
                   (1.0 - (clip.y / clip.w * 0.5 + 0.5)) * height)


def draw(painter, session, viewport, width, height) -> None:
    """Draw every nearby actor's way (see the module docstring)."""
    if not getattr(session, "show_paths", False) or viewport is None:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    ppos = session._player_pos()
    if ppos is None:
        return
    nav = getattr(session, "nav", None)
    routes = dict(getattr(nav, "_routes", {}) or {})
    by_id = {}
    try:
        actors = list(session._live_actors())
    except Exception:
        actors = []
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    for t in actors:
        p = t.properties
        if p.get("dead") or p.get("hidden"):
            continue
        x, y, z = float(t.pos[0]), float(t.pos[1]), float(t.pos[2])
        if (x - ppos[0]) ** 2 + (z - ppos[2]) ** 2 > REACH * REACH:
            continue
        by_id[id(t)] = t
        route = routes.get(id(t))
        if route is not None:
            points = [(x, z)] + list(route.points) + [tuple(route.goal)]
            colour = ROUTE
        else:
            goal = None
            colour = STRAIGHT
            if p.get("triggered") is False:
                aggro = p.get("_aggro_target")
                target = by_id.get(aggro) if aggro else None
                if target is None and aggro:
                    target = next((a for a in actors if id(a) == aggro), None)
                if target is not None:
                    goal, colour = (float(target.pos[0]), float(target.pos[2])), CHASE
                elif str(p.get("aggression")) == "hostile" and p.get("awake"):
                    goal, colour = (ppos[0], ppos[2]), CHASE
            if goal is None:
                dest = p.get("_dest")
                if not dest:
                    continue
                goal = (float(dest[0]), float(dest[2]))
            points = [(x, z), goal]
        screen = [_project(glm, proj, view, px, y, pz, width, height) for px, pz in points]
        screen = [s for s in screen if s is not None]
        if len(screen) < 2:
            continue
        painter.setPen(QPen(colour, WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for a, b in zip(screen, screen[1:]):
            painter.drawLine(a, b)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        for corner in screen[1:-1]:
            painter.drawEllipse(corner, 3.0, 3.0)
        painter.drawEllipse(screen[-1], 5.0, 5.0)
        painter.setBrush(Qt.NoBrush)
    painter.restore()
