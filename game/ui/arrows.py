"""
Arrows in flight, drawn as arrows.

Fio draws every projectile as one shared billboard -- a green orb, its monster
spit -- so a loosed arrow was a small orb crossing the screen in a fraction of
a second. The game takes its arrows out of that pass (``fio.set_projectile_
split``, see ``MiniwindSession._split_projectiles``) and draws each here, in
the 3D pass (Fio's ``render.post_scene`` hook): the ammo's own art, lying flat
for the top-down camera, its head pointing along the arrow's flight.

A loosed arrow leaves a trail: a dark red dotted line behind it, from the
bow to where the arrow is, ending at whatever it hit. Each dot fades out over
:data:`PATH_FADE_SECONDS` from the moment the arrow passed it, so the tail
dissolves first (:func:`draw_paths`; the traces are kept by
``MiniwindSession.trace_arrow``).
"""

from __future__ import annotations

import math
import os
import time

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


# --------------------------------------------------------------- flight paths
#: How long each dot of an arrow's trail takes to fade, from the moment the
#: arrow passed it (seconds).
PATH_FADE_SECONDS = 2.0
#: World distance between the dots, and each dot's size.
PATH_DOT_SPACING = 28.0
PATH_DOT_SIZE = 9.0
#: The dots' colour (dark red) and their opacity when fresh: faint, a hint
#: of the flight rather than a solid line.
PATH_COLOUR = (120, 8, 8)
PATH_ALPHA = 0.3
#: Most paths kept at once (a volley of arrows).
MAX_PATHS = 48


def path_dots(start, end, spacing=PATH_DOT_SPACING):
    """Points every *spacing* along the line from *start* to *end*."""
    dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    n = max(1, int(length // spacing))
    return [(start[0] + dx * i / n, start[1] + dy * i / n, start[2] + dz * i / n)
            for i in range(n + 1)]


_dot_texture = 0


def _dot(renderer) -> int:
    """A small round dark red dot texture, built on first use."""
    global _dot_texture
    if _dot_texture:
        return _dot_texture
    try:
        import numpy as np
        import OpenGL.GL as gl
        n = 16
        yy, xx = np.mgrid[0:n, 0:n]
        r = np.hypot(xx - (n - 1) / 2.0, yy - (n - 1) / 2.0)
        data = np.zeros((n, n, 4), dtype=np.uint8)
        data[..., 0], data[..., 1], data[..., 2] = PATH_COLOUR
        data[..., 3] = np.clip((n / 2.0 - r) * 255.0, 0, 255).astype(np.uint8)
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, n, n, 0, gl.GL_RGBA,
                        gl.GL_UNSIGNED_BYTE, data)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        _dot_texture = int(tex)
    except Exception:
        _dot_texture = 0
    return _dot_texture


def draw_paths(projection, view, paths, now=None) -> int:
    """Draw each arrow's trail (``(start, end, loosed_at, reached_at)``) as
    dark red dots, each faded by how long ago the arrow passed it; returns
    how many trails were drawn."""
    if not paths:
        return 0
    renderer = _arrow_renderer()
    if not renderer._ready():
        return 0
    tex = _dot(renderer)
    if not tex:
        return 0
    now = time.perf_counter() if now is None else now
    drawn = 0
    for start, end, loosed, reached in paths:
        if now - reached >= PATH_FADE_SECONDS:
            continue
        dots = path_dots(start, end)
        last = max(1, len(dots) - 1)
        for i, dot in enumerate(dots):
            # The arrow flies at a steady speed: it passed dot i at this time.
            passed = loosed + (reached - loosed) * (i / last)
            age = max(0.0, now - passed)
            if age >= PATH_FADE_SECONDS:
                continue
            opacity = PATH_ALPHA * (1.0 - age / PATH_FADE_SECONDS)
            renderer._draw_texture(projection, view, dot, 0.0, tex, PATH_DOT_SIZE,
                                   0.0, depth_write=False, opacity=opacity)
        drawn += 1
    return drawn
