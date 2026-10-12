"""
Arrows in flight, drawn as arrows.

Fio draws every projectile as one shared billboard -- a green orb, its monster
spit -- so a loosed arrow was a small orb crossing the screen in a fraction of
a second. The game takes its arrows out of that pass (``fio.set_projectile_
split``, see ``MiniwindSession._split_projectiles``) and draws each here, in
the 3D pass (Fio's ``render.post_scene`` hook): the ammo's own art, lying flat
for the top-down camera, its head pointing along the arrow's flight.
"""

from __future__ import annotations

import math
import os

#: The arrow art: assets/sprites/items/<ammo id>.png, head at the image top.
ARROW_DIR = "assets/sprites/items"
#: Art for an arrow whose ammo has no picture of its own.
DEFAULT_ARROW = f"{ARROW_DIR}/arrow.png"
#: World size of the square the arrow art is drawn on (the shaft is about
#: seven eighths of it).
ARROW_SIZE = 96.0


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def arrow_sprite(ammo_id) -> str:
    """Repo-relative art for an arrow of *ammo_id*: its own, else the plain arrow."""
    name = str(ammo_id or "").strip()
    if name:
        path = f"{ARROW_DIR}/{name}.png"
        if os.path.isfile(os.path.join(_repo_root(), path)):
            return path
    return DEFAULT_ARROW


def heading_of(vel) -> float:
    """The engine heading (forward = (sin h, cos h)) of a velocity."""
    return math.atan2(float(vel[0]), float(vel[2]))


_renderer = None


def _arrow_renderer():
    """One sprite renderer for every arrow, built on first use (GL context)."""
    global _renderer
    if _renderer is None:
        from engine.overhead_sprite import OverheadSpriteRenderer

        class _ArrowRenderer(OverheadSpriteRenderer):
            def texture(self, path):
                tex = self._textures.get(path)
                if tex is None:
                    tex = self._textures[path] = self._load_texture(
                        os.path.join(_repo_root(), path))
                return tex

        _renderer = _ArrowRenderer(frame_files={}, size=ARROW_SIZE, y_offset=0.0)
    return _renderer


def draw_arrows(projection, view, arrows) -> int:
    """Draw *arrows* (``(pos, vel, sprite)`` each); returns how many were drawn."""
    if not arrows:
        return 0
    renderer = _arrow_renderer()
    if not renderer._ready():
        return 0
    drawn = 0
    for pos, vel, sprite in arrows:
        tex = renderer.texture(sprite)
        if not tex:
            continue
        renderer._draw_texture(projection, view, pos, heading_of(vel), tex,
                               ARROW_SIZE, 0.0, depth_write=False)
        drawn += 1
    return drawn
