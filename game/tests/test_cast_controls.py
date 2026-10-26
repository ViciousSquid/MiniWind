"""The cast key (K) in its two prototype modes, and the hands on the mouse:
left the main hand, right the off hand (its weapon or a shield bash)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from .fio_logic import FioLogic


class _Thing:
    def __init__(self, name, pos=(0.0, 0.0, 0.0), **props):
        self.pos = list(pos)
        self.properties = {"name": name, "display_name": name, **props}


class _Player:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.angle = 0.0                    # facing +z
        self.camera_height = 48.0


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = _Player()


def _session(mode, *things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    s.cast_mode = lambda: mode
    c = s.game.character
    c.active_spell = "flare"
    c.can_use_magic = lambda: True
    c.health = c.max_health
    s.casts = []
    s.game.cast_active_spell = lambda: SimpleNamespace(cast=True, reason="", roll=None)
    s._spawn_player_spell_projectile = lambda spell, aim=None: s.casts.append(
        s._cast_point(aim, [0.0, 48.0, 0.0], 1000.0))
    s._magic_cast_fx = lambda *a, **k: None
    return s


def test_facing_mode_casts_straight_out_along_the_facing():
    s = _session("facing")
    assert s.cast_key()
    assert not s.spell_aiming
    (point,) = s.casts
    assert point[0] == pytest.approx(0.0) and point[2] == pytest.approx(1000.0)


def test_aimed_mode_waits_for_a_click_then_casts_there_and_turns_to_it():
    s = _session("aimed")
    assert s.cast_key() and s.spell_aiming and not s.casts
    assert s.escape_closes_modal()               # Escape belongs to the aim
    s.cast_at([300.0, 48.0, 0.0])
    assert not s.spell_aiming
    (point,) = s.casts
    assert point == [300.0, 48.0, 0.0]
    assert s.logic.player.angle == pytest.approx(math.pi / 2)   # faces +x


def test_k_again_puts_the_spell_away():
    s = _session("aimed")
    s.cast_key()
    s.cast_key()
    assert not s.spell_aiming and not s.casts


def test_a_spell_cast_on_oneself_needs_no_aim():
    s = _session("aimed")
    s.game.character.active_spell = "heal_minor"
    assert s.cast_key()
    assert not s.spell_aiming


def test_right_mouse_no_longer_casts():
    s = _session("facing")
    s.fire_player_weapon(s.logic, "secondary")
    assert not s.casts


def test_right_mouse_with_a_shield_worn_bashes_the_foe_in_front():
    bandit = _Thing("Bandit", (0.0, 0.0, 60.0), type="npc", health=40, max_health=40,
                    aggression="hostile")
    s = _session("facing", bandit)
    from ..rpg import items, inventory as inv
    inv.add_item(s.game.character.inventory, items.make("iron_shield", 1))
    s.game.equip("iron_shield")
    s._acquire_target = lambda reach, aim_dot=None: bandit    # the foe in front
    s.fire_player_weapon(s.logic, "secondary")
    expected = s.BASH_DAMAGE + 8 * s.BASH_ARMOUR_SHARE
    assert bandit.properties["health"] == 40 - round(expected)
    assert s._offhand_cooldown > 0 and not s.casts
