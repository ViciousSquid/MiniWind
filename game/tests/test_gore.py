"""
Headless tests for the gib (overkill death) rule.

A gib is a death from an oversized hit: the body then shows the universal gore
sprite instead of a clean corpse. These cover the pure decision rule
(:mod:`engine.gore`), the max-health baseline recorded on MiniWind actors, and
the game-core wiring that flags a slain creature as gibbed.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ..rpg import gore


def test_normal_kill_does_not_gib():
    # A hit that barely kills a full-health enemy is an ordinary death.
    assert gore.should_gib({"max_health": 100}, damage=110, new_health=-10) is False


def test_oversized_hit_gibs():
    # >= 1.2x max health in one blow gibs; a fifth over full health is enough.
    assert gore.GIB_DAMAGE_FRACTION == 1.2
    assert gore.should_gib({"max_health": 100}, damage=200, new_health=-100) is True
    assert gore.should_gib({"max_health": 100}, damage=120, new_health=-20) is True


def test_kill_just_under_threshold_does_not_gib():
    # A lethal blow below 1.2x max health is an ordinary death, not a gib.
    assert gore.should_gib({"max_health": 100}, damage=119, new_health=-19) is False


def test_gib_is_a_pure_ratio_of_max_health():
    # The rule is purely proportional: a small enemy gibs from a proportionally
    # large hit (no absolute-damage floor).
    assert gore.should_gib({"max_health": 5}, damage=6, new_health=-1) is True
    assert gore.should_gib({"max_health": 5}, damage=5, new_health=0) is False   # 5 < 6



def test_survived_hit_does_not_gib():
    assert gore.should_gib({"max_health": 100}, damage=300, new_health=25) is False


def test_max_health_falls_back_to_current_health():
    # Without an explicit max_health, current health is the baseline.
    assert gore.max_health({"health": 60}) == 60
    # Never zero (avoids a divide-by-nothing in the fraction test).
    assert gore.max_health({}) == 1


def test_mark_gibbed_only_flags_on_overkill():
    survivor = {"max_health": 100}
    assert gore.mark_gibbed(survivor, 110, -10) is False
    assert "gibbed" not in survivor

    victim = {"max_health": 100}
    assert gore.mark_gibbed(victim, 250, -150) is True
    assert victim["gibbed"] is True


def test_miniwind_actors_record_max_health():
    from .. import entities
    npc = entities.NPC(pos=[0, 0, 0], properties={"npc_role": "guard"})
    assert npc.properties["max_health"] == npc.properties["health"]
    wolf = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "wolf"})
    assert wolf.properties["max_health"] == wolf.properties["health"]


def test_game_state_wrapper_flags_gibbed():
    # The RPG-core wrapper delegates to engine.gore and is import-guarded.
    from ..rpg.game_state import _mark_gibbed
    props = {"max_health": 30}
    assert _mark_gibbed(props, 60, -30) is True
    assert props.get("gibbed") is True
    assert _mark_gibbed({"max_health": 30}, 10, 20) is False


# --- splatter selection (physical blood vs magical disintegration) ---------
def test_stain_folders_ship_with_defaults():
    from ..rpg import gib
    physical = gib.stain_paths(magical=False)
    magical = gib.stain_paths(magical=True)
    assert len(physical) >= 2 and all(p.endswith(".png") for p in physical)
    assert len(magical) >= 2
    # Sorted mild -> severe by filename.
    assert physical == sorted(physical)
    assert "blood_stains/" in physical[0]
    assert "disintegrate/" in magical[0]


def test_severity_picks_mild_vs_severe_stain():
    from ..rpg import gib
    mild = gib.stain_for(120, 100, magical=False)     # 1.2x -> mildest
    severe = gib.stain_for(400, 100, magical=False)    # >=3x -> severest
    assert "mild" in mild
    assert "severe" in severe
    assert mild != severe


def test_magical_gib_uses_disintegration_splatter():
    from ..rpg.game_state import _mark_gibbed
    physical = {"max_health": 100}
    assert _mark_gibbed(physical, 200, -100, magical=False) is True
    assert physical["gib_magical"] is False
    assert "blood_stains/" in physical["gib_sprite"]

    magical = {"max_health": 100}
    assert _mark_gibbed(magical, 200, -100, magical=True) is True
    assert magical["gib_magical"] is True
    assert "disintegrate/" in magical["gib_sprite"]


# -- gib.mp3: the body explodes ----------------------------------------------------
def _gib_session():
    from types import SimpleNamespace
    from .test_bow_draw import _session
    s, _shots = _session()
    heard = []
    s.play_sound_at = lambda name, pos, volume=1.0, radius=900.0: heard.append((name, tuple(pos))) or True
    s.logic.player = SimpleNamespace(pos=(10.0, 64.0, 20.0), angle=0.0)
    return s, heard


def _body(**props):
    from types import SimpleNamespace
    return SimpleNamespace(pos=[300.0, 56.0, -40.0],
                           properties={"health": 0, "max_health": 50, "npc_role": "villager",
                                       "sprite_width": 96, **props})


def test_an_exploding_body_plays_gib_mp3_once_from_where_it_stood():
    from .. import runtime as rt
    s, heard = _gib_session()
    body = _body(gibbed=True)
    s._gore_hit(body, 200.0, killed=True)
    s._gore_hit(body, 200.0, killed=True)              # more blows on the pieces: once
    assert heard == [(rt.GIB_SOUND, (300.0, 56.0, -40.0))] and rt.GIB_SOUND == "gib.mp3"


def test_an_ordinary_kill_or_a_disintegration_is_not_an_explosion():
    s, heard = _gib_session()
    s._gore_hit(_body(), 40.0, killed=True)            # a clean kill
    s._gore_hit(_body(gibbed=True, gib_magical=True), 200.0, killed=True, magical=True)
    assert heard == []


def test_the_player_blown_apart_plays_it_too():
    from types import SimpleNamespace
    from .. import runtime as rt
    s, heard = _gib_session()
    c = s.game.character
    blow = c.max_health * 3
    c.health = 0                                      # the killing blow has landed
    assert s._gib_player(c, blow, SimpleNamespace(pos=(0.0, 0.0, 0.0)))
    assert heard == [(rt.GIB_SOUND, (10.0, 64.0, 20.0))]


def test_gib_mp3_ships_and_is_found():
    from pathlib import Path
    from .. import runtime as rt
    data = (Path(rt.SOUND_DIR) / rt.GIB_SOUND).read_bytes()
    assert data[:3] == b"ID3" or data[0] == 0xFF
    assert rt.sound_available(rt.GIB_SOUND)


def test_the_explosion_is_heard_from_the_victim_never_the_attacker():
    from .. import runtime as rt
    s, heard = _gib_session()
    body = _body(gibbed=True)
    s._gore_hit(body, 200.0, killed=True, by_player=False, source=[-900.0, 64.0, 500.0])
    assert heard == [(rt.GIB_SOUND, (300.0, 56.0, -40.0))]          # the body, not the attacker
