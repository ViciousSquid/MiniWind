"""Editor visibility must not leave holes in a streamed terrain.

These tests exercise the real dense residency table without needing OpenGL.
The preview horizon is per-frame state, not a map or gameplay setting.
"""

import pytest

glm = pytest.importorskip("glm")

from engine.terrain import Terrain
from engine.terrain_table import TerrainTable


def _terrain():
    # Streaming is CPU-only; avoid constructing GL programs for this test.
    terrain = Terrain.__new__(Terrain)
    terrain.table = TerrainTable()
    terrain.chunk_size = 256.0
    terrain.offset_x = terrain.offset_z = 0.0
    terrain.min_chunk_x = terrain.min_chunk_z = -100
    terrain.max_chunk_x = terrain.max_chunk_z = 100
    terrain.stream_radius = 2048.0
    terrain.stream_evict_padding = 512.0
    terrain.editor_stream_horizon = 0.0
    terrain.streamed_chunks = 0
    terrain._free_gl = lambda slots: None
    return terrain


def test_editor_horizon_fills_visible_ground_beyond_activation_radius():
    terrain = _terrain()
    # Editor has the stock 4096-unit view while Big World streams at 2048.
    terrain.editor_stream_horizon = 4096.0
    terrain._stream_chunks(glm.vec3(0.0, 0.0, 0.0))

    assert (12, 0) in terrain.table.slot_of_coord  # starts at x=3072
    assert terrain.stream_radius == 2048.0  # the authored setting is untouched

    # Play clears the preview floor: the normal stream + eviction ring returns.
    terrain.editor_stream_horizon = 0.0
    terrain._stream_chunks(glm.vec3(0.0, 0.0, 0.0))
    assert (12, 0) not in terrain.table.slot_of_coord
    assert (0, 0) in terrain.table.slot_of_coord
    assert terrain.stream_radius == 2048.0


def test_editor_horizon_does_not_shrink_explicit_large_stream_radius():
    terrain = _terrain()
    terrain.stream_radius = 4600.0
    terrain.editor_stream_horizon = 1000.0
    terrain._stream_chunks(glm.vec3(0.0, 0.0, 0.0))
    assert (14, 0) in terrain.table.slot_of_coord  # x=3584
