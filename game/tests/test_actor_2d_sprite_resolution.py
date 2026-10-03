from types import SimpleNamespace

from game.entities import _actor_2d_sprite_path


def _actor(**properties):
    return SimpleNamespace(properties=properties)


def test_head_sprite_is_preferred_for_npc_2d_view():
    actor = _actor(
        type="npc",
        npc_role="guard",
        head="head07",
        custom_idle="assets/sprites/miniwind/guard.png",
    )
    assert _actor_2d_sprite_path(actor) == "assets/sprites/heads/head07.png"


def test_guard_head_sprite_is_preferred():
    actor = _actor(
        type="npc",
        npc_role="guard",
        head="guard03",
        custom_idle="assets/sprites/miniwind/guard.png",
    )
    assert _actor_2d_sprite_path(actor) == "assets/sprites/heads/guard03.png"


def test_custom_idle_is_used_when_no_head_is_assigned():
    actor = _actor(
        type="creature",
        npc_role="wolf",
        head="",
        custom_idle="assets/sprites/miniwind/wolf.png",
    )
    assert _actor_2d_sprite_path(actor) == "assets/sprites/miniwind/wolf.png"


def test_role_art_is_the_final_fallback():
    actor = _actor(
        type="npc",
        npc_role="merchant",
        head="",
        custom_idle="",
    )
    assert _actor_2d_sprite_path(actor) == "assets/sprites/miniwind/merchant.png"
