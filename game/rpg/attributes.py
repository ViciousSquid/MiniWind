"""
Core character attributes (the eight primary stats).

Modelled on the Elder Scrolls line (Morrowind/Oblivion): eight attributes on a
0-100 scale that every derived statistic, skill cap and combat formula reads
from. Attributes are raised at level-up (driven by which skills you trained) and
by races/birthsigns; they are *not* raised directly by use — skills are.

Pure data + helpers, no engine dependencies.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# The eight attributes
# ---------------------------------------------------------------------------
STRENGTH = "strength"
ENDURANCE = "endurance"
AGILITY = "agility"
SPEED = "speed"
INTELLIGENCE = "intelligence"
WILLPOWER = "willpower"
PERSONALITY = "personality"
LUCK = "luck"

ATTRIBUTES: List[str] = [
    STRENGTH, ENDURANCE, AGILITY, SPEED,
    INTELLIGENCE, WILLPOWER, PERSONALITY, LUCK,
]

#: Human-readable labels + one-line descriptions for the character sheet.
ATTRIBUTE_INFO: Dict[str, Dict[str, str]] = {
    STRENGTH:     {"label": "Strength",     "desc": "Melee damage and how much you can carry."},
    ENDURANCE:    {"label": "Endurance",    "desc": "Maximum health and stamina; health gained per level."},
    AGILITY:      {"label": "Agility",      "desc": "Hit chance, dodge, and resistance to being staggered."},
    SPEED:        {"label": "Speed",        "desc": "How fast you move."},
    INTELLIGENCE: {"label": "Intelligence", "desc": "Maximum magicka."},
    WILLPOWER:    {"label": "Willpower",    "desc": "Magicka regeneration and resistance to magic."},
    PERSONALITY:  {"label": "Personality",  "desc": "NPC disposition and merchant prices."},
    LUCK:         {"label": "Luck",         "desc": "A small thumb on the scale of every roll."},
}

#: The baseline every human-race attribute starts from before race/class bonuses.
BASE_ATTRIBUTE = 40
ATTRIBUTE_MIN = 0
ATTRIBUTE_MAX = 100


def label(attr: str) -> str:
    return ATTRIBUTE_INFO.get(attr, {}).get("label", str(attr).title())


def new_attribute_block(value: int = BASE_ATTRIBUTE) -> Dict[str, int]:
    """A fresh {attribute: value} dict with every attribute set to *value*."""
    return {a: int(value) for a in ATTRIBUTES}


def clamp(value: int) -> int:
    return max(ATTRIBUTE_MIN, min(ATTRIBUTE_MAX, int(value)))


def apply_bonuses(block: Dict[str, int], bonuses: Dict[str, int]) -> Dict[str, int]:
    """Return a copy of *block* with *bonuses* added and every value clamped."""
    out = dict(block)
    for attr, delta in (bonuses or {}).items():
        if attr in out:
            out[attr] = clamp(out[attr] + int(delta))
    return out
