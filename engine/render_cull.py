"""
MiniWind camera render-distance cull — the pure, GL-free geometry of it.

The renderer's main camera pass runs this cheap broad-phase cull *before*
``_sort_objects`` (and on top of the frustum cull it already does): any object
whose centre lies farther than :data:`CAMERA_RENDER_CULL_DISTANCE` world units
from the camera on the XZ plane is dropped. Distances are compared squared, so
no square root runs per object.

The logic lives here, apart from :mod:`engine.renderer_F`, for two reasons: it
carries no OpenGL/glm/Qt dependency, so it is unit-testable headlessly; and it
keeps the renderer's per-frame path a thin call over a persistent scratch buffer
(no per-frame list allocation). The shadow and portal passes deliberately do not
call this — they keep operating on the full scene.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence

#: Hard outer limit (world units) on the XZ plane, measured from the camera
#: centre. This is a *ceiling*, not the working radius: the actual relevant
#: region is derived from the live camera by :func:`visible_xz_bounds`, which
#: for MiniWind's top-down view is several times tighter. The ceiling still
#: matters — it bounds a first-person view whose frustum runs to the far plane.
CAMERA_RENDER_CULL_DISTANCE = 4096.0
#: Precomputed squared radius — the value the per-object test actually compares.
CAMERA_RENDER_CULL_DISTANCE_SQ = CAMERA_RENDER_CULL_DISTANCE * CAMERA_RENDER_CULL_DISTANCE

#: How far above and below the world's geometry the visible slab is extended,
#: so a tall billboard, a floating light or a jumping actor at the very top or
#: bottom of the world is never clipped out of the relevant region.
WORLD_SLAB_MARGIN = 512.0


def visible_xz_bounds(cam, corners, y_min, y_max, max_dist=CAMERA_RENDER_CULL_DISTANCE):
    """The XZ box the camera can actually see, given the world's height slab.

    MiniWind's camera looks straight down from a few hundred units. Its frustum
    is therefore a narrow cone that leaves the world's vertical slab almost
    immediately — the ground it covers is a box a couple of thousand units
    across, not the tens of thousands a far plane at 10,000 would suggest. A
    fixed radius cannot express that: it is either too loose overhead (drawing
    and simulating a ring of world nobody can see) or too tight in first person.

    So the region is derived from the live camera instead. *corners* are the
    four far-plane corner points in world space; each is clipped as a segment
    from *cam*, first to ``max_dist`` and then to the slab
    ``[y_min, y_max]`` the world's geometry occupies. The XZ bounds of what
    survives is the answer, plus the camera's own XZ when it sits inside the
    slab (so nothing directly beneath a first-person camera is ever dropped).

    Returns ``(min_x, min_z, max_x, max_z)``. Conservative by construction: it
    is the bounding box of the visible volume, never smaller than it.

    Pure arithmetic — no glm, no GL — so it is unit-testable headlessly.
    """
    cx, cy, cz = float(cam[0]), float(cam[1]), float(cam[2])
    lo_y = min(y_min, y_max) - WORLD_SLAB_MARGIN
    hi_y = max(y_min, y_max) + WORLD_SLAB_MARGIN

    min_x = max_x = cx
    min_z = max_z = cz
    seeded = lo_y <= cy <= hi_y
    if not seeded:
        min_x = min_z = float("inf")
        max_x = max_z = float("-inf")

    for corner in corners:
        dx = float(corner[0]) - cx
        dy = float(corner[1]) - cy
        dz = float(corner[2]) - cz
        # Clip the ray's length to the hard ceiling first.
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        t_far = 1.0 if length <= max_dist or length == 0.0 else max_dist / length
        t0, t1 = 0.0, t_far
        # Then to the world's height slab.
        if abs(dy) < 1e-9:
            if not (lo_y <= cy <= hi_y):
                continue                      # parallel to the slab and outside it
        else:
            ta = (lo_y - cy) / dy
            tb = (hi_y - cy) / dy
            if ta > tb:
                ta, tb = tb, ta
            t0 = max(t0, ta)
            t1 = min(t1, tb)
            if t0 > t1:
                continue                      # the segment never enters the slab
        for t in (t0, t1):
            x = cx + dx * t
            z = cz + dz * t
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if z < min_z:
                min_z = z
            if z > max_z:
                max_z = z

    if min_x > max_x:
        # Nothing in the slab is visible at all: degenerate to the camera point
        # rather than returning an inverted box a caller would misread.
        return (cx, cz, cx, cz)
    return (min_x, min_z, max_x, max_z)


def pos_of(obj):
    """The ``[x, y, z]`` of a brush dict or a Thing-like object, or ``None``."""
    if isinstance(obj, dict):
        return obj.get("pos")
    return getattr(obj, "pos", None)


def within_xz_sq(pos, cx: float, cz: float, limit_sq: float) -> bool:
    """Whether *pos* is within a squared XZ distance *limit_sq* of (cx, cz)."""
    dx = pos[0] - cx
    dz = pos[2] - cz
    return dx * dx + dz * dz <= limit_sq


def camera_xz(camera_pos):
    """(x, z) of the camera centre, accepting a glm vec or any ``[x, y, z]``."""
    if hasattr(camera_pos, "x"):
        return float(camera_pos.x), float(camera_pos.z)
    return float(camera_pos[0]), float(camera_pos[2])


def cull_by_distance(objects: Sequence, cx: float, cz: float,
                     limit_sq: float = CAMERA_RENDER_CULL_DISTANCE_SQ,
                     out: Optional[List] = None,
                     keep: Optional[Callable[[object], bool]] = None) -> List:
    """Return the subset of *objects* within *limit_sq* XZ of (cx, cz).

    Fills and returns *out* when given (cleared first), so a caller can reuse one
    persistent buffer across frames and allocate nothing; otherwise a fresh list
    is returned. An object for which *keep* returns True — or that has no readable
    position — is retained unconditionally (fail-open: never wrongly hide it)."""
    if out is None:
        out = []
    else:
        del out[:]
    for obj in objects:
        if keep is not None and keep(obj):
            out.append(obj)
            continue
        pos = pos_of(obj)
        if pos is None or within_xz_sq(pos, cx, cz, limit_sq):
            out.append(obj)
    return out
