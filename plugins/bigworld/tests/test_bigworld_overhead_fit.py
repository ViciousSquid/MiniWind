"""Fit-to-overhead-camera: residency and tiers sized from what is on screen.

With ``fit_overhead_camera`` on and an overhead camera, residency is a circle
just past the screen's corners, NEAR is the screen's rectangle (in cells), and
both follow the player's own movement instead of waiting for a cell crossing.
A host reads ``sim_tiers_fit_view`` to know that ACTIVE now means off screen.
"""

from engine.spatial import TIER_ACTIVE, TIER_NEAR, tier_of
from engine.view_distance import ViewDistance
from plugins.bigworld.config import config_from_properties
from plugins.bigworld.runtime import BigWorldSession
from plugins.bigworld.tiers import TierClassifier

from .test_bigworld_tiers import FakePlayer, FakeThing, grid_world


class OverheadLogic:
    """A streaming host whose overhead camera shows +/- (hx, hz) of ground."""

    def __init__(self, things, footprint=(1400.0, 800.0), at=(0.0, 0.0)):
        self.brushes = []
        self.things = things
        self.player = FakePlayer(*at)
        self.view_distance = ViewDistance()
        self.footprint = footprint
        self.overhead_height = 800.0

    def overhead_ground_footprint(self):
        return self.footprint


def fitted_session(things, **kw):
    logic = OverheadLogic(things, **kw)
    session = BigWorldSession(logic, activation_radius=2048.0,
                              deactivation_radius=2304.0, sim_near_radius=1024.0,
                              fit_overhead_camera=True)
    session.start()
    return logic, session


def test_the_settings_default_off():
    cfg = config_from_properties({})
    assert cfg["fit_overhead_camera"] is False
    assert cfg["terrain_stream"] is False


def test_residency_is_sized_from_the_screen_not_the_authored_radius():
    logic, session = fitted_session(grid_world(), footprint=(900.0, 500.0))
    corner = (900.0 ** 2 + 500.0 ** 2) ** 0.5
    act = session.manager.activation_radius
    # Past the corners by the refresh distance, and well inside the authored 2048.
    assert corner + session.FIT_REFRESH <= act < corner + session.FIT_REFRESH + session.FIT_QUANTUM
    assert act < 2048.0
    assert session.manager.deactivation_radius > act
    assert logic.sim_tiers_fit_view is True
    # The camera's far plane follows residency.
    assert logic.view_distance.limit is not None


def test_near_is_the_screen_rectangle_and_the_rest_resident_is_active():
    logic, session = fitted_session(grid_world(cells_each_way=8), footprint=(1400.0, 500.0))
    rx, rz = session.tiers.near_rect
    assert rx > rz
    near = [t for t in logic.things if tier_of(t) == TIER_NEAR]
    active = [t for t in logic.things if tier_of(t) == TIER_ACTIVE]
    assert near and active
    cell = session.manager.cell_size
    # NEAR: in a cell meeting the rectangle. ACTIVE: outside it on some axis.
    for t in near:
        assert abs(t.pos[0]) <= rx + cell and abs(t.pos[2]) <= rz + cell
    assert all(abs(t.pos[2]) > rz or abs(t.pos[0]) > rx for t in active)


def test_tiers_follow_the_player_between_cell_crossings():
    logic, session = fitted_session(grid_world(cells_each_way=8), footprint=(600.0, 400.0))
    before = session._tier_pos
    # Inside the same 512 cell, but past the re-tier step.
    logic.player.pos[0] += session.FIT_RETIER + 10.0
    session.tick()
    assert session._tier_pos != before


def test_without_an_overhead_camera_the_authored_radii_stand():
    logic, session = fitted_session(grid_world(), footprint=None)
    assert session.manager.activation_radius >= 2048.0
    assert session.tiers.near_rect is None
    assert not getattr(logic, "sim_tiers_fit_view", False)


def test_off_by_default_the_session_ignores_the_camera():
    logic = OverheadLogic(grid_world())
    session = BigWorldSession(logic, activation_radius=2048.0,
                              deactivation_radius=2304.0, sim_near_radius=1024.0)
    session.start()
    assert session.manager.activation_radius >= 2048.0
    assert session.tiers.near_rect is None


def test_the_classifier_rectangle_is_per_cell():
    class Manager:
        cell_size = 512.0

        def __init__(self, coords):
            self.active_cells = set(coords)
            self.cells = {}

    coords = [(x, z) for x in range(-4, 4) for z in range(-4, 4)]
    tiers = TierClassifier(near_radius=1024.0, active_radius=4096.0)
    tiers.set_near_rect((700.0, 100.0))
    tiers.update(Manager(coords), 256.0, 256.0)
    near = {c for c in coords if tiers.cell_tier(c) == TIER_NEAR}
    # The box spans x -444..956 and z 156..356: cells -1, 0 and 1 across,
    # only the player's row down.
    assert {z for _, z in near} == {0}
    assert {x for x, _ in near} == {-1, 0, 1}


def test_terrain_streams_inside_its_own_bounds():
    class Terrain:
        chunk_size = 2048.0
        min_chunk_x, max_chunk_x, min_chunk_z, max_chunk_z = -20, 19, -20, 19
        streaming = False
        stream_radius = 1536.0
        stream_evict_padding = 512.0

        def set_streaming(self, on, radius=None):
            self.streaming = on
            if radius:
                self.stream_radius = radius

        def set_bounds(self, *a, **k):
            raise AssertionError("terrain_stream must not re-bound the terrain")

    logic = OverheadLogic([FakeThing(0, 0)])
    logic.terrain = Terrain()
    session = BigWorldSession(logic, terrain_stream=True)
    session.start()
    assert logic.terrain.streaming is True
    assert (logic.terrain.min_chunk_x, logic.terrain.max_chunk_x) == (-20, 19)
    logic.terrain.set_bounds = lambda *a, **k: None     # restore may re-apply
    session.stop()
    assert logic.terrain.streaming is False
