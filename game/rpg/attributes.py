"""
Core character attributes (the six primary stats).

Six attributes on a 0-100 scale that every derived statistic, skill cap and
combat formula reads from. Three of them -- STRENGTH, ENDURANCE and CHARISMA
(Personality) -- are rolled at character creation and belong to every living
thing in the world, not just the player (:func:`of_creature`). Attributes are
raised at level-up and by races/birthsigns; they are *not* raised directly by
use — skills are.

There were eight: Agility and Willpower are folded into Endurance, which now
carries hit chance, dodging, magicka regeneration and resisting magic too.

Pure data + helpers, no engine dependencies.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# The six attributes
# ---------------------------------------------------------------------------
STRENGTH = "strength"
ENDURANCE = "endurance"
SPEED = "speed"
INTELLIGENCE = "intelligence"
PERSONALITY = "personality"
LUCK = "luck"

ATTRIBUTES: List[str] = [
    STRENGTH, ENDURANCE, SPEED, INTELLIGENCE, PERSONALITY, LUCK,
]

#: Attributes that no longer exist, and the one each was folded into -- for
#: authored data and old saves that still name them.
FOLDED = {"agility": ENDURANCE, "willpower": ENDURANCE}

#: Human-readable labels + one-line descriptions for the character sheet.
ATTRIBUTE_INFO: Dict[str, Dict[str, str]] = {
    STRENGTH:     {"label": "Strength",     "desc": "Melee damage and how much you can carry."},
    ENDURANCE:    {"label": "Endurance",    "desc": "Maximum health and stamina, health gained "
                   "per level, hit chance and dodging, magicka regeneration and "
                   "resisting magic."},
    SPEED:        {"label": "Speed",        "desc": "How fast you move."},
    INTELLIGENCE: {"label": "Intelligence", "desc": "Maximum magicka."},
    PERSONALITY:  {"label": "Charisma",  "desc": "How others see you: their disposition, "
                   "merchants' prices, and whether they can bear to deal with you."},
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
