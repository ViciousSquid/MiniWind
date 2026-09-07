"""
The engine's authoritative actor index and its simulation-LOD tiers.

``engine/world_index.py`` is the one place the engine answers "who is near the
player" — the AI's activation, the gameplay layer's perception, the streamer's
relevance and the render-state builder's culling all read it. These tests pin
the contract those four consumers rely on: the tier bands, the hysteresis that
stops a boundary-loiterer flapping, radius queries agreeing with a brute-force
scan (in both the small-world and the binned path), and the shared 512-unit cell
convention actually being shared.

Run:  python -m pytest engine/tests/test_world_index.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np

from engine.world_index import (BIN_THRESHOLD, TIER_ACTIVE, TIER_ACTIVE_RADIUS,
                                TIER_DISTANT, TIER_DORMANT, TIER_HYSTERESIS,
                                TIER_NEAR, TIER_NEAR_RADIUS, WorldIndex)


class _Actor:
    def __init__(self, x, z, y=64.0, **props):
        self.pos = [float(x), float(y), float(z)]
        self.properties = dict(props)
        self.properties.setdefault("team", "villagers")

    def __repr__(self):
        return f"<actor {self.pos[0]:.0f},{self.pos[2]:.0f}>"


def _index(actors, focus=(0.0, 0.0)):
    wi = WorldIndex()
    wi.rebuild(actors, focus)
    return wi


# --- tiers -----------------------------------------------------------------

def test_distance_sorts_actors_into_the_three_live_tiers():
    near = _Actor(TIER_NEAR_RADIUS - 10, 0)
    active = _Actor(TIER_ACTIVE_RADIUS - 10, 0)
    distant = _Actor(TIER_ACTIVE_RADIUS * 4, 0)
    wi = _index([near, active, distant])
    assert wi.tier_of(near) == TIER_NEAR
    assert wi.tier_of(active) == TIER_ACTIVE
    assert wi.tier_of(distant) == TIER_DISTANT


def test_a_parked_actor_is_dormant_however_close_it_stands():
    """The streamer's `disabled` (and a map's `hidden`) outrank distance —
    a streamed-out actor is not simulated even standing on the player."""
    for flag in ("disabled", "hidden"):
        a = _Actor(0, 0, **{flag: True})
        assert _index([a]).tier_of(a) == TIER_DORMANT, flag


def test_no_focus_point_leaves_everything_fully_simulated():
    """Headless tests and the editor have no player: the safe answer is full
    simulation, never a silently skipped world."""
    far = _Actor(1_000_000, 0)
    wi = WorldIndex()
    wi.rebuild([far], None)
    assert wi.tier_of(far) == TIER_NEAR


def test_tier_boundaries_have_hysteresis_so_a_loiterer_does_not_flap():
    a = _Actor(TIER_NEAR_RADIUS * 0.5, 0)
    wi = WorldIndex()
    wi.rebuild([a], (0.0, 0.0))
    assert wi.tier_of(a) == TIER_NEAR
    # Just outside the near radius, but inside the hysteresis band: stays NEAR.
    a.pos[0] = TIER_NEAR_RADIUS * (1.0 + TIER_HYSTERESIS * 0.5)
    wi.rebuild([a], (0.0, 0.0))
    assert wi.tier_of(a) == TIER_NEAR
    # Past the band: demoted.
    a.pos[0] = TIER_NEAR_RADIUS * (1.0 + TIER_HYSTERESIS * 2.0)
    wi.rebuild([a], (0.0, 0.0))
    assert wi.tier_of(a) == TIER_ACTIVE


def test_promotion_needs_no_hysteresis():
    """Walking *toward* the player must upgrade immediately — a late promotion
    is an actor that visibly stops simulating while on screen."""
    a = _Actor(TIER_ACTIVE_RADIUS * 3, 0)
    wi = WorldIndex()
    wi.rebuild([a], (0.0, 0.0))
    assert wi.tier_of(a) == TIER_DISTANT
    a.pos[0] = TIER_NEAR_RADIUS - 1.0
    wi.rebuild([a], (0.0, 0.0))
    assert wi.tier_of(a) == TIER_NEAR


# --- radius queries --------------------------------------------------------

def _brute(actors, x, z, r):
    return {i for i, a in enumerate(actors)
            if (a.pos[0] - x) ** 2 + (a.pos[2] - z) ** 2 <= r * r}


def test_radius_queries_match_a_brute_force_scan_on_a_small_world():
    rng = np.random.default_rng(7)
    actors = [_Actor(*rng.uniform(-2000, 2000, 2)) for _ in range(BIN_THRESHOLD // 2)]
    wi = _index(actors)
    for r in (100.0, 512.0, 1500.0):
        assert set(wi.rows_near(0.0, 0.0, r).tolist()) == _brute(actors, 0, 0, r)


def test_radius_queries_match_a_brute_force_scan_once_binning_kicks_in():
    rng = np.random.default_rng(11)
    actors = [_Actor(*rng.uniform(-8000, 8000, 2)) for _ in range(BIN_THRESHOLD * 8)]
    wi = _index(actors)
    wi.rows_near(0.0, 0.0, 1.0)          # bins are built on first query
    assert wi._bins, "a world this size should be binned"
    for (x, z, r) in ((0.0, 0.0, 700.0), (3333.0, -1234.0, 2048.0), (-6000.0, 6000.0, 300.0)):
        assert set(wi.rows_near(x, z, r).tolist()) == _brute(actors, x, z, r)


def test_nearest_respects_the_mask_and_excludes_the_asker():
    me = _Actor(0, 0)
    friend = _Actor(100, 0, team="villagers")
    foe = _Actor(300, 0, team="bandits")
    wi = _index([me, friend, foe])
    bandits = np.asarray([t == "bandits" for t in
                          (a.properties["team"] for a in [me, friend, foe])])
    row = wi.nearest(0.0, 0.0, 5000.0, mask=bandits, exclude_row=wi.row_of(me))
    assert wi.actors[row] is foe
    # No candidate in range -> -1, not an exception and not a wrong answer.
    assert wi.nearest(0.0, 0.0, 50.0, mask=bandits, exclude_row=wi.row_of(me)) == -1


def test_a_kill_resolved_mid_tick_stops_being_targetable_this_tick():
    a, b = _Actor(0, 0), _Actor(50, 0)
    wi = _index([a, b])
    assert wi.alive[wi.row_of(b)]
    wi.mark_dead(b)
    assert not wi.alive[wi.row_of(b)]
    assert wi.dead[wi.row_of(b)]


def test_team_relations_are_resolved_once_per_distinct_team():
    """The collapse that took faction lookups off the profile: the predicate is
    asked once per team name in the world, not once per actor pair."""
    actors = [_Actor(i, 0, team=("bandits" if i % 2 else "villagers"))
              for i in range(200)]
    wi = _index(actors)
    calls = []

    def rel(name):
        calls.append(name)
        return 1 if name == "bandits" else 0

    table = wi.team_relation_table(rel)
    assert len(calls) == len(set(calls)) == 2      # two distinct teams, two calls
    assert table[wi.team_ids[wi.row_of(actors[1])]] == 1
    assert table[wi.team_ids[wi.row_of(actors[0])]] == 0


def test_rebuilding_reuses_its_buffers_instead_of_reallocating():
    actors = [_Actor(i * 10, 0) for i in range(300)]
    wi = _index(actors)
    px = wi.px
    for _ in range(5):
        wi.rebuild(actors, (0.0, 0.0))
    assert wi.px is px, "a steady-state tick must not reallocate the buffers"


def test_derived_arrays_are_memoised_per_rebuild():
    actors = [_Actor(i, 0) for i in range(10)]
    wi = _index(actors)
    built = []

    def build():
        built.append(1)
        return np.ones(wi.n, dtype=bool)

    wi.derived("k", build)
    wi.derived("k", build)
    assert len(built) == 1
    wi.rebuild(actors, (0.0, 0.0))
    wi.derived("k", build)
    assert len(built) == 2, "a rebuild must drop last tick's derived data"


# --- the shared grid convention -------------------------------------------

def test_every_system_addresses_the_same_512_unit_cells():
    """One grid, imported — not four modules agreeing by comment."""
    from engine import cells as engine_cells
    from engine import world_cells
    from engine.physics import SpatialGrid
    from engine.logic_thread import CULL_CELL_SIZE
    from engine.world_index import CELL_SIZE as index_cell

    assert (engine_cells.CELL_SIZE == index_cell
            == world_cells.CELL_SIZE == CULL_CELL_SIZE)
    assert SpatialGrid().cell_size == engine_cells.CELL_SIZE
    assert world_cells.cell_of_point is engine_cells.cell_of_point
    for x, z in ((0.0, 0.0), (511.9, -0.1), (-1.0, 1024.0), (5000.0, -5000.0)):
        expect = (int(math.floor(x / 512.0)), int(math.floor(z / 512.0)))
        assert engine_cells.cell_of_point(x, z) == expect
