"""
Finding a way round: walking actors route around walls instead of into them.

Every mover in the world used to head straight for where it wanted to be and
slide along whatever wall got in the way. In the open that is all anyone
needs; at a town wall it left a guard who had seen a wolf outside pressed
against the stones, sliding nowhere. This module gives every walker a route:

* **When the way is clear**, nothing changes -- the walker heads straight for
  its goal, as before. Checking costs a handful of grid lookups along the
  first stretch of the line, and is repeated at most a few times a second.
* **When a wall is in the way**, :class:`Navigator` plans a route with A* over
  a coarse grid (:data:`CELL` units) and the walker heads for the next corner
  of it instead. The route is kept and followed, and planned again only when
  the goal has moved away from where it was planned to, or the route is old.

There is no navigation mesh to build or keep up to date. Whether a cell is
open is asked of the engine's own collision grid -- the very test the movers
already use to stop at walls -- on demand, and remembered for a while, so a
route through open country costs almost nothing and a route around a town
costs a few hundred lookups once.

Two callers: Fio's combat chase, through ``MonsterAI``'s steer hook (installed
by :class:`game.runtime.MiniwindSession`), and MiniWind's own schedule walking
(:meth:`game.runtime.MiniwindSession._move`).
"""

from __future__ import annotations

import heapq
import math
import time

#: Grid cell size (world units): about a body's width, so a doorway is found.
CELL = 48.0
#: How far along the straight line it is checked before trusting it: the
#: whole way to any goal a walker could see (a wall far off still counts, or
#: a route round it is dropped the moment the walker turns away from it).
LOOKAHEAD = 2400.0
#: How long a "the straight line is clear" answer stands (seconds).
CLEAR_CHECK_SECONDS = 0.25
#: A planned route is replanned once it is this old, or its goal has moved
#: this far from where it was planned to.
ROUTE_SECONDS = 2.0
ROUTE_GOAL_SLACK = 160.0
#: The search never looks further than this past the start and the goal, and
#: never at more cells than this: a route round a building, not a maze.
SEARCH_MARGIN = 1600.0
MAX_NODES = 6000
#: Whether a cell is open is remembered this long (doors and movers change).
CELL_MEMORY_SECONDS = 20.0

_NEIGHBOURS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
               (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))


class _Route:
    __slots__ = ("points", "goal", "made")

    def __init__(self, points, goal, made):
        self.points = points
        self.goal = goal
        self.made = made


class Navigator:
    """Routes for every walker, around whatever the collision grid calls solid.

    *blocked(x, y, z)* answers whether a body standing at (x, y, z) would be
    inside a wall. *clock* is the time source (seconds), swappable in tests.
    """

    def __init__(self, blocked, clock=time.monotonic):
        self._blocked = blocked
        self._clock = clock
        self._cells = {}
        self._cells_since = clock()
        self._routes = {}
        self._clear = {}

    # -- the grid ----------------------------------------------------------------
    def _cell_blocked(self, cx, cz, y) -> bool:
        key = (cx, cz, int(y // 64.0))
        hit = self._cells.get(key)
        if hit is None:
            try:
                hit = bool(self._blocked((cx + 0.5) * CELL, y, (cz + 0.5) * CELL))
            except Exception:
                hit = False
            self._cells[key] = hit
        return hit

    def _age_cells(self, now) -> None:
        if now - self._cells_since > CELL_MEMORY_SECONDS or len(self._cells) > 200000:
            self._cells.clear()
            self._cells_since = now

    def line_clear(self, x0, z0, x1, z1, y, limit=None) -> bool:
        """Whether a body can walk the straight line (x0, z0) -> (x1, z1),
        checked every half cell; only the first *limit* units if given."""
        dx, dz = x1 - x0, z1 - z0
        length = math.hypot(dx, dz)
        if length < 1e-6:
            return True
        span = length if limit is None else min(length, limit)
        steps = max(1, int(span / (CELL * 0.5)))
        for i in range(1, steps + 1):
            f = (span * i / steps) / length
            x, z = x0 + dx * f, z0 + dz * f
            if self._cell_blocked(int(math.floor(x / CELL)), int(math.floor(z / CELL)), y):
                return False
        return True

    # -- planning ------------------------------------------------------------------
    def find_path(self, start, goal, y):
        """Corner points ``[(x, z), ...]`` of a route from *start* to *goal*
        (each ``(x, z)``) for a body at height *y*, ending at the goal; or
        None when there is no way within the search's reach."""
        sx, sz = int(math.floor(start[0] / CELL)), int(math.floor(start[1] / CELL))
        gx, gz = int(math.floor(goal[0] / CELL)), int(math.floor(goal[1] / CELL))
        if (sx, sz) == (gx, gz):
            return [tuple(goal)]
        lo_x = min(sx, gx) - int(SEARCH_MARGIN / CELL)
        hi_x = max(sx, gx) + int(SEARCH_MARGIN / CELL)
        lo_z = min(sz, gz) - int(SEARCH_MARGIN / CELL)
        hi_z = max(sz, gz) + int(SEARCH_MARGIN / CELL)
        goal_cell = (gx, gz)
        if self._cell_blocked(gx, gz, y):
            # The goal is hard against a wall (someone standing by it): aim
            # for the nearest open cell beside it.
            goal_cell = self._nearest_open(gx, gz, y)
            if goal_cell is None:
                return None

        def h(cx, cz):
            return math.hypot(cx - goal_cell[0], cz - goal_cell[1])

        start_cell = (sx, sz)
        open_ = [(h(sx, sz), 0.0, start_cell)]
        came = {start_cell: None}
        cost = {start_cell: 0.0}
        found = False
        expanded = 0
        while open_:
            _f, g, cell = heapq.heappop(open_)
            if cell == goal_cell:
                found = True
                break
            if g > cost.get(cell, math.inf):
                continue
            expanded += 1
            if expanded > MAX_NODES:
                break
            cx, cz = cell
            for ox, oz, step in _NEIGHBOURS:
                nx, nz = cx + ox, cz + oz
                if nx < lo_x or nx > hi_x or nz < lo_z or nz > hi_z:
                    continue
                if self._cell_blocked(nx, nz, y):
                    continue
                if ox and oz and (self._cell_blocked(cx + ox, cz, y)
                                  or self._cell_blocked(cx, cz + oz, y)):
                    continue          # no squeezing diagonally past a corner
                ng = g + step
                if ng < cost.get((nx, nz), math.inf):
                    cost[(nx, nz)] = ng
                    came[(nx, nz)] = cell
                    heapq.heappush(open_, (ng + h(nx, nz), ng, (nx, nz)))
        if not found:
            return None
        cells = []
        cell = goal_cell
        while cell is not None:
            cells.append(cell)
            cell = came[cell]
        cells.reverse()
        points = [((cx + 0.5) * CELL, (cz + 0.5) * CELL) for cx, cz in cells[1:]]
        if goal_cell == (gx, gz):
            points[-1:] = [tuple(goal)]
        return self._smooth(tuple(start), points, y)

    def _nearest_open(self, gx, gz, y, reach=4):
        for r in range(1, reach + 1):
            for ox in range(-r, r + 1):
                for oz in (-r, r) if abs(ox) != r else range(-r, r + 1):
                    if not self._cell_blocked(gx + ox, gz + oz, y):
                        return (gx + ox, gz + oz)
        return None

    def _smooth(self, start, points, y):
        """Drop every corner the walker can cut straight past."""
        if len(points) <= 1:
            return points
        out = []
        here = start
        i = 0
        while i < len(points):
            j = len(points) - 1
            while j > i and not self.line_clear(here[0], here[1],
                                                points[j][0], points[j][1], y):
                j -= 1
            out.append(points[j])
            here = points[j]
            i = j + 1
        return out

    # -- following -------------------------------------------------------------
    def steer(self, key, pos, goal):
        """Where walker *key* at *pos* (x, y, z) should head next to reach
        *goal* (x, y, z): the goal itself when the way ahead is clear, else
        the next corner of a route round the obstacle."""
        now = self._clock()
        self._age_cells(now)
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        gx, gz = float(goal[0]), float(goal[2])
        route = self._routes.get(key)
        if route is not None:
            if (now - route.made > ROUTE_SECONDS
                    or math.hypot(gx - route.goal[0], gz - route.goal[1]) > ROUTE_GOAL_SLACK):
                route = None
                self._routes.pop(key, None)
        if route is None:
            clear = self._clear.get(key)
            if clear is None or now - clear[0] > CLEAR_CHECK_SECONDS:
                clear = (now, self.line_clear(x, z, gx, gz, y, LOOKAHEAD))
                self._clear[key] = clear
            if clear[1]:
                return goal
            points = self.find_path((x, z), (gx, gz), y)
            if not points:
                return goal               # nowhere better to go: as before
            route = self._routes[key] = _Route(points, (gx, gz), now)
            self._clear.pop(key, None)
        # On to the next corner once it can be walked to straight from here:
        # never on mere nearness, which cuts across the end of a wall.
        while len(route.points) > 1 and self.line_clear(
                x, z, route.points[1][0], route.points[1][1], y):
            route.points.pop(0)
        px, pz = route.points[0]
        if len(route.points) == 1:
            self._routes.pop(key, None)    # the last leg: straight on to the goal
            return goal
        return (px, float(goal[1]), pz)

    def has_route(self, key) -> bool:
        return key in self._routes

    def forget(self, key) -> None:
        self._routes.pop(key, None)
        self._clear.pop(key, None)

    def steer_many(self, things, starts, targets):
        """The engine's steer hook: for each chasing *thing*, its next
        waypoint toward its target. *starts* and *targets* are ``(n, 3)``
        arrays; returns a list of ``(x, y, z)`` (or None for no change)."""
        out = []
        for thing, start, target in zip(things, starts, targets):
            if thing is None:
                out.append(None)
                continue
            wp = self.steer(id(thing), start, target)
            out.append(None if wp is target else wp)
        return out
