"""
Tests for the overhead view's ground-quad layering (:mod:`engine.overhead_sprite`).

Blood, gib splatter, actors, their weapons and the corpse mark are all flat
quads lying in the floor's own plane. Spaced a world unit apart they z-fight:
the decal flickers against the floor and an actor standing in a pool of blood
sinks into it. The layer constants are what keep them apart, and this pins the
order and the clearances so a future edit cannot quietly re-stack them.

Run:  python -m pytest engine/tests/test_ground_layers.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import overhead_sprite as osp


def test_every_ground_quad_clears_the_floor():
    for name in ("DECAL_Y", "GIB_Y", "ACTOR_Y", "CORPSE_MARK_Y", "EFFECT_Y"):
        assert getattr(osp, name) >= osp.GROUND_CLEARANCE, name
    assert osp.GROUND_CLEARANCE > 0.0


def test_actors_always_sit_above_every_decal():
    """The reported bug: NPCs, monsters and the player under the blood."""
    assert osp.DECAL_Y < osp.GIB_Y < osp.ACTOR_Y


def test_a_weapon_and_a_corpse_mark_ride_above_their_actor():
    assert osp.WEAPON_Y_LIFT > 0.0
    assert osp.ACTOR_Y + osp.WEAPON_Y_LIFT < osp.CORPSE_MARK_Y


def test_effects_are_the_one_layer_reserved_above_actors():
    # Fire and explosions are allowed to cover an actor; nothing else is.
    assert osp.EFFECT_Y > osp.CORPSE_MARK_Y > osp.ACTOR_Y


def test_layers_are_far_enough_apart_to_beat_depth_precision():
    # A single world unit is what used to fight; every gap is comfortably more.
    gaps = [osp.GIB_Y - osp.DECAL_Y,
            osp.ACTOR_Y - osp.GIB_Y,
            osp.CORPSE_MARK_Y - (osp.ACTOR_Y + osp.WEAPON_Y_LIFT)]
    assert min(gaps) >= 4.0


def test_the_renderer_defaults_to_the_actor_layer():
    """A caller that names no layer is drawing an actor, not a decal."""
    import inspect
    default = inspect.signature(osp.OverheadSpriteRenderer).parameters["y_offset"].default
    assert default == osp.ACTOR_Y


def test_decals_can_be_drawn_without_writing_depth():
    """Two pools in one plane must blend, not fight.

    Clearing the floor was not enough on its own: coplanar decals still wrote
    depth and half-failed GL_LESS against each other across the overlap, which
    is the flicker. The draw call takes depth_write so the decal pass can turn
    it off.
    """
    import inspect
    for method in (osp.OverheadSpriteRenderer.draw,
                   osp.OverheadSpriteRenderer._draw_texture):
        params = inspect.signature(method).parameters
        assert "depth_write" in params
        assert params["depth_write"].default is True    # actors still write


def test_each_new_stain_is_laid_a_step_above_the_last():
    """So overlapping pools have a definite order instead of one shared plane."""
    from engine.monster_constants import BLOOD_STAIN_LAYER_STEP, BLOOD_STAIN_LAYERS

    assert BLOOD_STAIN_LAYER_STEP > 0.0
    assert BLOOD_STAIN_LAYERS > 1
    highest = osp.DECAL_Y + (BLOOD_STAIN_LAYERS - 1) * BLOOD_STAIN_LAYER_STEP
    # The whole climb has to stay under the layer above, or blood would end up
    # over the gib splatter it caused.
    assert highest < osp.GIB_Y
