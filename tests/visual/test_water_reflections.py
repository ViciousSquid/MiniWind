"""Visual tier: actors reflected in water, on a real OpenGL context.

An actor stands on the far shore of a pool seen from (almost) overhead. With
reflections on, its colour shows in the water just below it on screen --
clipped to the water -- and with them off it does not. The stencil bit the
water borrows is left clear for whatever draws next (portals).
"""

import numpy as np
import pytest

from tests.helpers import gl as glh
from tests.helpers.worlds import box_brush, make_thing

pytestmark = [pytest.mark.gl, pytest.mark.slow]

SIZE = 200


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(SIZE, SIZE) as ctx:
        yield ctx
    glh.reset_texture_cache()


def _red_texture():
    import OpenGL.GL as gl
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[..., 0], image[..., 3] = 255, 255
    tex = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, 16, 16, 0, gl.GL_RGBA,
                    gl.GL_UNSIGNED_BYTE, image.tobytes())
    for p, v in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST), (gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)):
        gl.glTexParameteri(gl.GL_TEXTURE_2D, p, v)
    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
    return int(tex)


def _scene():
    from editor.things import Light, Monster
    floor = box_brush('floor', (0, -40, 0), (4000, 64, 4000))
    water = box_brush('pool', (0, 0, 0), (1200, 32, 800))
    water.update(shader='Water', is_water=True, water_tint=[0.05, 0.3, 0.45],
                 water_opacity=0.8, water_fresnel=0.5, water_plane=True)
    # On the north shore (-z), feet on the water's level.
    actor = make_thing(Monster, 'wader', (0.0, 80.0, -470.0), render_mode='billboard',
                       sprite_size=[128.0, 128.0])
    light = make_thing(Light, 'sun', (0.0, 3000.0, 500.0), color=[255, 255, 255],
                       intensity=1.0, radius=20000.0, state='on', casts_shadows=False)
    return [floor, water], [actor, light], actor


def _render(context, reflections):
    import OpenGL.GL as gl
    from engine import entity_table
    renderer = glh.make_renderer()
    try:
        renderer.water_reflects_actors = reflections
        brushes, things, actor = _scene()
        tex = _red_texture()
        for key, *_rest in entity_table.sprite_candidates(actor):
            if key:
                renderer.sprite_textures[key] = tex
        projection, view, eye = glh.camera_matrices(
            aspect=1.0, fov_deg=60.0, eye=(0.0, 1500.0, 60.0), target=(0.0, 0.0, -200.0))
        config = glh.render_config(all_brushes=brushes, all_things=things, all_lights=things,
                                   play_mode=True, show_sprites_in_play_mode=True, time=1.0)
        context.bind()
        gl.glClearColor(0.2, 0.25, 0.2, 1.0)
        renderer.render_scene(projection, view, eye, None, config,
                              brush_slots=config["all_brush_slots"])
        gl.glFinish()
        pixels = context.read_pixels().astype(np.int32)
        stencil = gl.glReadPixels(0, 0, SIZE, SIZE, gl.GL_STENCIL_INDEX, gl.GL_UNSIGNED_BYTE)
        stencil = np.frombuffer(stencil, dtype=np.uint8)
        enabled = bool(gl.glIsEnabled(gl.GL_STENCIL_TEST))
        return pixels, stencil, enabled, renderer.render_stats.draw_calls
    finally:
        renderer.cleanup()


def test_an_actor_on_the_far_shore_shows_in_the_water(context):
    on, stencil, enabled, _ = _render(context, True)
    off, _s, _e, _ = _render(context, False)
    redder = (on[..., 0] - on[..., 2]) - (off[..., 0] - off[..., 2])
    changed = np.argwhere(redder > 12)
    assert len(changed) > 40, "no reflection appeared"
    # Below the actor on screen (in the water), never above it on land.
    red_rows = np.argwhere((off[..., 0] > 200) & (off[..., 1] < 80))[:, 0]
    assert len(red_rows), "the actor itself was not drawn"
    assert changed[:, 0].mean() > red_rows.mean()
    assert not (stencil & 0x80).any(), "the water's stencil bit was left set"
    assert not enabled
