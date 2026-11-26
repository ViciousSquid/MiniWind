"""Visual tier: ``[Renderer] skystyle`` on a real GL context.

Style 0 draws exactly what the renderer drew before the setting existed; the
others draw a sky behind the world, turning to space near the world's edge.
"""

import configparser

import numpy as np
import pytest

from tests.helpers import gl as glh
from tests.helpers import terrain_draw

pytestmark = [pytest.mark.gl, pytest.mark.slow]

W, H = 160, 120
CLEAR = (0.0, 0.0, 1.0)


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(W, H) as ctx:
        yield ctx
    glh.reset_texture_cache()


def _terrain():
    from engine.terrain import Terrain
    t = Terrain(seed=7)
    t.set_bounds(-1, 0, -1, 0)                       # 4096 square, strata walls on
    t.MAX_UPDATES_PER_FRAME = 16
    t.UPDATE_BUDGET_MS = 1.0e6
    return t


def _render(context, style, eye, target):
    """One settled frame at *style* (None: a renderer without settings)."""
    import glm
    import OpenGL.GL as gl
    from engine.renderer import renderer_factory
    from engine.view_distance import ViewDistance
    config = None
    if style is not None:
        config = configparser.ConfigParser()
        config.read_dict({'Renderer': {'skystyle': str(style)}})
    renderer = renderer_factory('Forward')(config, texture_loader=lambda *a: glh._white_texture())
    try:
        renderer.view_distance = ViewDistance(20000.0)
        terrain = _terrain()
        eye_v = glm.vec3(*eye)
        projection = glm.perspective(glm.radians(60.0), W / H, 10.0, 20000.0)
        view = glm.lookAt(eye_v, glm.vec3(*target), glm.vec3(0, 1, 0))
        image = None
        for i in range(3):
            config_frame = glh.render_config(play_mode=True, time=1.0 + i * 10.0)
            context.bind()
            gl.glClearColor(*CLEAR, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            with glh.no_gl_errors("skystyle %s" % style):
                terrain_draw.scene(renderer, terrain, projection, view, eye_v, config_frame,
                                   brush_slots=config_frame['all_brush_slots'])
                gl.glFinish()
            image = context.read_pixels().astype(np.float64)
        return image, renderer
    finally:
        renderer.cleanup()


# Over the middle of the 4096 world (far from no edge: it is small), looking
# out and up past its edge.
LOOK_UP = ((0.0, 300.0, 0.0), (0.0, 900.0, -1500.0))


def test_style_zero_draws_exactly_what_the_renderer_drew_before(context):
    before, _ = _render(context, None, *LOOK_UP)
    zero, _ = _render(context, 0, *LOOK_UP)
    assert np.array_equal(before, zero)


def test_the_other_styles_draw_a_sky_where_the_clear_colour_was(context):
    before, _ = _render(context, None, *LOOK_UP)
    sky = np.abs(before - np.array(CLEAR) * 255.0).sum(axis=-1) < 1.0
    assert sky.mean() > 0.2, "the view should see sky past the world"
    for style in (1, 2, 3):
        image, renderer = _render(context, style, *LOOK_UP)
        changed = np.abs(image - before).sum(axis=-1) > 30.0
        assert changed[sky].mean() > 0.9, style


def test_near_the_edge_style_one_keeps_the_sky_overhead_and_two_does_not(context):
    # A world this small is all within the fade of its edge: space at full.
    straight_up = ((0.0, 300.0, 0.0), (0.0, 5000.0, -1.0))
    one, _ = _render(context, 1, *straight_up)
    two, _ = _render(context, 2, *straight_up)
    three, _ = _render(context, 3, *straight_up)
    centre = (slice(H // 3, 2 * H // 3), slice(W // 3, 2 * W // 3))
    # Style 1's ceiling is the game's sky (bright blue by day); 2's and 3's
    # space (dark).
    assert one[centre].mean() > two[centre].mean() + 40.0
    assert np.abs(two[centre] - three[centre]).mean() < 1.0
