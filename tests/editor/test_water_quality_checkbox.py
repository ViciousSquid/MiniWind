"""Water quality is not a per-brush setting any more.

All water is high quality unless the game's graphics setting ([Renderer]
water_quality) says low, so the Property Editor no longer shows a "High
quality" checkbox on water brushes. Old maps' ``water_high_quality`` flags
still load into the render table, unused.
"""

import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

pytest.importorskip("PyQt5", reason="Qt is not available in this environment")

from PyQt5.QtWidgets import QCheckBox  # noqa: E402

from engine import brush_geometry as bg  # noqa: E402

pytestmark = pytest.mark.qt


def water_brush():
    return {
        'pos': [0, 0, 0], 'size': [256, 64, 256], 'name': 'pool', 'id': 'id-pool',
        'textures': {tag: 'water.jpg' for tag in bg.FACE_TAGS},
        'shader': 'Water', 'is_water': True,
    }


def _panel(main_window, **props):
    host = main_window
    editor = host.property_editor
    brush = water_brush()
    brush.update(props)
    host.state.brushes = [brush]
    host.set_selected_objects([brush])
    editor.set_object(brush, force=True)
    return host, editor


def test_there_is_no_per_brush_quality_checkbox(main_window):
    # All water is high quality unless the game's graphics setting says low.
    host, editor = _panel(main_window)
    assert 'water_quality_cb' not in editor._widgets
    assert 'water_plane_cb' in editor._widgets
    texts = [w.text() for w in editor._widgets['water_plane_cb'].parentWidget().findChildren(QCheckBox)]
    assert "High quality" not in texts


def test_the_render_table_reads_the_flag_per_brush():
    from engine.render_table import RenderTable, CLASS_WATER

    hq = water_brush()
    cheap = dict(water_brush(), id='id-cheap', water_high_quality=False)
    table = RenderTable()
    table.begin_frame([hq, cheap])
    assert (table.class_bits[:2] & CLASS_WATER).all()
    assert table.water_high_quality[:2].tolist() == [True, False]
