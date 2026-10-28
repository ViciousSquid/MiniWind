"""
The road network travellers walk.

Built once per play session from what the map already holds:

* **The PathNodes you place along your roads, named ``ROAD_*``** -- the same
  nodes live NPCs walk (:mod:`game.road_nav`); other PathNodes, a guard's
  patrol route for one, are not roads. A node's ``next_node`` names the
  node(s) it connects to -- several names, comma separated, make a junction --
  and every link is a two-way road. Nodes nobody linked (dropped along a road
  in a hurry) are joined to their nearest neighbours within
  :data:`AUTO_LINK_RADIUS`, so a dotted line of nodes still reads as a road.
* **Places** -- the location markers (towns, farms, shrines, lairs). Each is
  joined to the nearest road node within :data:`PLACE_ATTACH_RADIUS`.
* **Fallback tracks.** Wherever the authored roads leave places disconnected
  (or there are no roads at all yet), the gaps are bridged with straight
  tracks: a minimum spanning tree over the disconnected pieces plus a few
  short extra links, each broken into waypoints so a traveller walking it
  is steered rather than beelining. Author a road later and travellers
  simply prefer it, because it is what connects.

Routes are A* over that graph. Everything here is plain Python on ``(x, z)``
tuples -- no engine, no Qt -- so it is built and tested headless.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Unlinked PathNodes join their nearest neighbours within this distance.
AUTO_LINK_RADIUS = 1400.0
#: How many neighbours an unlinked node is joined to.
AUTO_LINK_NEIGHBOURS = 2
#: A place joins the nearest road node within this distance.
PLACE_ATTACH_RADIUS = 3200.0
#: Fallback tracks are cut into waypoints about this far apart.
WAYPOINT_SPACING = 1600.0
#: Extra fallback links per place (besides the spanning tree), and how long
#: one may be, so the network has a few loops rather than being a bare tree.
EXTRA_LINKS = 1
EXTRA_LINK_MAX = 14000.0


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def authored_roads(things) -> List[Tuple[str, float, float, Tuple[str, ...]]]:
    """``(name, x, z, linked names)`` of the map's road nodes: the ``ROAD_*``
    PathNodes only (:func:`game.road_nav.road_nodes`), never a patrol chain."""
    from ..road_nav import road_nodes
    return [(name, x, z, links) for name, x, z, links, _y in road_nodes(things)]


class RoadNetwork:
    """A graph of road points: nodes, two-way edges, and where places join."""

    def __init__(self):
        self.points: List[Tuple[float, float]] = []
        self.kinds: List[str] = []           # "road" (authored) | "track" | "place"
        self.adj: Dict[int, Dict[int, float]] = {}
        #: place key -> node index
        self.place_node: Dict[str, int] = {}
        self.authored_nodes = 0
        self.fallback_edges = 0

    # -- building -----------------------------------------------------------
    def add_node(self, x: float, z: float, kind: str = "road") -> int:
        self.points.append((float(x), float(z)))
        self.kinds.append(kind)
        i = len(self.points) - 1
        self.adj[i] = {}
        return i

    def link(self, a: int, b: int) -> None:
        if a == b:
            return
        d = _dist(self.points[a], self.points[b])
        self.adj[a][b] = d
        self.adj[b][a] = d

    def link_with_waypoints(self, a: int, b: int) -> None:
        """A fallback track from *a* to *b*, cut into evenly spaced waypoints."""
        pa, pb = self.points[a], self.points[b]
        d = _dist(pa, pb)
        steps = max(1, int(d // WAYPOINT_SPACING))
        prev = a
        for k in range(1, steps):
            t = k / float(steps)
            mid = self.add_node(pa[0] + (pb[0] - pa[0]) * t,
                                pa[1] + (pb[1] - pa[1]) * t, "track")
            self.link(prev, mid)
            prev = mid
        self.link(prev, b)
        self.fallback_edges += 1

    @classmethod
    def build(cls, pathnodes: Iterable[Tuple[str, float, float, Sequence[str]]],
              places: Iterable[Tuple[str, float, float]]) -> "RoadNetwork":
        """The network for *pathnodes* ``(name, x, z, linked names)`` and
        *places* ``(key, x, z)``."""
        net = cls()
        by_name: Dict[str, int] = {}
        links = []
        for name, x, z, nxt in pathnodes:
            i = net.add_node(x, z, "road")
            if name:
                by_name[str(name)] = i
            links.append((i, [str(n).strip() for n in (nxt or ()) if str(n).strip()]))
        net.authored_nodes = len(links)
        linked = set()
        for i, names in links:
            for n in names:
                j = by_name.get(n)
                if j is not None:
                    net.link(i, j)
                    linked.update((i, j))
        # A node no one linked joins its nearest neighbours.
        road = [i for i, _n in links]
        for i in road:
            if i in linked:
                continue
            near = sorted((j for j in road if j != i),
                          key=lambda j: _dist(net.points[i], net.points[j]))
            for j in near[:AUTO_LINK_NEIGHBOURS]:
                if _dist(net.points[i], net.points[j]) <= AUTO_LINK_RADIUS:
                    net.link(i, j)
        # Places join the nearest road node within reach.
        place_list = []
        for key, x, z in places:
            p = net.add_node(x, z, "place")
            net.place_node[str(key)] = p
            place_list.append(p)
            best, best_d = None, PLACE_ATTACH_RADIUS
            for j in road:
                d = _dist(net.points[p], net.points[j])
                if d < best_d:
                    best, best_d = j, d
            if best is not None:
                net.link(p, best)
        net._bridge(place_list)
        return net

    def _components(self) -> List[set]:
        seen, comps = set(), []
        for start in self.adj:
            if start in seen:
                continue
            comp, stack = set(), [start]
            while stack:
                n = stack.pop()
                if n in comp:
                    continue
                comp.add(n)
                stack.extend(m for m in self.adj[n] if m not in comp)
            seen |= comp
            comps.append(comp)
        return comps

    def _bridge(self, place_list: List[int]) -> None:
        """Join every piece holding a place into one network with fallback
        tracks (Prim's over pieces, nearest place-to-anything first), then add
        a few short extra links between places so routes have choices."""
        if len(place_list) < 2:
            return
        comps = [c for c in self._components() if any(p in c for p in place_list)]
        if len(comps) > 1:
            joined = set(comps[0])
            rest = [set(c) for c in comps[1:]]
            while rest:
                best = None
                for ci, comp in enumerate(rest):
                    # Join from a place (or road end) in the new piece to the
                    # nearest point of the joined network.
                    ends = [n for n in comp if self.kinds[n] != "track"]
                    for a in ends:
                        for b in joined:
                            if self.kinds[b] == "track":
                                continue
                            d = _dist(self.points[a], self.points[b])
                            if best is None or d < best[0]:
                                best = (d, ci, a, b)
                d, ci, a, b = best
                before = len(self.points)
                self.link_with_waypoints(a, b)
                joined |= rest.pop(ci)
                joined |= set(range(before, len(self.points)))   # its waypoints
        for p in place_list:
            near = sorted((q for q in place_list if q != p),
                          key=lambda q: _dist(self.points[p], self.points[q]))
            added = 0
            for q in near:
                if added >= EXTRA_LINKS:
                    break
                d = _dist(self.points[p], self.points[q])
                if d > EXTRA_LINK_MAX:
                    break
                # Only where the network would otherwise make a long detour.
                route = self.route_nodes(p, q)
                if route is None or self._length(route) > d * 1.8:
                    self.link_with_waypoints(p, q)
                    added += 1

    # -- routing --------------------------------------------------------------
    def _length(self, nodes: List[int]) -> float:
        return sum(self.adj[a][b] for a, b in zip(nodes, nodes[1:]))

    def route_nodes(self, a: int, b: int) -> Optional[List[int]]:
        """A* from node *a* to node *b*; the node list, or None if unreachable."""
        if a == b:
            return [a]
        goal = self.points[b]
        open_ = [(0.0, 0.0, a)]
        came = {a: None}
        cost = {a: 0.0}
        while open_:
            _f, g, n = heapq.heappop(open_)
            if n == b:
                out = []
                while n is not None:
                    out.append(n)
                    n = came[n]
                return out[::-1]
            if g > cost.get(n, math.inf):
                continue
            for m, w in self.adj[n].items():
                ng = g + w
                if ng < cost.get(m, math.inf):
                    cost[m] = ng
                    came[m] = n
                    heapq.heappush(open_, (ng + _dist(self.points[m], goal), ng, m))
        return None

    def route(self, a_key: str, b_key: str) -> Optional[List[Tuple[float, float]]]:
        """The road points from place *a_key* to place *b_key*, or None."""
        a, b = self.place_node.get(a_key), self.place_node.get(b_key)
        if a is None or b is None:
            return None
        nodes = self.route_nodes(a, b)
        if nodes is None:
            return None
        return [self.points[n] for n in nodes]

    def stats(self) -> Dict[str, int]:
        return {"nodes": len(self.points), "authored": self.authored_nodes,
                "places": len(self.place_node), "fallback_tracks": self.fallback_edges}


# ---------------------------------------------------------------------------
# Routes as polylines
# ---------------------------------------------------------------------------
def cumulative(route: Sequence[Tuple[float, float]]) -> List[float]:
    out = [0.0]
    for a, b in zip(route, route[1:]):
        out.append(out[-1] + _dist(a, b))
    return out


def point_at(route, cum, s: float) -> Tuple[float, float, int]:
    """The point *s* along *route* (with cumulative lengths *cum*), and the
    index of the segment it is on."""
    if not route:
        return (0.0, 0.0, 0)
    if s <= 0.0 or len(route) == 1:
        return (route[0][0], route[0][1], 0)
    if s >= cum[-1]:
        return (route[-1][0], route[-1][1], max(0, len(route) - 2))
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= s:
            lo = mid
        else:
            hi = mid
    seg = max(1e-6, cum[hi] - cum[lo])
    t = (s - cum[lo]) / seg
    a, b = route[lo], route[hi]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, lo)


def project(route, cum, x: float, z: float) -> float:
    """How far along *route* the point nearest (x, z) lies."""
    best_s, best_d = 0.0, math.inf
    for i, (a, b) in enumerate(zip(route, route[1:])):
        ax, az = a
        dx, dz = b[0] - ax, b[1] - az
        seg2 = dx * dx + dz * dz
        t = 0.0 if seg2 <= 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / seg2))
        px, pz = ax + dx * t, az + dz * t
        d = math.hypot(x - px, z - pz)
        if d < best_d:
            best_d = d
            best_s = cum[i] + math.sqrt(seg2) * t
    return best_s
