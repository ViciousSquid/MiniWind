"""
Items — weapons, armour, ammunition, potions, ingredients, books and loot.

An *item* in the world/inventory is a lightweight stack dict (see
:mod:`inventory`): ``{"id","name","qty","type","value","weight",...}``. This
module is the **item database**: the static definitions every ``id`` resolves
to (damage, armour rating, equip slot, material, effects). Keeping the heavy
data here and only the ``id`` + per-instance bits (quantity, enchant charge) in
the stack keeps saves small and lets one definition drive many stacks.

Nothing here imports the engine.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# item categories (superset of inventory.ITEM_TYPES for richer handling)
WEAPON = "weapon"
ARMOUR = "armour"
AMMO = "ammo"
POTION = "potion"
INGREDIENT = "ingredient"
BOOK = "book"
SCROLL = "scroll"
KEY = "key"
GOLD = "gold"
MISC = "misc"

# equip slots
SLOT_WEAPON = "weapon"
SLOT_AMMO = "ammo"
SLOT_SHIELD = "shield"
SLOT_HEAD = "head"
SLOT_CHEST = "chest"
SLOT_HANDS = "hands"
SLOT_LEGS = "legs"
SLOT_FEET = "feet"
SLOT_AMULET = "amulet"
SLOT_RING = "ring"

ARMOUR_SLOTS = (SLOT_HEAD, SLOT_CHEST, SLOT_HANDS, SLOT_LEGS, SLOT_FEET, SLOT_SHIELD)
ALL_SLOTS = (SLOT_WEAPON, SLOT_AMMO, SLOT_SHIELD, SLOT_HEAD, SLOT_CHEST,
             SLOT_HANDS, SLOT_LEGS, SLOT_FEET, SLOT_AMULET, SLOT_RING)

# weapon kinds (drive combat + which core attack the engine plays)
KIND_MELEE = "melee"
KIND_BOW = "bow"
KIND_STAFF = "staff"


class ItemDef:
    """Static definition of an item type."""

    def __init__(self, iid, name, category, value=0, weight=0.0, desc="", **extra):
        self.id = iid
        self.name = name
        self.category = category
        self.value = int(value)
        self.weight = float(weight)
        self.desc = desc
        self.extra = extra  # category-specific fields

    def get(self, key, default=None):
        return self.extra.get(key, default)

    def make_stack(self, qty: int = 1) -> Dict:
        """Build an inventory stack dict for this item."""
        return {
            "id": self.id, "name": self.name, "qty": int(qty),
            "type": self.category, "value": self.value, "weight": self.weight,
            "description": self.desc,
        }


# ---------------------------------------------------------------------------
# Rarity tiers (an ARPG touch — Diablo/Gothic flavour on top of the sim).
# A dropped stack may carry a "rarity" key; rarer finds are worth more and are
# tinted in the UI. Weapons/armour of a higher rarity also hit / protect harder.
# ---------------------------------------------------------------------------
COMMON = "common"
FINE = "fine"
RARE = "rare"
EPIC = "epic"

RARITY_ORDER = [COMMON, FINE, RARE, EPIC]
#: display prefix, value multiplier, stat multiplier, RGB tint
RARITY_INFO = {
    COMMON: {"prefix": "", "value": 1.0, "stat": 1.0, "rgb": (232, 228, 240)},
    FINE:   {"prefix": "Fine ", "value": 1.6, "stat": 1.15, "rgb": (120, 210, 130)},
    RARE:   {"prefix": "Rare ", "value": 3.0, "stat": 1.35, "rgb": (110, 170, 255)},
    EPIC:   {"prefix": "Fabled ", "value": 6.0, "stat": 1.7, "rgb": (200, 140, 255)},
}


def rarity_of(stack: Dict) -> str:
    r = stack.get("rarity", COMMON) if isinstance(stack, dict) else COMMON
    return r if r in RARITY_INFO else COMMON


def rarity_rgb(stack: Dict):
    return RARITY_INFO[rarity_of(stack)]["rgb"]


def apply_rarity(stack: Dict, rarity: str) -> Dict:
    """Tag a stack with a rarity, scaling its value/name in place."""
    info = RARITY_INFO.get(rarity)
    if not info or rarity == COMMON:
        return stack
    stack["rarity"] = rarity
    stack["value"] = int(stack.get("value", 0) * info["value"])
    if info["prefix"] and not stack.get("name", "").startswith(info["prefix"]):
        stack["name"] = info["prefix"] + stack.get("name", "")
    return stack


ITEMS: Dict[str, ItemDef] = {}


def register(item: ItemDef) -> ItemDef:
    ITEMS[item.id] = item
    return item


def get(item_id: str) -> Optional[ItemDef]:
    return ITEMS.get(str(item_id))


def make(item_id: str, qty: int = 1) -> Optional[Dict]:
    d = get(item_id)
    return d.make_stack(qty) if d else None


# ---------------------------------------------------------------------------
# The item database is editable *content*: every definition (weapons, armour,
# ammunition, potions, ingredients, books, misc) lives in ``game/data/items.json``
# (plus any mods), while the :class:`ItemDef` template, rarity system and combat
# maths that read these stay code. A modder retunes a sword's damage or adds a
# whole new weapon by editing JSON — no code change.
# ---------------------------------------------------------------------------
def _load_items() -> None:
    from game import data
    for iid, row in (data.load("items") or {}).items():
        row = dict(row)
        register(ItemDef(
            iid,
            row.pop("name", iid),
            row.pop("category", MISC),
            value=row.pop("value", 0),
            weight=row.pop("weight", 0.0),
            desc=row.pop("desc", ""),
            **row,   # category-specific fields: kind, skill, damage, slot, effects…
        ))


_load_items()


# ---------------------------------------------------------------------------
# Convenience queries
# ---------------------------------------------------------------------------
def is_equippable(item_id: str) -> bool:
    d = get(item_id)
    return bool(d and (d.get("slot") or d.category in (WEAPON, ARMOUR, AMMO)))


def slot_of(item_id: str) -> Optional[str]:
    d = get(item_id)
    if not d:
        return None
    return d.get("slot")


def items_by_category(category: str) -> List[ItemDef]:
    return [d for d in ITEMS.values() if d.category == category]
