"""
Character classes.

A class defines *how you level*: a specialisation (Combat/Magic/Stealth, which
gives a small bonus to every skill in it), two favoured attributes, and seven
**major skills**. Major skills start higher, and — crucially — training a major
skill is what accrues progress toward the next character level (see
:mod:`leveling`). Everything else is a minor skill: still improvable by use, but
it doesn't push your level.

Preset classes cover the classic archetypes; a fully custom class can be built
at character creation by handing :func:`make_custom` a spec.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr
from . import skills as sk


class CharClass:
    __slots__ = ("id", "label", "desc", "specialisation", "favored_attrs",
                 "major_skills", "starting_spells")

    def __init__(self, cid, label, desc, spec, favored_attrs, major_skills,
                 starting_spells=None):
        self.id = cid
        self.label = label
        self.desc = desc
        self.specialisation = spec
        self.favored_attrs = list(favored_attrs)
        self.major_skills = list(major_skills)
        # Spells a member of this class knows from the start. Spellcaster
        # classes get a basic spell so a fresh mage is never empty-handed even
        # if their race / birthsign granted nothing (see character.new_game).
        self.starting_spells = list(starting_spells or [])


CLASSES: Dict[str, CharClass] = {c.id: c for c in [
    CharClass("warrior", "Warrior",
              "A front-line fighter: heavy armour, a strong arm, a blade or a mace.",
              sk.COMBAT, [attr.STRENGTH, attr.ENDURANCE],
              [sk.BLADE, sk.BLUNT, sk.HEAVY_ARMOR, sk.BLOCK, sk.ATHLETICS,
               sk.MARKSMAN, sk.RESTORATION]),
    CharClass("knight", "Knight",
              "A chivalrous warrior as comfortable at court as in the melee.",
              sk.COMBAT, [attr.STRENGTH, attr.PERSONALITY],
              [sk.BLADE, sk.BLUNT, sk.HEAVY_ARMOR, sk.BLOCK, sk.SPEECHCRAFT,
               sk.ILLUSION, sk.RESTORATION]),
    CharClass("barbarian", "Barbarian",
              "A savage brawler who trades armour for raw ferocity and speed.",
              sk.COMBAT, [attr.STRENGTH, attr.SPEED],
              [sk.BLUNT, sk.BLADE, sk.LIGHT_ARMOR, sk.BLOCK, sk.ATHLETICS,
               sk.MARKSMAN, sk.ACROBATICS]),
    CharClass("scout", "Scout",
              "A wilderness ranger: bow, blade, light armour and a keen eye.",
              sk.COMBAT, [attr.SPEED, attr.ENDURANCE],
              [sk.BLADE, sk.MARKSMAN, sk.LIGHT_ARMOR, sk.BLOCK, sk.ATHLETICS,
               sk.SNEAK, sk.ALCHEMY]),
    CharClass("archer", "Archer",
              "Death from a distance; a bow, light feet and just enough steel.",
              sk.COMBAT, [attr.AGILITY, attr.STRENGTH],
              [sk.MARKSMAN, sk.BLADE, sk.LIGHT_ARMOR, sk.SNEAK, sk.ACROBATICS,
               sk.ATHLETICS, sk.ALCHEMY]),
    CharClass("mage", "Mage",
              "A student of all the arcane arts, weak of arm but deep of magicka.",
              sk.MAGIC, [attr.INTELLIGENCE, attr.WILLPOWER],
              [sk.DESTRUCTION, sk.RESTORATION, sk.ALTERATION, sk.CONJURATION,
               sk.ILLUSION, sk.MYSTICISM, sk.ALCHEMY],
              starting_spells=["flare", "heal_minor"]),
    CharClass("sorcerer", "Sorcerer",
              "A battle-mage who binds armour and summoned blades to raw destruction.",
              sk.MAGIC, [attr.INTELLIGENCE, attr.ENDURANCE],
              [sk.DESTRUCTION, sk.CONJURATION, sk.ALTERATION, sk.MYSTICISM,
               sk.HEAVY_ARMOR, sk.BLADE, sk.RESTORATION],
              starting_spells=["flare"]),
    CharClass("healer", "Healer",
              "A gentle spellcaster devoted to mending and warding.",
              sk.MAGIC, [attr.WILLPOWER, attr.PERSONALITY],
              [sk.RESTORATION, sk.ALTERATION, sk.ILLUSION, sk.ALCHEMY,
               sk.SPEECHCRAFT, sk.MYSTICISM, sk.BLUNT],
              starting_spells=["heal_minor", "flare"]),
    CharClass("nightblade", "Nightblade",
              "A shadow-mage who kills with spell and dagger, then vanishes.",
              sk.MAGIC, [attr.WILLPOWER, attr.SPEED],
              [sk.DESTRUCTION, sk.ILLUSION, sk.MYSTICISM, sk.BLADE,
               sk.LIGHT_ARMOR, sk.SNEAK, sk.ALTERATION],
              starting_spells=["flare"]),
    CharClass("thief", "Thief",
              "Light fingers, lighter feet: locks, pockets and a quick blade.",
              sk.STEALTH, [attr.AGILITY, attr.SPEED],
              [sk.SECURITY, sk.SNEAK, sk.LIGHT_FINGERS, sk.ACROBATICS,
               sk.LIGHT_ARMOR, sk.BLADE, sk.MERCANTILE]),
    CharClass("assassin", "Assassin",
              "A precise killer: sneak, marksmanship and a poisoned blade.",
              sk.STEALTH, [attr.SPEED, attr.INTELLIGENCE],
              [sk.SNEAK, sk.MARKSMAN, sk.BLADE, sk.LIGHT_ARMOR, sk.ACROBATICS,
               sk.SECURITY, sk.ALCHEMY]),
    CharClass("rogue", "Rogue",
              "A charming duellist who talks their way in and cuts their way out.",
              sk.STEALTH, [attr.SPEED, attr.PERSONALITY],
              [sk.BLADE, sk.LIGHT_ARMOR, sk.BLOCK, sk.SPEECHCRAFT,
               sk.MERCANTILE, sk.ILLUSION, sk.ALCHEMY]),
    CharClass("bard", "Bard",
              "A jack-of-all-trades: a little steel, a little magic, a lot of charm.",
              sk.STEALTH, [attr.PERSONALITY, attr.INTELLIGENCE],
              [sk.SPEECHCRAFT, sk.MERCANTILE, sk.ILLUSION, sk.BLADE,
               sk.LIGHT_ARMOR, sk.ALCHEMY, sk.SECURITY]),
]}

CLASS_IDS: List[str] = list(CLASSES.keys())

#: The curated, reduced set of classes offered in the simplified character
#: creator (the full CLASSES table still backs saves, NPCs and custom classes).
CREATION_CLASS_IDS: List[str] = ["warrior", "archer", "mage", "healer",
                                 "nightblade", "thief"]

#: Major skills start this much higher than minor skills.
MAJOR_SKILL_START = 25
MINOR_SKILL_START = 5
SPECIALISATION_BONUS = 5   # every skill in your specialisation gets +5


def get(class_id: str) -> CharClass:
    return CLASSES.get(str(class_id).lower(), CLASSES["warrior"])


def make_custom(label: str, spec: str, favored_attrs: List[str],
                major_skills: List[str], desc: str = "A custom class.") -> CharClass:
    """Build a one-off custom class (character-creation 'design your own')."""
    spec = spec if spec in (sk.COMBAT, sk.MAGIC, sk.STEALTH) else sk.COMBAT
    fav = [a for a in favored_attrs if a in attr.ATTRIBUTES][:2] or [attr.STRENGTH, attr.ENDURANCE]
    majors = [s for s in major_skills if s in sk.SKILLS][:7]
    # pad to 7 with sensible defaults if short
    for s in sk.SKILL_IDS:
        if len(majors) >= 7:
            break
        if s not in majors:
            majors.append(s)
    return CharClass("custom", label or "Adventurer", desc, spec, fav, majors)
