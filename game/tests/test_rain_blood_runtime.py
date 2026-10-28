"""Outdoor rain cleans blood locally without touching roads, shelter or loot."""

from types import SimpleNamespace

import numpy as np
import pytest

from engine.physics import SpatialGrid
from game.gore_fx import RAIN_WASH_SECONDS
from game.runtime import MiniwindSession
from tests.helpers.worlds import box_brush
from .test_cast_controls import _Logic, _Thing
from .test_blood import _flat_terrain


def _session(*actors, roof=False):
    logic = _Logic(actors)
    logic.camera = SimpleNamespace(overhead_ground_footprint=lambda: (200., 200., 300.))
    grid = SpatialGrid()
    grid.populate([box_brush("roof", (0., 220., 0.), (200., 20., 200.))] if roof else [])
    logic.session_runtime = SimpleNamespace(spatial_grid=grid, monster_lock=None)
    terrain = _flat_terrain()
    logic.world_runtime = SimpleNamespace(terrain=terrain)
    session = MiniwindSession(logic, cfg={})
    session.weather.set_weather("storm")
    session.weather.tick(6., 8.)
    return session, terrain


def test_rain_cleans_terrain_blood_and_preserves_authored_paint():
    session, terrain = _session()
    road = np.zeros((2, 2, 4), dtype=np.uint8)
    road[:] = [100, 90, 60, 255]
    terrain._load_texture_rgba = lambda path: road
    terrain.paint_texture_at(10., 10., 30., "road")
    original = terrain.texture_paint_maps[(0, 0)].copy()
    assert session._stamp_blood(dict(x=10., y=100., z=10., size=60., kind="pool"))
    assert terrain.washable_texture_paint_maps
    session._wash_blood(RAIN_WASH_SECONDS)
    assert not terrain.washable_texture_paint_maps
    np.testing.assert_array_equal(terrain.texture_paint_maps[(0, 0)], original)


def test_sheltered_blood_is_protected_on_terrain_and_floor_splats():
    session, terrain = _session(roof=True)
    assert session._stamp_blood(dict(x=10., y=100., z=10., size=60., kind="pool"))
    before = terrain.washable_texture_paint_maps[(0, 0)].copy()
    session.gore._splat((10., 100., 10.), 30.)
    splat = session.gore.splats[0]
    session._wash_blood(RAIN_WASH_SECONDS)
    np.testing.assert_array_equal(terrain.washable_texture_paint_maps[(0, 0)], before)
    assert session.gore.splat_alpha(splat) == 1.


@pytest.mark.parametrize("kind, enabled", [("clear", True), ("snow", True), ("storm", False)])
def test_dry_weather_snow_and_interiors_do_not_wash_blood(kind, enabled):
    session, _ = _session()
    session.weather.set_weather(kind)
    session.weather.tick(6., 8.)
    session.weather_enabled = enabled
    session.gore._splat((0., 100., 0.), 30.)
    splat = session.gore.splats[0]
    session._wash_blood(RAIN_WASH_SECONDS)
    assert session.gore.splat_alpha(splat) == 1.


def test_only_blood_inside_the_camera_area_washes():
    session, _ = _session()
    session.gore._splat((10., 100., 10.), 30.)
    session.gore._splat((2000., 100., 0.), 30.)
    distant = session.gore.splats[-1]
    session._wash_blood(RAIN_WASH_SECONDS)
    assert session.gore.splats == [distant]


def test_physical_gib_stain_fades_but_the_corpse_and_loot_remain():
    body = _Thing("Gib", (0., 156., 0.), type="creature", dead=True,
                  gibbed=True, gib_magical=False, health=0, sprite_height=112,
                  inventory=[{"id": "gold", "qty": 10}], loot_rolled=True)
    session, _ = _session(body)
    session._wash_blood(RAIN_WASH_SECONDS / 2.)
    assert body._respawn_fade_alpha == pytest.approx(.5)
    session._wash_blood(RAIN_WASH_SECONDS / 2.)
    assert body._respawn_fade_alpha == 0.
    assert body.properties['dead'] and body.properties['gibbed']
    assert session.nearest_corpse([0., 0., 0.]) is body
    assert body.properties['inventory'] == [{"id": "gold", "qty": 10}]


def test_restoring_a_washed_corpse_restores_its_visibility_and_debug_revival():
    body = _Thing("Gib", (0., 156., 0.), type="npc", dead=True, gibbed=True,
                  health=0, max_health=40, blood_rain_wash=RAIN_WASH_SECONDS / 2.)
    session, _ = _session(body)
    session._refresh_actor_cache()
    assert body._respawn_fade_alpha == pytest.approx(.5)
    body.properties['gibbed'] = False  # the debug resurrection command clears this
    assert session._revive_actor(body)
    assert body._respawn_fade_alpha == 1.
    assert 'blood_rain_wash' not in body.properties
