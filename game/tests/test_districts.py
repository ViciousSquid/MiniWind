"""The Vale's districts: membership, biomes, several seats, water, the
shader overlay and its agreement with Python, the console and the session."""

import os
from types import SimpleNamespace

import numpy as np
import pytest

from .. import districts as dd


def plain(**extra):
    """Two districts either side of x = 0, no warp, no biome pull."""
    content = {"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0, "edge_margin": 0.0,
               "border": {"cell": 20.0, "smoothing": 2},
               "districts": [{"id": "west", "seat": [-500, 0]},
                             {"id": "east", "seat": [500, 0]}]}
    content.update(extra)
    return dd.Districts(content)


# -- the shipped districts -----------------------------------------------------------
def test_the_shipped_districts_load_and_cover_the_world():
    found = dd.load()
    ids = [d.id for d in found.districts]
    assert len(ids) == len(set(ids)) == 8
    assert all(d.biome in dd.BIOMES for d in found.districts)
    assert len(found.get("cairnmoor").seats) == 2          # Cairnmoor took in Whisperdeep
    assert found.get("whisperdeep") is None
    assert found.fits({"seed": 53092}) and not found.fits({"seed": 1}) and not found.fits(None)
    x0, z0, x1, z1 = found.bounds
    xs, zs = np.meshgrid(np.linspace(x0, x1, 40), np.linspace(z0, z1, 40))
    idx = found.index_at(xs, zs)
    assert set(np.unique(idx)) == set(range(len(ids)))     # every district has land


def test_every_district_holds_its_chief_seat():
    found = dd.load()
    for i, d in enumerate(found.districts):
        for seat in d.seats:
            assert found.at(*seat) is d, d.id


# -- membership ---------------------------------------------------------------------------
def test_the_nearest_seat_wins_without_warp_or_biomes():
    found = plain()
    assert found.at(-10, 300).id == "west" and found.at(10, -300).id == "east"


def test_the_warp_moves_borders_but_keeps_them_continuous():
    found = plain(warp=200.0, warp_scale=400.0)
    xs = np.linspace(-1000, 1000, 400)
    flips = [np.count_nonzero(np.diff(found.index_at(xs, np.full_like(xs, z))))
             for z in np.linspace(-900, 900, 30)]
    assert all(f >= 1 for f in flips)
    straight = plain()
    bent = [abs(float(xs[np.argmax(found.index_at(xs, np.full_like(xs, z)))])) for z in
            np.linspace(-900, 900, 30)]
    assert max(bent) > 20.0                       # it wanders off the straight line
    assert straight.at(0.01, 0).id == "east"


def test_a_district_keeps_to_its_biome():
    def weights(xs, zs):              # desert east of x = 300
        out = np.zeros((len(xs), 4))
        out[:, 0] = (np.asarray(xs) > 300).astype(float)
        return out
    content = {"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 2000.0,
               "districts": [{"id": "green", "biome": "lowland", "seat": [-500, 0]},
                             {"id": "sand", "biome": "desert", "seat": [500, 0]}]}
    found = dd.Districts(content, biome_weights=weights)
    assert found.at(200, 0).id == "green"        # nearer the desert seat, but green ground
    assert found.at(320, 0).id == "sand"
    assert dd.Districts(content).at(200, 0).id == "sand"   # without biomes, distance alone


def test_seats_of_one_district_have_no_border_between_them():
    content = {"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0, "edge_margin": 0.0,
               "border": {"cell": 20.0},
               "districts": [{"id": "split", "seats": [[-600, 0], [600, 0]]},
                             {"id": "middle", "seat": [0, 700]}]}
    found = dd.Districts(content)
    assert found.at(-600, 0).id == found.at(600, 0).id == "split"
    for line in found.border_lines():
        for x, z in line:
            assert z > 0.0                         # only the border with "middle"


def test_bad_content_is_refused():
    with pytest.raises(ValueError):
        dd.Districts({"districts": []})
    with pytest.raises(ValueError):
        dd.Districts({"districts": [{"id": "a", "seat": [0, 0], "biome": "lava"}]})
    with pytest.raises(ValueError):
        dd.Districts({"districts": [{"id": str(i), "seat": [i, 0]} for i in range(dd.MAX_DISTRICTS + 1)]})


# -- borders as lines -----------------------------------------------------------------------
def test_border_lines_run_along_the_border_smoothed():
    found = plain()
    lines = found.border_lines()
    assert len(lines) == 1
    xs = [x for x, _z in lines[0]]
    assert max(abs(x) for x in xs) <= 20.0
    zs = sorted(z for _x, z in lines[0])
    assert zs[0] <= -980 and zs[-1] >= 980


def test_borders_end_short_of_the_world_s_edge():
    found = plain(edge_margin=300.0, edge_taper=200.0)
    for line in found.border_lines():
        assert min(found.edge_distance(x, z) for x, z in line) >= 300.0
    assert found.edge_fade(0.0, 0.0) == 1.0 and found.edge_fade(0.0, 990.0) == 0.0
    assert 0.0 < float(found.edge_fade(0.0, 1000 - 400.0)) < 1.0
    shipped = dd.load()
    assert shipped.edge_margin >= 5000.0


def test_borders_stop_at_water():
    water = [(-100.0, 200.0, 100.0, 1000.0, 50.0)]           # a sea over z > 200
    found = dd.Districts({"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0, "edge_margin": 0.0,
                          "border": {"cell": 20.0},
                          "districts": [{"id": "w", "seat": [-500, 0]}, {"id": "e", "seat": [500, 0]}]},
                         water=water, height=lambda xs, zs: np.zeros(len(xs)))
    for line in found.border_lines():
        assert all(z <= 205.0 for _x, z in line)
    assert found.under_water(0.0, 500.0, 10.0) and not found.under_water(0.0, 500.0, 60.0)
    assert not found.under_water(0.0, 0.0, 10.0)


def test_water_boxes_come_from_water_brushes_largest_first():
    brushes = [{"pos": [0, 0, 0], "size": [10, 10, 10], "textures": {"top": "stone"}},
               {"pos": [5, 40, 5], "size": [100, 20, 100], "is_water": True},
               {"pos": [0, 40, 0], "size": [1000, 20, 1000], "is_water": True}]
    from engine.constants import is_water_brush
    if not is_water_brush(brushes[1]):
        pytest.skip("this engine marks water another way")
    boxes = dd.water_boxes(brushes)
    assert boxes[0] == (-500.0, -500.0, 500.0, 500.0, 50.0) and len(boxes) == 2


# -- drawn by hand, baked into the paint ---------------------------------------------
class PaintGrid:
    """Just enough terrain for drawing: the engine's own paint calls."""
    from engine.terrain import Terrain as _T
    TERRAIN_PAINT_RESOLUTION = 64
    chunk_size = 512.0
    offset_x = offset_z = 0.0
    blend_paint = _T.blend_paint
    set_paint_texels = _T.set_paint_texels
    restore_paint = _T.restore_paint

    def __init__(self):
        self.texture_paint_maps = {}
        self.touched = set()

    def _paint_changed_grass(self, keys):
        pass

    def _touch_texture_paint(self, coord):
        self.touched.add(tuple(coord))


def small(**extra):
    content = {"bounds": [-1024, -1024, 1024, 1024], "warp": 0.0, "biome_bias": 0.0, "edge_margin": 0.0,
               "border": {"cell": 16.0, "width": 30.0},
               "districts": [{"id": "w", "seat": [-500, 0]}, {"id": "e", "seat": [500, 0]}]}
    content.update(extra)
    return dd.Districts(content)


def test_ink_is_a_line_with_rough_edges_and_a_second_stroke():
    zs = np.linspace(-3000, 3000, 600)
    ds = np.linspace(-dd.REACH, dd.REACH, 211)
    Z, D = np.meshgrid(zs, ds, indexing="ij")
    amount = dd.ink(np.zeros_like(Z), Z, D)
    strongest = amount.max(axis=1)
    assert (strongest > 0.15).mean() > 0.9           # a line all the way along ...
    assert strongest.std() > 0.05                    # ... darker and lighter as the pen goes
    where = np.abs(D[np.arange(len(zs)), amount.argmax(axis=1)])
    assert where.max() > 20.0                        # it wobbles off the true border
    assert dd.ink(0.0, 0.0, dd.REACH + 50) == 0.0    # and never strays past its reach


def test_the_bake_inks_the_border_and_lifts_it_exactly():
    grid = PaintGrid()
    road = np.zeros((64, 64, 4), np.uint8)
    road[:, 30:34] = (120, 110, 90, 255)            # a road already there
    grid.texture_paint_maps[(-1, 0)] = road.copy()
    found = small()
    drawing = found.bake(grid)
    inked = set(drawing.under)
    assert inked and all(abs(cx * 512 + 256) <= 768 for cx, _cz in inked)   # along x = 0
    assert grid.texture_paint_maps[(-1, 0)][:, 30:34, 3].min() == 255      # the road stays
    drawing.lift(grid)
    assert np.array_equal(grid.texture_paint_maps[(-1, 0)], road)
    assert set(grid.texture_paint_maps) == {(-1, 0)}                        # nothing left behind
    drawing.lay(grid)
    again = {k: v.copy() for k, v in grid.texture_paint_maps.items()}
    drawing.lift(grid)
    drawing.lay(grid)
    assert all(np.array_equal(again[k], grid.texture_paint_maps[k]) for k in again)


def test_the_drawing_is_kept_beside_the_map_and_read_back(tmp_path):
    grid = PaintGrid()
    drawing = small().bake(grid)
    path = dd.record_path(str(tmp_path / "world.json"))
    assert path.endswith("world.districts.npz")
    drawing.save(path)
    back = dd.Drawing.load(path, 64)
    assert back.laid and set(back.under) == set(drawing.under)
    back.lift(grid)
    assert grid.texture_paint_maps == {}
    assert dd.Drawing.load(str(tmp_path / "none.npz"), 64) is None
    with pytest.raises(ValueError):
        dd.Drawing(drawing.alphas, (0, 0, 0)).lay(type("G", (PaintGrid,), {"TERRAIN_PAINT_RESOLUTION": 32})())


def test_borders_skip_the_water():
    grid = PaintGrid()
    found = small(border={"cell": 16.0, "width": 30.0})
    found.water = [(-300.0, 0.0, 300.0, 1024.0, 50.0)]
    found.height = lambda xs, zs: np.zeros(len(xs))
    drawing = found.bake(grid)
    for (cx, cz), alpha in drawing.alphas.items():
        rows = np.nonzero(alpha.any(axis=0))[0]
        zs = cz * 512 + (rows + 0.5) * 8
        assert (zs < 8.0).all(), (cx, cz)


def test_the_shipped_world_has_its_borders_baked_and_recorded():
    found = dd.load()
    assert found.map == "maps/miniwind_world.json"
    record = dd.record_path(found.map)
    assert os.path.isfile(record)
    drawing = dd.Drawing.load(record, 512)
    assert drawing is not None and len(drawing.under) > 50


# -- the session, the host, the console ------------------------------------------------------
def _session(on=True):
    from ..runtime import MiniwindSession
    s = MiniwindSession.__new__(MiniwindSession)
    s.logic = object()
    s.districts = dd.load()
    s._district_borders = on
    s._district_drawing = None
    s._district_lifted = False
    s._player_pos = lambda: (500.0, 0.0, 600.0)
    return s


def test_shown_borders_cost_nothing_and_hiding_lifts_them_once(monkeypatch):
    from .. import runtime
    grid = PaintGrid()
    s = _session(True)
    s.districts = small()
    s._district_drawing = s.districts.bake(grid)
    painted = {k: v.copy() for k, v in grid.texture_paint_maps.items()}
    monkeypatch.setattr(runtime.fio, "terrain", lambda logic: grid)
    grid.touched.clear()
    s.set_district_borders(True)                 # already shown: nothing at all
    assert not grid.touched
    s.set_district_borders(False)
    assert s._district_lifted and grid.texture_paint_maps == {}
    s.set_district_borders(False)                # twice: still once
    s._restore_district_borders()                # the session ends: the map's paint again
    assert not s._district_lifted
    assert all(np.array_equal(painted[k], grid.texture_paint_maps[k]) for k in painted)
    assert s.district_at((1000.0, 0.0, 1500.0)).id == "e"


def test_the_console_reports_districts_and_toggles_borders(monkeypatch):
    from .. import console
    lines = []
    monkeypatch.setattr(console, "debug_log", lambda category, message: lines.append(message))
    s = _session(True)
    toggled = []
    s.set_district_borders = toggled.append
    ctx = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=s), play_mode=True)
    console.cmd_districts(ctx, "")
    assert "you are in Millbrook" in lines[0] and any("Cairnmoor" in l for l in lines)
    console.cmd_districts(ctx, "off")
    assert toggled == [False]
    console.cmd_districts(console.ConsoleContext(), "")
    assert "Play Mode only" in lines[-1]


def test_the_editor_keeps_the_ink_out_of_view_but_in_every_save(tmp_path, monkeypatch):
    from .. import district_editor
    grid = PaintGrid()
    grid._serialize_texture_paint = lambda: {k: v.copy() for k, v in grid.texture_paint_maps.items()}
    found = small()
    found.map = str(tmp_path / "world.json")
    drawing = found.bake(grid)                     # the map as its file has it: inked
    drawing.save(dd.record_path(found.map))
    inked = {k: v.copy() for k, v in grid.texture_paint_maps.items()}
    monkeypatch.setattr(dd, "load", lambda *a, **k: found)
    state = SimpleNamespace(terrain_data={"seed": 1, "texture_paint": inked}, level_data_hooks=[])
    editor = district_editor.EditorBorders()
    editor.level_loaded(state, grid, play_mode=False)
    assert not editor.drawing.is_laid(grid) and grid.texture_paint_maps == {}
    assert state.terrain_data["seed"] == 1 and "texture_paint" not in state.terrain_data
    level = {"terrain_data": dict(state.terrain_data)}
    for hook in state.level_data_hooks:
        hook(level)                                 # a save: the ink is in what is written
    saved = level["terrain_data"]["texture_paint"]
    assert set(saved) == set(inked) and all(np.array_equal(saved[k], inked[k]) for k in inked)
    assert grid.texture_paint_maps == {}            # and still out of view
    editor.play_start()
    assert editor.drawing.is_laid(grid)
    editor.play_start()                             # twice: inked once
    assert all(np.array_equal(grid.texture_paint_maps[k], inked[k]) for k in inked)
    editor.play_stop()
    assert grid.texture_paint_maps == {}
