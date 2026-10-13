"""
Equipment — what the character is wearing and wielding.

The character keeps ``equipment`` as ``{slot: item_id}``. This module is the
logic over it: equip/unequip (respecting slots and that the item is actually in
the inventory), the equipped weapon/ammo, and the total **armour rating** that
combat mitigation reads. Wearing armour also trains the governing armour skill
(handled in combat when you're hit).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from . import items
from . import inventory as inv
from . import skills as sk


def equipped_id(character, slot: str) -> Optional[str]:
    return character.equipment.get(slot)


def equipped_stack(character, slot: str):
    """The inventory stack backing the item in *slot* (carries rarity), or None."""
    iid = character.equipment.get(slot)
    if not iid:
        return None
    return inv.find(character.inventory, iid)


def rarity_stat(character, slot: str) -> float:
    """Stat multiplier from the equipped item's rarity (1.0 if common/absent)."""
    stack = equipped_stack(character, slot)
    if not stack:
        return 1.0
    return items.RARITY_INFO[items.rarity_of(stack)]["stat"]


def equipped_def(character, slot: str):
    iid = character.equipment.get(slot)
    return items.get(iid) if iid else None


def can_equip(character, item_id: str) -> bool:
    d = items.get(item_id)
    if not d:
        return False
    if not (d.get("slot") or d.category in (items.WEAPON, items.ARMOUR, items.AMMO)):
        return False
    return inv.has_item(character.inventory, item_id, 1)


def _slot_for(item_def) -> Optional[str]:
    slot = item_def.get("slot")
    if slot:
        return slot
    if item_def.category == items.AMMO:
        return items.SLOT_AMMO
    if item_def.category == items.WEAPON:
        return items.SLOT_WEAPON
    return None


def equip(character, item_id: str) -> bool:
    """Equip *item_id* from the inventory into its slot. Returns success."""
    d = items.get(item_id)
    if not d or not inv.has_item(character.inventory, item_id, 1):
        return False
    slot = _slot_for(d)
    if not slot:
        return False
    character.equipment[slot] = item_id
    # Equipping a two-handed weapon (bow, warhammer, battleaxe) frees the shield.
    if slot == items.SLOT_WEAPON and _is_two_handed(d):
        character.equipment.pop(items.SLOT_SHIELD, None)
    _refresh_weapon_kind(character)
    return True


def unequip(character, slot: str) -> bool:
    if slot in character.equipment:
        character.equipment.pop(slot, None)
        _refresh_weapon_kind(character)
        return True
    return False


#: Two-handers from before the item data carried the fact itself. Kept so an
#: older items.json (or a mod's) still classifies them correctly.
_LEGACY_TWO_HANDED = ("iron_warhammer", "iron_battleaxe")


def _is_two_handed(item_def) -> bool:
    if item_def.get("kind") == items.KIND_BOW:
        return True
    # A weapon says so itself where the data has it (scythe, pitchfork, shovel).
    if item_def.get("two_handed"):
        return True
    return item_def.id in _LEGACY_TWO_HANDED


def _refresh_weapon_kind(character) -> None:
    d = equipped_def(character, items.SLOT_WEAPON)
    if character.active_spell:
        character.active_weapon_kind = "spell"
    elif d is None:
        character.active_weapon_kind = "unarmed"
    else:
        character.active_weapon_kind = d.get("kind", items.KIND_MELEE)


def weapon(character):
    """The equipped weapon ItemDef, or None (unarmed)."""
    return equipped_def(character, items.SLOT_WEAPON)


def ammo(character):
    return equipped_def(character, items.SLOT_AMMO)


def light_source(character):
    """The equipped carried light (torch/lantern) ItemDef, or None.

    Read by the runtime to decide whether to float a dynamic light on the
    player; NPCs use an authored ``torch`` flag instead of an equipment slot."""
    d = equipped_def(character, items.SLOT_LIGHT)
    return d if items.is_light_source(d) else None


#: The three weights of armour. Light leaves you nimble, heavy turns blows
#: but slows nothing except your dodging.
LIGHT = "light"
MEDIUM = "medium"
HEAVY = "heavy"
ARMOUR_WEIGHTS = (LIGHT, MEDIUM, HEAVY)

#: Base Armour Class with nothing on, D&D-style.
BASE_AC = 10
#: Armour rating points per point of Armour Class.
RATING_PER_AC = 4.0
#: How many points of Agility bonus each weight of armour still lets through
#: (None: all of it). Agility gives +1 AC per 10 points above 40.
AGILITY_CAP = {LIGHT: None, MEDIUM: 2, HEAVY: 0}
#: Chance per point of AC above :data:`BASE_AC` that a blow glances off
#: entirely, and the most that can ever do.
DEFLECT_PER_AC = 0.025
DEFLECT_MAX = 0.6


def _armour_skill(character, weight: str) -> float:
    """The skill that makes armour of *weight* protect better. Medium armour
    draws on both Light and Heavy Armour, so either trains it."""
    if weight == HEAVY:
        return float(character.skill(sk.HEAVY_ARMOR))
    if weight == MEDIUM:
        return (character.skill(sk.HEAVY_ARMOR) + character.skill(sk.LIGHT_ARMOR)) / 2.0
    return float(character.skill(sk.LIGHT_ARMOR))


def armor_rating(character) -> float:
    """Sum of worn armour ratings, scaled by the relevant armour skill.

    Higher Heavy/Light Armor skill makes the same plate protect more (classic
    'skill multiplies base rating'). Shield adds when not two-handed.
    """
    total = 0.0
    for slot in items.ARMOUR_SLOTS:
        d = equipped_def(character, slot)
        if not d or d.category != items.ARMOUR:
            continue
        base = float(d.get("armor_rating", 0))
        skill = _armour_skill(character, str(d.get("armor_class", LIGHT)))
        total += base * (0.4 + skill / 100.0) * rarity_stat(character, slot)
    return total


def armor_class_worn(character) -> str:
    """The heaviest weight of armour worn: "heavy", "medium", "light" or
    "none". That is what governs how nimble you still are, and which armour
    skill a blow trains."""
    worn = set()
    for slot in items.ARMOUR_SLOTS:
        d = equipped_def(character, slot)
        if d and d.category == items.ARMOUR:
            weight = str(d.get("armor_class", LIGHT))
            if weight in ARMOUR_WEIGHTS:
                worn.add(weight)
    for weight in (HEAVY, MEDIUM, LIGHT):
        if weight in worn:
            return weight
    return "none"


def armour_class(character) -> int:
    """The character's Armour Class: how hard they are to hurt at all.

    ``10 + armour + agility + charms``: every :data:`RATING_PER_AC` points of
    (skill-scaled) armour rating add one; Agility adds one per ten points above
    40, as much as the heaviest armour worn allows (all of it in light armour,
    two in medium, none in heavy); and protective rings and amulets add their
    ``ac_bonus``. Shown on the inventory and character sheet, and rolled
    against every physical blow (:func:`deflect_chance`).
    """
    from . import attributes as attr
    armour = int(armor_rating(character) // RATING_PER_AC)
    agility = max(0, (int(character.attrs.get(attr.AGILITY, 40)) - 40) // 10)
    cap = AGILITY_CAP.get(armor_class_worn(character))
    if cap is not None:
        agility = min(agility, cap)
    charms = 0
    for slot in (items.SLOT_RING, items.SLOT_AMULET):
        d = equipped_def(character, slot)
        if d is not None:
            try:
                charms += int(d.get("ac_bonus", 0) or 0)
            except (TypeError, ValueError):
                pass
    return BASE_AC + armour + agility + charms


def deflect_chance(character) -> float:
    """Chance a physical blow glances off without harm, from Armour Class."""
    return max(0.0, min(DEFLECT_MAX, (armour_class(character) - BASE_AC) * DEFLECT_PER_AC))


def total_equipped_weight(character) -> float:
    total = 0.0
    for slot, iid in character.equipment.items():
        d = items.get(iid)
        if d:
            total += d.weight
    return total
