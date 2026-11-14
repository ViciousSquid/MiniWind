"""A map's terrain paint in its own ``.stamp`` file, the paint resolution
following the chunk size, and the integer paint mip.

The overworld's road paint (ten megabytes) lives in ``<map>.stamp`` beside
the map rather than inside its JSON; everything past the file boundary sees
the level as it always did."""

import json
import os

import numpy as np

from engine import terrain_stamp
from engine.terrain_frame import paint_chain, paint_mip, paint_mip_levels
from engine.terrain import Terrain

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _level():
    return {
        "version": 5, "brushes": [], "things": [],
        "terrain_data": {
            "chunk_size": 2048.0,
            "texture_paint_resolution": 512,
            "texture_paint": [{"coord": [0, 1], "data": "abc"}],
            "texture_paint_base": [{"coord": [0, 1], "data": "base"}],
            "paint_stamps": [{"id": "s1", "texture": "t.png", "x": 1.0, "z": 2.0,
                              "radius": 8.0, "angle": 0.0, "feather": 0.2, "opacity": 1.0}],
        },
    }


def test_a_map_saves_its_paint_beside_it_and_reads_it_back(tmp_path):
    path = str(tmp_path / "world.json")
    level = _level()
    terrain_stamp.write_level(path, level, indent=4)
    on_disk = json.load(open(path, encoding="utf-8"))
    td = on_disk["terrain_data"]
    assert td == {"chunk_size": 2048.0, "paint_file": "world.stamp"}
    assert os.path.isfile(tmp_path / "world.stamp")
    # Read back, the level is as it was saved.
    merged = terrain_stamp.merge_level_paint(on_disk, path)
    assert merged["terrain_data"] == level["terrain_data"]
    # And the level handed in was not changed by saving it.
    assert "texture_paint" in level["terrain_data"]


def test_a_map_without_paint_has_no_stamp_file(tmp_path):
    path = str(tmp_path / "plain.json")
    terrain_stamp.write_level(path, {"brushes": [], "terrain_data": {"enabled": True}})
    assert not os.path.exists(tmp_path / "plain.stamp")
    assert json.load(open(path))["terrain_data"] == {"enabled": True}


def test_an_old_map_with_inline_paint_loads_as_it_was():
    level = _level()
    assert terrain_stamp.merge_level_paint(json.loads(json.dumps(level)), "x.json") == level


def test_a_missing_stamp_file_loads_the_map_without_paint(tmp_path, capsys):
    level = {"terrain_data": {"paint_file": "gone.stamp", "chunk_size": 256.0}}
    out = terrain_stamp.merge_level_paint(level, str(tmp_path / "m.json"))
    assert out["terrain_data"] == {"chunk_size": 256.0}
    assert "could not be read" in capsys.readouterr().out


def test_exporting_stamps_over_a_maps_stamp_file_keeps_its_paint(tmp_path):
    path = str(tmp_path / "world.json")
    terrain_stamp.write_level(path, _level())
    stamp_path = terrain_stamp.map_stamp_path(path)
    terrain = Terrain(seed=1)
    terrain_stamp.save_stamp_file(terrain, stamp_path)
    data = json.load(open(stamp_path))
    assert data["paint"]["chunks"] == [{"coord": [0, 1], "data": "abc"}]
    assert terrain_stamp.load_stamp_file(stamp_path)["version"] == terrain_stamp.STAMP_VERSION


def test_the_overworld_keeps_its_paint_in_its_stamp_file():
    path = os.path.join(ROOT, "maps", "miniwind_world.json")
    with open(path, encoding="utf-8") as fh:
        level = json.load(fh)
    td = level["terrain_data"]
    assert td.get("paint_file") == "miniwind_world.stamp"
    assert not any(k in td for k in terrain_stamp.PAINT_FIELDS)
    terrain_stamp.merge_level_paint(level, path)
    assert level["terrain_data"]["texture_paint_resolution"] == 512
    assert len(level["terrain_data"]["texture_paint"]) > 100


def test_paint_resolution_follows_the_chunk_size():
    assert Terrain.paint_resolution_for(256.0) == 256
    assert Terrain.paint_resolution_for(1024.0) == 256
    assert Terrain.paint_resolution_for(2048.0) == 512        # four units a texel
    assert Terrain.paint_resolution_for(1e6) == Terrain.MAX_PAINT_RESOLUTION
    t = Terrain(seed=1)
    assert t.TERRAIN_PAINT_RESOLUTION == 256
    t.from_dict({"chunk_size": 2048.0})
    assert t.TERRAIN_PAINT_RESOLUTION == 512
    assert t.publish().paint_resolution == 512
    # A page holds what a streamed world keeps resident, not 32 empty layers.
    assert t.paint_page_layers() == 16
    assert Terrain(seed=1).paint_page_layers() == 32


def _float_mip(paint):
    """The float alpha-weighted mip the integer one replaced."""
    n = paint.shape[0] // 2
    blocks = paint[:n * 2, :n * 2].reshape(n, 2, n, 2, 4).astype(np.float32)
    alpha = blocks[..., 3:4]
    weight = alpha.sum(axis=(1, 3))
    colour = (blocks[..., :3] * alpha).sum(axis=(1, 3))
    np.divide(colour, weight, out=colour, where=weight > 0.0)
    out = np.empty((n, n, 4), dtype=np.uint8)
    out[..., :3] = np.clip(colour + 0.5, 0, 255)
    out[..., 3:4] = np.clip(weight * 0.25 + 0.5, 0, 255)
    return out


def test_the_integer_paint_mip_matches_the_float_one():
    rng = np.random.default_rng(7)
    for side in (64, 256, 512):
        paint = np.zeros((side, side, 4), np.uint8)
        yy, xx = np.mgrid[0:side, 0:side]
        road = np.abs(yy - xx * 0.7 - side * 0.1) < side * 0.08
        paint[road] = rng.integers(0, 256, (int(road.sum()), 4))
        paint[road & (rng.random((side, side)) < 0.2), 3] = 0
        paint[paint[..., 3] == 0, :3] = 0
        a = b = paint
        for _ in range(paint_mip_levels(side)):
            a, b = paint_mip(a), _float_mip(b)
            assert np.array_equal(a, b)
    assert paint_mip_levels(256) == 3
    assert paint_mip_levels(512) == 4
    assert len(paint_chain(np.zeros((512, 512, 4), np.uint8), 512)) == 5
