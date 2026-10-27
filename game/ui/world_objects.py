"""
Containers and things lying about, drawn as the top-down camera sees them.

A container or an item pickup is an ordinary entity to Fio: in Play it draws
nothing for it (only actors, props and models are drawn), so a chest could be
opened that could not be seen. They are drawn here instead, in the 3D pass
(Fio's ``render.pre_sprites`` hook: after the world, before the effects and
actors, so every actor goes over them), as flat quads lying on the floor
they stand on:

* a **container** in its top-down art (``assets/sprites/miniwind/topdown/
  <kind>.png``, game/tools/make_container_art.py), turned by its ``angle``
  (degrees; an unturned one gets a steady turn of its own from its id, a
  chest square to the world);
* an **item pickup** in its item's icon (game/item_icons.py) -- a book, a
  note, a sword dropped on the floor.

They lie on the floor itself, layered over the blood and under the actors
by depth (engine/overhead_sprite.py's ground stack -- never lifted toward
the camera), so walls hide them and anyone walking past covers them. Only
those near the player are drawn.
"""

from __future__ import annotations

import math
import os
import zlib

from engine.overhead_sprite import ACTOR_Y, GIB_Y

from .. import fio

TOPDOWN_DIR = os.path.join("assets", "sprites", "miniwind", "topdown")
#: How far from the player things are drawn (world units).
DRAW_RADIUS = 3200.0
#: Their layers in the ground stack (depth, not height): containers under the
#: actors, pickups under those.
CONTAINER_Y = GIB_Y + 10.0
PICKUP_Y = GIB_Y + 4.0
#: The quad each container kind is drawn on (its art fills part of it).
CONTAINER_SIZE = {"chest": 150.0, "barrel": 118.0, "crate": 140.0, "sack": 124.0,
                  "urn": 112.0}
PICKUP_SIZE = 64.0

assert CONTAINER_Y < ACTOR_Y


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def container_art(kind) -> str:
    """The top-down art for a container *kind* (the chest's when unknown)."""
    root = _repo_root()
    path = os.path.join(root, TOPDOWN_DIR, f"{kind}.png")
    return path if os.path.isfile(path) else os.path.join(root, TOPDOWN_DIR, "chest.png")


def turn_of(props, square=False) -> float:
    """How the thing is turned (radians): its ``angle``, or a steady one of
    its own from its id -- a quarter turn for something *square* to the world."""
    angle = props.get("angle")
    if angle is not None:
        try:
            return math.radians(float(angle))
        except (TypeError, ValueError):
            pass
    h = zlib.crc32(str(props.get("id") or props.get("name") or "").encode("utf-8"))
    if square:
        return (h % 4) * math.pi / 2.0
    return (h % 3600) / 3600.0 * math.tau


def floor_of(logic, thing, reach=0.0) -> float:
    """The floor *thing* rests on, found once per place it stands: the highest
    ground under its footprint (its centre and four points *reach* out), as a
    crate sits on a slope -- so no corner of it is buried in the terrain."""
    p = thing.properties
    x, y, z = float(thing.pos[0]), float(thing.pos[1]), float(thing.pos[2])
    cached = p.get("_floor_at")
    if cached and cached[0] == round(x) and cached[1] == round(z):
        return cached[2]
    found = []
    for dx, dz in ((0.0, 0.0), (reach, 0.0), (-reach, 0.0), (0.0, reach), (0.0, -reach)):
        g = fio.ground_height(logic, x + dx, z + dz, below=y + 40.0)
        if g is not None:
            found.append(float(g))
    floor = max(found) if found else y
    p["_floor_at"] = (round(x), round(z), floor)
    return floor


def _hidden(p) -> bool:
    return bool(p.get("dead") or p.get("hidden") or p.get("_bw_parked_hidden"))


def visible(session):
    """``[(pos, turn, image, size, layer)]`` for every container and pickup
    near the player, containers first."""
    ppos = session._player_pos() if hasattr(session, "_player_pos") else None
    if ppos is None:
        return []
    logic = getattr(session, "logic", None)
    r2 = DRAW_RADIUS * DRAW_RADIUS
    out = []
    from .. import item_icons
    for kind in ("container", "itempickup"):
        for t in session._things_of_type(kind):
            p = t.properties
            if _hidden(p):
                continue
            dx, dz = float(t.pos[0]) - ppos[0], float(t.pos[2]) - ppos[2]
            if dx * dx + dz * dz > r2:
                continue
            if kind == "container":
                ck = str(p.get("container_kind") or "chest")
                floor = floor_of(logic, t, CONTAINER_SIZE.get(ck, 130.0) * 0.35)
                out.append(((t.pos[0], floor, t.pos[2]),
                            turn_of(p, square=ck in ("chest", "crate")),
                            container_art(ck), CONTAINER_SIZE.get(ck, 130.0), CONTAINER_Y))
            else:
                floor = floor_of(logic, t, PICKUP_SIZE * 0.35)
                icon = item_icons.icon_path(p.get("item_id"), p.get("_stack"))
                if icon:
                    out.append(((t.pos[0], floor, t.pos[2]), turn_of(p), icon,
                                PICKUP_SIZE, PICKUP_Y))
    return out


_renderer = None


def _object_renderer():
    """One sprite renderer for every object, built on first use (GL context)."""
    global _renderer
    if _renderer is None:
        from engine.overhead_sprite import OverheadSpriteRenderer

        class _ObjectRenderer(OverheadSpriteRenderer):
            def texture(self, path):
                tex = self._textures.get(path)
                if tex is None:
                    tex = self._textures[path] = self._load_texture(path)
                return tex

        _renderer = _ObjectRenderer(frame_files={}, size=1.0, y_offset=0.0)
    return _renderer


def draw(projection, view, objects) -> int:
    """Draw *objects* (from :func:`visible`) flat on the floor; returns how
    many were drawn."""
    if not objects:
        return 0
    renderer = _object_renderer()
    if not renderer._ready():
        return 0
    renderer._gl.glEnable(renderer._gl.GL_DEPTH_TEST)
    drawn = 0
    for pos, turn, image, size, layer in objects:
        tex = renderer.texture(image)
        if not tex:
            continue
        renderer._draw_texture(projection, view, pos, turn, tex, size, layer)
        drawn += 1
    return drawn
