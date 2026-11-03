"""An inactive terrain paint sampler still needs a complete texture array."""

import glm
import numpy as np
import pytest

from tests.helpers.gl import GLTestContext

pytestmark = pytest.mark.gl


@pytest.fixture
def current_context():
    with GLTestContext(256, 256):
        yield


def test_paint_sampler_is_complete_without_paint_and_after_cleanup(current_context):
    from OpenGL import GL as gl
    from engine import shaders
    from engine.terrain import Terrain

    t = Terrain()
    t.enabled, t.grass_enabled = True, False
    t.set_bounds(0, 0, 0, 0)
    eye = glm.vec3(128, 500, 128)
    projection = glm.ortho(-256, 256, -256, 256, 1, 1000)
    view = glm.lookAt(eye, glm.vec3(128, 0, 128), glm.vec3(0, 0, -1))

    def render():
        for _ in range(3):
            t.update_and_render(projection, view, eye)
        gl.glFinish()
        assert t.visible_chunks == 1
        gl.glActiveTexture(gl.GL_TEXTURE0 + 4 + shaders.MAX_SHADOW_LIGHTS + 1)
        bound = int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D_ARRAY))
        assert bound != 0
        for dim in (gl.GL_TEXTURE_WIDTH, gl.GL_TEXTURE_HEIGHT, gl.GL_TEXTURE_DEPTH):
            assert gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D_ARRAY, 0, dim) > 0
        program = t.block_program if t.appearance.terrace_mode == "blocks" else t.shader_program
        gl.glValidateProgram(program)
        assert gl.glGetProgramiv(program, gl.GL_VALIDATE_STATUS), gl.glGetProgramInfoLog(program)
        assert gl.glGetError() == gl.GL_NO_ERROR
        gl.glActiveTexture(gl.GL_TEXTURE0)
        return bound

    try:
        assert render() == t._empty_paint_texture
        placeholder = t._empty_paint_texture
        t.texture_paint_maps[(0, 0)] = np.full(
            (t.TERRAIN_PAINT_RESOLUTION, t.TERRAIN_PAINT_RESOLUTION, 4), 255, dtype=np.uint8)
        t._touch_texture_paint((0, 0))
        assert render() == t._paint_pages[0]
        t.clear_texture_paint()
        assert render() == placeholder
        t.appearance.terrace_mode = "blocks"
        t.mark_all_dirty()
        assert render() == placeholder
        t.cleanup()
        assert not gl.glIsTexture(placeholder)
        assert t._empty_paint_texture == 0
        t.appearance.terrace_mode = "smooth"
        assert render() == t._empty_paint_texture
    finally:
        t.cleanup()
