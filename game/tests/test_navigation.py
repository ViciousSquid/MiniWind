"""Route safety and work cadence, independent of renderer frame rate."""

import math
from types import SimpleNamespace

import pytest

from ..navigation import CELL, Navigator, PlanningBudget, RETRY_SECONDS, ROUTE_SECONDS
from engine.spatial import SIM_TIER_KEY, TIER_ACTIVE, TIER_DISTANT, TIER_DORMANT, TIER_NEAR


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class CountingNavigator(Navigator):
    def __init__(self, blocked, clock):
        # Bounded by nodes, not wall time (as the other tests here are): a
        # 3 ms real-time slot can run out on a busy machine and defer the
        # search these tests count, failing them by load alone.
        super().__init__(blocked, clock, track_stats=True,
                         planning_budget=PlanningBudget(max_seconds=math.inf))
        self.line_checks = 0

    def line_clear(self, *args, **kwargs):
        self.line_checks += 1
        return super().line_clear(*args, **kwargs)


def enclosed(x, y, z):
    return max(abs(math.floor(x / CELL)), abs(math.floor(z / CELL))) == 2


@pytest.mark.parametrize("hz", [30, 60, 120])
def test_unreachable_searches_run_at_two_hz_not_the_callers_tick_rate(hz):
    clock = Clock()
    nav = CountingNavigator(enclosed, clock)
    for tick in range(hz * 2):
        clock.now = tick / hz
        nav.steer("trapped", (24, 0, 24), (1000, 0, 1000))
    stat = nav.search_stats()["trapped"]
    assert stat["searches"] == 4
    assert stat["failed_searches"] == 4
    assert stat["steer_calls"] == hz * 2
    assert stat["reasons"] == {"missing": 1, "retry": 3}
    assert stat["expanded_nodes"] > 0


@pytest.mark.parametrize("start,goal", [((72, 0, 24), (1000, 0, 1000)),
                                        ((24, 64, 24), (1000, 64, 1000)),
                                        ((24, 0, 24), (-1000, 0, -1000))])
def test_new_origin_height_or_distant_goal_bypasses_failure_cooldown(start, goal):
    clock = Clock()
    nav = CountingNavigator(enclosed, clock)
    nav.steer("npc", (24, 0, 24), (1000, 0, 1000))
    clock.now = RETRY_SECONDS / 2
    nav.steer("npc", start, goal)
    assert nav.search_stats()["npc"]["searches"] == 2


def test_new_target_cell_invalidates_a_cached_clear_answer():
    nav = Navigator(lambda x, y, z: 48 <= x < 96 and -96 < z < 96)
    clear = (24, 0, 96)
    assert nav.steer("npc", (24, 0, 24), clear) is clear
    target = (168, 0, 24)
    assert nav.steer("npc", (24, 0, 24), target) != target


def test_collision_revision_observes_a_closing_passage_immediately():
    state = {"closed": False, "revision": 0}
    clock = Clock()
    nav = Navigator(lambda x, y, z: state["closed"] and 48 <= x < 96,
                    clock, revision=lambda: state["revision"])
    start, goal = (24, 0, 24), (168, 0, 24)
    assert nav.steer("npc", start, goal) == goal
    state.update(closed=True, revision=1)
    # Perception uses line_clear directly, without a steer call in between.
    assert not nav.line_clear(24, 24, 168, 24, 0)
    assert nav._clear == {}


def test_collision_revision_retries_a_newly_open_passage_without_waiting():
    state = {"closed": True, "revision": 0}
    nav = CountingNavigator(lambda x, y, z: state["closed"] and enclosed(x, y, z), Clock())
    nav._revision_source = lambda: state["revision"]
    start, goal = (24, 0, 24), (1000, 0, 1000)
    nav.steer("npc", start, goal)
    assert nav._failed
    state.update(closed=False, revision=1)
    assert nav.steer("npc", start, goal) == goal
    assert not nav._failed


def test_moving_unrelated_obstacles_preserves_a_valid_route():
    revision = [0]
    clock = Clock()
    nav = CountingNavigator(lambda x, y, z: -400 < x < 400 and 200 < z < 260, clock)
    nav._revision_source = lambda: revision[0]
    start, goal = (24, 0, 24), (24, 0, 1000)
    waypoint = nav.steer("npc", start, goal)
    assert nav.has_route("npc")
    for tick in range(1, 15):
        revision[0] += 1
        clock.now = tick / 30
        assert nav.steer("npc", start, goal) == waypoint
    assert nav.search_stats()["npc"]["searches"] == 1


def test_live_door_movement_and_grid_rebuild_reach_the_navigation_cache():
    import numpy as np
    from engine.mover_table import MoverTable
    from ..runtime import MiniwindSession

    door = {"pos": [72, 0, 24], "size": [48, 128, 48], "is_door": True}
    table = MoverTable()
    table.doors.ensure([(0, door)])
    grid = SimpleNamespace(navigation_revision=0)
    session = object.__new__(MiniwindSession)
    session.logic = SimpleNamespace(
        monster_ai=SimpleNamespace(_grid=grid),
        mover_runtime=SimpleNamespace(_mover_table=table))
    # Fio 3.5 keeps a moving door's position in the mover table, not in the
    # brush: ask where it is now, as the engine's own collision does.
    from engine import brush_placement

    def centre():
        return brush_placement.placement(door).centre

    walls = []

    def blocked(x, y, z):
        return any(abs(x - c[0]) < 24 and abs(z - c[2]) < 24
                   for c in [centre()] + walls)

    nav = Navigator(blocked,
                    Clock(), revision=session._navigation_revision)
    assert not nav.line_clear(24, 24, 168, 24, 0)
    table.doors._write_positions(np.array([0]), np.array([[72, 0, 240]]), None)
    assert nav.line_clear(24, 24, 168, 24, 0)
    revision = table.doors.position_revision
    table.doors._write_positions(np.array([0]), np.array([[72, 0, 240]]), None)
    assert table.doors.position_revision == revision
    # Static geometry can change without moving a door.
    walls.append([72, 0, 24])
    grid.navigation_revision += 1
    assert not nav.line_clear(24, 24, 168, 24, 0)


def test_a_shared_planning_budget_bounds_the_whole_crowd_not_each_actor():
    clock = Clock()
    budget = PlanningBudget(max_nodes=64, max_seconds=math.inf)
    wall = lambda x, y, z: -400 < x < 400 and 200 < z < 260
    navigators = [Navigator(wall, clock, planning_budget=budget) for _ in range(2)]
    for nav in navigators:
        for actor in range(50):
            nav.steer(actor, (24, 0, 24), (24, 0, 1000))
    assert budget.nodes == 64
    # Re-entering from another movement/perception caller cannot reset the quota.
    for nav in navigators:
        nav.steer(0, (24, 0, 24), (24, 0, 1000))
    assert budget.nodes == 64


def test_queued_searches_resume_and_every_actor_eventually_gets_a_safe_route():
    clock = Clock()
    budget = PlanningBudget(max_nodes=128, max_seconds=math.inf)
    nav = Navigator(lambda x, y, z: -400 < x < 400 and 200 < z < 260,
                    clock, track_stats=True, planning_budget=budget)
    start, goal = (24, 0, 24), (24, 0, 1000)
    solved = set()
    for tick in range(300):
        clock.now = tick / 60
        for actor in range(12):
            waypoint = nav.steer(actor, start, goal)
            if nav.has_route(actor):
                solved.add(actor)
                assert nav.line_clear(start[0], start[2], waypoint[0], waypoint[2], 0)
        assert budget.nodes <= 128
        if len(solved) == 12:
            break
    assert solved == set(range(12)), "queued actors must not starve behind the first request"
    assert all(stat["searches"] == 1 for stat in nav.search_stats().values())


def test_suspending_an_actor_cancels_its_queued_frontier():
    budget = PlanningBudget(max_nodes=1, max_seconds=math.inf)
    nav = Navigator(lambda x, y, z: -400 < x < 400 and 200 < z < 260,
                    Clock(), planning_budget=budget)
    assert nav.steer("npc", (24, 0, 24), (24, 0, 1000)) == (24, 0, 24)
    plan = nav._pending["npc"]
    nav.suspend("npc")
    assert plan.cancelled
    budget.run(1.0)
    assert budget.nodes == 0
    assert not nav.has_route("npc")


def test_schedule_movement_waits_when_its_route_is_queued():
    from .test_npc_movement import _NPC, _Walker, _WALL_ACROSS_PATH

    walker = _Walker(_WALL_ACROSS_PATH)
    walker.nav = Navigator(walker._blocked_by_wall, Clock(),
                           planning_budget=PlanningBudget(max_nodes=1, max_seconds=math.inf))
    npc = _NPC(pos=(24, 0, 24), dest=(24, 0, 1000), _blocked_ticks=1)
    walker._move(npc, 0.1)
    assert npc.pos == [24, 0, 24]
    assert id(npc) in walker.nav._pending


def test_a_changed_goal_replaces_a_queued_search():
    nav = Navigator(lambda x, y, z: -400 < x < 400 and 200 < z < 260,
                    Clock(), planning_budget=PlanningBudget(max_nodes=1, max_seconds=math.inf))
    nav.steer("npc", (24, 0, 24), (24, 0, 1000))
    previous = nav._pending["npc"]
    nav.steer("npc", (24, 0, 24), (24, 0, 2000))
    assert previous.cancelled
    assert nav._pending["npc"].goal == (24, 2000)


@pytest.mark.parametrize("start,end", [((24, 24), (72, 72)), ((72, 72), (24, 24))])
def test_visibility_cannot_squeeze_diagonally_past_a_solid_corner(start, end):
    nav = Navigator(lambda x, y, z: math.floor(x / CELL) == 1 and math.floor(z / CELL) == 0)
    assert not nav.line_clear(*start, *end, 0)
    path = nav.find_path(start, end, 0)
    assert path
    for a, b in zip([start, *path], path):
        assert nav.line_clear(*a, *b, 0), (a, b)


def test_visibility_visits_cells_clipped_between_sampling_positions():
    nav = Navigator(lambda x, y, z: math.floor(x / CELL) == 0 and math.floor(z / CELL) == 1)
    assert not nav.line_clear(1, 47.1, 95, 49, 0)


@pytest.mark.parametrize("start,end", [((-96, -96), (0, 0)), ((0, 0), (-96, -96)),
                                        ((-96, 0), (0, -96)), ((0, 0), (0, -96)),
                                        ((0, 0), (-96, 0)), ((24, 24), (24, 24))])
def test_visibility_handles_negative_coordinates_and_boundary_endpoints(start, end):
    assert Navigator(lambda *args: False).line_clear(*start, *end, 0)


def test_visibility_respects_lookahead_limit():
    nav = Navigator(lambda x, y, z: x > 200)
    assert nav.line_clear(24, 24, 500, 24, 0, limit=100)
    assert not nav.line_clear(24, 24, 500, 24, 0)


def test_smoothing_uses_a_forward_pass_in_a_winding_corridor():
    cells = []
    for row in range(10):
        xs = range(21) if row % 2 == 0 else range(20, -1, -1)
        cells.extend((x, row * 4) for x in xs)
        if row < 9:
            cells.extend((cells[-1][0], row * 4 + dz) for dz in range(1, 4))
    open_cells = set(cells)
    nav = CountingNavigator(lambda x, y, z: (math.floor(x / CELL), math.floor(z / CELL))
                            not in open_cells, Clock())
    points = [((x + .5) * CELL, (z + .5) * CELL) for x, z in cells]
    path = nav._smooth(points[0], points[1:], 0)
    assert nav.line_checks <= 22, "each turn should be tested once, without rescanning the tail"
    assert path[-1] == points[-1]
    for a, b in zip([points[0], *path], path):
        assert nav.line_clear(*a, *b, 0), (a, b)


def test_waypoint_visibility_is_throttled_but_routes_still_expire():
    clock = Clock()
    nav = CountingNavigator(lambda x, y, z: -400 < x < 400 and 200 < z < 260, clock)
    pos, goal = (0, 0, 0), (0, 0, 1000)
    nav.steer("npc", pos, goal)
    initial_checks = nav.line_checks
    for tick in range(1, 30):
        clock.now = tick / 30
        nav.steer("npc", pos, goal)
    assert nav.line_checks - initial_checks <= 4
    assert nav.search_stats()["npc"]["searches"] == 1
    clock.now = ROUTE_SECONDS
    nav.steer("npc", pos, goal)
    assert nav.search_stats()["npc"]["reasons"] == {"missing": 1, "expired": 1}


def test_a_blocked_goal_keeps_its_safe_endpoint_instead_of_steering_into_a_wall():
    nav = Navigator(lambda x, y, z: math.floor(x / CELL) == 5 and math.floor(z / CELL) == 0)
    pos, goal = (24, 0, 24), (264, 0, 24)
    waypoint = nav.steer("npc", pos, goal)
    assert waypoint != goal
    assert nav.has_route("npc")
    assert nav.line_clear(pos[0], pos[2], waypoint[0], waypoint[2], 0)


def test_batch_uses_one_timestamp_and_preserves_none_entries():
    calls = []
    nav = Navigator(lambda *args: False, lambda: calls.append(1) or 0.0)
    calls.clear()
    assert nav.steer_many([object(), None, object()], [(0, 0, 0)] * 3,
                          [(100, 0, 100)] * 3) == [None, None, None]
    assert len(calls) == 1


def test_debug_snapshots_are_detached_and_do_not_request_routes():
    clock = Clock()
    nav = Navigator(enclosed, clock)
    assert nav.debug_snapshot() == {}
    nav.set_debug(True)
    nav.steer("npc", (24, 0, 24), (1000, 0, 1000))
    first = nav.debug_snapshot()
    first["npc"]["state"] = "modified"
    assert nav.debug_snapshot()["npc"]["state"] == "failed"
    assert nav.search_stats()["npc"]["searches"] == 1
    nav.reset_search_stats()
    assert nav.search_stats() == {}
    nav.forget("npc")
    assert nav.debug_snapshot() == {}
    nav.set_debug(False)
    nav.steer("npc", (24, 0, 24), (1000, 0, 1000))
    assert nav.search_stats() == {}


@pytest.mark.parametrize("tier", [TIER_DISTANT, TIER_DORMANT])
def test_bigworld_demotion_clears_route_work_and_promotion_plans_afresh(tier):
    nav = CountingNavigator(enclosed, Clock())
    actor = SimpleNamespace(properties={SIM_TIER_KEY: TIER_NEAR})
    pos, goal = (24, 0, 24), (1000, 0, 1000)
    nav.steer_actor(actor, pos, goal)
    key = id(actor)
    assert nav.search_stats()[key]["searches"] == 1
    checks = nav.line_checks
    actor.properties[SIM_TIER_KEY] = tier
    assert nav.steer_actor(actor, pos, goal) is goal
    assert nav.line_checks == checks
    assert key not in nav._failed and not nav.has_route(key)
    actor.properties[SIM_TIER_KEY] = TIER_ACTIVE
    nav.steer_actor(actor, pos, goal)
    assert nav.search_stats()[key]["searches"] == 2


def test_batch_and_combat_tactics_obey_bigworld_stamps_without_classifying_distance():
    from engine.spatial import tier_of
    from ..combat_tactics import CombatTactics
    clock = Clock()
    nav = CountingNavigator(enclosed, clock)
    actors = [SimpleNamespace(properties={SIM_TIER_KEY: tier})
              for tier in (TIER_NEAR, TIER_ACTIVE, TIER_DISTANT, TIER_DORMANT)]
    # All four actors occupy exactly the same location. The authoritative
    # stamp, rather than a new distance heuristic, decides who gets live A*.
    tactics = CombatTactics(clock, nav=nav, tier_of=tier_of)
    assert tactics.steer_many(actors, [(24, 0, 24)] * 4, [(1000, 0, 1000)] * 4) == [None] * 4
    assert set(nav.search_stats()) == {id(actor) for actor in actors[:2]}


def test_distant_schedule_movement_keeps_collision_checks_without_live_searches():
    from .test_npc_movement import _NPC, _Walker, _WALL_ACROSS_PATH
    npc = _NPC(pos=(0, 0, 170))
    npc.properties[SIM_TIER_KEY] = TIER_DISTANT
    walker = _Walker(_WALL_ACROSS_PATH)
    walker.nav.set_debug(True)
    for _ in range(3):
        walker._move(npc, .1)
    assert walker.logic.monster_ai.queries > 0
    assert walker.nav.search_stats() == {}
    assert npc.pos[2] < 200


def test_generated_routes_keep_every_smoothed_segment_walkable():
    import random
    for seed in range(30):
        rng = random.Random(seed)
        blocked = {(x, z) for x in range(-10, 11) for z in range(-10, 11)
                   if rng.random() < .2}
        blocked.discard((-8, -8))
        blocked.discard((8, 8))
        nav = Navigator(lambda x, y, z: (math.floor(x / CELL), math.floor(z / CELL)) in blocked)
        start, goal = (-8 * CELL + 10, -8 * CELL + 30), (8 * CELL + 40, 8 * CELL + 5)
        path = nav.find_path(start, goal, 0)
        assert path and path[-1] == goal, seed
        for a, b in zip([start, *path], path):
            assert nav.line_clear(*a, *b, 0), (seed, a, b)

