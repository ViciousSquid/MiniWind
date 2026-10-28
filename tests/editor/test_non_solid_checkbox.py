"""Brush collision can be switched from the property editor and undone."""

import pytest

pytest.importorskip("PyQt5")

from engine.physics import SpatialGrid
from tests.helpers.worlds import box_brush

pytestmark = pytest.mark.qt


def _panel(host, **props):
    brush = box_brush("decoration", **props)
    host.state.brushes = [brush]
    host.set_selected_objects([brush])
    host.property_editor.set_object(brush, force=True)
    return brush, host.property_editor._widgets['non_solid_cb']


@pytest.mark.parametrize("props, checked", [
    ({}, False), ({'no_collision': False}, False), ({'no_collision': True}, True),
])
def test_non_solid_checkbox_shows_saved_state_without_changing_it(main_window,
                                                                props, checked):
    brush, checkbox = _panel(main_window, **props)
    assert checkbox.text() == "Non solid"
    assert checkbox.isChecked() == checked
    assert ('no_collision' in brush) == ('no_collision' in props)


def test_non_solid_changes_live_collision_and_supports_undo_redo(main_window):
    host = main_window
    brush, checkbox = _panel(host)
    logic = host.view_3d.logic_thread
    grid = SpatialGrid()
    logic.session_runtime.spatial_grid = grid
    grid.populate(host.state.brushes)
    assert grid.raycast_down(0., 0., 100.) == 32.

    checkbox.setChecked(True)
    logic.collision_runtime.rebuild_if_dirty()
    assert brush['no_collision'] is True
    assert not brush.get('hidden', False)
    assert grid.raycast_down(0., 0., 100.) is None
    assert host.unsaved_changes

    host.undo()
    assert not host.state.brushes[0].get('no_collision', False)
    assert not host.property_editor._widgets['non_solid_cb'].isChecked()
    host.redo()
    assert host.state.brushes[0]['no_collision'] is True
    checkbox = host.property_editor._widgets['non_solid_cb']
    assert checkbox.isChecked()

    checkbox.setChecked(False)
    logic.collision_runtime.rebuild_if_dirty()
    assert host.state.brushes[0]['no_collision'] is False
    assert grid.raycast_down(0., 0., 100.) == 32.
