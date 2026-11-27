"""The Trees tool: click the terrain in the 3D view to plant a random tree
brush -- 128 to 512 units square, every side nodraw but the top (a tree
texture fitted to it), floating 100 to 110 above the ground -- each tree one
undo step. It sits beside DECAL in the Asset Browser, with its own icon."""

import os
import random

import pytest

pytestmark = pytest.mark.qt

pytest.importorskip("PyQt5")

from PyQt5.QtCore import QEvent, QPoint, Qt                       # noqa: E402
from PyQt5.QtGui import QMouseEvent                               # noqa: E402

from editor import tree_tool as tt                                # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_a_tree_brush_is_a_thin_square_slab_with_a_tree_on_top():
    rng = random.Random(4)
    for _ in range(200):
        b = tt.tree_brush(100.0, 250.0, -40.0, rng)
        w, h, d = b["size"]
        assert w == d and tt.SIZE_RANGE[0] <= w <= tt.SIZE_RANGE[1] and h == tt.THICKNESS
        underside = b["pos"][1] - h / 2.0
        assert 100.0 <= underside - 250.0 <= 110.0
        assert (b["pos"][0], b["pos"][2]) == (100.0, -40.0)
        tex = b["textures"]
        assert tex["top"] in tt.TREE_TEXTURES
        assert all(tex[side] == "nodraw.jpg" for side in ("north", "south", "east", "west", "down"))
        assert b["uv_scale"]["top"] == [1.0, 1.0]            # the image fitted to the top
        assert b["uv_angle"]["top"] in (0.0, 90.0, 180.0, 270.0)
    ids = {tt.tree_brush(0, 0, 0, rng)["id"] for _ in range(20)}
    assert len(ids) == 20


def test_every_tree_texture_ships():
    for name in tt.TREE_TEXTURES:
        assert os.path.isfile(os.path.join(ROOT, "assets", "textures", name)), name



def press(tool, x, y):
    return tool.press(QMouseEvent(QEvent.MouseButtonPress, QPoint(x, y), Qt.LeftButton,
                                  Qt.LeftButton, Qt.NoModifier))


@pytest.fixture
def trees(main_window, monkeypatch):
    main_window.state.clear_scene()
    tool = main_window.view_3d.tree_tool
    ground = {}
    monkeypatch.setattr(tool, "ground_at", lambda mx, my: ground.get((mx, my)))
    tool.ground = ground
    main_window.toggle_tree_tool(True)
    yield tool
    tool.set_active(False)


@pytest.mark.qt
def test_clicking_the_terrain_plants_a_tree_and_undo_removes_it(main_window, trees):
    assert trees.active and main_window.tree_tool_action.isChecked()
    assert main_window.asset_browser.tab_textures.trees_btn.isChecked()
    before = len(main_window.state.brushes)
    trees.ground[(20, 30)] = (512.0, 300.0, -256.0)
    press(trees, 20, 30)
    press(trees, 20, 30)
    assert len(main_window.state.brushes) == before + 2
    planted = main_window.state.brushes[-1]
    assert planted["textures"]["top"] in tt.TREE_TEXTURES
    assert 400.0 <= planted["pos"][1] <= 420.0
    main_window.undo()
    assert len(main_window.state.brushes) == before + 1          # one tree per undo step
    main_window.undo()
    assert len(main_window.state.brushes) == before
    main_window.redo()
    assert len(main_window.state.brushes) == before + 1


@pytest.mark.qt
def test_a_click_off_the_terrain_plants_nothing(main_window, trees):
    before = len(main_window.state.brushes)
    assert press(trees, 5, 5)                                     # handled, nothing there
    assert len(main_window.state.brushes) == before


@pytest.mark.qt
def test_one_placing_tool_at_a_time_and_escape_leaves(main_window, trees):
    main_window.toggle_decal_tool(True)
    assert main_window.view_3d.decal_tool.active and not trees.active
    assert not main_window.asset_browser.tab_textures.trees_btn.isChecked()
    main_window.toggle_tree_tool(True)
    assert trees.active and not main_window.view_3d.decal_tool.active
    trees.escape()
    assert not trees.active and not main_window.tree_tool_action.isChecked()


@pytest.mark.qt
def test_the_trees_button_sits_beside_decal_with_its_icon(main_window):
    tab = main_window.asset_browser.tab_textures
    button = tab.trees_btn
    assert not button.icon().isNull()
    assert button.size() == tab.decal_btn.size()
    layout = tab.decal_btn.parentWidget().layout()
    assert button.parentWidget() is tab.decal_btn.parentWidget()
    button.click()
    assert main_window.view_3d.tree_tool.active
    button.click()
    assert not main_window.view_3d.tree_tool.active
    assert layout is not None
