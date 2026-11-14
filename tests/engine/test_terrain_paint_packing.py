"""Terrain paint is kept packed away from the camera.

Every painted chunk is a 512x512 RGBA array (1 MB); the shipped overworld has
107 of them. Packed as a map saves them (each chunk's zlib stream) they are a
few MB, so a chunk's paint is kept unpacked only while its chunk is resident:
it is packed at load, unpacked on the builder thread as its chunk streams in
and dropped as it leaves. Readers see the same arrays as ever.
"""

import threading
import time

import glm
import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="stamp textures are loaded with QImage")
pytestmark = pytest.mark.qt

from engine.terrain import Terrain, _PackedPaint              # noqa: E402

FAR = (3, 3)


@pytest.fixture
def texture(tmp_path):
    from PyQt5.QtGui import QColor, QImage
    image = QImage(16, 16, QImage.Format_RGBA8888)
    image.fill(QColor(120, 110, 90, 255))
    path = str(tmp_path / "path.png")
    assert image.save(path)
    return path


@pytest.fixture
def painted(texture):
    """A saved terrain painted in chunk (0, 0) and in far chunk FAR."""
    terrain = Terrain(seed=4)
    terrain.set_bounds(-4, 4, -4, 4)
    cs = terrain.chunk_size
    terrain.add_paint_stamp(cs * 0.5, cs * 0.5, cs * 0.2, texture)
    terrain.add_paint_stamp(cs * (FAR[0] + 0.5), cs * (FAR[1] + 0.5), cs * 0.2, texture)
    data = terrain.to_dict()
    arrays = {key: np.array(paint) for key, paint in terrain.texture_paint_maps.items()}
    return data, arrays


@pytest.fixture
def made():
    terrains = []

    def make(background=True):
        terrain = Terrain(seed=4)
        terrain.BACKGROUND_BUILDS = background
        terrains.append(terrain)
        return terrain
    yield make
    for terrain in terrains:
        terrain.cleanup()
    assert not [t for t in threading.enumerate() if t.name == 'TerrainBuilder']


def test_loaded_paint_is_packed_and_reads_back_the_same(painted, made):
    data, arrays = painted
    terrain = made()
    terrain.from_dict(data)
    stored = dict.items(terrain.texture_paint_maps)
    assert {key for key, _ in stored} == set(arrays)
    assert all(type(value) is _PackedPaint and value.array is None for _, value in stored)
    for key, original in arrays.items():
        paint = terrain.texture_paint_maps.get(key)
        assert np.array_equal(paint, original)
        assert not paint.flags.writeable            # never written in place
    # Saved again it is the same paint, byte for byte, never recompressed.
    assert terrain.to_dict()['texture_paint'] == data['texture_paint']


def test_only_resident_chunks_are_kept_unpacked(painted, made):
    data, arrays = painted
    terrain = made()
    terrain.from_dict(data)
    terrain.set_streaming(True, radius=terrain.chunk_size)
    camera = glm.vec3(terrain.chunk_size * 0.5, 0.0, terrain.chunk_size * 0.5)
    near = dict.get(terrain.texture_paint_maps, (0, 0))
    far = dict.get(terrain.texture_paint_maps, FAR)
    deadline = time.time() + 10.0
    while near.array is None and time.time() < deadline:
        terrain.advance(camera)                     # unpacked on the builder thread
        time.sleep(0.005)
    assert near.array is not None and np.array_equal(near.array, arrays[(0, 0)])
    assert far.array is None
    # Walking away: the near chunk leaves and its array goes with it.
    away = glm.vec3(terrain.chunk_size * (FAR[0] + 0.5), 0.0, terrain.chunk_size * (FAR[1] + 0.5))
    deadline = time.time() + 10.0
    while near.array is not None and time.time() < deadline:
        terrain.advance(away)
        time.sleep(0.005)
    assert near.array is None
    assert np.array_equal(terrain.texture_paint_maps[(0, 0)], arrays[(0, 0)])


def test_a_bake_made_while_packing_is_never_undone(painted, made, texture):
    data, _arrays = painted
    terrain = made(background=False)
    terrain.from_dict(data)
    cs = terrain.chunk_size
    terrain.add_paint_stamp(cs * 0.5, cs * 0.5, cs * 0.3, texture)   # (0, 0) baked: an array
    fresh = terrain._paint_to_pack(frozenset())
    baked = dict(fresh)[(0, 0)]
    packed = [(key, array, b'stale', None) for key, array in fresh]
    terrain.add_paint_stamp(cs * 0.4, cs * 0.4, cs * 0.3, texture)   # baked again meanwhile
    newer = dict.get(terrain.texture_paint_maps, (0, 0))
    assert newer is not baked
    terrain._store_packed(packed)
    assert dict.get(terrain.texture_paint_maps, (0, 0)) is newer


def test_resident_paint_gets_its_mip_chain_from_the_builder(painted, made):
    """A renderer only uploads: the chain of each resident chunk's paint is
    made on the builder thread, published with the array it was made from,
    and while it is being made the frame says so (the renderer waits)."""
    from engine.terrain_frame import paint_chain
    data, arrays = painted
    terrain = made()
    terrain.from_dict(data)
    terrain.set_streaming(True, radius=terrain.chunk_size)
    callers = []
    import engine.terrain as terrain_module
    real = terrain_module.paint_chain
    terrain_module.paint_chain = lambda *a: callers.append(threading.current_thread().name) or real(*a)
    try:
        camera = glm.vec3(terrain.chunk_size * 0.5, 0.0, terrain.chunk_size * 0.5)
        terrain.advance(camera)
        assert (0, 0) in terrain.publish().paint_chains_pending
        deadline = time.time() + 10.0
        while (0, 0) not in terrain._paint_chains and time.time() < deadline:
            terrain.advance(camera)
            time.sleep(0.005)
    finally:
        terrain_module.paint_chain = real
    frame = terrain.publish()
    array, chain = frame.paint_chains[(0, 0)]
    assert array is terrain.texture_paint_maps[(0, 0)]
    expected = paint_chain(arrays[(0, 0)], terrain.TERRAIN_PAINT_RESOLUTION)
    assert len(chain) == len(expected)
    assert all(np.array_equal(a, b) for a, b in zip(chain, expected))
    assert (0, 0) not in frame.paint_chains_pending
    assert set(callers) == {'TerrainBuilder'}
    assert FAR not in frame.paint_chains
