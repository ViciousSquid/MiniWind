"""Luck and saving throws: the fate die.

Everyone in the world has a Luck -- the player, every NPC, every animal (an
NPC's or animal's is rolled once, like its Strength: game.rpg.charisma.core).
At the extremes it reaches into saving throws, on a d20 of its own -- the
*fate die*, rolled beside the save and shown in its roll box:

* **Lucky.** A failed save by someone of Luck LUCKY_FROM or more, at level
  LUCKY_LEVEL or above, rolls the fate die: on a success the save comes good
  after all, and better -- the whole blow is turned aside. "LUCK!"
* **Unlucky.** A successful save by someone of Luck UNLUCKY_TO or less, at any
  level, rolls the fate die: on a success the save comes undone and the whole
  blow lands. "UNLUCKY!"

Whatever fate does, it says what happened -- a line of what went right (or
wrong), told to the player in the roll box, over the character's head and in
the log. Everyone else never rolls a fate die at all.
"""

from __future__ import annotations

from typing import Dict, Optional

#: Luck from which a failed save may come good...
LUCKY_FROM = 60
#: ...for characters of this level or more.
LUCKY_LEVEL = 10
#: Luck at or below which a successful save may come undone (any level).
UNLUCKY_TO = 25
#: The fate die's chances: the least that is possible (5%, one face of the
#: d20), what each point of Luck past the mark (and, lucky, each level past
#: LUCKY_LEVEL) adds, and the most it can ever be.
FATE_BASE = 0.05
LUCKY_PER_LUCK = 0.004
LUCKY_PER_LEVEL = 0.004
UNLUCKY_PER_LUCK = 0.008
FATE_MAX = 0.25

LUCK_TEXT = "LUCK!"
UNLUCKY_TEXT = "UNLUCKY!"

#: What luck did, one at random -- said of anyone, the player or a hen.
LUCKY_LINES = (
    "The blow caught on a belt buckle.",
    "The attacker slipped on something unspeakable.",
    "A bird swooped at the attacker's face.",
    "The blade turned on a lucky coin.",
    "A well-timed sneeze ducked the blow.",
    "The attacker's bootlace snapped.",
    "The blow went straight through a hole in the cloak.",
    "A gust of wind blew grit in the attacker's eyes.",
)
#: What bad luck did.
UNLUCKY_LINES = (
    "The shield strap snapped.",
    "A sneeze, at the worst possible moment.",
    "Tripped over a hen.",
    "The sun, right in the eyes.",
    "Distracted by a butterfly.",
    "The shield was held upside down.",
    "A boot stuck fast in the mud.",
    "A wasp chose that moment.",
)


def lucky_chance(luck: int, level: int) -> float:
    """The fate die's chance of rescuing a failed save, or 0 for anyone not
    lucky enough (or not yet high enough level)."""
    luck, level = int(luck), int(level)
    if luck < LUCKY_FROM or level < LUCKY_LEVEL:
        return 0.0
    return min(FATE_MAX, FATE_BASE + (luck - LUCKY_FROM) * LUCKY_PER_LUCK
               + (level - LUCKY_LEVEL) * LUCKY_PER_LEVEL)


def unlucky_chance(luck: int) -> float:
    """The fate die's chance of undoing a successful save, or 0 for anyone
    not unlucky."""
    luck = int(luck)
    if luck > UNLUCKY_TO:
        return 0.0
    return min(FATE_MAX, FATE_BASE + (UNLUCKY_TO - luck) * UNLUCKY_PER_LUCK)


def fate_die(saved: bool, luck: int, level: int, dice, defender: str, *,
             npc: bool = False, against_player: bool = False) -> Optional[Dict]:
    """After a saving throw (*saved* or not): roll the fate die if Luck says
    so, else None. The roll it returns carries ``fate`` -- "lucky",
    "unlucky" or None (the die was rolled and fate let it be) -- ``line``,
    what happened, and a ``detail`` for the roll box."""
    from ..diceroll import roll_check
    chance = unlucky_chance(luck) if saved else lucky_chance(luck, level)
    if chance <= 0.0:
        return None
    kind = "unlucky" if saved else "lucky"
    roll = roll_check(
        dice, chance, f"{defender}: {'bad ' if saved else ''}luck",
        source="combat.fate",
        why=(f"Luck {int(luck)}: a good save may yet go wrong" if saved else
             f"Luck {int(luck)}, level {int(level)}: a failed save may yet come good"),
        context={"quiet": True, "npc": npc, "against_player": against_player,
                 "saving_throw": True})
    roll["die_role"] = "luck"
    face = int(roll.get("roll_result", 0) or 0)
    need = roll.get("target")
    if roll.get("success"):
        lines = UNLUCKY_LINES if saved else LUCKY_LINES
        roll["fate"] = kind
        roll["line"] = lines[(face * 7 + len(str(defender))) % len(lines)]
        word = UNLUCKY_TEXT if saved else LUCK_TEXT
        roll["detail"] = f"Luck d20: {face} (need {need}+) — {word}"
    else:
        roll["fate"] = None
        roll["line"] = ""
        roll["detail"] = f"Luck d20: {face} (need {need}+) — fate lets it be"
    return roll
