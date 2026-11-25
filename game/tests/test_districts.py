"""The Vale's districts: membership, biomes, several seats, water, the
shader overlay and its agreement with Python, the console and the session."""

import json
import math
import os
from types import SimpleNamespace

import numpy as np
import pytest

from .. import districts as dd


def plain(**extra):
    """Two districts either side of x = 0, no warp, no biome pull."""
    content = {"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0,
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
    content = {"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0,
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


def test_borders_stop_at_water():
    water = [(-100.0, 200.0, 100.0, 1000.0, 50.0)]           # a sea over z > 200
    found = dd.Districts({"bounds": [-1000, -1000, 1000, 1000], "warp": 0.0, "biome_bias": 0.0,
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


# -- the shader's copy ----------------------------------------------------------------------
def test_the_overlay_carries_seats_districts_biomes_and_water():
    found = dd.load(water=[(0, 0, 10, 10, 5.0)])
    ov = found.overlay()
    assert ov is found.overlay()                              # cached: uploaded once
    assert len(ov["seats"]) == sum(len(d.seats) for d in found.districts)
    assert list(ov["seat_of"]).count(found.districts.index(found.get("cairnmoor"))) == 2
    assert ov["water_count"] == 1 and ov["water_top"][0] == 5.0
    assert ov["seed"] == dd.seed_term(found.seed)
    assert ov["warp"][3] == found.border["width"]


def test_the_terrain_shader_declares_and_draws_the_borders():
    from engine import shaders
    from engine.renderer.core.terrain_gl import TerrainGL
    frag = shaders.DEFAULT_SHADERS["terrain.frag"]
    for name in ("uDistrictSeats", "uDistrictSeat", "uDistrictWater", "uDistrictSeed"):
        assert name in frag and name in TerrainGL.UNIFORM_NAMES
    assert "if (uDistrictSeats > 0)" in frag
    assert str(dd.HASH_X) + "u" in frag and str(dd.HASH_MIX) + "u" in frag


@pytest.mark.gl
def test_the_shader_noise_matches_python_exactly():
    """The warp noise, run in GLSL, gives Python's values (8-bit output)."""
    from OpenGL import GL as gl
    from OpenGL.GL.shaders import compileProgram, compileShader
    from engine import shaders
    from tests.helpers.gl import GLTestContext

    frag_src = shaders.DEFAULT_SHADERS["terrain.frag"]
    start = frag_src.index("// The districts' warp noise")
    end = frag_src.index("// How strongly this fragment is a district border")
    funcs = frag_src[start:end]
    salt = dd.seed_term(1187)
    vert = """#version 330 core
layout (location = 0) in vec2 pos;
void main() { gl_Position = vec4(pos, 0.0, 1.0); }"""
    frag = """#version 330 core
out vec4 FragColor;
""" + funcs + """
void main() {
    ivec2 c = ivec2(gl_FragCoord.xy);
    highp vec2 p = vec2(float(c.x) * 0.37 - 11.3, float(c.y) * 0.53 - 2.1);
    FragColor = vec4(districtFbm(p, %du) * 0.5 + 0.5,
                     districtHash(c - ivec2(30, 2), %du), 0.0, 1.0);
}""" % (salt, salt)
    w, h = 64, 4
    with GLTestContext(w, h):
        prog = compileProgram(compileShader(vert, gl.GL_VERTEX_SHADER),
                              compileShader(frag, gl.GL_FRAGMENT_SHADER), validate=False)
        quad = np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], np.float32)
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        try:
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, quad.nbytes, quad, gl.GL_STATIC_DRAW)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glViewport(0, 0, w, h)
            gl.glUseProgram(prog)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
            raw = gl.glReadPixels(0, 0, w, h, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        finally:
            gl.glDeleteBuffers(1, [vbo])
            gl.glDeleteVertexArrays(1, [vao])
            gl.glDeleteProgram(prog)
    got = np.frombuffer(raw, np.uint8).reshape(h, w, 4).astype(np.float64) / 255.0
    cx, cy = np.meshgrid(np.arange(w), np.arange(h))
    fbm = dd._fbm(cx * 0.37 - 11.3, cy * 0.53 - 2.1, salt) * 0.5 + 0.5
    hashed = dd._hash(cx - 30, cy - 2, salt)
    assert np.abs(got[..., 0] - fbm).max() < 2.5 / 255.0
    assert np.abs(got[..., 1] - hashed).max() < 1.5 / 255.0


# -- the session, the host, the console ------------------------------------------------------
def _session(on=True):
    from ..runtime import MiniwindSession
    s = MiniwindSession.__new__(MiniwindSession)
    s.districts = dd.load()
    s._district_borders = on
    s._player_pos = lambda: (500.0, 0.0, 600.0)
    return s


def test_the_session_hands_out_the_overlay_only_while_borders_are_on():
    s = _session(True)
    assert s.district_overlay() is s.districts.overlay()
    assert s.district_at((1000.0, 0.0, 1500.0)).id == "millbrook"
    s._district_borders = False
    assert s.district_overlay() is None
    s.districts = None
    s._district_borders = True
    assert s.district_overlay() is None and s.district_at((0.0, 0.0, 0.0)) is None


def test_the_console_reports_districts_and_toggles_borders(monkeypatch):
    from .. import console
    lines = []
    monkeypatch.setattr(console, "debug_log", lambda category, message: lines.append(message))
    s = _session(True)
    ctx = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=s), play_mode=True)
    console.cmd_districts(ctx, "")
    assert "you are in Millbrook" in lines[0] and any("Cairnmoor" in l for l in lines)
    console.cmd_districts(ctx, "off")
    assert s._district_borders is False and s.district_overlay() is None
    console.cmd_districts(console.ConsoleContext(), "")
    assert "Play Mode only" in lines[-1]


@pytest.mark.gl
def test_borders_change_a_real_terrain_frame_and_none_changes_nothing(qt_app):
    from tests.helpers import scenes
    from tests.helpers.session import FioTestSession
    found = dd.Districts({"bounds": [-600, -600, 600, 600], "warp": 120.0, "warp_scale": 400.0,
                          "border": {"width": 12.0, "alpha": 0.9},
                          "districts": [{"id": "a", "seat": [-300, 0]},
                                        {"id": "b", "seat": [300, 50]},
                                        {"id": "c", "seat": [0, 400]}]})
    session = FioTestSession(qt_app, scenes.terrain_map(), size=(320, 180))
    try:
        renderer = session.view.renderer
        session.paint()
        renderer.district_overlay = None
        off = session.paint().astype(int)
        renderer.district_overlay = found.overlay()
        on = session.paint().astype(int)
        renderer.district_overlay = None
        again = session.paint().astype(int)
    finally:
        session.close()
    changed = np.abs(on - off).sum(axis=2) > 0
    assert changed.any()
    assert on[changed].mean() < off[changed].mean()           # dark lines
    assert np.array_equal(off, again)                         # off again: untouched
