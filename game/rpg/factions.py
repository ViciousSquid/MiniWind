"""
Faction / team relationships for the Miniwind RPG plugin.

Fio monsters already carry a ``team`` string, and the core ``MonsterAI`` is
team-aware: same-team monsters never target or crossfire each other, and an
awake monster prefers an enemy-team monster over the player
(``engine/monster_ai.py``). This module layers the *smallest possible* faction
model on top of that: given two team names, what is their default relationship?

    relationship("guards", "bandits")  -> "hostile"
    relationship("villagers", "player") -> "friendly"
    relationship("villagers", "wildlife") -> "neutral"

Deliberately not a reputation simulator (§2). It answers one question so AI
target selection and combat can branch on it, while leaving room to grow: the
matrix is data, and per-pair overrides can be layered in later (or fed from the
``LogicKeyValueStore`` for quest-driven faction changes) without touching call
sites.

Pure Python, no Qt / NumPy — safe to import in the editor, the engine and the
dependency-free player runtime.
"""

from __future__ import annotations

from typing import Dict, Tuple

FRIENDLY = "friendly"
NEUTRAL = "neutral"
HOSTILE = "hostile"

#: The canonical starter factions (§2). Team strings on monsters/NPCs are
#: normalised (lower-cased, stripped) before lookup, so "Guards" == "guards".
PLAYER = "player"
VILLAGERS = "villagers"
GUARDS = "guards"
BANDITS = "bandits"
CULTISTS = "cultists"
WILDLIFE = "wildlife"
MONSTERS = "monsters"

def _load_defaults() -> Dict[Tuple[str, str], str]:
    """Load the cross-faction relationship matrix from ``game/data/factions.json``.

    The matrix is editable *content*; :func:`relationship` and its callers are
    the *rules*. Each data entry is ``[team_a, team_b, relationship]``; only the
    interesting (non-neutral) pairs are listed. Everything unlisted defaults to
    NEUTRAL, a team paired with itself is always FRIENDLY, and pairs are
    symmetric: ``(a, b)`` implies ``(b, a)``.
    """
    from game import data
    out: Dict[Tuple[str, str], str] = {}
    for entry in (data.load("factions") or {}).get("relationships", []):
        if len(entry) >= 3:
            out[(normalise_team(entry[0]), normalise_team(entry[1]))] = entry[2]
    return out


def normalise_team(team) -> str:
    """Lower-case + strip a team string for stable comparison ('' if falsy)."""
    if not team:
        return ""
    return str(team).strip().lower()


#: Default cross-faction relationships, loaded from editable content. Populated
#: after :func:`normalise_team` so the loader can normalise team names.
_DEFAULTS: Dict[Tuple[str, str], str] = _load_defaults()


def relationship(team_a, team_b, overrides: Dict[Tuple[str, str], str] = None) -> str:
    """Return the default relationship between two teams/factions.

    One of :data:`FRIENDLY` / :data:`NEUTRAL` / :data:`HOSTILE`. Same team is
    friendly; a team with no name is neutral to everyone. *overrides* is an
    optional ``{(a, b): relationship}`` map (already-normalised keys) consulted
    before the built-in table — the hook for quest-driven faction changes.
    """
    a = normalise_team(team_a)
    b = normalise_team(team_b)
    if not a or not b:
        return NEUTRAL
    if a == b:
        return FRIENDLY

    if overrides:
        if (a, b) in overrides:
            return overrides[(a, b)]
        if (b, a) in overrides:
            return overrides[(b, a)]

    if (a, b) in _DEFAULTS:
        return _DEFAULTS[(a, b)]
    if (b, a) in _DEFAULTS:
        return _DEFAULTS[(b, a)]
    return NEUTRAL


def is_hostile(team_a, team_b, overrides=None) -> bool:
    return relationship(team_a, team_b, overrides) == HOSTILE


def is_friendly(team_a, team_b, overrides=None) -> bool:
    return relationship(team_a, team_b, overrides) == FRIENDLY
