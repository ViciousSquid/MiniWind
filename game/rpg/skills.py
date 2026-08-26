"""
Skills — the heart of the "get better by doing" progression (Elder-Scrolls style).

Every skill:

* is governed by one primary :mod:`attributes` attribute (which nudges its
  starting value and thematically ties it to the sheet),
* belongs to one of three specialisations — Combat, Magic or Stealth,
* runs from 0-100 and **improves through use**: each successful use grants skill
  XP; enough XP raises the skill by one point (harder as the skill climbs), and
  raising a *major* skill is what drives character level-up (see
  :mod:`leveling`).

The module is pure data + a couple of helpers. Skill *use* is recorded on a
:class:`~game.rpg.character.Character` via ``character.use_skill``;
here we only define the skills and the XP curve.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr

# Specialisations
COMBAT = "Combat"
MAGIC = "Magic"
STEALTH = "Stealth"

# ---------------------------------------------------------------------------
# Skill ids
# ---------------------------------------------------------------------------
# Combat
BLADE = "blade"
BLUNT = "blunt"
MARKSMAN = "marksman"        # bows
BLOCK = "block"
HEAVY_ARMOR = "heavy_armor"
LIGHT_ARMOR = "light_armor"
ATHLETICS = "athletics"
# Magic
DESTRUCTION = "destruction"
RESTORATION = "restoration"
ALTERATION = "alteration"
CONJURATION = "conjuration"
ILLUSION = "illusion"
MYSTICISM = "mysticism"
ALCHEMY = "alchemy"
# Stealth
SNEAK = "sneak"
SECURITY = "security"        # lockpicking
MARKSMANSHIP = MARKSMAN      # alias kept for readability
MERCANTILE = "mercantile"
SPEECHCRAFT = "speechcraft"
ACROBATICS = "acrobatics"
LIGHT_FINGERS = "light_fingers"  # pickpocketing / sleight of hand


class SkillDef:
    """Static definition of one skill."""

    __slots__ = ("id", "label", "spec", "governing_attr", "desc")

    def __init__(self, sid: str, label: str, spec: str, gov: str, desc: str = ""):
        self.id = sid
        self.label = label
        self.spec = spec
        self.governing_attr = gov
        self.desc = desc


SKILLS: Dict[str, SkillDef] = {s.id: s for s in [
    # --- Combat ---
    SkillDef(BLADE, "Blade", COMBAT, attr.STRENGTH,
             "Swords, daggers and other edged weapons."),
    SkillDef(BLUNT, "Blunt", COMBAT, attr.STRENGTH,
             "Maces, axes, hammers and warhammers."),
    SkillDef(MARKSMAN, "Marksman", COMBAT, attr.AGILITY,
             "Bows and thrown weapons."),
    SkillDef(BLOCK, "Block", COMBAT, attr.AGILITY,
             "Deflecting blows with a shield or weapon."),
    SkillDef(HEAVY_ARMOR, "Heavy Armor", COMBAT, attr.ENDURANCE,
             "Wearing plate, chain and other heavy protection."),
    SkillDef(LIGHT_ARMOR, "Light Armor", COMBAT, attr.SPEED,
             "Wearing leather, fur and light protection."),
    SkillDef(ATHLETICS, "Athletics", COMBAT, attr.SPEED,
             "Running and swimming; raises stamina with use."),
    # --- Magic ---
    SkillDef(DESTRUCTION, "Destruction", MAGIC, attr.WILLPOWER,
             "Fire, frost and shock — offensive magic."),
    SkillDef(RESTORATION, "Restoration", MAGIC, attr.WILLPOWER,
             "Healing, warding and curing."),
    SkillDef(ALTERATION, "Alteration", MAGIC, attr.WILLPOWER,
             "Shields, feather, water-walking, telekinesis."),
    SkillDef(CONJURATION, "Conjuration", MAGIC, attr.INTELLIGENCE,
             "Summoning creatures and bound weapons."),
    SkillDef(ILLUSION, "Illusion", MAGIC, attr.PERSONALITY,
             "Light, calm, frenzy, invisibility and command."),
    SkillDef(MYSTICISM, "Mysticism", MAGIC, attr.INTELLIGENCE,
             "Detection, soul trap, telekinesis and dispel."),
    SkillDef(ALCHEMY, "Alchemy", MAGIC, attr.INTELLIGENCE,
             "Brewing potions and poisons from ingredients."),
    # --- Stealth ---
    SkillDef(SNEAK, "Sneak", STEALTH, attr.AGILITY,
             "Moving unseen; enables devastating sneak attacks."),
    SkillDef(SECURITY, "Security", STEALTH, attr.AGILITY,
             "Picking locks and disarming traps."),
    SkillDef(MERCANTILE, "Mercantile", STEALTH, attr.PERSONALITY,
             "Buying low and selling high."),
    SkillDef(SPEECHCRAFT, "Speechcraft", STEALTH, attr.PERSONALITY,
             "Persuading, bribing and intimidating."),
    SkillDef(ACROBATICS, "Acrobatics", STEALTH, attr.SPEED,
             "Jumping and cushioning falls."),
    SkillDef(LIGHT_FINGERS, "Light Fingers", STEALTH, attr.AGILITY,
             "Pickpocketing and sleight of hand."),
]}

SKILL_IDS: List[str] = list(SKILLS.keys())

#: Skills grouped by specialisation, for the character sheet.
BY_SPEC: Dict[str, List[str]] = {}
for _sid, _sd in SKILLS.items():
    BY_SPEC.setdefault(_sd.spec, []).append(_sid)


def label(skill_id: str) -> str:
    sd = SKILLS.get(skill_id)
    return sd.label if sd else str(skill_id).replace("_", " ").title()


def governing_attribute(skill_id: str) -> str:
    sd = SKILLS.get(skill_id)
    return sd.governing_attr if sd else attr.LUCK


def new_skill_block(default: int = 5) -> Dict[str, int]:
    """A fresh {skill_id: value} dict, every skill at *default*."""
    return {sid: int(default) for sid in SKILL_IDS}


# ---------------------------------------------------------------------------
# The use → improvement curve
# ---------------------------------------------------------------------------
# Each *use* of a skill grants a base amount of skill XP (scaled by the action's
# difficulty). ``xp_to_raise`` is how much XP moves a skill from level L to L+1;
# it grows with the skill so early points come fast and mastery is a grind.
SKILL_XP_BASE = 1.0


def xp_to_raise(current_level: int) -> float:
    """Skill XP needed to advance a skill from *current_level* to the next.

    A gentle quadratic: 1→2 is cheap, 90→91 is a slog. Tuned so a focused
    playstyle can push a couple of skills to mastery over a long game while
    incidental skills climb slowly.
    """
    lvl = max(0, int(current_level))
    return 1.0 + (lvl * lvl) * 0.05 + lvl * 0.5
