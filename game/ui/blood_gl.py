"""
Blood on the floor, in the 3D pass.

Blood that comes to rest on the terrain is stamped into it (see
``MiniwindSession._stamp_blood``). Blood on a built floor -- a dungeon, a
house, a bridge -- cannot be, and neither can a pool still spreading or a
splat waiting its turn to be stamped. Those are drawn here, in Fio's
``render.post_scene`` hook, as flat decals of the same stamp art lying on
the floor: depth-tested, at the bottom of the ground stack (a depth layer,
see ``engine.overhead_sprite``), so the actors standing on them and the
weapons in their hands always cover them, whatever their shape or turn.
"""

from __future__ import annotations

from engine.overhead_sprite import DECAL_Y

_renderer = None


def _decal_renderer():
    """One sprite renderer for every splat, built on first use (GL context)."""
    global _renderer
    if _renderer is None:
        from engine.overhead_sprite import OverheadSpriteRenderer

        class _DecalRenderer(OverheadSpriteRenderer):
            def texture(self, path):
                tex = self._textures.get(path)
                if tex is None:
                    tex = self._textures[path] = self._load_texture(path)
                return tex

        _renderer = _DecalRenderer(frame_files={}, size=1.0, y_offset=DECAL_Y)
    return _renderer


def draw_decals(projection, view, decals) -> int:
    """Draw *decals* (``(pos, rot, image, size, opacity)`` each, from
    :meth:`game.gore_fx.GoreFX.floor_decals`); returns how many were drawn."""
    if not decals:
        return 0
    renderer = _decal_renderer()
    if not renderer._ready():
        return 0
    # Under whatever stands on it: the depth test is what keeps blood off the
    # actors, so it must be on whatever the pass before left it as.
    renderer._gl.glEnable(renderer._gl.GL_DEPTH_TEST)
    drawn = 0
    for pos, rot, image, size, opacity in decals:
        tex = renderer.texture(image)
        if not tex:
            continue
        renderer._draw_texture(projection, view, pos, rot, tex, size, DECAL_Y,
                               depth_write=False, opacity=opacity)
        drawn += 1
    return drawn
