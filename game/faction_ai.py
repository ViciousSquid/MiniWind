"""
MiniWind's factions, handed to Fio's monster AI as a dense hostility model.

Fio's MonsterAI decides who fights whom from an
:class:`engine.hostility.HostilityModel` when a game installs one (see that
module). MiniWind's is built from its faction table
(``game/data/factions.json`` through :mod:`game.rpg.factions`):

* ``hostile[a, b]``: faction *a* attacks faction *b* (their relationship is
  hostile). Wildlife is neutral to villagers, so deer no longer fight
  farmers; guards and bandits still fight.
* ``hunts_player[a]``: faction *a* is hostile to the player (bandits,
  cultists, monsters), overridden per actor by its ``aggression``: an actor
  whose aggression is "hostile" goes for the player (a wolf, a guard chasing
  a fugitive, a villager the player provoked), a "passive" or "defensive"
  one does not.

Installed with the session and removed with it (:func:`install`,
:func:`uninstall`), together with the combat-loadout hook, so neither can
outlive a play session.
"""

from __future__ import annotations

import numpy as np

from .rpg import factions


def build_model():
    """The hostility model for the current faction table."""
    from engine.hostility import HostilityModel
    from . import data
    names = [factions.normalise_team(n)
             for n in (data.load("factions") or {}).get("factions", [])]
    names = [n for n in dict.fromkeys(names) if n]
    g = len(names)
    hostile = np.zeros((g, g), dtype=bool)
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            hostile[i, j] = i != j and factions.is_hostile(a, b)
    hunts = np.array([factions.is_hostile(factions.PLAYER, n) for n in names], dtype=bool)
    return HostilityModel(names, hostile, hunts, hunts_key="aggression",
                          hunts_values=("hostile",))


def install(logic) -> None:
    """Give *logic*'s monster AI MiniWind's hostility and combat loadout."""
    ai = getattr(logic, "monster_ai", None)
    if ai is None:
        return
    ai.set_hostility(build_model())
    from . import combat_loadout
    combat_loadout.install_engine_hook()


def uninstall(logic) -> None:
    """Take them back out (the symmetric half of :func:`install`)."""
    ai = getattr(logic, "monster_ai", None)
    if ai is not None and getattr(ai, "hostility", None) is not None:
        ai.set_hostility(None)
    from . import combat_loadout
    combat_loadout.uninstall_engine_hook()
