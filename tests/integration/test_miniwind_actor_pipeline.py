"""MiniWind actors on Fio 2.5.5's dense render path -- one feature per test.

Fio draws every monster from its entity projection: the logic thread refreshes
each monster's render snapshot once per frame, :class:`engine.entity_table.
EntityTable` re-resolves a monster's sprite only when the inputs it watches
change, and the instanced sprite pass reads columns. MiniWind's actors enter
that pipeline without a renderer of their own:

* **identity** -- a slain head actor, a gibbed body -- is a value in a field
  Fio already watches (``custom_dead``), derived in :mod:`game.actor_look`;
* the **per-frame look** -- heading, hit flash, fade -- rides the same
  snapshot into three warm columns (:meth:`EntityTable.refresh_actor_look`).

These tests drive the real classes and the real projection, headless. The GL
tier (``tests/visual/test_miniwind_actor_look.py``) checks the pixels.
"""

import math
import os

import numpy as np
import pytest

pytestmark = pytest.mark.qt          # editor.things imports PyQt5 (no display)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _npc(head="head05", **props):
    from game.entities import NPC
    p = {"name": "Villager", "head": head}
    p.update(props)
    return NPC(pos=[0.0, 64.0, 0.0], properties=p)


def _wolf(**props):
    from game.entities import Creature
    p = {"name": "Wolf", "npc_role": "wolf"}
    p.update(props)
    return Creature(pos=[100.0, 64.0, 0.0], properties=p)


def _publish(things, table=None, epoch=1):
    """What LogicThread._update_render_state does with the entity half."""
    from engine.entity_table import EntityTable
    table = table if table is not None else EntityTable()
    table.begin_frame(things, epoch)
    refs = np.empty(table.count, dtype=object)
    for i, thing in enumerate(things):
        refs[i] = thing
    for i in table.monster_slots:
        refs[i] = things[int(i)].get_render_snapshot()
    table.refresh_actor_look(refs, table.monster_slots)
    return table, refs


def _drawn_path(table, slot):
    """The asset path the sprite pass will load for *slot* (first candidate)."""
    recipe = table.sprite_recipes()[int(table.sprite_key_id[slot])]
    key, filename, subfolder, _cache = recipe[0]
    return "assets/%s/%s" % (subfolder, filename)


# ---------------------------------------------------------------------------
# Identity: which picture, through the field Fio already watches
# ---------------------------------------------------------------------------

def test_a_living_head_actor_draws_its_head():
    npc = _npc()
    table, _ = _publish([npc])
    assert _drawn_path(table, 0) == "assets/sprites/heads/head05.png"


def test_a_slain_head_actor_keeps_its_head_with_the_dead_mark():
    from PIL import Image
    npc = _npc()
    table, _ = _publish([npc])
    npc.properties["dead"] = True
    table, _ = _publish([npc], table)          # same epoch: the warm path

    path = _drawn_path(table, 0)
    assert path == "assets/sprites/heads/dead_cache/head05__dead.png"
    composite = Image.open(os.path.join(ROOT, path)).convert("RGBA")
    head = Image.open(os.path.join(ROOT, "assets/sprites/heads/head05.png")).convert("RGBA")
    assert composite.size == head.size
    assert composite.tobytes() != head.tobytes(), "the dead mark was not painted on"


def test_a_gibbed_body_draws_its_splatter():
    from game.rpg.game_state import _mark_gibbed
    npc = _npc()
    table, _ = _publish([npc])
    npc.properties["dead"] = True
    assert _mark_gibbed(npc.properties, damage=10_000, new_health=0)
    table, _ = _publish([npc], table)
    assert _drawn_path(table, 0) == npc.properties["gib_sprite"]
    assert "blood_stains" in npc.properties["gib_sprite"]


def test_a_magical_kill_draws_the_disintegration_splatter():
    from game.rpg.game_state import _mark_gibbed
    npc = _npc()
    npc.properties["dead"] = True
    assert _mark_gibbed(npc.properties, damage=10_000, new_health=0, magical=True)
    table, _ = _publish([npc])
    assert "disintegrate" in _drawn_path(table, 0)


def test_a_revived_actor_is_its_living_head_again():
    from game import actor_look
    from game.rpg.game_state import _mark_gibbed
    npc = _npc()
    npc.properties["dead"] = True
    _mark_gibbed(npc.properties, damage=10_000, new_health=0)
    table, _ = _publish([npc])

    npc.properties.pop("dead")                   # Fio's play-start reset
    actor_look.reset_transient([npc])            # MiniWind's, right after it
    table, _ = _publish([npc], table)
    assert "gibbed" not in npc.properties
    assert _drawn_path(table, 0) == "assets/sprites/heads/head05.png"
    # ...and if it dies again it is a head with the dead mark, not a splatter.
    npc.properties["dead"] = True
    table, _ = _publish([npc], table)
    assert _drawn_path(table, 0).endswith("head05__dead.png")


def test_a_role_art_creature_uses_its_types_corpse():
    wolf = _wolf()
    wolf.properties["dead"] = True
    table, _ = _publish([wolf])
    assert "custom_dead" not in wolf.properties
    assert _drawn_path(table, 0) == "assets/sprites/monsters/human/dead.png"


def test_the_2d_icon_follows_the_same_death_look():
    npc = _npc()
    npc.properties["dead"] = True
    assert npc.get_sprite_path().endswith("heads/dead_cache/head05__dead.png")


def test_a_hit_flash_never_re_resolves_the_sprite():
    """The flash changes every frame; the picture does not. It must stay off
    the sprite-state tuple, or every hit would re-intern a recipe."""
    npc = _npc()
    table, _ = _publish([npc])
    key, recipes = int(table.sprite_key_id[0]), len(table.sprite_recipes())
    for flash in (0.18, 0.1, 0.02, 0.0):
        npc.properties["_hit_flash"] = flash
        table, _ = _publish([npc], table)
        assert int(table.sprite_key_id[0]) == key
    assert len(table.sprite_recipes()) == recipes


# ---------------------------------------------------------------------------
# Per-frame look: through the snapshot into the warm columns
# ---------------------------------------------------------------------------

def test_a_head_actor_turns_to_face_its_heading():
    from game.actor_look import HEAD_FACING_OFFSET
    npc = _npc(_facing=0.7)
    table, _ = _publish([npc])
    assert table.sprite_orient[0] == 1.0
    assert table.sprite_heading[0] == pytest.approx(0.7 + HEAD_FACING_OFFSET)
    npc.properties["_facing"] = -1.2
    table, _ = _publish([npc], table)
    assert table.sprite_heading[0] == pytest.approx(-1.2 + HEAD_FACING_OFFSET)


def test_a_role_art_actor_stays_an_upright_billboard():
    wolf = _wolf(_facing=0.7)
    table, _ = _publish([wolf])
    assert table.sprite_orient[0] == 0.0


def test_the_reaper_declares_its_head_outright():
    npc = _npc(is_head=True, custom_idle="assets/sprites/heads/reaper.png")
    table, _ = _publish([npc])
    assert table.sprite_orient[0] == 1.0


def test_a_hit_flash_tints_red_and_fades_out():
    npc = _npc(_hit_flash=0.1)
    table, _ = _publish([npc])
    r, g, b, strength = table.sprite_tint[0]
    assert (r, g, b) == pytest.approx((1.0, 0.15, 0.1))
    assert strength == pytest.approx(0.4)
    npc.properties["_hit_flash"] = 0.5                 # capped
    table, _ = _publish([npc], table)
    assert table.sprite_tint[0][3] == pytest.approx(0.75)
    npc.properties["_hit_flash"] = 0.0
    table, _ = _publish([npc], table)
    assert np.all(table.sprite_tint[0] == 0.0)


def test_the_reaper_fades_in_and_out():
    npc = _npc(_opacity=0.25)
    table, _ = _publish([npc])
    assert table.sprite_fade[0] == pytest.approx(0.75)
    npc.properties["_opacity"] = 1.0
    table, _ = _publish([npc], table)
    assert table.sprite_fade[0] == pytest.approx(0.0)


def test_a_plain_fio_monster_keeps_the_stock_billboard():
    from editor.things import Monster
    grunt = Monster(pos=[0.0, 64.0, 0.0], properties={"name": "grunt"})
    npc = _npc(_facing=1.0, _hit_flash=0.1, _opacity=0.5)
    table, _ = _publish([grunt, npc])
    assert table.sprite_orient[0] == 0.0 and table.sprite_heading[0] == 0.0
    assert np.all(table.sprite_tint[0] == 0.0) and table.sprite_fade[0] == 0.0
    assert table.sprite_orient[1] == 1.0


def test_a_level_without_actor_looks_pays_nothing_and_resets():
    from editor.things import Monster
    grunts = [Monster(pos=[i * 10.0, 64.0, 0.0], properties={"name": "g%d" % i})
              for i in range(4)]
    table, _ = _publish(grunts)
    assert not table._look_live
    assert not np.any(table.sprite_orient[:4])


def test_a_structural_change_clears_the_rows_that_moved():
    npc = _npc(_hit_flash=0.2)
    wolf = _wolf()
    table, _ = _publish([npc, wolf])
    assert table.sprite_tint[0][3] > 0.0
    table, _ = _publish([wolf], table, epoch=2)        # npc removed; wolf moved
    assert np.all(table.sprite_tint[0] == 0.0)


def test_the_look_columns_reach_the_instance_payload():
    """What draw_sprites_instanced packs, column for column (no GL needed)."""
    from engine.renderer_core import BaseRenderer
    layout = dict((loc, (n, off)) for loc, n, off in BaseRenderer.SPRITE_INSTANCE_LAYOUT)
    assert BaseRenderer.SPRITE_INSTANCE_FLOATS == 12
    assert layout[3] == (1, 5) and layout[4] == (1, 6)     # heading, orient
    assert layout[5] == (4, 7) and layout[6] == (1, 11)    # tint, fade
