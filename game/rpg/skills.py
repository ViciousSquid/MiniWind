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
# Magic: three schools, and no others -- what harms, what heals, wards and
# aids, and the dark arts that raise, unmake and bind.
OFFENSIVE = "offensive"
DEFENSIVE = "defensive"
OCCULT = "occult"
#: The schools of magic, the only ones there are. Every spell belongs to one.
SCHOOLS = (OFFENSIVE, DEFENSIVE, OCCULT)
ALCHEMY = "alchemy"
#: Magic skills that no longer exist, and the school each was folded into --
#: for old saves, old custom classes and authored data that still name them.
FOLDED = {"destruction": OFFENSIVE, "conjuration": OCCULT,
          "restoration": DEFENSIVE, "alteration": DEFENSIVE,
          "illusion": DEFENSIVE, "mysticism": OCCULT, "necromancy": OCCULT}
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
    SkillDef(MARKSMAN, "Marksman", COMBAT, attr.ENDURANCE,
             "Bows and thrown weapons."),
    SkillDef(BLOCK, "Block", COMBAT, attr.ENDURANCE,
             "Deflecting blows with a shield or weapon."),
    SkillDef(HEAVY_ARMOR, "Heavy Armor", COMBAT, attr.ENDURANCE,
             "Wearing plate, chain and other heavy protection."),
    SkillDef(LIGHT_ARMOR, "Light Armor", COMBAT, attr.SPEED,
             "Wearing leather, fur and light protection."),
    SkillDef(ATHLETICS, "Athletics", COMBAT, attr.SPEED,
             "Running and swimming; raises stamina with use."),
    # --- Magic ---
    SkillDef(OFFENSIVE, "Offensive", MAGIC, attr.INTELLIGENCE,
             "Magic that harms: fire, frost and shock, and blades bound "
             "from raw magicka."),
    SkillDef(DEFENSIVE, "Defensive", MAGIC, attr.ENDURANCE,
             "Magic that heals, wards and aids: mending, shields, light, "
             "invisibility, calming a foe, opening a lock."),
    SkillDef(OCCULT, "Occult", MAGIC, attr.PERSONALITY,
             "The dark arts: calling the dead back to their bodies, unmaking "
             "the living, summoning spirit beasts, bending creatures to your "
             "will and sensing the life around you."),
    SkillDef(ALCHEMY, "Alchemy", MAGIC, attr.INTELLIGENCE,
             "Brewing potions and poisons from ingredients."),
    # --- Stealth ---
    SkillDef(SNEAK, "Sneak", STEALTH, attr.ENDURANCE,
             "Moving unseen; enables devastating sneak attacks."),
    SkillDef(SECURITY, "Security", STEALTH, attr.ENDURANCE,
             "Picking locks and disarming traps."),
    SkillDef(MERCANTILE, "Mercantile", STEALTH, attr.PERSONALITY,
             "Buying low and selling high."),
    SkillDef(SPEECHCRAFT, "Speechcraft", STEALTH, attr.PERSONALITY,
             "Persuading, bribing and intimidating."),
    SkillDef(ACROBATICS, "Acrobatics", STEALTH, attr.SPEED,
             "Jumping and cushioning falls."),
    SkillDef(LIGHT_FINGERS, "Light Fingers", STEALTH, attr.ENDURANCE,
             "Pickpocketing and sleight of hand."),
]}

SKILL_IDS: List[str] = list(SKILLS.keys())

#: Skills grouped by specialisation, for the character sheet.
BY_SPEC: Dict[str, List[str]] = {}
for _sid, _sd in SKILLS.items():
    BY_SPEC.setdefault(_sd.spec, []).append(_sid)


def fold(skill_id: str) -> str:
    """*skill_id*, or the school an old magic skill was folded into."""
    return FOLDED.get(str(skill_id), str(skill_id))


def school(value) -> str:
    """The school of magic *value* names: one of :data:`SCHOOLS`. An old
    school folds into its successor; anything else is Offensive."""
    value = fold(str(value or "").strip().lower())
    return value if value in SCHOOLS else OFFENSIVE


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
# Mastery ranks
# ---------------------------------------------------------------------------
#: Mastery ranks a skill passes on its way to 100: (from level, name). The
#: skill tree draws them as pips; a trainer's rank caps what it can teach.
RANKS = ((0, "Novice"), (25, "Apprentice"), (50, "Journeyman"), (75, "Expert"),
         (100, "Master"))


def rank(level) -> tuple:
    """``(index, name)`` of the mastery rank *level* has reached."""
    level = int(level)
    out = (0, RANKS[0][1])
    for i, (lo, name) in enumerate(RANKS):
        if level >= lo:
            out = (i, name)
    return out


def rank_name(level) -> str:
    return rank(level)[1]


def rank_level(value) -> int:
    """A skill level from *value*: a number, or a rank's name ("Journeyman"
    is 50). Unreadable, it is a Novice's 0."""
    if isinstance(value, str):
        named = {name.lower(): lo for lo, name in RANKS}
        if value.strip().lower() in named:
            return named[value.strip().lower()]
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return 0


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
