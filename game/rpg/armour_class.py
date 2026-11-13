"""
Armour Class and attack bonuses: who hits whom, on a d20.

Every living thing has an **Armour Class** (AC) -- the player, every NPC,
every monster and every animal. Every attack is a d20 roll plus the
attacker's **attack bonus**; it lands when the total reaches the target's
AC (a natural 1 always misses and a natural 20 always hits: the chance is
held between 5% and 95%). The same rule decides the player's swings and
shots, every blow the player takes, and every fight between NPCs and
creatures. A raised shield's block is then a saving throw that AC makes
easier (game/rpg/blocking.py).

The player's AC is their armour, Endurance and charms
(:func:`game.rpg.equipment.armour_class`). Anything else's is
:func:`of`: an authored ``armour_class``, else ``BASE_AC`` + the natural
armour of its kind (a bear's hide, a guard's mail) + its shield + its
Endurance + a little for its level.

This module is the one place the numbers live; RULES.md describes them.
"""

from __future__ import annotations

from typing import Dict, Optional

from . import attributes as attr
from . import charisma

#: AC of an unarmoured, unremarkable body.
BASE_AC = 10

#: Natural armour by kind (``npc_role`` / ``creature_role``): hide, shell,
#: bone, or the kit a role always wears. Added to :data:`BASE_AC`.
NATURAL_ARMOUR: Dict[str, int] = {
    # animals
    "hen": 0, "sheep": 0, "cow": 1, "deer": 1, "wolf": 1, "boar": 2,
    "bear": 3, "mudcrab": 5,
    # the dead and the monstrous
    "skeleton": 2, "skeleton_archer": 1, "wraith": 3, "monster": 3, "dragon": 8,
    # people, by what their role wears
    "guard": 4, "guard_archer": 3, "bandit": 1, "bandit_archer": 1,
    "bandit_chief": 4, "cultist": 0, "villager": 0, "merchant": 0,
    "blacksmith": 1, "farmer": 0, "beggar": 0,
}

#: Every point of Endurance above this adds to AC, one per
#: :data:`ENDURANCE_STEP`, up to :data:`ENDURANCE_MAX` -- for anyone but the
#: player, whose Endurance bonus is capped by the armour they wear instead.
ENDURANCE_FROM = 40
ENDURANCE_STEP = 10
ENDURANCE_MAX = 4

#: A creature's level adds one AC per this many levels above the first.
LEVELS_PER_AC = 3

#: Attack bonus of anyone but the player: this, plus their level, plus one
#: per :data:`STRENGTH_STEP` points of Strength above :data:`STRENGTH_FROM`.
NPC_ATTACK_BASE = 6
STRENGTH_FROM = 40
STRENGTH_STEP = 15

#: The player's attack bonus: this, plus a tenth of the weapon skill, plus
#: Luck (one per :data:`LUCK_STEP` above :data:`LUCK_FROM`, one off per step below:
#: :func:`luck_bonus`) and, for melee,
#: Strength (one per :data:`STRENGTH_STEP` above :data:`STRENGTH_FROM`).
PLAYER_ATTACK_BASE = 3
LUCK_FROM = 40
LUCK_STEP = 20
#: Penalties to the player's attack bonus.
WINDED_BELOW = 0.75          # stamina share below which you are winded
WINDED_PENALTY = 2
DUAL_WIELD_PENALTY = 2

#: Everyone rolls for a critical hit the same way, after a hit lands: a d20
#: check at CRIT_BASE + Luck x CRIT_PER_LUCK (11% at Luck 40), for
#: CRIT_DAMAGE times the damage -- the player (game.rpg.combat.critical_chance)
#: and every NPC and animal alike (:func:`crit_chance`).
CRIT_BASE = 0.05
CRIT_PER_LUCK = 0.0015
CRIT_DAMAGE = 1.5

#: Each point of AC above BASE_AC adds this to a block's saving throw.
BLOCK_PER_AC = 0.025

#: The attack bonus assumed when the attacker is unknown (a trap, a stray
#: arrow): a typical level-1 foe.
TYPICAL_ATTACK_BONUS = NPC_ATTACK_BASE + 1


def to_hit(attack_bonus: float, armour_class: float) -> float:
    """The chance a d20 + *attack_bonus* reaches *armour_class*: 5% to 95%."""
    return max(0.05, min(0.95, (21.0 + float(attack_bonus) - float(armour_class)) / 20.0))


def _int(value, default=None) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def kind(props: Dict) -> str:
    return str(props.get("npc_role") or props.get("creature_role") or "").lower()


def level(props: Dict) -> int:
    return max(1, _int(props.get("creature_level") or props.get("level"), 1) or 1)


def shield_ac(item_def) -> int:
    """What a shield adds to AC: one per RATING_PER_AC of its armour rating,
    never less than one."""
    if item_def is None:
        return 0
    from . import equipment as eq
    rating = float(item_def.get("armor_rating", 0) or 0)
    return max(1, int(round(rating / eq.RATING_PER_AC)))


def of(props: Optional[Dict]) -> int:
    """The Armour Class of any creature but the player (its ``properties``).

    An authored ``armour_class`` (or ``ac``) wins. Otherwise: BASE_AC + the
    natural armour of its kind + the shield it carries + its Endurance bonus
    + one per LEVELS_PER_AC levels above the first."""
    if not isinstance(props, dict):
        return BASE_AC
    for key in ("armour_class", "armor_class", "ac"):
        authored = _int(props.get(key))
        if authored is not None and not isinstance(props.get(key), bool):
            return max(1, authored)
    ac = BASE_AC + NATURAL_ARMOUR.get(kind(props), 0)
    try:
        from .blocking import npc_shield
        ac += shield_ac(npc_shield(props))
    except Exception:
        pass
    endurance = charisma.core(props, attr.ENDURANCE)
    ac += max(0, min(ENDURANCE_MAX, (endurance - ENDURANCE_FROM) // ENDURANCE_STEP))
    ac += (level(props) - 1) // LEVELS_PER_AC
    return int(ac)


def npc_attack_bonus(props: Optional[Dict]) -> int:
    """The attack bonus of any creature but the player: an authored
    ``attack_bonus``, else NPC_ATTACK_BASE + its level + its Strength."""
    if not isinstance(props, dict):
        return TYPICAL_ATTACK_BONUS
    authored = _int(props.get("attack_bonus"))
    if authored is not None and not isinstance(props.get("attack_bonus"), bool):
        return authored
    strength = charisma.core(props, attr.STRENGTH)
    return int(NPC_ATTACK_BASE + level(props)
               + max(0, (strength - STRENGTH_FROM) // STRENGTH_STEP)
               + luck_bonus(charisma.core(props, attr.LUCK)))


def luck_bonus(luck: int) -> int:
    """What Luck does to anyone's attack bonus, both ways: +1 for each full
    LUCK_STEP above LUCK_FROM, -1 for each full LUCK_STEP below it -- the
    lucky land more blows, the unlucky fewer."""
    return int((int(luck) - LUCK_FROM) / LUCK_STEP)      # toward zero


def player_attack_bonus(character, skill: int, *, melee: bool,
                        fatigue: float = 1.0, dual: bool = False) -> int:
    """The player's attack bonus with a weapon of *skill*."""
    luck = int(character.attrs.get(attr.LUCK, 40))
    bonus = PLAYER_ATTACK_BASE + int(skill) // 10
    bonus += luck_bonus(luck)
    if melee:
        strength = int(character.attrs.get(attr.STRENGTH, 40))
        bonus += max(0, (strength - STRENGTH_FROM) // STRENGTH_STEP)
    if fatigue < WINDED_BELOW:
        bonus -= WINDED_PENALTY
    if dual:
        bonus -= DUAL_WIELD_PENALTY
    return int(bonus)


def crit_chance(props: Optional[Dict]) -> float:
    """The chance a landed blow by anyone but the player is a critical hit:
    the player's rule, from its Luck (authored ``luck``, else 40)."""
    luck = charisma.core(props, attr.LUCK) if isinstance(props, dict) else 40
    return CRIT_BASE + max(0, min(100, luck)) * CRIT_PER_LUCK


def roll_crit(props, dice=None, rng=None, name: str = "") -> bool:
    """Roll whether a landed blow by *props* is a critical hit (a d20 check,
    on *dice* when given -- shown nowhere: an NPC's roll)."""
    from ..diceroll import DiceRoller, roll_check
    chance = crit_chance(props)
    roller = DiceRoller(rng=rng) if dice is None else dice
    roll = roll_check(roller, chance, f"{name}: roll for a critical hit".strip(": "),
                      source="combat.npc_critical",
                      why=f"Luck: {chance * 100:.0f}% chance of x{CRIT_DAMAGE:g} damage",
                      context={"quiet": True, "npc": True})
    return bool(roll["success"])


def block_bonus(armour_class: float) -> float:
    """What AC adds to a block's saving throw chance."""
    return max(0.0, (float(armour_class) - BASE_AC) * BLOCK_PER_AC)
