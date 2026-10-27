"""Route safety and work cadence, independent of renderer frame rate."""

import math
from types import SimpleNamespace

import pytest

from ..navigation import CELL, Navigator, RETRY_SECONDS, ROUTE_SECONDS
from engine.spatial import SIM_TIER_KEY, TIER_ACTIVE, TIER_DISTANT, TIER_DORMANT, TIER_NEAR


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class CountingNavigator(Navigator):
    def __init__(self, blocked, clock):
        super().__init__(blocked, clock, track_stats=True)
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
