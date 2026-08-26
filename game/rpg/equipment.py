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


def _is_two_handed(item_def) -> bool:
    if item_def.get("kind") == items.KIND_BOW:
        return True
    return item_def.id in ("iron_warhammer", "iron_battleaxe")


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
        klass = d.get("armor_class", "light")
        skill_id = sk.HEAVY_ARMOR if klass == "heavy" else sk.LIGHT_ARMOR
        skill = character.skill(skill_id)
        total += base * (0.4 + skill / 100.0) * rarity_stat(character, slot)
    return total


def armor_class_worn(character) -> str:
    """Whether the character is mostly in heavy or light armour (for training)."""
    heavy = light = 0
    for slot in items.ARMOUR_SLOTS:
        d = equipped_def(character, slot)
        if d and d.category == items.ARMOUR:
            if d.get("armor_class") == "heavy":
                heavy += 1
            else:
                light += 1
    return "heavy" if heavy >= light and heavy > 0 else ("light" if light > 0 else "none")


def total_equipped_weight(character) -> float:
    total = 0.0
    for slot, iid in character.equipment.items():
        d = items.get(iid)
        if d:
            total += d.weight
    return total
