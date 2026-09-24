"""MiniWind's actor looks, drawn by Fio 2.5.5's instanced sprite pass.

The headless half (``tests/integration/test_miniwind_actor_pipeline.py``)
proves the right values reach the entity projection's columns. This half
proves the pixels: each look is drawn by the *instanced* pass on a real GL
context, one feature per test --

* the hit flash tints the actor red;
* the reaper's fade makes it translucent, then invisible;
* a head actor's billboard turns with its heading, and a role-art actor's
  does not;
* in overhead play a head actor lies flat on the ground;
* the inspector's hover tints exactly one actor, and never hides a flash.

Every scene is one or two actors on a black background, drawn with their
real head art (the sprite pass resolves sprite textures from the assets, not
from the brush texture loader), so each assertion compares the frame with and
without the one look under test.
"""

import numpy as np
import pytest

from tests.helpers import gl as glh

pytestmark = [pytest.mark.gl, pytest.mark.qt]

SIZE = 160


@pytest.fixture
def context():
    glh.reset_texture_cache()
    with glh.GLTestContext(SIZE, SIZE) as ctx:
        yield ctx
    glh.reset_texture_cache()


@pytest.fixture
def renderer(context):
    from engine.renderer_F import Renderer_F
    made = Renderer_F(lambda name, subfolder: 0, 64, 4096, None)
    made.update_grid_buffers(4096, 64)
    made.set_sprite_textures({})
    assert 'sprite_instanced' in made.shaders, "the instanced sprite program did not compile"
    yield made
    try:
        made.cleanup()
    except Exception:
        pass


def _npc(name="Villager", pos=(0.0, 64.0, 0.0), **props):
    from game.entities import NPC
    p = {"name": name, "head": "head05", "id": "npc-" + name,
         "sprite_width": 120, "sprite_height": 120}
    p.update(props)
    return NPC(pos=list(pos), properties=p)


def _wolf(pos=(0.0, 64.0, 0.0), **props):
    from game.entities import Creature
    p = {"name": "Wolf", "npc_role": "wolf", "id": "wolf-1",
         "sprite_width": 120, "sprite_height": 120}
    p.update(props)
    return Creature(pos=list(pos), properties=p)


def _render(renderer, context, things, look=None, eye=glh.CAMERA_EYE,
            target=glh.CAMERA_TARGET):
    """One frame through the numeric path, published as the logic thread does."""
    import OpenGL.GL as gl
    from engine.entity_table import EntityTable
    from engine.render_table import RenderTable

    table = EntityTable()
    hidden = table.begin_frame(things, 1)
    refs = np.empty(table.count, dtype=object)
    for i, thing in enumerate(things):
        refs[i] = thing
    for i in table.monster_slots:
        refs[i] = things[int(i)].get_render_snapshot()
    table.refresh_actor_look(refs, table.monster_slots)

    brushes = RenderTable()
    brushes.sync([], 1)
    projection, view, eye_v = glh.camera_matrices(aspect=1.0, eye=eye, target=target)
    config = glh.render_config(all_brushes=[], all_things=list(refs))
    config.update(render_table=brushes, render_refs=np.empty(0, dtype=object),
                  all_brush_slots=np.empty(0, dtype=np.int32),
                  entity_table=table, entity_refs=refs,
                  visible_thing_slots=np.arange(table.count, dtype=np.int32),
                  thing_hidden=hidden, sprite_look=look or {})
    renderer.view_distance.fog_enabled = False
    assert renderer.will_instance_sprites(config, np.empty(0, dtype=np.int32))
    context.bind()
    gl.glClearColor(0.0, 0.0, 0.0, 1.0)
    renderer.render_scene(projection, view, eye_v, [], list(refs), None, config,
                          brush_slots=np.empty(0, dtype=np.int32))
    gl.glFinish()
    return context.read_pixels().astype(np.int16)


def _lit(image):
    """Mask of pixels something was drawn on."""
    return image.sum(axis=-1) > 30


def _mean_colour(image):
    mask = _lit(image)
    assert mask.any(), "nothing was drawn"
    return image[mask].mean(axis=0)


# ---------------------------------------------------------------------------

def _changed(a, b, level=30):
    """How many pixels differ by more than *level* in some channel."""
    return int((np.abs(a - b).max(axis=-1) > level).sum())


def test_the_hit_flash_tints_the_actor_red(renderer, context):
    plain = _mean_colour(_render(renderer, context, [_npc()]))
    hit = _mean_colour(_render(renderer, context, [_npc(_hit_flash=0.18)]))
    assert hit[0] > plain[0] + 40, "no red flash: %s -> %s" % (plain, hit)
    assert hit[1] < plain[1] - 20, "the flash did not pull green down: %s -> %s" % (plain, hit)


def test_the_reaper_fades_to_translucent_then_invisible(renderer, context):
    solid = _render(renderer, context, [_npc(_opacity=1.0)])
    half = _render(renderer, context, [_npc(_opacity=0.5)])
    gone = _render(renderer, context, [_npc(_opacity=0.0)])
    assert glh.is_blank(gone), "an actor at opacity 0 was still drawn"
    mask = _lit(solid)
    ratio = half[mask].sum() / float(solid[mask].sum())
    assert 0.35 < ratio < 0.65, "opacity 0.5 drew at %.2f of full brightness" % ratio


def test_a_head_actor_turns_with_its_heading(renderer, context):
    import math
    a = _render(renderer, context, [_npc(_facing=0.3)])
    b = _render(renderer, context, [_npc(_facing=0.3 + math.pi)])
    full = _render(renderer, context, [_npc(_facing=0.3 + 2 * math.pi)])
    assert _changed(a, b) > 40, "turning the heading by 180 degrees did not turn the sprite"
    assert _changed(a, full) == 0, "a full turn should draw the same sprite"


def test_a_role_art_actor_ignores_its_heading(renderer, context):
    a = _render(renderer, context, [_wolf(_facing=0.3)])
    b = _render(renderer, context, [_wolf(_facing=2.9)])
    assert not glh.is_blank(a)
    assert float(np.abs(a - b).mean()) == 0.0


OVERHEAD_EYE = (0.0, 900.0, 1.0)
OVERHEAD_TARGET = (0.0, 0.0, 0.0)


def test_in_overhead_play_a_head_actor_lies_on_the_ground(renderer, context):
    upright = _render(renderer, context, [_npc(_facing=0.0)],
                      eye=OVERHEAD_EYE, target=OVERHEAD_TARGET)
    ground = _render(renderer, context, [_npc(_facing=0.0)],
                     look={"ground": True, "ground_lift": 38.0, "ground_size": 128.0},
                     eye=OVERHEAD_EYE, target=OVERHEAD_TARGET)
    # Seen from straight above, an upright billboard is edge-on-ish but still
    # camera-facing; a ground quad is a full square footprint.
    assert _lit(ground).sum() > _lit(upright).sum(), (
        "the ground quad should cover the overhead sprite size, not the billboard")
    # ...and it turns on the ground with its heading.
    turned = _render(renderer, context, [_npc(_facing=1.2)],
                     look={"ground": True, "ground_lift": 38.0, "ground_size": 128.0},
                     eye=OVERHEAD_EYE, target=OVERHEAD_TARGET)
    assert _changed(turned, ground) > 40


def test_ground_mode_leaves_ordinary_sprites_standing(renderer, context):
    look = {"ground": True, "ground_lift": 38.0, "ground_size": 128.0}
    a = _render(renderer, context, [_wolf()], eye=OVERHEAD_EYE, target=OVERHEAD_TARGET)
    b = _render(renderer, context, [_wolf()], look=look,
                eye=OVERHEAD_EYE, target=OVERHEAD_TARGET)
    assert float(np.abs(a - b).mean()) == 0.0


def test_the_inspector_hover_tints_exactly_one_actor(renderer, context):
    left, right = (-120.0, 64.0, 0.0), (120.0, 64.0, 0.0)
    pair = [_npc("A", left), _npc("B", right)]
    plain = _render(renderer, context, pair)
    hovered = _render(renderer, context, [_npc("A", left), _npc("B", right)],
                      look={"highlight_slot": 0})
    half = SIZE // 2
    assert _changed(hovered[:, :half], plain[:, :half]) > 20
    assert _changed(hovered[:, half:], plain[:, half:], level=0) == 0


def test_a_hit_flash_wins_over_the_hover_tint(renderer, context):
    flashing = _render(renderer, context, [_npc(_hit_flash=0.18)])
    both = _render(renderer, context, [_npc(_hit_flash=0.18)],
                   look={"highlight_slot": 0})
    assert float(np.abs(both - flashing).mean()) == 0.0
