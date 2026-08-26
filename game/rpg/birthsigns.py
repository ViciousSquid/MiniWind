"""
Birthsigns — a small permanent bonus chosen at character creation.

Each sign grants a flat stat bonus and/or a granted spell/power, in the tradition
of the Elder Scrolls "sign under which you were born". Kept intentionally light:
one meaningful pick, no ongoing bookkeeping.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr


class Birthsign:
    __slots__ = ("id", "label", "desc", "attr_bonuses", "stat_bonuses", "spells")

    def __init__(self, sid, label, desc, attr_bonuses=None, stat_bonuses=None, spells=None):
        self.id = sid
        self.label = label
        self.desc = desc
        self.attr_bonuses = attr_bonuses or {}
        #: flat additions to derived pools, e.g. {"magicka": 50} or {"health": 25}
        self.stat_bonuses = stat_bonuses or {}
        self.spells = spells or []


BIRTHSIGNS: Dict[str, Birthsign] = {b.id: b for b in [
    Birthsign("warrior", "The Warrior",
              "The warrior's fortune favours those who live by the blade. +10 Strength.",
              attr_bonuses={attr.STRENGTH: 10, attr.ENDURANCE: 5}),
    Birthsign("mage", "The Mage",
              "Magicka runs deeper in those born under the Mage. +50 magicka.",
              attr_bonuses={attr.INTELLIGENCE: 10}, stat_bonuses={"magicka": 50}),
    Birthsign("thief", "The Thief",
              "The quick and the lucky are the Thief's children. +10 Agility, +5 Luck.",
              attr_bonuses={attr.AGILITY: 10, attr.SPEED: 5, attr.LUCK: 5}),
    Birthsign("lady", "The Lady",
              "Grace and vigour. +10 Endurance and Personality.",
              attr_bonuses={attr.ENDURANCE: 10, attr.PERSONALITY: 10}),
    Birthsign("steed", "The Steed",
              "The restless are born under the Steed. +15 Speed.",
              attr_bonuses={attr.SPEED: 15}),
    Birthsign("lord", "The Lord",
              "Slow to fall, quick to mend. +25 health and a healing gift.",
              stat_bonuses={"health": 25}, spells=["heal_minor"]),
    Birthsign("apprentice", "The Apprentice",
              "Great power, and great risk. +100 magicka but weaker to magic.",
              stat_bonuses={"magicka": 100}, attr_bonuses={attr.INTELLIGENCE: 5}),
    Birthsign("golem", "The Golem",
              "A vessel of raw power. +150 magicka but it never regenerates on its own.",
              stat_bonuses={"magicka": 150}),
    Birthsign("shadow", "The Shadow",
              "Born to slip away unseen — a gift of invisibility.",
              spells=["invisibility_minor"], attr_bonuses={attr.AGILITY: 5}),
    Birthsign("none", "No Sign",
              "You were born under no particular star. No bonus.",),
]}

BIRTHSIGN_IDS: List[str] = list(BIRTHSIGNS.keys())


def get(sign_id: str) -> Birthsign:
    return BIRTHSIGNS.get(str(sign_id).lower(), BIRTHSIGNS["none"])
