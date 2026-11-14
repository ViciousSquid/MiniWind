"""The grass sways in the wind a game hands the renderer (``grass_wind``).

``renderer.grass_wind`` is ``(dir x, dir z, strength)``, set by a game before
the scene as ``sky_state`` is; the built-in renderer passes it to the
terrain's grass pass (engine/renderer/core/grass_wind.py), which drives the
grass shader's ``windStrength``, ``uWindDir`` and ``uWindScroll``. Without a
game the grass sways in the old default breeze. Headless: the pure helpers,
the hand-off and the shader source -- no GL.
"""

import math
import pathlib

import pytest

from engine.renderer.core import grass_wind as gw

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_no_wind_or_a_bad_one_is_the_default_breeze():
    default = gw.resolve(None)
    (dx, dz), strength = default
    assert strength == gw.DEFAULT_STRENGTH == 0.65
    assert math.hypot(dx, dz) == pytest.approx(1.0)
    assert dz / dx == pytest.approx(0.35)
    for bad in ((0.0, 0.0, 1.0), ("x", 1, 1), (1.0, 2.0), (float("nan"), 0.0, 1.0),
                (1.0, 0.0, float("inf"))):
        assert gw.resolve(bad) == default


def test_a_game_s_wind_is_normalised_and_bounded():
    (dx, dz), strength = gw.resolve((0.0, -3.0, 1.4))
    assert (dx, dz) == pytest.approx((0.0, -1.0)) and strength == 1.4
    assert gw.resolve((1.0, 0.0, 99.0))[1] == gw.MAX_STRENGTH
    assert gw.resolve((1.0, 0.0, -1.0))[1] == 0.0


def test_the_gust_field_rolls_downwind_faster_the_harder_it_blows():
    calm = gw.advance_scroll((0.0, 0.0), (1.0, 0.0), 0.65, 0.05)
    gale = gw.advance_scroll((0.0, 0.0), (1.0, 0.0), 1.3, 0.05)
    # The default breeze rolls as the old shader did (direction x 0.6 a second).
    assert calm == pytest.approx((0.6 * 0.05, 0.0))
    assert gale[0] == pytest.approx(2.0 * calm[0]) and gale[1] == 0.0
    # A stalled frame does not lurch it.
    assert gw.advance_scroll((0.0, 0.0), (0.0, 1.0), 0.65, 5.0)[1] == pytest.approx(0.06)


def test_a_turning_wind_never_jumps_the_field():
    """However long it has blown, a heading that turns a hair moves the field
    a hair (it was direction x time in the shader: a jump of hair x clock)."""
    scroll = (0.0, 0.0)
    for i in range(20000):
        a = 0.3 + i * 1e-4
        before = scroll
        scroll = gw.advance_scroll(scroll, (math.cos(a), math.sin(a)), 1.0, 1 / 60)
        step = math.hypot(*(((s - b + gw.SCROLL_WRAP / 2) % gw.SCROLL_WRAP) - gw.SCROLL_WRAP / 2
                            for s, b in zip(scroll, before)))
        assert step < 0.02


def test_the_wrap_is_seamless_for_both_noise_fields():
    """The shader samples the field at the offset and at 2.7 times it, in
    noise that repeats every 289: the wrap must be a whole number of periods
    for both."""
    for k in (1.0, 2.7):
        periods = gw.SCROLL_WRAP * k / 289.0
        assert periods == pytest.approx(round(periods))


def test_the_renderer_hands_the_wind_to_the_grass_pass():
    passes = (ROOT / "engine" / "renderer" / "forward" / "passes.py").read_text(encoding="utf-8")
    body = passes[passes.index("def render_terrain("):passes.index("def _terrain_gl(")]
    assert "grass_wind=getattr(self, 'grass_wind', None)" in body


@pytest.mark.qt
def test_the_terrain_keeps_the_wind_for_the_frame_it_draws():
    from engine.renderer.core.terrain_gl import TerrainGL
    held = TerrainGL()
    seen = []
    held._render = lambda *a, **k: seen.append(held.grass_wind)
    frame = type("Frame", (), {"enabled": True})()
    held.render(frame, None, None, None, grass_wind=(0.0, 1.0, 1.5))
    held.render(frame, None, None, None)
    assert seen == [(0.0, 1.0, 1.5), None]


def test_the_grass_shader_reads_the_live_wind():
    from engine import shaders
    vert = shaders.DEFAULT_SHADERS['grass.vert']
    for decl in ("uniform float windStrength;", "uniform vec2 uWindDir;",
                 "uniform vec2 uWindScroll;"):
        assert decl in vert
    assert "windDir * time" not in vert
    source = (ROOT / "engine" / "renderer" / "core" / "terrain_gl.py").read_text(encoding="utf-8")
    assert "glUniform1f(u['windStrength'], 0.65)" not in source
    assert "glUniform2f(u['uWindDir']" in source and "glUniform2f(u['uWindScroll']" in source
