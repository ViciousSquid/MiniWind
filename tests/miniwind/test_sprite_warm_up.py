"""The sprite array's warm-up, bounded for MiniWind's world.

Fio 3.5.0.1611 fills the sprite texture array up front -- every sprite the
map's rows may draw, and every monster's fight frames -- so that no sprite is
imported (and the array regrown) as it first comes into view. Fio's maps are
small; MiniWind's world has 890 sprite rows and ~500 monster recipes, of which
the opening draws 19 images. Warmed whole, that was 252 layers of 512 x 512
(341 MB of texture, 540 MB resident) and 3.4 s before Play started.

So the warm-up takes the rows within the camera's view distance, and leaves a
monster's fight frames to be imported when they are first drawn: an actor's
attack frame is its own head, and its dead frame is Fio's 341 x 512 stock
corpse, which alone makes every 128 x 128 layer sixteen times the size.
"""

import numpy as np
import pytest

from tests.helpers import gl as glh
from tests.helpers.worlds import make_thing


def _synced(things):
    from engine.entity_table import EntityTable
    table = EntityTable()
    table.begin_frame(things, epoch=1)
    return table


@pytest.mark.qt
def test_fight_frames_are_filed_under_the_monster_that_shows_them():
    """The renderer asks for the fight frames of the monsters it is about to
    draw, not of every monster in the map."""
    from editor.things import Monster

    one = make_thing(Monster, 'one', custom_idle='assets/sprites/heads/head01.png',
                     custom_shoot='assets/sprites/heads/head01.png')
    two = make_thing(Monster, 'two', (64.0, 0.0, 0.0),
                     custom_idle='assets/sprites/heads/head02.png',
                     custom_shoot='assets/sprites/heads/head02.png')
    table = _synced([one, two])
    recipes = table.sprite_recipes()
    key_one, key_two = (int(k) for k in table.sprite_key_id[:2])

    frames_one = table.fight_frame_ids([key_one])
    frames_two = table.fight_frame_ids([key_two])
    names_one = {recipes[i][0][0] for i in frames_one}
    names_two = {recipes[i][0][0] for i in frames_two}
    assert any('_shoot_' in n and 'head01' in n for n in names_one)
    assert any('_dead_' in n for n in names_one)
    assert not any('head02' in n for n in names_one)
    assert any('head02' in n for n in names_two)
    assert table.fight_frame_ids([]) == []
    assert sorted(set(frames_one) | set(frames_two)) == table.fight_frame_ids(
        np.array([key_one, key_two, key_one]))

    # A second monster of a kind adds nothing; a copy of the table keeps them.
    count = len(recipes)
    again = _synced([one, two, make_thing(Monster, 'three', (128.0, 0.0, 0.0),
                                          custom_idle='assets/sprites/heads/head01.png',
                                          custom_shoot='assets/sprites/heads/head01.png')])
    assert len(again.sprite_recipes()) == count
    from engine.entity_table import EntityTable
    copy = EntityTable()
    copy.adopt(table)
    assert copy.fight_frame_ids([key_one]) == frames_one


def test_miniwind_does_not_warm_fight_frames():
    from engine.renderer.forward.passes import PassesMixin
    assert PassesMixin.WARM_FIGHT_FRAMES is False


# -- the warm-up itself (a real GL context) ----------------------------------

SIZE = 96


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(SIZE, SIZE) as ctx:
        yield ctx
    glh.reset_texture_cache()


@pytest.fixture
def renderer(context):
    made = glh.make_renderer()
    yield made
    try:
        made.cleanup()
    except Exception:
        pass


def _solid(rgb, size=16):
    import OpenGL.GL as gl
    image = np.zeros((size, size, 4), dtype=np.uint8)
    image[..., :3] = rgb
    image[..., 3] = 255
    tex = int(gl.glGenTextures(1))
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, size, size, 0,
                    gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, image.tobytes())
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
    return tex


def _billboard(renderer, name, pos, tex_id):
    from editor.things import Prop
    from engine import entity_table

    prop = make_thing(Prop, name, pos, render_mode="billboard",
                      sprite_path="assets/sprites/%s.png" % name,
                      sprite_size=[100.0, 100.0])
    renderer.sprite_textures[entity_table.sprite_candidates(prop)[0][0]] = tex_id
    return prop


def _play_frame(renderer, context, config, eye, target):
    import OpenGL.GL as gl
    projection, view, eye_v = glh.camera_matrices(aspect=1.0, eye=eye, target=target)
    context.bind()
    renderer.render_scene(projection, view, eye_v, None, config,
                          brush_slots=np.empty(0, dtype=np.int32))
    gl.glFinish()


@pytest.mark.gl
@pytest.mark.slow
def test_play_warms_what_the_view_distance_holds_and_no_further(renderer, context,
                                                               monkeypatch):
    """Near sprites are imported in one go, seen or not; one beyond the view
    distance is not imported until it is drawn."""
    from engine import sprite_layers
    from engine.view_distance import ViewDistance

    imports = []
    real = sprite_layers.SpriteLayers._import

    def counted(self, new_ids):
        imports.append(len(new_ids))
        return real(self, new_ids)

    monkeypatch.setattr(sprite_layers.SpriteLayers, '_import', counted)
    renderer.view_distance = ViewDistance(2000.0)
    ahead = _billboard(renderer, "ahead", (0.0, 60.0, 0.0), _solid((255, 0, 0)))
    behind = [_billboard(renderer, "behind%d" % i, (40.0 * i, 60.0, 1200.0),
                         _solid((0, 255, 0)))
              for i in range(4)]
    far_tex = _solid((0, 0, 255))
    far = _billboard(renderer, "far", (0.0, 60.0, -20000.0), far_tex)
    config = glh.render_config(all_brushes=[], all_things=[ahead] + behind + [far],
                               play_mode=True, camera_distance_cull=True)

    eye = (0.0, 60.0, 600.0)
    _play_frame(renderer, context, config, eye, (0.0, 60.0, 0.0))
    assert imports == [5]                       # the one ahead and the four behind
    layers = renderer._sprite_layers
    assert layers.count == 5
    assert layers._layer_by_gl[far_tex] < 0     # the far one: not yet

    _play_frame(renderer, context, config, eye, (0.0, 60.0, 1200.0))
    assert imports == [5]                       # turning round imported nothing

    # Walk to it: imported when it is first drawn, as it always was.
    _play_frame(renderer, context, config, (0.0, 60.0, -19400.0), (0.0, 60.0, -20000.0))
    assert imports == [5, 1]
    assert layers._layer_by_gl[far_tex] >= 0


@pytest.mark.gl
@pytest.mark.slow
def test_the_editor_still_warms_the_whole_map(renderer, context, monkeypatch):
    """Editing has no view distance: every row's sprite is imported at once,
    as Fio does."""
    from engine import sprite_layers

    imports = []
    real = sprite_layers.SpriteLayers._import

    def counted(self, new_ids):
        imports.append(len(new_ids))
        return real(self, new_ids)

    monkeypatch.setattr(sprite_layers.SpriteLayers, '_import', counted)
    things = [_billboard(renderer, "near", (0.0, 60.0, 0.0), _solid((255, 0, 0))),
              _billboard(renderer, "far", (0.0, 60.0, -20000.0), _solid((0, 0, 255)))]
    config = glh.render_config(all_brushes=[], all_things=things)
    _play_frame(renderer, context, config, (0.0, 60.0, 600.0), (0.0, 60.0, 0.0))
    assert imports == [2]
