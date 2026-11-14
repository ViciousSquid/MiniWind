"""What the terrain publishes for a renderer: tables all the way to GL.

A renderer never holds the live :class:`engine.terrain.Terrain`. Each frame
the host asks the terrain for a :class:`TerrainFrame` -- an immutable record
of this frame's appearance beside the terrain's dense, versioned stores --
and hands that to the renderer as the ``terrain`` frame input:

* ``table``: the :class:`engine.terrain_table.TerrainTable` (one row per
  resident chunk: height grid, resolution, bounds, ``version``);
* ``products``: :class:`TerrainProducts`, the per-slot CPU arrays that are
  not a height grid (grass blade instances, block-terrace meshes), each
  with a version;
* the paint maps and their versions, by chunk coordinate;
* numbers and flags, copied (colours, gradient, grass settings, modes);
* the regional biome weights (one read-only RGBA array, its version and its
  world bounds) and the actors parting the grass this frame.

Everything a renderer builds from these -- programs, height and paint
texture pages, index and grass buffers -- it owns and frees itself
(``engine/renderer/core/terrain_gl.py``). The terrain's CPU upkeep
(streaming, LOD scheduling, building height grids) happens in
``Terrain.advance``, before the frame is drawn and not inside it.

No OpenGL, Qt or glm here.
"""

from __future__ import annotations

import itertools
import math
import threading
from types import MappingProxyType

import numpy as np

_KEYS = itertools.count(1)


def new_publication_key() -> int:
    """A token naming one terrain's publications for as long as it lives; a
    renderer keeps its GL state for a terrain under it."""
    return next(_KEYS)


class TerrainProducts:
    """Per-slot CPU arrays published beside the height grids.

    ``grass[slot]`` and ``blocks[slot]`` are ``(version, slot_order, data)``:
    *version* is unique to that build (a renderer uploads when the one it
    holds differs), *slot_order* is the table's allocation counter of the row
    it was built for (a reused slot never shows the previous chunk's), *data*
    a read-only float32 array. Written by the terrain (GUI thread), read by
    the renderer in the same thread's paint; the lock covers a tool reading
    from another thread.
    """

    __slots__ = ('grass', 'blocks', 'lock', '_versions')

    def __init__(self):
        self.grass = {}
        self.blocks = {}
        self.lock = threading.Lock()
        self._versions = itertools.count(1)

    def put(self, store, slot, slot_order, data):
        data = np.ascontiguousarray(data, dtype=np.float32)
        data.flags.writeable = False
        with self.lock:
            store[int(slot)] = (next(self._versions), int(slot_order), data)

    def drop(self, slots):
        with self.lock:
            for slot in slots:
                self.grass.pop(int(slot), None)
                self.blocks.pop(int(slot), None)

    def drop_grass(self, slots):
        """Give back the grass of *slots* (chunks far out of view); their
        block meshes stay. A renderer frees the buffers it built for them
        when it next sees the store without them."""
        with self.lock:
            for slot in slots:
                self.grass.pop(int(slot), None)

    def clear_store(self, store):
        with self.lock:
            store.clear()


class TerrainFrame:
    """One frame's published terrain. Immutable: set once, by the terrain."""

    __slots__ = (
        'key', 'enabled', 'table', 'products',
        'flat_mode', 'wireframe', 'use_textures', 'blocks',
        'appearance', 'gradient', 'tiling',
        'grass_enabled', 'grass_color', 'grass_tip_colour', 'grass_match_ground',
        'grass_tip_auto', 'grass_height', 'grass_lod_start', 'grass_lod_distance',
        'grass_fade_start', 'grass_max_distance', 'grass_segments',
        'grass_blade_width',
        'paint_display', 'paint_maps', 'paint_versions', 'paint_epoch', 'paint_resolution',
        # Mip chains made on the builder thread: chunk -> (the paint array
        # it was made from, [level arrays]), and the chunks whose chain is
        # being made (a renderer waits for those rather than making one).
        'paint_chains', 'paint_chains_pending',
        'paint_page_layers', 'height_page_layers', 'max_gradient_stops',
        'triangle_count',
        # Regional biomes (engine/terrain_biomes.py): the RGBA weights a
        # renderer uploads as one texture (read-only uint8 HxWx4, or None),
        # the version naming that array, and where it lies in the world as
        # (min x, min z, 1 / range x, 1 / range z).
        'biome_map', 'biome_version', 'biome_bounds',
        # Actors parting the grass this frame: read-only float32 (n, 4) rows
        # of (x, z, radius, strength), n <= MAX_GRASS_PUSHERS, or None.
        'grass_pushers',
        '_sealed',
    )

    #: Fields a frame may leave out (a renderer reads them as None).
    _OPTIONAL = ('biome_map', 'biome_version', 'biome_bounds', 'grass_pushers',
                 'paint_chains', 'paint_chains_pending')

    def __init__(self, **fields):
        for name in self._OPTIONAL:
            fields.setdefault(name, None)
        for name, value in fields.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, '_sealed', True)

    def __setattr__(self, name, value):
        raise AttributeError("a TerrainFrame is immutable (%s)" % name)

    def __delattr__(self, name):
        raise AttributeError("a TerrainFrame is immutable (%s)" % name)


def read_only(mapping):
    """A read-only view of a published dictionary."""
    return MappingProxyType(mapping)


def heightfield_indices(res: int) -> np.ndarray:
    """The index list one heightfield chunk of *res* quads a side is drawn
    with (``terrain_indexed.vert``): ``6 * res * res`` indices over two
    layers of the ``(res + 1)^2`` grid points.

    Quads in the order the unindexed draw used (``q = ix * res + iz``), each
    as its two triangles with the same corners and winding, rotated so that
    the last index -- the provoking vertex -- is the one that carries the
    triangle's flat normal and colour: the layer-0 point (ix, iz) for the
    first, the layer-1 point (ix + 1, iz + 1) for the second.
    """
    side = res + 1
    ix, iz = np.meshgrid(np.arange(res, dtype=np.uint32),
                         np.arange(res, dtype=np.uint32), indexing='ij')
    ix, iz = ix.ravel(), iz.ravel()

    def point(i, k, layer=0):
        return layer * side * side + i * side + k

    # terrain.vert: (a, b, c) = (ix,iz) (ix+1,iz) (ix,iz+1), then
    #               (a, b, c) = (ix+1,iz) (ix+1,iz+1) (ix,iz+1).
    quads = np.stack([
        point(ix + 1, iz), point(ix, iz + 1), point(ix, iz),            # b c a
        point(ix, iz + 1), point(ix + 1, iz), point(ix + 1, iz + 1, 1),  # c a b
    ], axis=1)
    return np.ascontiguousarray(quads.ravel(), dtype=np.uint32)


#: Most grass pushers a frame publishes (``uPushers`` in ``grass.vert``).
MAX_GRASS_PUSHERS = 32


def grass_vertex_count(segments: int) -> int:
    """Vertices per blade instance: (segments - 1) quads plus the tip."""
    return (max(1, int(segments)) - 1) * 6 + 3


def frustum_planes(view_projection):
    """Six normalised planes ``(a, b, c, d)`` of a view-projection matrix
    (column-major, ``m[col][row]``); a point is inside when
    ``a*x + b*y + c*z + d >= 0`` for each. The planes
    ``TerrainTable.visible`` takes, as the renderer derives its own."""
    m = tuple(tuple(view_projection[col]) for col in range(4))

    def norm(a, b, c, d):
        length = math.sqrt(a * a + b * b + c * c)
        if length < 1e-8:
            return (0.0, 0.0, 0.0, 0.0)
        return (a / length, b / length, c / length, d / length)

    return tuple(
        norm(m[0][3] + sign * m[0][row], m[1][3] + sign * m[1][row],
             m[2][3] + sign * m[2][row], m[3][3] + sign * m[3][row])
        for row in range(3) for sign in (1.0, -1.0))


# ---------------------------------------------------------------------------
# Paint mip chains: pure NumPy, made on the terrain's builder thread for the
# chunks streaming in, and by a renderer for any other.
# ---------------------------------------------------------------------------

#: Side of a paint page's smallest mip level. Enough levels that paint in the
#: distance does not shimmer; few enough that a chunk's edge texels are not
#: averaged far into its neighbour's missing ones. (Three levels at 256 a
#: chunk, four at 512.)
PAINT_MIP_FLOOR = 32

#: Side of the tiles :func:`paint_mip` skips when they hold no paint.
PAINT_MIP_TILE = 32


def paint_mip_levels(side: int) -> int:
    """Mip levels a paint page of *side* texels has beyond the first."""
    side = int(side)
    if side <= PAINT_MIP_FLOOR:
        return 0
    return int(round(math.log2(side / float(PAINT_MIP_FLOOR))))


def _paint_mip_block(paint):
    """:func:`paint_mip` of a block of paint with even sides."""
    alpha = paint[..., 3].astype(np.uint32)
    weighted = paint[..., :3].astype(np.uint32) * alpha[..., None]
    weight = alpha[0::2, 0::2] + alpha[1::2, 0::2] + alpha[0::2, 1::2] + alpha[1::2, 1::2]
    colour = (weighted[0::2, 0::2] + weighted[1::2, 0::2]
              + weighted[0::2, 1::2] + weighted[1::2, 1::2])
    out = np.zeros(weight.shape + (4,), dtype=np.uint8)
    some = weight > 0
    w = weight[some][:, None]
    out[..., :3][some] = ((colour[some] + (w >> 1)) // w).astype(np.uint8)
    out[..., 3] = ((weight + 2) >> 2).astype(np.uint8)
    return out


def paint_mip(paint):
    """*paint* (n, n, 4 uint8) at half the side, colour weighted by alpha
    (an unpainted texel is black, and must not darken its neighbours).

    Integer arithmetic, and only the rows of tiles that hold paint (a road
    crosses a fraction of a chunk): the same texels as the float version it
    replaced at a quarter of the time (19.5 against 4.5 ms a 512 chain)."""
    n2 = paint.shape[0]
    out = np.zeros((n2 // 2, n2 // 2, 4), dtype=np.uint8)
    t = min(PAINT_MIP_TILE, n2)
    k = n2 // t
    if k * t != n2:
        return _paint_mip_block(paint[:n2 // 2 * 2, :n2 // 2 * 2])
    alive = paint[..., 3].reshape(k, t, k, t).any(axis=(1, 3))
    rows, cols = np.nonzero(alive)
    for r in np.unique(rows).tolist():
        here = cols[rows == r]
        c0, c1 = int(here.min()) * t, (int(here.max()) + 1) * t
        out[r * t // 2:(r + 1) * t // 2, c0 // 2:c1 // 2] = _paint_mip_block(
            paint[r * t:(r + 1) * t, c0:c1])
    return out


def paint_chain(paint, side):
    """*paint* and its mip levels, each C-contiguous uint8, ready to upload
    (a chunk streaming in, or its paint changing). 4.5 ms for a 512 road
    chunk: see :func:`paint_mip`."""
    data = np.ascontiguousarray(paint, dtype=np.uint8)
    chain = [data]
    for level in range(1, paint_mip_levels(side) + 1):
        if side >> level < 1:
            break
        data = np.ascontiguousarray(paint_mip(data))
        chain.append(data)
    return chain
