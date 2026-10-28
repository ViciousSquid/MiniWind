"""The authored non-solid flag removes a brush from physical world queries."""

from types import SimpleNamespace
import threading

import glm
import numpy as np
import pytest

from engine.logic_collision import LogicCollision
from engine.physics import SpatialGrid
from tests.helpers.worlds import angled_brush, box_brush


@pytest.mark.parametrize("kind", [{}, {"is_mover": True}, {"is_door": True}],
                         ids=["static", "mover", "door"])
def test_non_solid_brushes_allow_actors_and_rays_through(kind):
    brush = box_brush("decoration", no_collision=True, **kind)
    grid = SpatialGrid()
    grid.populate([brush])

    assert grid.get_potential_colliders(glm.vec3(-10), glm.vec3(10)) == []
    assert not grid.overlaps_wall(0., -64., 0., 10.)
    assert not grid.overlaps_wall_batch([0.], [-64.], [0.], 10.)[0]
    assert grid.raycast_down(0., 0., 200.) is None
    assert np.isnan(grid.raycast_down_batch([0.], [0.], [200.])[0])
    for threshold in (0, 1000):
        grid.LOS_DENSE_MIN_CANDIDATES = threshold
        assert grid.has_line_of_sight(glm.vec3(-100, 0, 0), glm.vec3(100, 0, 0))

    brush["no_collision"] = False
    grid.populate([brush])
    assert grid.overlaps_wall(0., -64., 0., 10.)
    assert grid.raycast_down(0., 0., 200.) == 32.
    assert not grid.has_line_of_sight(glm.vec3(-100, 0, 0), glm.vec3(100, 0, 0))


def test_non_solid_water_keeps_its_swimming_volume():
    pool = box_brush("pool", is_water=True, no_collision=True)
    grid = SpatialGrid()
    grid.populate([pool])
    assert grid.water_brushes == [pool]
    assert not grid.overlaps_wall(0., -64., 0., 10.)


def test_marking_an_angled_brush_non_solid_removes_its_collision_mesh():
    brush = angled_brush()
    collision = LogicCollision(SimpleNamespace(editor_state=SimpleNamespace(brushes=[brush])))
    assert collision.prepare_angled_brush_collision() == 1
    assert brush["_collision_mode"] == "mesh"
    brush["no_collision"] = True
    assert collision.prepare_angled_brush_collision() == 0
    assert "_collision_mode" not in brush


def test_live_non_solid_edits_rebuild_angled_collision_on_the_logic_thread():
    brush = angled_brush(no_collision=True)
    grid = SpatialGrid()
    world = SimpleNamespace(
        notify_authored_visibility_changed=lambda: grid.populate([brush]))
    logic = SimpleNamespace(editor_state=SimpleNamespace(brushes=[brush]),
                            session_runtime=SimpleNamespace(monster_lock=threading.RLock()),
                            world_runtime=world)
    collision = LogicCollision(logic)
    grid.populate([brush])
    assert not grid.overlaps_wall(0., -64., 0., 10.)

    brush["no_collision"] = False
    collision.mark_dirty(rebuild_geometry=True)
    # A later ordinary invalidation must preserve the queued geometry rebuild.
    collision.mark_dirty()
    assert "_collision_mode" not in brush
    assert collision.rebuild_if_dirty()
    assert brush["_collision_mode"] == "mesh"
    assert grid.overlaps_wall(0., -64., 0., 10.)
    assert not collision.rebuild_if_dirty()

    brush["no_collision"] = True
    collision.mark_dirty(rebuild_geometry=True)
    assert collision.rebuild_if_dirty()
    assert "_collision_mode" not in brush
    assert not grid.overlaps_wall(0., -64., 0., 10.)
