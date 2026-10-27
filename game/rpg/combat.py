"""
Combat rules — the maths of hitting things and being hit.

Pure, deterministic-ish formulas (an optional RNG is injected for tests). Covers:

* **player melee / bow / spell damage** against a creature — scaled by weapon,
  the governing skill, Strength (melee), draw quality (bow), sneak attacks and a
  luck-weighted critical chance;
* **incoming damage mitigation** for the player — armour rating, active shield
  effects, blocking, and elemental resistances from the character;
* **hit chance** — fatigue/endurance/weapon-skill vs a target's endurance.

Creature-vs-creature and creature ranged travel are handled by the engine's
:class:`~engine.monster_ai.MonsterAI` (now fantasy: melee & arrows, no guns);
this module governs everything the *player character* does, where the deep RPG
stats live.
"""

from __future__ import annotations

import random
from typing import Dict, Optional

from . import attributes as attr
from . import skills as sk
from . import items
from . import equipment as eq
from . import charisma
from ..diceroll import DiceRoller, check_target, roll_check


# ---------------------------------------------------------------------------
# Hit chance
# ---------------------------------------------------------------------------
#: Two weapons at once cost accuracy: each hand's chance to hit is scaled by
#: this, and a pair of crossbows scatters its bolts by up to DUAL_WIELD_SPREAD
#: degrees. A trade some fighters decline (game.held_weapons).
DUAL_WIELD_ACCURACY = 0.8
DUAL_WIELD_SPREAD = 5.0


def hit_chance(character, weapon_skill: int, target_endurance: int = 40,
               fatigue_frac: float = 1.0) -> float:
    """Probability [0.05, 0.95] that a swing/shot lands.

    Weapon skill + endurance/luck + fatigue, minus the
    target's endurance (every living thing has one, see
    :func:`charisma.core`). Fatigue below full drags the chance down.
    """
    end = character.attrs.get(attr.ENDURANCE, 40)
    luck = character.attrs.get(attr.LUCK, 40)
    attack = weapon_skill + end * 0.2 + luck * 0.1
    attack *= (0.5 + 0.5 * max(0.0, min(1.0, fatigue_frac)))
    defend = target_endurance * 0.15
    chance = (attack - defend) / 100.0
    return max(0.05, min(0.95, chance))


def _target_name(target_props: Dict) -> str:
    return str(target_props.get("display_name") or target_props.get("name") or "")


def _hit_why(character, skill_id: str, skill: int, target_endurance: int,
             fatigue_frac: float, chance: float) -> str:
    """What went into a hit chance, in the player's terms:
    ``Blade 35 vs their Endurance 40, winded — 48%``."""
    parts = [f"{sk.label(skill_id)} {skill} vs their Endurance {target_endurance}"]
    if fatigue_frac < 0.75:
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
    "why"}`` -- the same numbers :func:`player_attack` will roll against. A
    *sure_hit* (a lone melee weapon in reach) needs no hit roll at all.
    """
    w = eq.hand_weapon(character, hand)
    skill_id = w.get("skill", sk.BLADE) if w else sk.BLADE
    skill = character.skill(skill_id)
    target_end = charisma.core(target_props, attr.ENDURANCE)
    fatigue = character.stamina / character.max_stamina if character.max_stamina else 1.0
    chance = hit_chance(character, skill, target_end, fatigue)
    if eq.dual_wielding(character):
        chance *= DUAL_WIELD_ACCURACY
    crit = critical_chance(character)
    return {"hit_chance": chance, "hit_target": check_target(chance),
            "sure_hit": bool(sure_hit),
            "crit_chance": crit, "crit_target": check_target(crit),
            "why": _hit_why(character, skill_id, skill, target_end, fatigue, chance)}


# ---------------------------------------------------------------------------
# Player outgoing damage
# ---------------------------------------------------------------------------
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

    ``guaranteed_hit`` skips the hit-chance roll for melee swings only (bows
    and staves still roll normally). The caller sets this when the target was
    already confirmed to be in melee range and squarely faced — camera pitch
    plays no part in that check, so a close, faced target should never whiff.

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
    target_end = charisma.core(target_props, attr.ENDURANCE)
    fatigue_frac = character.stamina / character.max_stamina if character.max_stamina else 1.0

    result = {"hit": False, "damage": 0.0, "crit": False, "sneak": False,
              "skill": skill_id, "difficulty": 1.0, "killed": False, "kind": kind}

    # Bows and crossbows need ammo; a staff spends magicka handled by the caller.
    shot = eq.ammo_for(character, w) if kind in items.RANGED_KINDS else None
    if kind in items.RANGED_KINDS and shot is None:
        result["no_ammo"] = True
        return result

    hit_probability = hit_chance(character, skill, target_end, fatigue_frac)
    if eq.dual_wielding(character):
        hit_probability *= DUAL_WIELD_ACCURACY
    if guaranteed_hit and kind == items.KIND_MELEE:
        # Near + facing, confirmed by the caller: always connects.
        result["hit_probability"] = hit_probability
    elif dice is not None:
        # Resolved on a d20, not a percentile die: every roll is shown to the
        # player and there is no d100 in this game (see diceroll.CHECK_DIE).
        hit_roll = roll_check(
            dice, hit_probability, f"Roll to hit {_target_name(target_props)}".strip(),
            source="combat.hit",
            why=_hit_why(character, skill_id, skill, target_end, fatigue_frac,
                         hit_probability),
            context={"skill": skill_id, "target": target_props.get("name", "")})
        result["hit_roll"] = hit_roll
        if not hit_roll["success"]:
            return result
    elif rng.random() > hit_probability:
        return result  # miss
    result["hit"] = True

    # --- base scaling by skill (0.4x at 0 skill → ~1.3x at 100) ---
    dmg = base * (0.4 + skill / 110.0)

    if kind == items.KIND_MELEE:
        # Strength adds a meaningful chunk to melee.
        dmg *= 0.7 + character.attrs.get(attr.STRENGTH, 40) / 100.0
        # A gathered blow (a warrior's charged fist) multiplies it.
        dmg *= max(0.1, float(power))
    elif kind == items.KIND_BOW:
        dmg += float(shot.get("damage", 0)) if shot else 0.0
        dmg *= 0.5 + 0.5 * max(0.1, min(1.0, draw))   # a fuller draw hits harder
    elif kind == items.KIND_CROSSBOW:
        dmg += float(shot.get("damage", 0)) if shot else 0.0   # no draw: always full
    elif kind == items.KIND_STAFF:
        dmg *= 0.7 + character.skill(sk.OFFENSIVE) / 100.0

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
                     dice: Optional[DiceRoller] = None, attacker: str = "") -> Dict:
    """Apply armour, shield, block and resistance to *raw_damage*.

    Returns ``{"final", "blocked", "armor", "resisted", "armor_class"}``. Does
    **not** subtract from health (the caller does, so it can also fire death
    logic); does return the armour class worn so the caller can train the skill.

    With *dice*, the Armour Class check is shown as the *attacker* rolling to
    hit the player ("Bandit rolls to hit you: 9 (need 13+)"): a miss is a blow
    the armour turned aside. A ``quiet`` roll -- the roll log, not the dice
    panel, so the player's own rolls stay on screen mid-fight.
    """
    from . import races
    rng = rng or random
    dmg = max(0.0, float(raw_damage))
    result = {"final": dmg, "blocked": 0.0, "armor": 0.0, "resisted": 0.0,
              "armor_class": eq.armor_class_worn(character)}

    # Armour Class: a well-armoured, nimble body turns some blows aside
    # completely before anything else is weighed.
    if damage_kind == "physical" and dmg > 0:
        result["ac"] = eq.armour_class(character)
        deflect = eq.deflect_chance(character)
        if dice is not None and deflect > 0.0:
            roll = roll_check(
                dice, 1.0 - deflect, f"{attacker or 'Your foe'} rolls to hit you",
                source="combat.incoming",
                why=f"against your Armour Class {result['ac']}",
                context={"quiet": True, "against_player": True})
            result["defence_roll"] = roll
            deflected = not roll["success"]
        else:
            deflected = rng.random() < deflect
        if deflected:
            result["deflected"] = True
            result["final"] = 0.0
            return result

    # Block: a shield + Block skill soaks a fraction of a physical blow.
    if blocking and damage_kind == "physical":
        shield = eq.shield(character)
        block_skill = character.skill(sk.BLOCK)
        block_frac = min(0.75, (0.2 if shield else 0.05) + block_skill / 200.0)
        blocked = dmg * block_frac
        result["blocked"] = round(blocked, 1)
        dmg -= blocked
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
