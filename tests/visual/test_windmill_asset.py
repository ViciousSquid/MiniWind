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


def test_the_placed_mill_keeps_its_silhouette_at_rest_and_only_the_sails_move():
    import json
    import glm
    import OpenGL.GL as gl
    from editor.editor_state import EditorState
    from editor.things import Light, Prop
    from engine.logic_thread import LogicThread
    from engine.renderer.forward import ForwardRenderer
    from engine.threaded_game_state import ThreadedGameState
    from game.windmills import ROTOR_FOR, SPIN_UP_SECONDS, Windmills

    root = Path(__file__).resolve().parents[2]
    folder = root / 'assets/models'
    logic = LogicThread(ThreadedGameState(), EditorState())
    world = json.loads((root / 'maps/miniwind_world.json').read_text())
    tower_record = next(t for t in world['things'] if t['properties'].get('name') == 'windmill')
    rotor_record = next(t for t in world['things']
                        if t['properties'].get(ROTOR_FOR) == tower_record['properties']['id'])
    body = Prop(pos=tower_record['pos'], properties=tower_record['properties'])
    rotor = Prop(pos=rotor_record['pos'], properties=rotor_record['properties'])
    complete = Prop.for_model(str(folder / 'windmill.glb'))
    complete.pos = list(body.pos)
    complete.properties['rotation'] = list(body.properties['rotation'])
    complete.properties['scale'] = list(body.properties['scale'])
    logic.editor_state.things.extend([body, rotor])
    mills = Windmills(logic)
    mills.install()
    with glh.GLTestContext(384, 384) as ctx:
        renderer = ForwardRenderer(None)
        renderer.shadows_enabled = False
        try:
            basis = glm.rotate(glm.mat4(1), glm.radians(body.properties['rotation'][1]), glm.vec3(0, 1, 0))
            eye = glm.vec3(*body.pos) + glm.vec3(basis * glm.vec4(100, 650, 1800, 0))
            projection = glm.ortho(-500, 500, -500, 500, 1, 6000)
            view = glm.lookAt(eye, glm.vec3(*body.pos) + glm.vec3(0, 420, 0), glm.vec3(0, 1, 0))
            light_pos = glm.vec3(*body.pos) + glm.vec3(basis * glm.vec4(-500, 1200, 1000, 0))
            light = Light(pos=list(light_pos), properties={
                'color': [255, 240, 225], 'intensity': 1.0, 'radius': 6000,
                'casts_shadows': False})

            def draw(things):
                config = glh.render_config(all_things=things + [light], shadows_enabled=False)
                ctx.bind()
                gl.glClearColor(0.02, 0.03, 0.05, 1)
                renderer.render_scene(projection, view, eye, None, config,
                                      brush_slots=config['all_brush_slots'])
                gl.glFinish()
                return ctx.read_pixels()

            full = draw([complete])
            at_rest = draw([body, rotor])
            assert np.mean(np.max(np.abs(full.astype(float) - at_rest), axis=-1) > 8) < 0.005
            mills.update(SPIN_UP_SECONDS)
            turning = draw([body, rotor])
            changed = np.max(np.abs(turning.astype(float) - at_rest), axis=-1) > 8
            assert changed.mean() > 0.015
            assert body.properties['rotation'] == complete.properties['rotation']
            assert glh.drain_gl_errors() == []
        finally:
            mills.clear()
            logic.stop()
            renderer.cleanup()
