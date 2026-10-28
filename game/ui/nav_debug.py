"""Live road-network overlay: console ``shownav``.

Draws, over the 3D view, the navigation graph built from the map's ``ROAD_*``
PathNodes (game/road_nav.py) and what walkers are doing with it right now:

* every road link -- solid where the map links the nodes, dashed where an
  unlinked node was joined to its nearest neighbours;
* every road node, with its name near the player;
* each walker's current road leg: from the walker to the node it is heading
  for (bright while it is on the road, dim while it walks to join it), along
  the rest of the road it will take, then dashed from where it leaves the
  road to its goal;
* a summary line: nodes, links, separate networks, graph builds, walkers.

Only reads what the session already holds: drawing never plans a route.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPen

ROAD = QColor(110, 230, 120, 230)
ROAD_AUTO = QColor(110, 230, 120, 150)
NODE = QColor(200, 255, 200, 240)
LEG_ON = QColor(255, 175, 40, 240)
LEG_JOIN = QColor(255, 175, 40, 140)
LEG_OFF = QColor(255, 230, 160, 170)
INK = QColor(235, 240, 230)
#: Node names are written only this near the player (world units).
LABEL_RADIUS = 2500.0
#: Lines are drawn this far above the ground, clear of it.
LIFT = 10.0


def _project(glm, proj, view, x, y, z, width, height):
    clip = proj * view * glm.vec4(float(x), float(y), float(z), 1.0)
    if clip.w <= 1e-4:
        return None
    return QPointF((clip.x / clip.w * 0.5 + 0.5) * width,
                   (1.0 - (clip.y / clip.w * 0.5 + 0.5)) * height)


def summary(session) -> dict:
    """What the overlay's caption says, for the console too."""
    graph = getattr(session, "_road_graph", None)
    plans = getattr(session, "_road_plans", {}) or {}
    walking = sum(1 for plan in plans.values()
                  if plan.get("points") and plan.get("i", 0) < len(plan["points"]))
    if graph is None:
        return {"nodes": 0, "links": 0, "auto_links": 0, "networks": 0,
                "builds": getattr(getattr(session, "roads", None), "builds", 0),
                "walkers": 0}
    edges = list(graph.edges())
    return {"nodes": len(graph), "links": len(edges),
            "auto_links": sum(1 for *_ab, auto in edges if auto),
            "networks": graph.pieces() if len(graph) else 0,
            "builds": session.roads.builds, "walkers": walking}


def draw(painter, session, viewport, width, height):
    if not getattr(session, "show_nav", False) or viewport is None:
        return
    import glm
    proj, view = viewport.projection_matrix, viewport.view_matrix
    graph = getattr(session, "_road_graph", None)

    def screen(x, y, z):
        return _project(glm, proj, view, x, y + LIFT, z, width, height)

    painter.save()
    try:
        painter.setRenderHint(painter.Antialiasing, True)
        if graph is not None and len(graph):
            nodes = [screen(x, graph.heights[i], z) for i, (x, z) in enumerate(graph.points)]
            for a, b, auto in graph.edges():
                pa, pb = nodes[a], nodes[b]
                if pa is None or pb is None:
                    continue
                painter.setPen(QPen(ROAD_AUTO if auto else ROAD, 2.0 if auto else 3.5,
                                    Qt.DashLine if auto else Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(pa, pb)
            player = session._player_pos()
            painter.setFont(QFont("Segoe UI", 8))
            for i, point in enumerate(nodes):
                if point is None:
                    continue
                painter.setPen(QPen(QColor(20, 40, 20), 1.2))
                painter.setBrush(NODE)
                painter.drawEllipse(point, 5.0, 5.0)
                x, z = graph.points[i]
                if player is not None and math.hypot(x - player[0], z - player[2]) <= LABEL_RADIUS:
                    painter.setPen(INK)
                    painter.drawText(QPointF(point.x() + 8, point.y() - 6), graph.names[i])
            _draw_legs(painter, session, screen)
        _draw_caption(painter, session, graph)
    finally:
        painter.restore()


def _draw_legs(painter, session, screen):
    """Each walker's road leg: to its next node, along the road, off to the goal."""
    plans = getattr(session, "_road_plans", {}) or {}
    painter.setBrush(Qt.NoBrush)
    for actor in session._live_actors():
        plan = plans.get(id(actor))
        if not plan or not plan.get("points"):
            continue
        points, i = plan["points"], plan.get("i", 0)
        if i >= len(points):
            continue
        y = float(actor.pos[1])
        here = screen(actor.pos[0], y, actor.pos[2])
        road = [screen(x, y, z) for x, z in points[i:]]
        goal = screen(plan["goal"][0], y, plan["goal"][1])
        from ..runtime import ROAD_WIDTH, _segment_distance
        a = points[i - 1] if i > 0 else points[i]
        on_road = _segment_distance((actor.pos[0], actor.pos[2]), a, points[i]) <= ROAD_WIDTH
        painter.setPen(QPen(LEG_ON if on_road else LEG_JOIN, 3.0, Qt.SolidLine, Qt.RoundCap))
        if here is not None and road[0] is not None:
            painter.drawLine(here, road[0])
        painter.setPen(QPen(LEG_ON, 2.0, Qt.SolidLine, Qt.RoundCap))
        for pa, pb in zip(road, road[1:]):
            if pa is not None and pb is not None:
                painter.drawLine(pa, pb)
        painter.setPen(QPen(LEG_OFF, 1.6, Qt.DashLine, Qt.RoundCap))
        if road[-1] is not None and goal is not None:
            painter.drawLine(road[-1], goal)
            painter.drawEllipse(goal, 4.0, 4.0)


def _draw_caption(painter, session, graph):
    info = summary(session)
    if graph is None or not len(graph):
        text = "shownav: no ROAD_* PathNodes on this map"
    else:
        text = (f"Roads: {info['nodes']} nodes · {info['links']} links "
                f"({info['auto_links']} auto-joined) · {info['networks']} network"
                f"{'s' if info['networks'] != 1 else ''} · built {info['builds']}× · "
                f"{info['walkers']} walking a road")
    painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
    box = QRectF(12, 120, painter.fontMetrics().horizontalAdvance(text) + 20, 24)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(10, 16, 10, 200))
    painter.drawRoundedRect(box, 4, 4)
    painter.setPen(ROAD)
    painter.drawText(box, int(Qt.AlignCenter), text)
