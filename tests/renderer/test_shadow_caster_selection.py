"""Shadow selection and invalidation, independent of a GL driver."""

from types import SimpleNamespace

import numpy as np

from engine.render_cull import shadow_casters_in_reach


def caster_table():
    return SimpleNamespace(
        center=np.array([[0., 0., 0.], [5000., 0., 0.]]),
        half=np.full((2, 3), 50.), rot=np.zeros((2, 4)),
        geo_epoch=np.array([1, 1], dtype=np.int64), generation=1)


def selection(table):
    return shadow_casters_in_reach(table, np.array([0, 1], dtype=np.int32),
                                   0., 0., 0., 500.)


def test_an_unchanged_shadow_scene_reuses_its_cache_key():
    table = caster_table()
    slots, first = selection(table)
    again, second = selection(table)
    np.testing.assert_array_equal(slots, [0])
    np.testing.assert_array_equal(again, slots)
    assert first == second


def test_reshaping_a_caster_without_changing_its_box_invalidates_the_shadow():
    table = caster_table()
    _, first = selection(table)
    # A convex edit changes its planes/epoch while its world extents stay put.
    table.geo_epoch[0] += 1
    _, changed = selection(table)
    assert changed != first


def test_reusing_a_slot_for_new_geometry_invalidates_the_shadow():
    table = caster_table()
    _, first = selection(table)
    # A replacement may start with the same local epoch and transform.
    table.generation += 1
    _, changed = selection(table)
    assert changed != first


def test_reshaping_an_out_of_range_brush_keeps_the_shadow_cached():
    table = caster_table()
    _, first = selection(table)
    table.geo_epoch[1] += 1
    _, unchanged = selection(table)
    assert unchanged == first


def test_a_light_touching_a_box_corner_keeps_the_caster():
    table = caster_table()
    table.center[0] = (100, 0, 100)
    table.half[0] = (80, 1, 80)
    slots, _ = shadow_casters_in_reach(table, np.array([0], dtype=np.int32),
                                      0., 0., 0., 30.)
    # Its nearest corner is sqrt(20**2 + 20**2) < 30 from the light.
    np.testing.assert_array_equal(slots, [0])


def test_the_caster_bound_encloses_rotated_box_corners():
    table = caster_table()
    table.half[0] = (80, 20, 50)
    table.rot[0] = (0, 1, 0, 45)
    angle = np.deg2rad(45)
    rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                         [-np.sin(angle), 0, np.cos(angle)]])
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                corner = rotation @ (table.half[0] * (x, y, z))
                light = corner + corner / np.linalg.norm(corner) * 5
                slots, _ = shadow_casters_in_reach(
                    table, np.array([0], dtype=np.int32), *light, 10.)
                np.testing.assert_array_equal(slots, [0])


def test_a_caster_wholly_outside_the_light_bound_is_still_culled():
    table = caster_table()
    table.center[0] = (200, 0, 200)
    slots, signature = shadow_casters_in_reach(table, np.array([0], dtype=np.int32),
                                              0., 0., 0., 30.)
    assert not len(slots)
    assert signature == ()
