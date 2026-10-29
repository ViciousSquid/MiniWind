"""The ROAD_* navigation graph: built ahead, rebuilt only when the roads
change, taken only where it helps, and left for anything more pressing."""

from __future__ import annotations

import math

import pytest

from .. import road_nav
from ..road_nav import RoadCache, RoadGraph, road_nodes


class _Node:
    def __init__(self, name, x, z, next_node="", **extra):
        self.pos = [float(x), 0.0, float(z)]
        self.properties = {"type": "path_node", "name": name, "next_node": next_node, **extra}


def _straight_road(n=6, spacing=1000.0, z=0.0, prefix="ROAD_"):
    """ROAD_1 .. ROAD_n along the x axis, each linked to the next."""
    return [_Node(f"{prefix}{i}", i * spacing, z,
                  f"{prefix}{i + 1}" if i < n else "") for i in range(1, n + 1)]


def test_only_road_nodes_make_the_graph_and_links_run_both_ways():
    things = _straight_road(3) + [_Node("patrol_1", 1500, 0, "ROAD_1"),
                                  _Node("ROAD_9", 50000, 50000)]
    nodes = road_nodes(things)
    assert [n[0] for n in nodes] == ["ROAD_1", "ROAD_2", "ROAD_3", "ROAD_9"]
    g = RoadGraph.build(nodes)
    a, c = g.names.index("ROAD_1"), g.names.index("ROAD_3")
    assert g.route(a, c) == [a, g.names.index("ROAD_2"), c]
    assert g.route(c, a) == [c, g.names.index("ROAD_2"), a]
    assert g.route(a, g.names.index("ROAD_9")) is None     # far off, unlinked


def test_junctions_and_the_shortest_road_come_from_the_tables():
    things = [_Node("ROAD_A", 0, 0, "ROAD_B, ROAD_C"), _Node("ROAD_B", 1000, 0, "ROAD_D"),
              _Node("ROAD_C", 0, 3000, "ROAD_D"), _Node("ROAD_D", 2000, 0)]
    g = RoadGraph.build(road_nodes(things))
    a, b, d = (g.names.index(n) for n in ("ROAD_A", "ROAD_B", "ROAD_D"))
    assert g.route(a, d) == [a, b, d]
    assert g.dist[a][d] == pytest.approx(2000.0)


def test_a_long_walk_joins_near_the_start_and_leaves_near_the_goal():
    g = RoadGraph.build(road_nodes(_straight_road(8)))
    # Start a little off the road near ROAD_1, goal off it near ROAD_8.
    plan = g.plan((1000.0, 400.0), (8100.0, 500.0))
    assert plan is not None
    # It joins where the whole trip is cheapest -- cutting the corner to the
    # second node rather than doubling back to the first -- and likewise
    # leaves by whichever node near the goal is cheapest.
    assert plan[0] in ((1000.0, 0.0), (2000.0, 0.0))
    assert plan[-1] in ((7000.0, 0.0), (8000.0, 0.0))
    assert [x for x, _z in plan] == sorted(x for x, _z in plan)


def test_the_road_is_not_taken_where_it_does_not_help():
    g = RoadGraph.build(road_nodes(_straight_road(8)))
    assert g.plan((2000.0, 50.0), (2600.0, 50.0)) is None            # a short walk
    assert g.plan((1000.0, 9000.0), (8000.0, 9000.0)) is None        # no road nearby
    # Across the road, not along it: straight over is cheaper.
    assert g.plan((4000.0, -1500.0), (4000.0, 1500.0)) is None


def test_the_graph_is_reused_until_the_roads_change(monkeypatch):
    monkeypatch.setattr(RoadCache, "_built", {})
    things = _straight_road(4)
    cache = RoadCache()
    first = cache.graph(things)
    assert cache.graph(things) is first and cache.builds == 1
    things[1].pos[0] += 300.0                        # a node moved
    moved = cache.graph(things)
    assert moved is not first and cache.builds == 2
    things[1].properties["next_node"] = ""           # relinked
    assert cache.graph(things) is not moved
    # The same roads in a new session: nothing to build.
    again = RoadCache()
    assert again.graph(things) is cache.current and again.builds == 0


# --------------------------------------------------------------- in the game
def _walker(pos, dest, **extra):
    from .test_combat_ai import _FakeThing
    p = {"type": "npc", "name": "Walker", "npc_role": "villager", "faction": "villagers",
         "team": "villagers", "aggression": "passive", "triggered": True,
         "sched_state": "GOING_TO_WORK", "_dest": list(dest), "move_speed": 90.0}
    p.update(extra)
    return _FakeThing(list(pos), p)


def _session(things):
    from .test_combat_ai import _FakeLogic, _FakePlayer
    from ..runtime import MiniwindSession
    s = MiniwindSession(_FakeLogic(things, _FakePlayer([99999, 0, 99999])), cfg={})
    s._blocked_by_wall = lambda x, y, z: False
    s._refresh_roads(force=True)
    return s


def test_a_walker_heads_for_the_road_then_along_it_then_off_to_its_goal():
    road = _straight_road(8)
    walker = _walker([1000.0, 0.0, 400.0], [8100.0, 0.0, 500.0])
    s = _session(road + [walker])
    assert s._road_graph is not None and len(s._road_graph) == 8
    target, on_road = s._road_target(walker, walker.pos, walker.properties["_dest"])
    entry = (target[0], target[2])
    assert entry in ((1000.0, 0.0), (2000.0, 0.0)) and not on_road
    walker.pos = [entry[0] + 10.0, 0.0, 20.0]        # reached the road
    target, on_road = s._road_target(walker, walker.pos, walker.properties["_dest"])
    assert (target[0], target[2]) == (entry[0] + 1000.0, 0.0) and on_road
    walker.pos = [8000.0, 0.0, 10.0]                 # the end of the road
    assert s._road_target(walker, walker.pos, walker.properties["_dest"]) is None


def test_a_frightened_or_fighting_walker_leaves_the_road():
    road = _straight_road(8)
    walker = _walker([1000.0, 0.0, 400.0], [8100.0, 0.0, 500.0])
    s = _session(road + [walker])
    assert s._road_target(walker, walker.pos, walker.properties["_dest"]) is not None
    walker.properties["sched_state"] = "FLEE"
    assert s._road_target(walker, walker.pos, walker.properties["_dest"]) is None
    assert id(walker) not in s._road_plans
    walker.properties["sched_state"] = "GOING_TO_WORK"
    walker.properties["_aggro_target"] = 1234
    assert s._road_target(walker, walker.pos, walker.properties["_dest"]) is None


def test_walking_moves_along_the_road_quicker_than_off_it():
    from ..runtime import ROAD_SPEED
    road = _straight_road(8)
    walker = _walker([2000.0, 0.0, 0.0], [8100.0, 0.0, 500.0])     # on ROAD_2
    s = _session(road + [walker])
    s._step_to = lambda npc, x, z: (npc.pos.__setitem__(0, x), npc.pos.__setitem__(2, z)) or True
    before = list(walker.pos)
    s._move(walker, 1.0)
    moved = math.hypot(walker.pos[0] - before[0], walker.pos[2] - before[2])
    assert moved == pytest.approx(90.0 * ROAD_SPEED)
    assert abs(walker.pos[2]) < 1e-6                  # along the road, not cutting off it


def test_changed_roads_drop_every_walkers_road_leg(monkeypatch):
    monkeypatch.setattr(road_nav.RoadCache, "_built", {})
    road = _straight_road(8)
    walker = _walker([1000.0, 0.0, 400.0], [8100.0, 0.0, 500.0])
    s = _session(road + [walker])
    s._road_target(walker, walker.pos, walker.properties["_dest"])
    assert s._road_plans
    old = s._road_graph
    road[3].pos[2] += 500.0
    s._type_index_token = None
    s._refresh_roads(force=True)
    assert s._road_graph is not old and not s._road_plans


def test_unlinked_nodes_are_joined_and_marked_as_auto_links():
    things = [_Node("ROAD_1", 0, 0, "ROAD_2"), _Node("ROAD_2", 1000, 0),
              _Node("ROAD_3", 2000, 0), _Node("ROAD_4", 90000, 0)]
    g = RoadGraph.build(road_nodes(things))
    edges = {(g.names[a], g.names[b]): auto for a, b, auto in g.edges()}
    assert edges[("ROAD_1", "ROAD_2")] is False
    assert edges[("ROAD_2", "ROAD_3")] is True
    assert g.pieces() == 2                           # ROAD_4 stands alone


# --------------------------------------------------------- console 'shownav'
def test_shownav_toggles_the_overlay_and_reports_the_graph(monkeypatch):
    from types import SimpleNamespace
    from .. import console
    logs = []
    monkeypatch.setattr(console, "debug_log", lambda category, text: logs.append((category, text)))
    s = _session(_straight_road(4))
    ctx = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=s), play_mode=True)
    console.cmd_shownav(ctx, "")
    assert s.show_nav is True
    assert "4 nodes, 3 links" in logs[-1][1]
    console.cmd_shownav(ctx, "off")
    assert s.show_nav is False
    console.cmd_shownav(ctx, "sideways")
    assert logs[-1][0] == "Error"
    out = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=s), play_mode=False)
    console.cmd_shownav(out, "on")
    assert logs[-1] == ("Error", "shownav: enter Play Mode first.")


@pytest.mark.qt
def test_the_overlay_draws_the_roads_and_a_walkers_leg(qt_app):
    import glm
    from types import SimpleNamespace
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import nav_debug
    road = _straight_road(6)
    walker = _walker([1000.0, 0.0, 400.0], [6100.0, 0.0, 500.0])
    s = _session(road + [walker])
    s._live_actors = lambda: [walker]
    s._road_target(walker, walker.pos, walker.properties["_dest"])
    # A top-down projection: clip x = x/8000 - 0.5, clip y = -z/8000.
    proj = glm.mat4(0.0)
    proj[0][0] = 1.0 / 8000.0
    proj[2][1] = -1.0 / 8000.0
    proj[3][0] = -0.5
    proj[3][3] = 1.0
    view = SimpleNamespace(projection_matrix=proj, view_matrix=glm.mat4(1))
    image = QImage(800, 600, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        nav_debug.draw(painter, s, view, 800, 600)      # off: nothing drawn
        assert image.pixelColor(400, 300).alpha() == 0
        s.show_nav = True
        nav_debug.draw(painter, s, view, 800, 600)
    finally:
        painter.end()

    def at(x, z):
        cx, cy = x / 8000.0 - 0.5, -z / 8000.0
        return image.pixelColor(int((cx * 0.5 + 0.5) * 800), int((1 - (cy * 0.5 + 0.5)) * 600))
    road_px = at(3500.0, 0.0)                            # between ROAD_3 and ROAD_4
    assert road_px.green() > 150 and road_px.alpha() > 100
    assert nav_debug.summary(s)["walkers"] == 1


def test_patrol_nodes_are_never_roads_for_live_walkers_or_travellers():
    from ..living import roads as living_roads
    patrol = [_Node("patrol_1", 1000, 300, "patrol_2"), _Node("patrol_2", 2000, 300, "ROAD_2"),
              _Node("guard_post_a", 1500, 600)]
    road = _straight_road(3)
    road[0].properties["next_node"] = "ROAD_2, patrol_1"      # a link to a patrol node
    things = patrol + road
    # Live NPCs' graph: the three roads, the patrol link ignored.
    g = RoadGraph.build(road_nodes(things))
    assert g.names == ["ROAD_1", "ROAD_2", "ROAD_3"]
    assert {(g.names[a], g.names[b]) for a, b, _auto in g.edges()} == {
        ("ROAD_1", "ROAD_2"), ("ROAD_2", "ROAD_3")}
    # The living world's travellers read the same road nodes and nothing else.
    authored = living_roads.authored_roads(things)
    assert [n[0] for n in authored] == ["ROAD_1", "ROAD_2", "ROAD_3"]
    net = living_roads.RoadNetwork.build(authored, [])
    assert net.authored_nodes == 3


def test_walkers_keep_to_a_winding_road_rather_than_cut_across_country():
    # A road that bows far out to the side: about 1.8 times the straight line.
    pts = [(-4000.0, 0.0), (-2500.0, 2600.0), (0.0, 3400.0), (2500.0, 2600.0), (4000.0, 0.0)]
    things = []
    for i, (x, z) in enumerate(pts):
        links = f"ROAD_{i + 1}" if i + 1 < len(pts) else ""
        things.append(_Node(f"ROAD_{i}", x, z, links))
    g = RoadGraph.build(road_nodes(things))
    leg = g.plan((-4000.0, -200.0), (4000.0, -200.0))
    assert leg is not None and leg[0] == pts[0] and leg[-1] == pts[-1]
    # Only a road far more roundabout than that is left for open country.
    assert road_nav.ROAD_COST * 2.5 <= 1.0 + 1e-9
