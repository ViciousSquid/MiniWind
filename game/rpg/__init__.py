"""
Miniwind RPG — the first-party fantasy role-playing core.

This package is the *game*: a self-contained, engine-agnostic simulation of an
Elder-Scrolls-style RPG — attributes, skills that improve with use, races,
classes, birthsigns, levelling, an item/equipment model, melee & archery & magic
combat rules, spells, quests, guild factions with reputation, loot tables and a
saveable game world. None of it imports PyQt or OpenGL, so the whole game can be
driven and unit-tested head-lessly; the thin ``game`` Fio adapter
(HUD, input, entities, screens) wires it into the live engine.

Design: the rules live here as pure data + functions; state lives on a
:class:`~game.rpg.character.Character` (the player) and on ordinary
entity ``properties`` dicts (NPCs/creatures), so Fio's stock UUID-matched
serializer persists the world for free and the whole thing round-trips through
save/load with no new format.
"""

from __future__ import annotations

# Version of the Miniwind game itself (distinct from the Fio plugin-API level).
GAME_NAME = "Miniwind"
GAME_VERSION = "1.0.0"
GAME_TAGLINE = "A fantasy RPG built on Fio"

__all__ = ["GAME_NAME", "GAME_VERSION", "GAME_TAGLINE"]
