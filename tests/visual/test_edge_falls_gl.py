"""Visual tier: waterfalls off the world's edge on a real GL context.

Renders are compared with each other (falls or none), never against a
particular GPU's shading.
"""

import numpy as np
import pytest

from tests.helpers import gl as glh
from tests.helpers import terrain_draw

pytestmark = [pytest.mark.gl, pytest.mark.slow]

W, H = 200, 150
SKY = (0.0, 0.0, 1.0)
ENV = {'uFogEnabled': 0, 'uFogColor': (0.5, 0.5, 0.5), 'uFogStart': 1.0e5,
       'uFogEnd': 2.0e5, 'uFogDensity': 0.0, 'uFogCamPos': (0.0, 0.0, 0.0),
       'uAmbient': (0.05, 0.05, 0.05)}


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(W, H) as ctx:
        yield ctx
    glh.reset_texture_cache()


def _terrain(white):
    from engine.terrain import Terrain
    t = Terrain(seed=7)
    t.set_bounds(-1, 0, -1, 0)
    t.grass_tex = t.rock_tex = t.sand_tex = t.snow_tex = white
    t.MAX_UPDATES_PER_FRAME = 16
    t.UPDATE_BUDGET_MS = 1.0e6
    return t


def _render(ctx, terrain, water_top, reach_edge, eye, target):
    """Draw *terrain*, then the falls of one water brush over all of it
    whose surface is *water_top* -- reaching its edges or stopping short."""
    import glm
    import OpenGL.GL as gl
    from engine.renderer.core.terrain_gl import TerrainGL
    eye_v = glm.vec3(*eye)
    proj = glm.perspective(glm.radians(60.0), W / H, 1.0, 60000.0)
    view = glm.lookAt(eye_v, glm.vec3(*target), glm.vec3(0, 1, 0))
    planes = terrain_draw.frustum_planes(proj * view)
    env = dict(ENV, uFogCamPos=tuple(eye))
    held = None
    for _ in range(3):
        ctx.bind()
        gl.glClearColor(*SKY, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        held = terrain_draw.draw(terrain, proj, view, eye_v, planes, env_uniforms=env)
        bounds = terrain.publish().skirt
        inset = 0.0 if reach_edge else 200.0
        centre = ((bounds[0] + bounds[1]) / 2.0, water_top - 16.0,
                  (bounds[2] + bounds[3]) / 2.0)
        half = ((bounds[1] - bounds[0]) / 2.0 - inset, 16.0,
                (bounds[3] - bounds[2]) / 2.0 - inset)
        falls = TerrainGL.edge_falls(bounds, [centre], [half])
        held.draw_falls(falls, proj, view, (eye[0], eye[1], eye[2]), env_uniforms=env, time=2.0)
    assert glh.drain_gl_errors() == []
    return ctx.read_pixels().astype(np.float64), held


def _drawn(image):
    return np.abs(image - np.array(SKY) * 255.0).sum(axis=-1) > 30.0


# Outside the -x edge, looking back at it and down past its foot.
OUTSIDE = ((-3500.0, 200.0, -1000.0), (-2000.0, -900.0, -1000.0))


def test_water_reaching_the_edge_pours_over_it(context):
    white = glh._white_texture()
    terrain = _terrain(white)
    top = float(terrain.publish().skirt[6]) + 50.0      # above all the ground
    falls, held = _render(context, terrain, top, True, *OUTSIDE)
    assert held.falls_sides > 0
    dry, held_dry = _render(context, _terrain(white), top, False, *OUTSIDE)
    assert held_dry.falls_sides == 0
    added = _drawn(falls) & ~_drawn(dry)
    assert added.mean() > 0.02, "the falls added almost nothing below the edge"


def test_nothing_falls_where_the_ground_is_above_the_water(context):
    white = glh._white_texture()
    terrain = _terrain(white)
    low = float(terrain.publish().skirt[5]) - 50.0      # below all the ground
    falls, held = _render(context, terrain, low, True, *OUTSIDE)
    # Chunk sides whose lowest ground is above the water are not drawn.
    assert held.falls_sides == 0
