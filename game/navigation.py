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

from engine.spatial import TIER_ACTIVE, tier_of

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
#: An unreachable goal is retried at 2 Hz, independently of the 30 Hz AI tick.
RETRY_SECONDS = 0.5
#: The search never looks further than this past the start and the goal, and
#: never at more cells than this: a route round a building, not a maze.
SEARCH_MARGIN = 1600.0
MAX_NODES = 6000
#: Whether a cell is open is remembered this long (doors and movers change).
CELL_MEMORY_SECONDS = 20.0

_NEIGHBOURS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
               (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))


class _Route:
    __slots__ = ("points", "goal", "made", "layer", "index", "checked", "origin")

    def __init__(self, points, goal, made, layer, origin):
        self.points = points
        self.goal = goal
        self.made = made
        self.layer = layer
        self.index = 0
        self.checked = made
        self.origin = origin


class _SearchStats:
    __slots__ = ("since", "steer_calls", "searches", "failed_searches", "reasons",
                 "expanded_nodes", "search_seconds", "smoothing_checks", "last_search")

    def __init__(self, now):
        self.since = now
        self.steer_calls = 0
        self.searches = 0
        self.failed_searches = 0
        self.reasons = {}
        self.expanded_nodes = 0
        self.search_seconds = 0.0
        self.smoothing_checks = 0
        self.last_search = None


class Navigator:
    """Routes for every walker, around whatever the collision grid calls solid.

    *blocked(x, y, z)* answers whether a body standing at (x, y, z) would be
    inside a wall. *clock* is the time source (seconds), swappable in tests.
    Enable *track_stats* to measure each NPC's search frequency with
    :meth:`search_stats`; counters are otherwise disabled.
    """

    def __init__(self, blocked, clock=time.monotonic, *, track_stats=False):
        self._blocked = blocked
        self._clock = clock
        self._cells = {}
        self._cells_since = clock()
        self._routes = {}
        self._clear = {}
        self._failed = {}
        self._stats = {}
        self._track_stats = track_stats
        self._debug_enabled = False
        self._debug = {}

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
        visiting each crossed grid cell; only the first *limit* units if given.

        At a grid corner both side cells must be open, just as in A*. Sampling
        at fixed distances can miss a cell clipped by the line, or let smoothing
        undo the search's diagonal corner checks.
        """
        dx, dz = x1 - x0, z1 - z0
        length = math.hypot(dx, dz)
        if length < 1e-6:
            return True
        if limit is not None and length > limit:
            dx *= limit / length
            dz *= limit / length
            x1, z1 = x0 + dx, z0 + dz
        cx, cz = math.floor(x0 / CELL), math.floor(z0 / CELL)
        gx, gz = math.floor(x1 / CELL), math.floor(z1 / CELL)
        blocked = self._cell_blocked
        if blocked(cx, cz, y):
            return False
        ox, oz = (1 if dx > 0 else -1), (1 if dz > 0 else -1)
        tx_step = CELL / abs(dx) if dx else math.inf
        tz_step = CELL / abs(dz) if dz else math.inf
        tx = ((cx + (dx > 0)) * CELL - x0) / dx if dx else math.inf
        tz = ((cz + (dz > 0)) * CELL - z0) / dz if dz else math.inf
        while (cx, cz) != (gx, gz):
            # An endpoint on a boundary belongs to floor(endpoint / CELL),
            # including when walking in the negative direction.
            next_x = tx if cx != gx else math.inf
            next_z = tz if cz != gz else math.inf
            if math.isclose(next_x, next_z, rel_tol=0.0, abs_tol=1e-12):
                if blocked(cx + ox, cz, y) or blocked(cx, cz + oz, y):
                    return False
                cx, cz = cx + ox, cz + oz
                tx, tz = tx + tx_step, tz + tz_step
            elif next_x < next_z:
                cx += ox
                tx += tx_step
            else:
                cz += oz
                tz += tz_step
            if blocked(cx, cz, y):
                return False
        return True

    # -- planning ------------------------------------------------------------------
    def find_path(self, start, goal, y, *, _metrics=None):
        """Corner points ``[(x, z), ...]`` of a route from *start* to *goal*
        (each ``(x, z)``) for a body at height *y*, ending at the goal; or
        None when there is no way within the search's reach."""
        sx, sz = int(math.floor(start[0] / CELL)), int(math.floor(start[1] / CELL))
        gx, gz = int(math.floor(goal[0] / CELL)), int(math.floor(goal[1] / CELL))
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
        if (sx, sz) == goal_cell:
            return [tuple(goal) if goal_cell == (gx, gz)
                    else ((sx + 0.5) * CELL, (sz + 0.5) * CELL)]

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
        if _metrics is not None:
            _metrics["expanded_nodes"] = expanded
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
        return self._smooth(tuple(start), points, y, _metrics=_metrics)

    def _nearest_open(self, gx, gz, y, reach=4):
        for r in range(1, reach + 1):
            for ox in range(-r, r + 1):
                for oz in (-r, r) if abs(ox) != r else range(-r, r + 1):
                    if not self._cell_blocked(gx + ox, gz + oz, y):
                        return (gx + ox, gz + oz)
        return None

    def _smooth(self, start, points, y, *, _metrics=None):
        """Pull the route taut with a forward pass over its turns.

        Collapse straight grid runs first, then test each remaining candidate
        once. Scanning backwards from the destination at every corner used to
        re-test long blocked stretches, particularly in winding corridors.
        Visibility is not monotone, so binary searching for a corner is unsafe.
        """
        if len(points) <= 1:
            return points
        if _metrics is not None:
            _metrics["smoothing_checks"] = 1
        if self.line_clear(*start, *points[-1], y):
            return [points[-1]]
        turns = [points[0]]
        for i in range(1, len(points) - 1):
            ax, az = points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]
            bx, bz = points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
            if ax * bz != az * bx or ax * bx + az * bz <= 0:
                turns.append(points[i])
        turns.append(points[-1])
        out = []
        here = start
        for i in range(1, len(turns)):
            if _metrics is not None:
                _metrics["smoothing_checks"] += 1
            if not self.line_clear(*here, *turns[i], y):
                here = turns[i - 1]
                out.append(here)
        out.append(turns[-1])
        return out

    # -- following -------------------------------------------------------------
    def steer_actor(self, actor, pos, goal):
        """Actor entry point: obey Big World's authoritative simulation stamp.

        The runtime owns NEAR/ACTIVE scheduling (including off-screen strides).
        DISTANT keeps coarse movement, without live A*; DORMANT is never woken
        here. No distance-based tier classification or extra tick is introduced.
        """
        if tier_of(actor) > TIER_ACTIVE:
            self.suspend(id(actor))
            return goal
        return self.steer(id(actor), pos, goal)

    def steer(self, key, pos, goal):
        """Where walker *key* at *pos* (x, y, z) should head next to reach
        *goal* (x, y, z): the goal itself when the way ahead is clear, else
        the next corner of a route round the obstacle.

        This low-level keyed API has no actor to read tiers from; game callers
        use ``steer_actor`` or ``steer_many`` for Big World eligibility.
        """
        now = self._clock()
        self._age_cells(now)
        wp = self._steer(key, pos, goal, now)
        self._remember_debug(key, pos, goal, wp, now)
        return wp

    def _goal_clear(self, key, x, z, gx, gz, y, origin, now):
        # Cache only queries in the same cells and height band. A new target
        # cell must not inherit a clear answer for an unrelated destination.
        query = (origin, math.floor(gx / CELL), math.floor(gz / CELL))
        clear = self._clear.get(key)
        if clear is None or now - clear[0] >= CLEAR_CHECK_SECONDS or clear[2] != query:
            clear = (now, self.line_clear(x, z, gx, gz, y, LOOKAHEAD), query)
            self._clear[key] = clear
        return clear[1]

    def _steer(self, key, pos, goal, now):
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        gx, gz = float(goal[0]), float(goal[2])
        layer = int(y // 64.0)
        origin = (math.floor(x / CELL), math.floor(z / CELL), layer)
        stats = None
        if self._track_stats or self._debug_enabled:
            stats = self._stats.get(key)
            if stats is None:
                stats = self._stats[key] = _SearchStats(now)
            stats.steer_calls += 1
        route = self._routes.get(key)
        reason = "missing"
        if route is not None:
            if route.layer != layer:
                reason = "height"
            elif math.hypot(gx - route.goal[0], gz - route.goal[1]) > ROUTE_GOAL_SLACK:
                reason = "goal_moved"
            elif now - route.made >= ROUTE_SECONDS:
                reason = "expired"
            else:
                reason = None
            if reason is not None:
                route = None
                self._routes.pop(key, None)
        if route is None:
            if self._goal_clear(key, x, z, gx, gz, y, origin, now):
                self._failed.pop(key, None)
                return goal
            failed = self._failed.get(key)
            if failed is not None:
                made, old_origin, old_goal = failed
                if (now - made < RETRY_SECONDS and origin == old_origin
                        and math.hypot(gx - old_goal[0], gz - old_goal[1]) <= ROUTE_GOAL_SLACK):
                    return goal
                reason = "retry"
            if stats is not None:
                stats.searches += 1
                stats.reasons[reason] = stats.reasons.get(reason, 0) + 1
                metrics = {}
                started = time.perf_counter()
                points = self.find_path((x, z), (gx, gz), y, _metrics=metrics)
                elapsed = time.perf_counter() - started
                stats.expanded_nodes += metrics.get("expanded_nodes", 0)
                stats.smoothing_checks += metrics.get("smoothing_checks", 0)
                stats.search_seconds += elapsed
                stats.last_search = dict(metrics, at=now, reason=reason,
                                         outcome="found" if points else "unreachable",
                                         elapsed_ms=elapsed * 1000.0)
            else:
                points = self.find_path((x, z), (gx, gz), y)
            if not points:
                self._failed[key] = (now, origin, (gx, gz))
                if stats is not None:
                    stats.failed_searches += 1
                return goal               # nowhere better to go: as before
            self._failed.pop(key, None)
            route = self._routes[key] = _Route(points, (gx, gz), now, layer, origin)
            self._clear.pop(key, None)
        # On to the next corner once it can be walked to straight from here:
        # never on mere nearness, which cuts across the end of a wall.
        # Steering can run every AI tick. Visibility checks run at 4 Hz while
        # in the same cell; entering another cell triggers an immediate check.
        if now - route.checked >= CLEAR_CHECK_SECONDS or origin != route.origin:
            while route.index + 1 < len(route.points) and self.line_clear(
                    x, z, *route.points[route.index + 1], y):
                route.index += 1
            route.checked, route.origin = now, origin
        px, pz = route.points[route.index]
        if route.index == len(route.points) - 1:
            # A blocked goal may have been snapped to a nearby open cell.
            # Keep that safe endpoint until the actual goal is walkable.
            if self._goal_clear(key, x, z, gx, gz, y, origin, now):
                self._routes.pop(key, None)
                return goal
        return (px, float(goal[1]), pz)

    def search_stats(self):
        """Snapshot per-key search counts, reasons and average searches/second.

        Construct with ``track_stats=True`` to collect. Rates cover the time
        since a key's first steer call, including idle time. ``forget(key)``
        also removes its counters. Reading this snapshot does not reset them.
        """
        now = self._clock()
        return {key: {"steer_calls": stat.steer_calls, "searches": stat.searches,
                      "failed_searches": stat.failed_searches,
                      "expanded_nodes": stat.expanded_nodes,
                      "smoothing_checks": stat.smoothing_checks,
                      "search_ms": stat.search_seconds * 1000.0,
                      "last_search": dict(stat.last_search) if stat.last_search else None,
                      "searches_per_second": stat.searches / (now - stat.since)
                      if now > stat.since else 0.0,
                      "reasons": stat.reasons.copy()}
                for key, stat in self._stats.copy().items()}

    def reset_search_stats(self):
        """Begin a fresh observation window without discarding active routes."""
        self._stats.clear()

    def set_debug(self, enabled):
        """Collect render snapshots and search counts only while requested."""
        self._debug_enabled = bool(enabled)
        if not enabled:
            self._debug.clear()
            if not self._track_stats:
                self._stats.clear()

    def _remember_debug(self, key, pos, goal, waypoint, now):
        if not self._debug_enabled:
            return
        route = self._routes.get(key)
        state = "route" if route is not None else "failed" if key in self._failed else "direct"
        points = tuple(route.points[route.index:]) if route is not None else ()
        # Replace a complete record at once. The UI never walks a live route
        # or mutates the planner's lists while either AI caller is steering.
        self._debug[key] = {"pos": tuple(float(v) for v in pos),
                            "goal": tuple(float(v) for v in goal),
                            "waypoint": tuple(float(v) for v in waypoint),
                            "points": points, "state": state, "seen": now,
                            "decision": "follow_waypoint" if route is not None
                            else "retry_wait" if state == "failed" else "direct_goal",
                            "route_age": now - route.made if route is not None else None}

    def debug_snapshot(self):
        """Detached render records for recently steered actors (no planning)."""
        if not self._debug_enabled:
            return {}
        now = self._clock()
        stats = self.search_stats()
        return {key: dict(record, **stats.get(key, {}))
                for key, record in self._debug.copy().items()
                if now - record["seen"] <= ROUTE_SECONDS + RETRY_SECONDS}

    def has_route(self, key) -> bool:
        return key in self._routes

    def forget(self, key) -> None:
        self.suspend(key)
        self._stats.pop(key, None)

    def suspend(self, key) -> None:
        """Discard live route work on demotion, retaining observation counts."""
        self._routes.pop(key, None)
        self._clear.pop(key, None)
        self._failed.pop(key, None)
        self._debug.pop(key, None)

    def steer_many(self, things, starts, targets):
        """The engine's steer hook: for each chasing *thing*, its next
        waypoint toward its target. *starts* and *targets* are ``(n, 3)``
        arrays; returns a list of ``(x, y, z)`` (or None for no change)."""
        now = self._clock()
        self._age_cells(now)
        out = []
        for thing, start, target in zip(things, starts, targets):
            if thing is None:
                out.append(None)
                continue
            if tier_of(thing) > TIER_ACTIVE:
                self.suspend(id(thing))
                out.append(None)
                continue
            wp = self._steer(id(thing), start, target, now)
            self._remember_debug(id(thing), start, target, wp, now)
            out.append(None if wp is target else wp)
        return out
