"""
Combat rules — the maths of hitting things and being hit.

Pure, deterministic-ish formulas (an optional RNG is injected for tests). Covers:

* **player melee / bow / spell damage** against a creature — scaled by weapon,
  the governing skill, Strength (melee), draw quality (bow), sneak attacks and a
  luck-weighted critical chance;
* **incoming damage mitigation** for the player — armour rating, active shield
  effects, blocking, and elemental resistances from the character;
* **hit chance** — fatigue/agility/weapon-skill vs a target's agility.

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
from ..diceroll import DiceRoller


# ---------------------------------------------------------------------------
# Hit chance
# ---------------------------------------------------------------------------
def hit_chance(character, weapon_skill: int, target_agility: int = 30,
               fatigue_frac: float = 1.0) -> float:
    """Probability [0.05, 0.95] that a swing/shot lands.

    Classic Morrowind-ish: weapon skill + agility/luck + fatigue, minus the
    target's agility. Fatigue below full drags the chance down.
    """
    agi = character.attrs.get(attr.AGILITY, 40)
    luck = character.attrs.get(attr.LUCK, 40)
    attack = weapon_skill + agi * 0.2 + luck * 0.1
    attack *= (0.5 + 0.5 * max(0.0, min(1.0, fatigue_frac)))
    defend = target_agility * 0.25
    chance = (attack - defend) / 100.0
    return max(0.05, min(0.95, chance))


# ---------------------------------------------------------------------------
# Player outgoing damage
# ---------------------------------------------------------------------------
def player_attack(character, target_props: Dict, *, sneaking: bool = False,
                  draw: float = 1.0, rng: Optional[random.Random] = None,
                  dice: Optional[DiceRoller] = None,
                  guaranteed_hit: bool = False) -> Dict:
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
    """
    rng = rng or random
    w = eq.weapon(character)
    kind = w.get("kind", items.KIND_MELEE) if w else items.KIND_MELEE
    skill_id = w.get("skill", sk.BLADE) if w else sk.BLADE
    if w is None:
        # Unarmed: hand-to-hand, small damage scaled by strength.
        skill_id = sk.BLADE
        base = 2.0
        kind = items.KIND_MELEE
    else:
        base = float(w.get("damage", 5)) * eq.rarity_stat(character, items.SLOT_WEAPON)

    skill = character.skill(skill_id)
    target_agi = int(target_props.get("agility", 24))
    fatigue_frac = character.stamina / character.max_stamina if character.max_stamina else 1.0

    result = {"hit": False, "damage": 0.0, "crit": False, "sneak": False,
              "skill": skill_id, "difficulty": 1.0, "killed": False, "kind": kind}

    # Bows need ammo; a staff spends magicka handled by the caller.
    if kind == items.KIND_BOW and eq.ammo(character) is None:
        result["no_ammo"] = True
        return result

    hit_probability = hit_chance(character, skill, target_agi, fatigue_frac)
    if guaranteed_hit and kind == items.KIND_MELEE:
        # Near + facing, confirmed by the caller: always connects.
        result["hit_probability"] = hit_probability
    elif dice is not None:
        hit_roll = dice.request_roll(
            "1d100", source="combat.hit",
            context={"skill": skill_id, "target": target_props.get("name", "")})
        result["hit_roll"] = hit_roll
        hit_value = hit_roll["roll_result"]
        if hit_value > hit_probability * 100.0:
            return result
    elif rng.random() > hit_probability:
        return result  # miss
    result["hit"] = True

    # --- base scaling by skill (0.4x at 0 skill → ~1.3x at 100) ---
    dmg = base * (0.4 + skill / 110.0)

    if kind == items.KIND_MELEE:
        # Strength adds a meaningful chunk to melee.
        dmg *= 0.7 + character.attrs.get(attr.STRENGTH, 40) / 100.0
    elif kind == items.KIND_BOW:
        arrow = eq.ammo(character)
        dmg += float(arrow.get("damage", 0)) if arrow else 0.0
        dmg *= 0.5 + 0.5 * max(0.1, min(1.0, draw))   # a fuller draw hits harder
    elif kind == items.KIND_STAFF:
        dmg *= 0.7 + character.skill(sk.DESTRUCTION) / 100.0

    # --- sneak attack ---
    if sneaking:
        mult = 3.0 if kind == items.KIND_MELEE else 2.0
        # a dagger sneak is the assassin's classic ×6
        if w and w.id.endswith("dagger"):
            mult = 6.0
        dmg *= mult
        result["sneak"] = True

    # --- critical (luck-weighted) ---
    crit_chance = 0.05 + character.attrs.get(attr.LUCK, 40) * 0.0015
    if dice is not None:
        crit_roll = dice.request_roll(
            "1d100", source="combat.critical",
            context={"skill": skill_id, "target": target_props.get("name", "")})
        result["critical_roll"] = crit_roll
        is_critical = crit_roll["roll_result"] <= crit_chance * 100.0
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
                     blocking: bool = False, rng: Optional[random.Random] = None) -> Dict:
    """Apply armour, shield, block and resistance to *raw_damage*.

    Returns ``{"final", "blocked", "armor", "resisted", "armor_class"}``. Does
    **not** subtract from health (the caller does, so it can also fire death
    logic); does return the armour class worn so the caller can train the skill.
    """
    from . import races
    rng = rng or random
    dmg = max(0.0, float(raw_damage))
    result = {"final": dmg, "blocked": 0.0, "armor": 0.0, "resisted": 0.0,
              "armor_class": eq.armor_class_worn(character)}

    # Block: a shield + Block skill soaks a fraction of a physical blow.
    if blocking and damage_kind == "physical":
        shield = eq.equipped_def(character, items.SLOT_SHIELD)
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
        resist += character.attrs.get(attr.WILLPOWER, 40) * 0.002
    resist = max(-1.0, min(1.0, resist))
    if resist:
        before = dmg
        dmg *= (1.0 - resist)
        result["resisted"] = round(before - dmg, 1)

    result["final"] = max(0.0, round(dmg, 1))
    return result
