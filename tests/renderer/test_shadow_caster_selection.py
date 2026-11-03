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
