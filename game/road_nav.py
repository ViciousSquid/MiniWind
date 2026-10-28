"""
The roads live NPCs walk: a navigation graph over the map's ``ROAD_*`` nodes.

Place PathNodes named ``ROAD_1``, ``ROAD_2`` ... along a road and link them
the way any PathNode chain is linked -- ``next_node`` (or ``links``) names
the next node, several names separated by commas make a junction, and every
link is two-way. A ROAD node nobody linked joins its nearest ROAD neighbours
(:data:`AUTO_LINK_RADIUS`), so a dotted line of nodes still reads as a road.
Links to nodes that are not roads are ignored: patrol chains are not roads.

**Built once, not searched live.** When play starts the graph is built and
every shortest road route is worked out in advance (:meth:`RoadGraph.build`:
a Dijkstra from each node), so planning a trip while the game runs is a few
table lookups, never a search. The graph carries a signature of the nodes it
was made from -- their names, places and links -- and is kept, across play
sessions too, for as long as the roads are what it was made from; the moment
they differ (a node moved, added, renamed or relinked) it is thrown away and
a new one built (:class:`RoadCache`).

**Roads are a help, not a rail.** :meth:`RoadGraph.plan` gives a walker the
road only when it is worth it: the trip is long enough, a road starts near
enough and ends near enough, and walking to it, along it and off it again is
cheaper than going straight -- road walking counts for :data:`ROAD_COST` of
its length, as a cleared, level way does. The walker joins at whichever node
makes the whole trip cheapest (not just the nearest), leaves at whichever
node is best for its goal, and between them the ordinary A* navigator still
takes it round whatever is in the way. Anything more urgent -- a fight, a
fright, an attacker -- simply takes the walker off the road
(:meth:`game.runtime.MiniwindSession._road_target`).

Plain Python on ``(x, z)`` tuples -- no engine, no Qt.
"""

from __future__ import annotations

import heapq
import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: The names that make a PathNode a road node.
ROAD_NAME = re.compile(r"^road_", re.IGNORECASE)
#: A road node nobody linked joins this many nearest road nodes within reach.
AUTO_LINK_RADIUS = 1400.0
AUTO_LINK_NEIGHBOURS = 2
#: Trips shorter than this are walked straight (world units).
MIN_TRIP = 1200.0
#: How far a walker will go to join a road, or from its end to the goal.
JOIN_RADIUS = 2000.0
#: How many of the nearest nodes are weighed as places to join or leave.
CANDIDATES = 5
#: Walking a road costs this much of its length, against 1.0 off it.
ROAD_COST = 0.7
#: The road must make the trip at least this much cheaper to be taken.
MIN_SAVING = 0.05

#: ``(name, x, z, linked names, y)`` -- *y* only places the node for
#: drawing (console ``shownav``); routes are on the ground plane.
Node = Tuple[str, float, float, Sequence[str], float]


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_road(name) -> bool:
    return bool(ROAD_NAME.match(str(name or "").strip()))


def road_nodes(things) -> List[Node]:
    """``(name, x, z, linked names, y)`` of every ``ROAD_*`` PathNode in *things*,
    in a stable order (by name), so the same roads always give the same
    signature."""
    out = []
    for t in things or ():
        p = getattr(t, "properties", None) or {}
        if str(p.get("type", "")).replace("_", "").lower() != "pathnode":
            continue
        name = str(p.get("name", "") or "").strip()
        if not is_road(name):
            continue
        links = [n.strip() for field in ("next_node", "links")
                 for n in str(p.get(field, "") or "").split(",") if n.strip()]
        pos = getattr(t, "pos", None)
        if pos is None:
            continue
        out.append((name, float(pos[0]), float(pos[2]), tuple(links), float(pos[1])))
    out.sort(key=lambda n: (n[0], n[1], n[2]))
    return out


def signature(nodes: Sequence[Node]) -> Tuple:
    """What a graph was built from: names, positions (to a unit) and links."""
    return tuple((n[0], round(n[1]), round(n[2]), tuple(sorted(n[3]))) for n in nodes)


class RoadGraph:
    """The road nodes, their two-way links, and every shortest road route."""

    def __init__(self):
        self.names: List[str] = []
        self.points: List[Tuple[float, float]] = []
        self.heights: List[float] = []
        self.adj: List[Dict[int, float]] = []
        #: Links made by joining an unlinked node to its neighbours, as
        #: ``(low, high)`` index pairs (the rest were authored).
        self.auto_links = set()
        #: dist[a][b]: road distance from node a to b (inf: not connected).
        self.dist: List[List[float]] = []
        #: hop[a][b]: the node after a on the shortest road from a to b
        #: (-1: none).
        self.hop: List[List[int]] = []
        self.signature: Tuple = ()

    def __len__(self) -> int:
        return len(self.points)

    def edges(self):
        """Every link once, as ``(a, b, auto)`` with ``a < b``."""
        for a, links in enumerate(self.adj):
            for b in links:
                if a < b:
                    yield a, b, (a, b) in self.auto_links

    def pieces(self) -> int:
        """How many separate road networks the nodes make (1: all joined)."""
        seen, count = set(), 0
        for start in range(len(self)):
            if start in seen:
                continue
            count += 1
            stack = [start]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                stack.extend(self.adj[n])
        return count

    # -- building -----------------------------------------------------------
    @classmethod
    def build(cls, nodes: Sequence[Node]) -> "RoadGraph":
        g = cls()
        g.signature = signature(nodes)
        by_name: Dict[str, int] = {}
        for node in nodes:
            name, x, z = node[0], node[1], node[2]
            by_name.setdefault(name, len(g.points))
            g.names.append(name)
            g.points.append((x, z))
            g.heights.append(float(node[4]) if len(node) > 4 else 0.0)
            g.adj.append({})
        linked = set()
        for i, node in enumerate(nodes):
            for other in node[3]:
                j = by_name.get(other)
                if j is not None and j != i:
                    g._link(i, j)
                    linked.update((i, j))
        for i in range(len(g.points)):
            if i in linked:
                continue
            near = sorted((j for j in range(len(g.points)) if j != i),
                          key=lambda j: _dist(g.points[i], g.points[j]))
            for j in near[:AUTO_LINK_NEIGHBOURS]:
                if _dist(g.points[i], g.points[j]) <= AUTO_LINK_RADIUS:
                    if j not in g.adj[i]:
                        g.auto_links.add((min(i, j), max(i, j)))
                    g._link(i, j)
        g._precompute()
        return g

    def _link(self, a: int, b: int) -> None:
        d = _dist(self.points[a], self.points[b])
        self.adj[a][b] = d
        self.adj[b][a] = d

    def _precompute(self) -> None:
        """Every shortest road route, ahead of time: a Dijkstra from each
        node, keeping the distance and the first step of each route."""
        n = len(self.points)
        self.dist = []
        self.hop = []
        for src in range(n):
            dist = [math.inf] * n
            first = [-1] * n
            dist[src] = 0.0
            first[src] = src
            heap = [(0.0, src)]
            while heap:
                d, u = heapq.heappop(heap)
                if d > dist[u]:
                    continue
                for v, w in self.adj[u].items():
                    nd = d + w
                    if nd < dist[v]:
                        dist[v] = nd
                        first[v] = v if u == src else first[u]
                        heapq.heappush(heap, (nd, v))
            self.dist.append(dist)
            self.hop.append(first)

    # -- routing --------------------------------------------------------------
    def route(self, a: int, b: int) -> Optional[List[int]]:
        """The nodes of the shortest road from *a* to *b*, read off the
        tables (no search); None when no road joins them."""
        if not (0 <= a < len(self) and 0 <= b < len(self)) or math.isinf(self.dist[a][b]):
            return None
        out = [a]
        while out[-1] != b:
            out.append(self.hop[out[-1]][b])
            if len(out) > len(self) + 1:          # pragma: no cover - defensive
                return None
        return out

    def _nearest(self, point, limit=JOIN_RADIUS, k=CANDIDATES) -> List[Tuple[float, int]]:
        near = sorted((_dist(point, p), i) for i, p in enumerate(self.points))
        return [(d, i) for d, i in near[:k] if d <= limit]

    def plan(self, start, goal) -> Optional[List[Tuple[float, float]]]:
        """The road points for a walk from *start* to *goal* (each ``(x, z)``):
        from the node it joins at to the node it leaves by; then it goes on
        to the goal by itself. None when the road does not help -- a short
        trip, no road near either end, or no cheaper than going straight."""
        if len(self) < 2:
            return None
        direct = _dist(start, goal)
        if direct < MIN_TRIP:
            return None
        best, choice = direct * (1.0 - MIN_SAVING), None
        exits = self._nearest(goal)
        if not exits:
            return None
        for d_in, a in self._nearest(start):
            row = self.dist[a]
            for d_out, b in exits:
                if a == b or math.isinf(row[b]):
                    continue
                cost = d_in + row[b] * ROAD_COST + d_out
                if cost < best:
                    best, choice = cost, (a, b)
        if choice is None:
            return None
        nodes = self.route(*choice)
        return [self.points[i] for i in nodes] if nodes else None


class RoadCache:
    """The current road graph, kept while the roads are unchanged.

    :meth:`graph` is cheap to call often: it rebuilds only when the road
    nodes' signature differs from the one the graph was built from. Graphs
    are also remembered by signature, so starting play again on the same
    roads builds nothing."""

    #: Graphs by signature, across sessions (the last few road layouts).
    _built: Dict[Tuple, RoadGraph] = {}
    _KEEP = 4

    def __init__(self):
        self.current: Optional[RoadGraph] = None
        self.builds = 0

    def graph(self, things) -> RoadGraph:
        nodes = road_nodes(things)
        sig = signature(nodes)
        if self.current is not None and self.current.signature == sig:
            return self.current
        graph = RoadCache._built.get(sig)
        if graph is None:
            graph = RoadGraph.build(nodes)
            self.builds += 1
            if len(RoadCache._built) >= RoadCache._KEEP:
                RoadCache._built.pop(next(iter(RoadCache._built)))
            RoadCache._built[sig] = graph
        self.current = graph
        return graph
