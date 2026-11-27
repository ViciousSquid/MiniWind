"""Settled snow on the terrain (``snow_cover``).

A game sets ``renderer.snow_cover`` (0..1) before the scene as it sets
``sky_state``; the renderer hands it to the terrain pass, which sets the
terrain shader's ``uSnowCover``: patches first, a white blanket from about
0.8, thin on steep slopes. Headless checks of the hand-off and the shader
source, and a real compile under a GL context.
"""

import pathlib

import pytest

pytestmark = pytest.mark.qt

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_renderer_hands_snow_cover_to_the_terrain_pass():
    passes = (ROOT / "engine" / "renderer" / "forward" / "passes.py").read_text(encoding="utf-8")
    body = passes[passes.index("def render_terrain("):passes.index("def _terrain_gl(")]
    assert "snow_cover=float(getattr(self, 'snow_cover', 0.0) or 0.0)" in body


def test_the_terrain_shaders_lay_snow_by_cover():
    from engine import shaders
    from engine.renderer.core.terrain_gl import TerrainGL
    assert "uSnowCover" in TerrainGL.UNIFORM_NAMES
    for name in ("terrain.frag", "terrain_flat.frag", "terrain_skirt.frag"):
        frag = shaders.DEFAULT_SHADERS[name]
        assert "uniform float uSnowCover;" in frag, name
        assert "if (uSnowCover > 0.001)" in frag, name


@pytest.mark.qt
def test_the_terrain_keeps_the_snow_cover_for_the_frame_it_draws():
    from engine.renderer.core.terrain_gl import TerrainGL
    held = TerrainGL()
    seen = []
    held._render = lambda *a, **k: seen.append(held.snow_cover)
    frame = type("Frame", (), {"enabled": True})()
    held.render(frame, None, None, None, snow_cover=0.6)
    held.render(frame, None, None, None)
    held.render(frame, None, None, None, snow_cover=7.0)
    assert seen == [0.6, 0.0, 1.0]


@pytest.mark.gl
def test_the_terrain_programs_compile_with_a_live_snow_uniform():
    pytest.importorskip("OpenGL")
    from OpenGL import GL as gl
    from OpenGL.GL.shaders import compileProgram, compileShader

    from engine import shaders
    from tests.helpers.gl import GLTestContext

    with GLTestContext(32, 32):
        for vert, frag in (("terrain.vert", "terrain.frag"),
                           ("terrain_indexed.vert", "terrain_flat.frag")):
            program = compileProgram(
                compileShader(shaders.DEFAULT_SHADERS[vert], gl.GL_VERTEX_SHADER),
                compileShader(shaders.DEFAULT_SHADERS[frag], gl.GL_FRAGMENT_SHADER),
                validate=False)
            try:
                assert gl.glGetUniformLocation(program, "uSnowCover") != -1, frag
            finally:
                gl.glDeleteProgram(program)


@pytest.mark.gl
def test_snow_whitens_a_real_terrain_frame(qt_app):
    """The editor draws a procedural terrain; deeper snow, a whiter frame."""
    from tests.helpers import scenes
    from tests.helpers.session import FioTestSession

    session = FioTestSession(qt_app, scenes.terrain_map(), size=(320, 180))
    try:
        renderer = session.view.renderer
        session.paint()                          # the terrain is uploaded
        means = []
        for cover in (0.0, 0.45, 1.0):
            renderer.snow_cover = cover
            means.append(float(session.paint().mean()))
        assert means[0] < means[1] < means[2]
        assert means[2] - means[0] > 10.0
    finally:
        session.close()
