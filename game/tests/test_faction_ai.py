"""
MiniWind's factions as Fio's hostility model (:mod:`game.faction_ai`), and
its game hooks' lifecycle: installed with a session, removed with it.

Run:  python -m pytest game/tests/test_faction_ai.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import combat_loadout, faction_ai      # noqa: E402


def test_the_model_follows_the_faction_table():
    m = faction_ai.build_model()
    assert m.is_hostile("guards", "bandits") and m.is_hostile("bandits", "guards")
    assert not m.is_hostile("wildlife", "villagers")       # deer leave farmers be
    assert not m.is_hostile("villagers", "guards")
    assert m.is_hostile("villagers", "monsters")


def test_who_goes_for_the_player():
    m = faction_ai.build_model()
    assert m.hunts({"team": "bandits"})                     # hostile faction
    assert not m.hunts({"team": "villagers"})
    assert not m.hunts({"team": "wildlife", "aggression": "passive"})   # a deer
    assert m.hunts({"team": "wildlife", "aggression": "hostile"})       # a wolf
    assert m.hunts({"team": "guards", "aggression": "hostile"})         # a chase
    assert not m.hunts({"team": "bandits", "aggression": "defensive"})


class _AI:
    def __init__(self):
        self.hostility = None

    def set_hostility(self, model):
        self.hostility = model


class _Logic:
    def __init__(self):
        self.monster_ai = _AI()


def test_install_and_uninstall_are_symmetric():
    from engine.monster_ai import MonsterAI
    logic = _Logic()
    faction_ai.install(logic)
    try:
        assert logic.monster_ai.hostility is not None
        assert MonsterAI._attack_style_hook is combat_loadout.attack_style_for
    finally:
        faction_ai.uninstall(logic)
    assert logic.monster_ai.hostility is None
    assert MonsterAI._attack_style_hook is None
