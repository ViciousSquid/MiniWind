"""
The engine's one cell-grid convention.

Fio partitions the XZ plane into fixed 512-unit columns, addressed by integer
``(cell_x, cell_z)`` and indexed as ``floor(coord / cell_size)``. Four systems
depend on that convention agreeing exactly:

* :class:`engine.physics.SpatialGrid` — collision and ray queries;
* :class:`engine.world_index.WorldIndex` — actor relevance and simulation LOD;
* :class:`~engine.logic_thread.LogicThread`'s render-state cull — which brushes
  the camera's region can reach;
* :class:`engine.world_cells.WorldCellIndex` — which cells are streamed in.

They used to agree by *comment* — each restated the rule and the constant in its
own module, and a change to one would have silently desynchronised the others.
This module is the single definition they all import, so a cell means the same
patch of ground to every one of them.

Deliberately stdlib-only (no NumPy, no glm, no Qt): the streaming plugin, the
headless player and the editor all import it, and none of them should have to
pull a dependency in to ask which cell a point is in.
"""

from __future__ import annotations

import math
from typing import List, Tuple

#: Cell edge length in world units.
CELL_SIZE = 512.0

#: A cell coordinate: ``(cell_x, cell_z)`` integers.
CellCoord = Tuple[int, int]


def cell_of_point(x: float, z: float, cell_size: float = CELL_SIZE) -> CellCoord:
    """The integer cell containing world point ``(x, z)``."""
    inv = 1.0 / cell_size
    return (int(math.floor(x * inv)), int(math.floor(z * inv)))


def cells_for_aabb(min_x: float, min_z: float, max_x: float, max_z: float,
                   cell_size: float = CELL_SIZE) -> List[CellCoord]:
    """Every cell an XZ axis-aligned box overlaps (inclusive of both edges)."""
    cx0, cz0 = cell_of_point(min_x, min_z, cell_size)
    cx1, cz1 = cell_of_point(max_x, max_z, cell_size)
    return [(cx, cz)
            for cx in range(cx0, cx1 + 1)
            for cz in range(cz0, cz1 + 1)]


def cell_bounds(cell_x: int, cell_z: int, cell_size: float = CELL_SIZE):
    """``(min_x, min_z, max_x, max_z)`` of a cell in world units."""
    min_x = cell_x * cell_size
    min_z = cell_z * cell_size
    return (min_x, min_z, min_x + cell_size, min_z + cell_size)


def cell_distance_sq(cell_x: int, cell_z: int, px: float, pz: float,
                     cell_size: float = CELL_SIZE) -> float:
    """Squared XZ distance from ``(px, pz)`` to the nearest point of a cell.

    Zero when the point is inside the cell. Squared so callers compare against a
    squared radius and never take a square root in a hot loop.
    """
    min_x, min_z, max_x, max_z = cell_bounds(cell_x, cell_z, cell_size)
    dx = 0.0
    if px < min_x:
        dx = min_x - px
    elif px > max_x:
        dx = px - max_x
    dz = 0.0
    if pz < min_z:
        dz = min_z - pz
    elif pz > max_z:
        dz = pz - max_z
    return dx * dx + dz * dz
