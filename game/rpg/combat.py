"""
Combat rules — the maths of hitting things and being hit.

Pure, deterministic-ish formulas (an optional RNG is injected for tests). Covers:

* **player melee / bow / spell damage** against a creature — scaled by weapon,
  the governing skill, Strength (melee), draw quality (bow), sneak attacks and a
  luck-weighted critical chance;
* **incoming damage mitigation** for the player — armour rating, active shield
  effects, blocking, and elemental resistances from the character;
* **to hit** — every attack is d20 + the attacker's bonus against the
  target's Armour Class (game/rpg/armour_class.py), the player's included.

Creature-vs-creature and creature ranged travel are handled by the engine's
:class:`~engine.monster_ai.MonsterAI` (now fantasy: melee & arrows, no guns);
this module governs everything the *player character* does, where the deep RPG
stats live.
"""

from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

from . import attributes as attr
from . import skills as sk
from . import items
from . import equipment as eq
from . import charisma
from . import armour_class as ac_rules
from ..diceroll import DiceRoller, check_target, roll_check


# ---------------------------------------------------------------------------
# Hit chance
# ---------------------------------------------------------------------------
#: Two weapons at once cost accuracy: each hand's chance to hit is scaled by
#: this, and a pair of crossbows scatters its bolts by up to DUAL_WIELD_SPREAD
#: degrees. A trade some fighters decline (game.held_weapons).
DUAL_WIELD_ACCURACY = 0.8      # (old percentile rule; see armour_class.DUAL_WIELD_PENALTY)
DUAL_WIELD_SPREAD = 5.0


def hit_chance(character, weapon_skill: int, target_ac: int = ac_rules.BASE_AC,
               fatigue_frac: float = 1.0, *, melee: bool = True,
               dual: bool = False) -> float:
    """The chance the player's d20 + attack bonus (weapon skill, Luck, melee
    Strength, winded and two-weapon penalties) reaches *target_ac*."""
    bonus = ac_rules.player_attack_bonus(character, weapon_skill, melee=melee,
                                         fatigue=fatigue_frac, dual=dual)
    return ac_rules.to_hit(bonus, target_ac)


def _target_name(target_props: Dict) -> str:
    return str(target_props.get("display_name") or target_props.get("name") or "")


def _hit_why(character, skill_id: str, skill: int, bonus: int, target_ac: int,
             fatigue_frac: float, chance: float) -> str:
    """What went into a to-hit roll, in the player's terms:
    ``d20 +5 (Blade 35) vs Armour Class 12, winded — 70%``."""
    parts = [f"d20 {bonus:+d} ({sk.label(skill_id)} {skill}) vs Armour Class {target_ac}"]
    if fatigue_frac < ac_rules.WINDED_BELOW:
        parts.append("winded")
    if eq.dual_wielding(character):
        parts.append("two weapons")
    return f"{', '.join(parts)} — {chance * 100:.0f}%"


def strength_factor(strength: int) -> float:
    """How a creature's Strength scales the physical damage it deals: x1.0 at
    50, from x0.7 at 0 to x1.3 at 100."""
    return 0.7 + max(0, min(100, int(strength))) * 0.006


def critical_chance(character) -> float:
    """Probability a landed blow is a critical (x1.5 damage), from Luck."""
    return 0.05 + character.attrs.get(attr.LUCK, 40) * 0.0015


def attack_odds(character, target_props: Dict, hand: str = "main",
                sure_hit: bool = False) -> Dict:
    """The odds of attacking *target_props* right now, before the swing, as
    the HUD shows them over a target.

    ``{"hit_chance", "hit_target", "sure_hit", "crit_chance", "crit_target",
    "why", "ac", "bonus"}`` -- the same numbers :func:`player_attack` will
    roll against: d20 + the attack bonus against the target's Armour Class.
    Every attack rolls (*sure_hit* is kept for old callers and ignored).
    """
    w = eq.hand_weapon(character, hand)
    kind = w.get("kind", items.KIND_MELEE) if w else items.KIND_MELEE
    skill_id = w.get("skill", sk.BLADE) if w else sk.BLADE
    skill = character.skill(skill_id)
    target_ac = ac_rules.of(target_props)
    fatigue = character.stamina / character.max_stamina if character.max_stamina else 1.0
    dual = eq.dual_wielding(character)
    bonus = ac_rules.player_attack_bonus(character, skill, melee=kind == items.KIND_MELEE,
                                         fatigue=fatigue, dual=dual)
    chance = ac_rules.to_hit(bonus, target_ac)
    crit = critical_chance(character)
    return {"hit_chance": chance, "hit_target": check_target(chance),
            "sure_hit": False, "ac": target_ac, "bonus": bonus,
            "crit_chance": crit, "crit_target": check_target(crit),
            "why": _hit_why(character, skill_id, skill, bonus, target_ac, fatigue, chance)}


# ---------------------------------------------------------------------------
# Player outgoing damage
# ---------------------------------------------------------------------------
#: The dice a weapon's damage is rolled on (see :func:`damage_die`).
DAMAGE_DICE = (4, 6, 8, 10, 12)


def damage_die(base: float, weapon=None) -> Tuple[int, float]:
    """The die a weapon of *base* damage rolls, and the flat amount added to
    it: ``(sides, flat)``, so the roll averages *base*. An item can name its
    own die (``"damage_die": "d8"``); otherwise it is the largest of
    :data:`DAMAGE_DICE` whose average does not pass *base* (a d4 at least)."""
    sides = None
    own = weapon.get("damage_die") if weapon is not None else None
    if own:
        try:
            sides = int(str(own).lower().lstrip("1").lstrip("d"))
        except ValueError:
            sides = None
    if sides is None:
        sides = DAMAGE_DICE[0]
        for die in DAMAGE_DICE:
            if (die + 1) / 2.0 <= base:
                sides = die
    return sides, float(base) - (sides + 1) / 2.0


def roll_damage(base: float, weapon=None, *, dice=None, rng=None,
                target_name: str = "") -> Dict:
    """Roll a weapon's damage die: ``{"base", "face", "sides", "flat"}`` --
    *base* replaced by the die's face plus its flat amount (never below 1).
    With *dice*, the roll is shown beside the to-hit d20."""
    sides, flat = damage_die(base, weapon)
    if dice is not None:
        name = getattr(weapon, "name", None) or "Unarmed"
        label = f"Damage ({name}: d{sides}{flat:+.0f})" if round(flat) else \
            f"Damage ({name}: d{sides})"
        result = dice.request_roll(f"1d{sides}", source="combat.damage",
                                   context={"label": label, "damage_die": True,
                                            "target": target_name})
        face = int(result.get("roll_result", 1))
        # What the roll box says under the hit: "Iron Longsword d12+10 → 19".
        bonus = f"{flat:+.0f}" if round(flat) else ""
        result["detail"] = f"{name} d{sides}{bonus} → {int(round(max(1.0, face + flat)))}"
    else:
        roll = getattr(rng, "randint", None) or random.randint
        face = int(roll(1, sides))
    return {"base": max(1.0, face + flat), "face": face, "sides": sides, "flat": flat}


def base_ranged_damage(character, *, hand="main", ammo=None, draw=1.0, base=None):
    """An arrow's physical energy before critical/sneak and class bonuses
    (*base* replaces the weapon's own damage: its rolled damage die)."""
    weapon = eq.hand_weapon(character, hand)
    if weapon is None or weapon.get("kind") not in items.RANGED_KINDS:
        return 0.0
    if base is None:
        base = float(weapon.get("damage", 5)) * eq.rarity_stat(character, eq.hand_slot(hand))
    skill = character.skill(weapon.get("skill", sk.MARKSMAN))
    damage = base * (0.4 + skill / 110.0) + (float(ammo.get("damage", 0)) if ammo else 0)
    if weapon.get("kind") == items.KIND_BOW:
        damage *= 0.5 + 0.5 * max(0.1, min(1.0, draw))
    return damage


def player_attack(character, target_props: Dict, *, sneaking: bool = False,
                  draw: float = 1.0, rng: Optional[random.Random] = None,
                  dice: Optional[DiceRoller] = None,
                  guaranteed_hit: bool = False, power: float = 1.0,
                  hand: str = "main") -> Dict:
    """Resolve a player attack against a creature's ``properties`` dict.

    Returns a result dict::

        {"hit", "damage", "crit", "sneak", "skill", "difficulty",
         "killed", "kind"}

    The caller applies ``damage`` to the target's ``health`` and reports
    ``skill``/``difficulty`` back to :meth:`Character.use_skill` so combat
    trains the weapon skill.

    Every attack rolls d20 + the attack bonus against the target's Armour
    Class. ``guaranteed_hit`` is kept for old callers and no longer skips the
    roll: a melee swing at a close, faced target rolls like any other.

    ``hand`` is which weapon strikes: ``"main"`` or ``"off"`` (the second
    weapon of a dual wielder). Each hand is its own attack, with its own
    weapon, hit roll and damage.
    """
    rng = rng or random
    w = eq.hand_weapon(character, hand)
    kind = w.get("kind", items.KIND_MELEE) if w else items.KIND_MELEE
    skill_id = w.get("skill", sk.BLADE) if w else sk.BLADE
    if w is None:
        # Unarmed: hand-to-hand, small damage scaled by strength.
        skill_id = sk.BLADE
        base = 2.0
        kind = items.KIND_MELEE
    else:
        base = float(w.get("damage", 5)) * eq.rarity_stat(character, eq.hand_slot(hand))

    skill = character.skill(skill_id)
    fatigue_frac = character.stamina / character.max_stamina if character.max_stamina else 1.0

    result = {"hit": False, "damage": 0.0, "crit": False, "sneak": False,
              "skill": skill_id, "difficulty": 1.0, "killed": False, "kind": kind}

    # Bows and crossbows need ammo; a staff spends magicka handled by the caller.
    shot = eq.ammo_for(character, w) if kind in items.RANGED_KINDS else None
    if kind in items.RANGED_KINDS and shot is None:
        result["no_ammo"] = True
        return result

    # Every attack rolls: d20 + the attack bonus against the target's Armour
    # Class (game/rpg/armour_class.py), melee included.
    target_ac = ac_rules.of(target_props)
    bonus = ac_rules.player_attack_bonus(
        character, skill, melee=kind == items.KIND_MELEE, fatigue=fatigue_frac,
        dual=eq.dual_wielding(character))
    hit_probability = ac_rules.to_hit(bonus, target_ac)
    result["ac"], result["attack_bonus"] = target_ac, bonus
    result["hit_probability"] = hit_probability
    if dice is not None:
        # Resolved on a d20, not a percentile die: every roll is shown to the
        # player and there is no d100 in this game (see diceroll.CHECK_DIE).
        hit_roll = roll_check(
            dice, hit_probability, f"Roll to hit {_target_name(target_props)}".strip(),
            source="combat.hit",
            why=_hit_why(character, skill_id, skill, bonus, target_ac, fatigue_frac,
                         hit_probability),
            context={"skill": skill_id, "target": target_props.get("name", ""),
                     "against_name": _target_name(target_props),
                     "attack_bonus": bonus, "armour_class": target_ac})
        result["hit_roll"] = hit_roll
        if not hit_roll["success"]:
            return result
    elif rng.random() > hit_probability:
        return result  # miss
    result["hit"] = True

    # --- the weapon's damage die: base becomes the die + its flat amount ---
    rolled = roll_damage(base, w, dice=dice, rng=rng,
                         target_name=str(target_props.get("name", "")))
    result.update(damage_face=rolled["face"], damage_die=rolled["sides"])
    base = rolled["base"]

    # --- base scaling by skill (0.4x at 0 skill → ~1.3x at 100) ---
    dmg = base * (0.4 + skill / 110.0)

    if kind == items.KIND_MELEE:
        # Strength adds a meaningful chunk to melee.
        dmg *= 0.7 + character.attrs.get(attr.STRENGTH, 40) / 100.0
        # A gathered blow (a warrior's charged fist) multiplies it.
        dmg *= max(0.1, float(power))
    elif kind in items.RANGED_KINDS:
        dmg = base_ranged_damage(character, hand=hand, ammo=shot, draw=draw, base=base)
    elif kind == items.KIND_STAFF:
        dmg *= 0.7 + character.skill(sk.OFFENSIVE) / 100.0

    # --- class: a Warrior hits harder than anyone (classes.WARRIOR_DAMAGE) ---
    import game.rpg.classes as _classes
    dmg *= _classes.damage_mult(character)

    # --- sneak attack ---
    if sneaking:
        mult = 3.0 if kind == items.KIND_MELEE else 2.0
        # a dagger sneak is the assassin's classic ×6
        if w and w.id.endswith("dagger"):
            mult = 6.0
        dmg *= mult
        result["sneak"] = True

    # --- critical (luck-weighted) ---
    crit_chance = critical_chance(character)
    if dice is not None:
        crit_roll = roll_check(
            dice, crit_chance, "Roll for a critical hit", source="combat.critical",
            why=f"Luck {character.attrs.get(attr.LUCK, 40)}: "
                f"{crit_chance * 100:.0f}% chance of x1.5 damage",
            context={"skill": skill_id, "target": target_props.get("name", "")})
        result["critical_roll"] = crit_roll
        is_critical = crit_roll["success"]
    else:
        is_critical = rng.random() < crit_chance
    if is_critical:
        dmg *= 1.5
        result["crit"] = True

    # tougher targets train the skill more
    result["difficulty"] = 1.0 + int(target_props.get("health", 30)) / 120.0
    result["damage"] = round(dmg, 1)
    return result


# ---------------------------------------------------------------------------
# Player incoming damage mitigation
# ---------------------------------------------------------------------------
def resolve_incoming(character, raw_damage: float, *, damage_kind: str = "physical",
                     blocking: bool = False, rng: Optional[random.Random] = None,
                     dice: Optional[DiceRoller] = None, attacker: str = "",
                     attack_bonus: Optional[int] = None) -> Dict:
    """Apply armour, shield, block and resistance to *raw_damage*.

    Returns ``{"final", "blocked", "armor", "resisted", "armor_class"}``. Does
    **not** subtract from health (the caller does, so it can also fire death
    logic); does return the armour class worn so the caller can train the skill.

    With *dice*, the Armour Class check is shown as the *attacker* rolling to
    hit the player ("Bandit rolls to hit you: 9 (need 13+)"): a miss is a blow
    the armour turned aside. A ``quiet`` roll -- the roll log, not the dice
    panel, so the player's own rolls stay on screen mid-fight.
    A held block then makes its own d20 saving throw; only a success reduces
    the damage. The player's saving throw may animate like other player rolls.
    """
    import game.rpg.races as races
    rng = rng or random
    dmg = max(0.0, float(raw_damage))
    result = {"final": dmg, "blocked": 0.0, "armor": 0.0, "resisted": 0.0,
              "armor_class": eq.armor_class_worn(character)}

    # Armour Class: the attacker rolls d20 + their attack bonus against it;
    # a miss is a blow the armour (or a nimble body) turned aside, before
    # anything else is weighed.
    if damage_kind == "physical" and dmg > 0:
        result["ac"] = eq.armour_class(character)
        bonus = ac_rules.TYPICAL_ATTACK_BONUS if attack_bonus is None else int(attack_bonus)
        chance = ac_rules.to_hit(bonus, result["ac"])
        result["attack_bonus"] = bonus
        if dice is not None:
            roll = roll_check(
                dice, chance, f"{attacker or 'Your foe'} rolls to hit you",
                source="combat.incoming",
                why=f"d20 {bonus:+d} against your Armour Class {result['ac']}",
                context={"quiet": True, "against_player": True,
                         "attack_bonus": bonus, "armour_class": result["ac"]})
            result["defence_roll"] = roll
            deflected = not roll["success"]
        else:
            deflected = rng.random() >= chance
        if deflected:
            result["deflected"] = True
            result["final"] = 0.0
            return result

    # A held block is an attempted saving throw, not guaranteed mitigation.
    if blocking and damage_kind == "physical" and dmg > 0 and character.stamina > 0:
        from .blocking import block_save
        shield = eq.shield(character)
        block_skill = character.skill(sk.BLOCK)
        saved = block_save(
            dmg, block_skill, character.attrs.get(attr.ENDURANCE, 40),
            character.stamina / max(1, character.max_stamina), shield=shield,
            dice=dice, rng=rng, defender=character.name or "You",
            armour_class=eq.armour_class(character),
        )
        dmg = saved["damage"]
        result.update(blocked=saved["blocked"], block_roll=saved["block_roll"])
        character.use_skill(sk.BLOCK, 1.0)

    # Armour rating: each point reduces damage with diminishing returns.
    if damage_kind == "physical":
        rating = eq.armor_rating(character)
        # mitigation fraction: rating / (rating + 100)  → 100 rating = 50% off
        mitig = rating / (rating + 100.0)
        armored = dmg * mitig
        result["armor"] = round(armored, 1)
        dmg -= armored

    # Active shield spell/potion effect (flat points, magic-source armour).
    shield_mag = character.effect_magnitude("shield")
    if shield_mag > 0:
        soak = min(dmg, shield_mag * 0.5)
        dmg -= soak

    # Elemental / magical resistances from race + effects.
    resist = 0.0
    race = races.get(character.race_id)
    resist += race.resistances.get(damage_kind, 0.0)
    resist += character.effect_magnitude("resist_" + damage_kind) / 100.0
    if damage_kind == "magic":
        resist += character.attrs.get(attr.ENDURANCE, 40) * 0.002
    resist = max(-1.0, min(1.0, resist))
    if resist:
        before = dmg
        dmg *= (1.0 - resist)
        result["resisted"] = round(before - dmg, 1)

    result["final"] = max(0.0, round(dmg, 1))
    return result
