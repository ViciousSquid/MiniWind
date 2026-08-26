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

from engine import gore


def test_normal_kill_does_not_gib():
    # A hit that barely kills a full-health enemy is an ordinary death.
    assert gore.should_gib({"max_health": 100}, damage=110, new_health=-10) is False


def test_oversized_hit_gibs():
    # >= 1.5x max health in one blow gibs.
    assert gore.should_gib({"max_health": 100}, damage=200, new_health=-100) is True
    assert gore.should_gib({"max_health": 100}, damage=150, new_health=-50) is True


def test_small_absolute_hit_never_gibs():
    # Even huge relative overkill on a tiny enemy needs a real hit (>= GIB_MIN_DAMAGE).
    assert gore.GIB_MIN_DAMAGE == 40
    assert gore.should_gib({"max_health": 5}, damage=30, new_health=-25) is False
    assert gore.should_gib({"max_health": 5}, damage=45, new_health=-40) is True


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
    from game import entities
    npc = entities.NPC(pos=[0, 0, 0], properties={"npc_role": "guard"})
    assert npc.properties["max_health"] == npc.properties["health"]
    wolf = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "wolf"})
    assert wolf.properties["max_health"] == wolf.properties["health"]


def test_game_state_wrapper_flags_gibbed():
    # The RPG-core wrapper delegates to engine.gore and is import-guarded.
    from game.rpg.game_state import _mark_gibbed
    props = {"max_health": 30}
    assert _mark_gibbed(props, 60, -30) is True
    assert props.get("gibbed") is True
    assert _mark_gibbed({"max_health": 30}, 10, 20) is False
