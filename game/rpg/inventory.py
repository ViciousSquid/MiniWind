"""
A simple, expandable RPG inventory (§6).

An inventory is just a ``list`` of item-stack dicts stored on an entity under
``properties['inventory']``. Because it lives in the ordinary ``properties``
dict (no leading underscore), Fio's existing serializer saves and UUID-matches
it for free — player, NPC and monster inventories all persist through the stock
save/load path with no new format (§12).

Item schema (all optional except ``id``)::

    {
        "id": "iron_sword",     # stable item type id
        "name": "Iron Sword",   # display name
        "qty": 1,               # stack quantity
        "type": "weapon",       # weapon|armour|consumable|quest|misc|key|gold
        "value": 25,            # gold value
        "weight": 8.0,          # encumbrance weight
        "description": "A plain but reliable blade.",
    }

These are free functions that operate on the list in place, so they work
whether the owner is a ``Thing`` subclass, the player stats object, or a bare
dict — nothing here imports the editor. The data model deliberately leaves room
for equipment slots, containers, loot tables and per-instance ids later without
changing the storage shape.

Pure Python — safe everywhere.
"""

from __future__ import annotations

from typing import Dict, List, Optional

ITEM_TYPES = ("weapon", "armour", "consumable", "quest", "misc", "key", "gold")


def make_item(item_id: str, name: str = "", qty: int = 1, item_type: str = "misc",
              value: int = 0, weight: float = 0.0, description: str = "") -> Dict:
    """Build a well-formed item-stack dict."""
    return {
        "id": str(item_id),
        "name": name or str(item_id).replace("_", " ").title(),
        "qty": int(qty),
        "type": item_type if item_type in ITEM_TYPES else "misc",
        "value": int(value),
        "weight": float(weight),
        "description": description,
    }


def _coerce(inv) -> List[Dict]:
    """Return a mutable item list, tolerating None / bad hand-edited data."""
    if isinstance(inv, list):
        return inv
    return []


def get_inventory(owner) -> List[Dict]:
    """Return (creating if needed) the inventory list for *owner*.

    *owner* may be anything with a ``properties`` dict, or a plain dict.
    """
    props = getattr(owner, "properties", owner)
    inv = props.get("inventory")
    if not isinstance(inv, list):
        inv = []
        props["inventory"] = inv
    return inv


def find(inv: List[Dict], item_id: str) -> Optional[Dict]:
    item_id = str(item_id)
    for stack in _coerce(inv):
        if str(stack.get("id")) == item_id:
            return stack
    return None


def quantity(inv: List[Dict], item_id: str) -> int:
    stack = find(inv, item_id)
    return int(stack.get("qty", 0)) if stack else 0


def has_item(inv: List[Dict], item_id: str, qty: int = 1) -> bool:
    return quantity(inv, item_id) >= qty


def add_item(inv: List[Dict], item: Dict, qty: int = None) -> Dict:
    """Add *item* to *inv*, stacking onto an existing stack by ``id``.

    Returns the resulting stack. *qty* overrides ``item['qty']`` when given.
    """
    inv = _coerce(inv)
    add_qty = int(qty if qty is not None else item.get("qty", 1))
    existing = find(inv, item.get("id"))
    if existing is not None:
        existing["qty"] = int(existing.get("qty", 0)) + add_qty
        return existing
    stack = dict(item)
    stack["qty"] = add_qty
    inv.append(stack)
    return stack


def remove_item(inv: List[Dict], item_id: str, qty: int = 1) -> int:
    """Remove up to *qty* of *item_id*. Returns the amount actually removed."""
    inv = _coerce(inv)
    stack = find(inv, item_id)
    if stack is None:
        return 0
    have = int(stack.get("qty", 0))
    take = min(have, int(qty))
    stack["qty"] = have - take
    if stack["qty"] <= 0:
        inv.remove(stack)
    return take


def transfer(src: List[Dict], dst: List[Dict], item_id: str, qty: int = 1) -> int:
    """Move up to *qty* of *item_id* from *src* to *dst*. Returns amount moved."""
    stack = find(src, item_id)
    if stack is None:
        return 0
    template = dict(stack)
    moved = remove_item(src, item_id, qty)
    if moved > 0:
        add_item(dst, template, qty=moved)
    return moved


def total_weight(inv: List[Dict]) -> float:
    return sum(float(s.get("weight", 0.0)) * int(s.get("qty", 0)) for s in _coerce(inv))


def total_value(inv: List[Dict]) -> int:
    return sum(int(s.get("value", 0)) * int(s.get("qty", 0)) for s in _coerce(inv))
