"""The castle kit draws in Fio's renderer through both supported formats."""
from pathlib import Path

import numpy as np
import pytest

from tests.helpers import gl as glh

pytestmark = [pytest.mark.gl, pytest.mark.slow]


def test_castle_exports_draw_the_same_upright_textured_assembly():
    import glm
    import OpenGL.GL as gl
    from editor.things import Light, Prop
    from engine.renderer.forward import ForwardRenderer

    folder = Path(__file__).resolve().parents[2] / 'assets/models'
    with glh.GLTestContext(512, 384) as ctx:
        renderer = ForwardRenderer(None)
        renderer.shadows_enabled = False
        images = []
        eye = glm.vec3(1800, 1450, 2700)
        projection = glm.ortho(-1250, 1250, -938, 938, 1, 8000)
        view = glm.lookAt(eye, glm.vec3(720, 330, 0), glm.vec3(0, 1, 0))
        try:
            for extension in ('obj', 'glb'):
                props = [Prop.for_model(str(folder / f'castle_tower.{extension}'))]
                props += [Prop.for_model(str(folder / f'town_wall.{extension}'), pos=[480, 0, 0]),
                          Prop.for_model(str(folder / f'castle_gatehouse.{extension}'), pos=[1248, 0, 0])]
                light = Light(pos=[-600, 1800, 1000], properties={
                    'color': [255, 240, 225], 'intensity': 1, 'radius': 6500,
                    'casts_shadows': False})
                config = glh.render_config(all_things=props + [light], shadows_enabled=False)
                ctx.bind()
                gl.glClearColor(.025, .035, .045, 1)
                renderer.render_scene(projection, view, eye, None, config,
                                      brush_slots=config['all_brush_slots'])
                gl.glFinish()
                pixels = ctx.read_pixels()
                visible = np.max(np.abs(pixels.astype(float) - pixels[0, 0]), axis=-1) > 8
                assert visible.mean() > .08
                images.append(pixels)
                stone = renderer.load_model(str(folder / f'castle_tower.{extension}')).materials['Castle_stone']
                texture = renderer._model_texture_id(stone['texture'], stone)
                gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
                assert gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D, 0, gl.GL_TEXTURE_WIDTH) == 1024
            # Includes the brick colour as well as silhouette and material grouping.
            assert np.mean(np.max(np.abs(images[0].astype(float) - images[1]), axis=-1) > 8) < .01
            assert glh.drain_gl_errors() == []
        finally:
            renderer.cleanup()
