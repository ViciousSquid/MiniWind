"""The Trees tool: click the terrain in the 3D view to place a random tree.

A tree is the map's usual tree brush: a thin square slab, every side
``nodraw`` but the top, which carries a tree texture fitted to it (UV scale
1 x 1: one image across the whole face). The tool picks the texture at random
from the tree textures (:data:`TREE_TEXTURES`), a size at random from
:data:`SIZE_RANGE` (128 x 128 to 512 x 512), a quarter-turn of the image at
random, and floats the slab :data:`HEIGHT_RANGE` (100 to 110 units) above the
terrain where you clicked -- so a forest is planted click by click, every
tree a little different.

* **Tools > Trees Tool**, or the Trees button beside DECAL in the Asset
  Browser, turns it on (the Decal tool and terrain sculpting go off: one
  placing tool at a time).
* **Click** the terrain: a tree. Each one is its own undo step (Ctrl+Z).
* **Escape** leaves the tool.
"""

from __future__ import annotations

import random
import uuid

from PyQt5.QtCore import Qt

#: The tree textures (assets/textures), as the map's own trees use them.
TREE_TEXTURES = ("tree01.png", "tree02.png", "tree03.png", "tree04.png",
                 "tree05.png", "tree06.png", "tree07.png", "trees0.png",
                 "deadtree01.png")
#: Width and depth of a tree (world units; square).
SIZE_RANGE = (128.0, 512.0)
#: How far above the terrain the slab's underside floats.
HEIGHT_RANGE = (100.0, 110.0)
#: The slab's thickness, as the map's trees have it.
THICKNESS = 8.0


def tree_brush(x, ground, z, rng=None):
    """A new tree brush (a dict, as the map stores brushes) over the point
    (x, z) of terrain at height *ground*."""
    rng = rng or random
    size = round(rng.uniform(*SIZE_RANGE), 1)
    lift = rng.uniform(*HEIGHT_RANGE)
    sides = [size / 128.0, THICKNESS / 64.0]
    return {
        "pos": [float(x), float(ground) + lift + THICKNESS / 2.0, float(z)],
        "size": [size, THICKNESS, size],
        "textures": {"north": "nodraw.jpg", "south": "nodraw.jpg", "east": "nodraw.jpg",
                     "west": "nodraw.jpg", "top": rng.choice(TREE_TEXTURES),
                     "down": "nodraw.jpg"},
        "uv_scale": {"north": list(sides), "south": list(sides), "east": list(sides),
                     "west": list(sides), "top": [1.0, 1.0],
                     "down": [size / 128.0, size / 128.0]},
        "uv_angle": {"top": float(rng.choice((0.0, 90.0, 180.0, 270.0)))},
        "id": str(uuid.uuid4()),
    }


class TreeTool:
    """Owned by the 3D view; see the module docstring."""

    def __init__(self, view):
        self.view = view
        self.active = False
        self.rng = random.Random()

    @property
    def editor(self):
        return self.view.editor

    def set_active(self, active):
        active = bool(active)
        if active == self.active:
            return
        if active:
            if getattr(self.view, 'terrain_sculpt_active', False):
                self.view.terrain_edit.set_terrain_sculpt_active(False)
            decals = getattr(self.view, 'decal_tool', None)
            if decals is not None:
                decals.set_active(False)          # one placing tool at a time
        self.active = active
        self.view.setCursor(Qt.CrossCursor if active else Qt.ArrowCursor)
        # The Tools menu item and the Asset Browser's Trees button follow.
        action = getattr(self.editor, 'tree_tool_action', None)
        if action is not None and action.isChecked() != active:
            action.blockSignals(True)
            action.setChecked(active)
            action.blockSignals(False)
        browser = getattr(self.editor, 'asset_browser', None)
        textures = getattr(browser, 'tab_textures', None)
        button = getattr(textures, 'trees_btn', None)
        if button is not None and button.isChecked() != active:
            button.blockSignals(True)
            button.setChecked(active)
            button.blockSignals(False)
        if active:
            self.editor.show_toast("Trees: click the terrain to plant a tree (Esc to stop)")
        self.view.update()

    def ground_at(self, mx, my):
        """``(x, ground, z)``: the terrain under the cursor, or None. The
        ray is cast against the terrain itself, so a click over a tree (or
        any brush) plants on the ground beneath it."""
        terrain = getattr(self.editor, 'terrain', None)
        if terrain is None or not getattr(terrain, 'enabled', False):
            return None
        hit = self.view.terrain_edit.raycast_terrain(mx, my)
        if hit is None:
            # Further than the terrain ray reaches: what the view drew there.
            surface = self.view.decal_tool.surface_at(mx, my)
            if surface is None:
                return None
            hit = surface[0]
        x, z = float(hit[0]), float(hit[2])
        ground = terrain.get_height_at_safe(x, z)
        if ground is None:
            return None
        return x, float(ground), z

    def place_at(self, x, ground, z):
        """Plant a random tree over (x, z); one undo step. Returns it."""
        brush = tree_brush(x, ground, z, self.rng)
        self.editor.save_state()
        self.editor.state.brushes.append(brush)
        size = brush["size"][0]
        self.editor.show_toast(f"Tree: {brush['textures']['top']} ({size:.0f} x {size:.0f})")
        self.view.update()
        return brush

    def press(self, event):
        """A left press in the 3D view while the tool is on. Always handled."""
        if event.button() != Qt.LeftButton:
            return False
        hit = self.ground_at(event.x(), event.y())
        if hit is None:
            self.editor.show_toast("Trees: click on the terrain", is_error=True)
            return True
        self.place_at(*hit)
        return True

    def escape(self):
        self.set_active(False)
