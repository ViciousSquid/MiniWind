"""The shipped OBJ and GLB windmills load and draw in Fio's real renderer."""

from pathlib import Path

import numpy as np
import pytest

from tests.helpers import gl as glh

pytestmark = [pytest.mark.gl, pytest.mark.slow]


def test_both_windmill_formats_draw_the_same_silhouette():
    import glm
    import OpenGL.GL as gl
    from editor.things import Light, Prop
    from engine.renderer.forward import ForwardRenderer

    root = Path(__file__).resolve().parents[2]
    images = []
    with glh.GLTestContext(384, 384) as ctx:
        renderer = ForwardRenderer(None)
        renderer.shadows_enabled = False
        try:
            eye = glm.vec3(800, 750, 1500)
            projection = glm.ortho(-560, 560, -560, 560, 1, 6000)
            view = glm.lookAt(eye, glm.vec3(0, 420, 0), glm.vec3(0, 1, 0))
            for extension in ('obj', 'glb'):
                folder = root / 'assets/models'
                path = str(folder / f'windmill.{extension}')
                prop = Prop.for_model(path)
                light = Light(pos=[-500, 1200, 1000], properties={
                    'color': [255, 240, 225], 'intensity': 1.0, 'radius': 6000,
                    'casts_shadows': False})
                config = glh.render_config(all_things=[prop, light], shadows_enabled=False)
                ctx.bind()
                gl.glClearColor(0.02, 0.03, 0.05, 1)
                renderer.render_scene(projection, view, eye, None, config,
                                      brush_slots=config['all_brush_slots'])
                gl.glFinish()
                pixels = ctx.read_pixels()
                background = pixels[0, 0]
                visible = np.max(np.abs(pixels.astype(float) - background), axis=-1) > 8
                assert visible.mean() > 0.10
                images.append(visible)
                model = renderer.load_model(path)
                assert model.is_loaded and model.vao and len(model.groups) >= 8
                brick = model.materials['Brick']
                texture = renderer._model_texture_id(brick['texture'], brick)
                gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
                assert gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D, 0, gl.GL_TEXTURE_WIDTH) == 1024
            assert np.mean(images[0] != images[1]) < 0.01
            assert glh.drain_gl_errors() == []
        finally:
            renderer.cleanup()
