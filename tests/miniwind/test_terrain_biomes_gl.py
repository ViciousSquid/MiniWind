"""Visual tier: MiniWind's terrain features drawn by the renderer's TerrainGL.

The terrain publishes numbers (``tests/engine/test_terrain_biome_publication.py``);
here the GL side is checked on a real context: the biome map is uploaded
once per version and blended by the terrain program, the grass program is
told who is parting the grass, grass the terrain gave back is freed, and
every name made for them is deleted with the rest.
"""

import numpy as np
import pytest

from engine import terrain_biomes as tb
from tests.helpers import gl as glh
from tests.helpers import terrain_draw
from tests.visual.test_terrain_appearance_render import _ground, _render, _terrain

pytestmark = [pytest.mark.gl, pytest.mark.slow]

W, H = 160, 120


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(W, H) as ctx:
        yield ctx
    glh.reset_texture_cache()


def _paint(terrain, channel, channels=4):
    biome = np.zeros((4, 4, channels), dtype=np.uint8)
    biome[..., channel] = 255
    terrain.set_biome_map(biome)


def _mean(image):
    return image[_ground(image)].mean(axis=0)


def test_a_biome_map_repaints_the_ground_and_is_uploaded_once_per_version(context, monkeypatch):
    import OpenGL.GL as gl
    from engine.renderer.core import terrain_gl
    terrain = _terrain(glh._white_texture())
    terrain.set_grass(False)
    plain = _mean(_render(context, terrain))
    held = terrain_draw.gl_for(terrain)
    assert held._biome_tex == 0

    uploads = []
    real = gl.glTexImage2D
    monkeypatch.setattr(terrain_gl.gl, 'glTexImage2D',
                        lambda *a, **k: (uploads.append(a[3:5]), real(*a, **k))[1])
    _paint(terrain, tb.SNOW)
    snow = _mean(_render(context, terrain))
    assert held._biome_tex and gl.glIsTexture(held._biome_tex)
    assert uploads == [(4, 4)], "one upload for three frames of the same map"
    assert np.abs(snow - plain).max() > 10.0, (plain, snow)
    assert snow[2] > snow[0], snow                             # snowfields: cold white

    _paint(terrain, tb.DESERT)
    sand = _mean(_render(context, terrain))
    assert len(uploads) == 2
    assert sand[0] > sand[2] * 1.25, sand                      # sand: red over blue
    assert snow[2] > sand[2] + 20.0

    # Clearing the map goes back to the plain ground, with no further upload.
    terrain.set_biome_map(None)
    again = _mean(_render(context, terrain))
    assert np.abs(again - plain).max() < 2.0
    assert len(uploads) == 2

    texture = held._biome_tex
    held.cleanup()
    assert not gl.glIsTexture(texture) and held._biome_tex == 0


def test_the_biome_sampler_has_its_own_texture_unit(context):
    import OpenGL.GL as gl
    from engine import shaders
    from engine.renderer.core.terrain_gl import TerrainGL
    from engine.renderer.forward.renderer import ForwardRenderer
    height_unit = 4 + shaders.MAX_SHADOW_LIGHTS
    assert TerrainGL.BIOME_TEXTURE_UNIT not in (
        0, 1, 2, 3, height_unit, height_unit + 1, ForwardRenderer.GEO_TRANSFORM_UNIT)
    assert TerrainGL.BIOME_TEXTURE_UNIT not in range(4, height_unit)
    assert TerrainGL.BIOME_TEXTURE_UNIT < 16                    # GL 3.3 fragment units
    terrain = _terrain(glh._white_texture())
    _paint(terrain, tb.SWAMP)
    _render(context, terrain)
    held = terrain_draw.gl_for(terrain)
    value = np.zeros(1, dtype=np.int32)
    gl.glGetUniformiv(held.shader_program, held.uniforms['uBiomeMap'], value)
    assert value[0] == TerrainGL.BIOME_TEXTURE_UNIT
    gl.glGetUniformiv(held.shader_program, held.uniforms['uBiomeEnabled'], value)
    assert value[0] == 1
    gl.glValidateProgram(held.shader_program)
    assert gl.glGetProgramiv(held.shader_program, gl.GL_VALIDATE_STATUS)


def _wheat_terrain():
    terrain = _terrain(glh._white_texture())
    terrain.set_grass(True, density=0.06)
    terrain.set_appearance(layer_heights=(0.0, 1.0, 1.0))
    terrain.GRASS_MIN_NORMAL_Y = 0.0
    _paint(terrain, tb.WHEAT)
    return terrain


def _field_view(terrain):
    y = terrain._get_height_scalar(40.0, 80.0)
    return (40.0, y + 12.0, 120.0), (40.0, terrain._get_height_scalar(40.0, 0.0), 0.0)


def test_grass_pushers_reach_the_grass_program_and_part_the_blades(context):
    import OpenGL.GL as gl
    terrain = _wheat_terrain()
    eye, target = _field_view(terrain)
    standing = _render(context, terrain, eye=eye, target=target)
    held = terrain_draw.gl_for(terrain)
    count = np.zeros(1, dtype=np.int32)
    gl.glGetUniformiv(held.grass_shader_program, held.grass_uniforms['uPusherCount'], count)
    assert count[0] == 0

    terrain.set_grass_pushers([("player", 40.0, 60.0, 60.0)])
    parted = _render(context, terrain, eye=eye, target=target)
    gl.glGetUniformiv(held.grass_shader_program, held.grass_uniforms['uPusherCount'], count)
    assert count[0] >= 1
    row = np.zeros(4, dtype=np.float32)
    gl.glGetUniformfv(held.grass_shader_program, held.grass_uniforms['uPushers'], row)
    assert row.tolist() == [40.0, 60.0, 60.0, 1.0]
    assert np.abs(parted - standing).mean() > 0.5, "the blades did not move"


def test_grass_is_not_drawn_when_the_renderer_says_so(context):
    import glm
    import OpenGL.GL as gl
    terrain = _wheat_terrain()
    eye, target = _field_view(terrain)
    grassy = _render(context, terrain, eye=eye, target=target)
    held = terrain_draw.gl_for(terrain)
    draws = []
    real = gl.glDrawArraysInstanced
    from engine.renderer.core import terrain_gl
    try:
        terrain_gl.gl.glDrawArraysInstanced = lambda *a: (draws.append(a), real(*a))[1]
        eye_v = glm.vec3(*eye)
        proj = glm.perspective(glm.radians(60.0), W / H, 1.0, 20000.0)
        view = glm.lookAt(eye_v, glm.vec3(*target), glm.vec3(0, 1, 0))
        context.bind()
        held.render(terrain.publish(), proj, view, eye_v, draw_grass=False)
        assert draws == []
        held.render(terrain.publish(), proj, view, eye_v)
        assert draws
    finally:
        terrain_gl.gl.glDrawArraysInstanced = real
    assert glh.drain_gl_errors() == []
    assert grassy is not None


def test_grass_the_terrain_gives_back_is_freed_and_uploaded_again(context):
    import OpenGL.GL as gl
    terrain = _wheat_terrain()
    eye, target = _field_view(terrain)
    _render(context, terrain, eye=eye, target=target, frames=6)
    held = terrain_draw.gl_for(terrain)
    grown = [slot for slot in terrain.products.grass if held._grass_count[slot] > 0]
    assert grown, "the test needs a wheat chunk with blades"
    slot = grown[0]
    vao, vbo = int(held._grass_vao[slot]), int(held._grass_vbo[slot])
    assert gl.glIsVertexArray(vao) and gl.glIsBuffer(vbo)

    # What Terrain.advance does for a chunk far out of grass range.
    terrain.products.drop_grass([slot])
    import glm
    eye_v = glm.vec3(*eye)
    proj = glm.perspective(glm.radians(60.0), W / H, 1.0, 20000.0)
    view = glm.lookAt(eye_v, glm.vec3(*target), glm.vec3(0, 1, 0))
    context.bind()
    held.render(terrain.publish(), proj, view, eye_v)
    assert held._grass_count[slot] == 0 and held._grass_vao[slot] == 0
    assert not gl.glIsBuffer(vbo)

    terrain.table.grass_dirty[slot] = True
    _render(context, terrain, eye=eye, target=target, frames=4)
    assert held._grass_count[slot] > 0 and gl.glIsBuffer(int(held._grass_vbo[slot]))
    assert glh.drain_gl_errors() == []
