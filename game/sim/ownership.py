"""
Ownership — the one property that turns "picking something up" into a story.

Every world object and every item stack may carry an ``owner`` (a stable actor
key) and, for placeables, an ``owner_faction``. Nothing else changes: a bucket
of milk is an ordinary item that happens to be owned. From that single field
the rest of the simulation gets, for free:

* taking it is a **theft** event, which is a crime, which needs witnesses
* the owner's disposition toward the thief drops when they find out
* a stolen stack stays marked, so a merchant can refuse to buy it back and a
  guard who searches you finds it
* giving it away, trading it or dropping it re-assigns or clears the owner

No quest, no special case, no "milk quest". A cow that produces a bucket owned
by its owner is enough for milk to become worth stealing.
"""

from __future__ import annotations

from typing import Dict, Optional

#: Property/stack keys. Kept as plain strings so authored JSON, the editor's
#: property panel and save files all agree without a schema.
OWNER = "owner"
OWNER_NAME = "owner_name"
OWNER_FACTION = "owner_faction"
STOLEN = "stolen"
STOLEN_FROM = "stolen_from"

#: Minimum bounty a theft carries however worthless the goods — the offence is
#: the taking, not the value.
MIN_THEFT_VALUE = 5


def owner_of(props: Optional[Dict]) -> str:
    """The owning actor's key, or ``""`` when the thing is unowned."""
    if not isinstance(props, dict):
        return ""
    return str(props.get(OWNER, "") or "").strip()


def owner_name_of(props: Optional[Dict]) -> str:
    if not isinstance(props, dict):
        return ""
    return str(props.get(OWNER_NAME, "") or props.get(OWNER, "") or "").strip()


def owner_faction_of(props: Optional[Dict]) -> str:
    if not isinstance(props, dict):
        return ""
    return str(props.get(OWNER_FACTION, "") or "").strip()


def is_owned(props: Optional[Dict]) -> bool:
    return bool(owner_of(props) or owner_faction_of(props))


def set_owner(props: Dict, owner_key: str, owner_name: str = "",
              faction: str = "") -> None:
    """Assign (or, with an empty key, clear) ownership of a thing or stack."""
    if not isinstance(props, dict):
        return
    key = str(owner_key or "").strip()
    if key:
        props[OWNER] = key
        props[OWNER_NAME] = str(owner_name or key)
    else:
        props.pop(OWNER, None)
        props.pop(OWNER_NAME, None)
    if faction:
        props[OWNER_FACTION] = str(faction)
    else:
        props.pop(OWNER_FACTION, None)


def belongs_to(props: Optional[Dict], actor_key: str,
               actor_faction: str = "") -> bool:
    """Whether *actor_key* may take this freely — they own it, or their faction
    does. Unowned things belong to whoever picks them up."""
    if not is_owned(props):
        return True
    key = str(actor_key or "")
    if key and owner_of(props) == key:
        return True
    of = owner_faction_of(props)
    return bool(of and actor_faction and of == actor_faction)


def is_theft(props: Optional[Dict], taker_key: str,
             taker_faction: str = "") -> bool:
    """Is taking this thing a crime for this taker?"""
    return is_owned(props) and not belongs_to(props, taker_key, taker_faction)


def mark_stolen(stack: Dict, from_key: str, from_name: str = "") -> Dict:
    """Brand an item stack as stolen goods (it keeps the brand until fenced)."""
    if isinstance(stack, dict):
        stack[STOLEN] = True
        stack[STOLEN_FROM] = str(from_name or from_key or "")
    return stack


def is_stolen(stack: Optional[Dict]) -> bool:
    return bool(isinstance(stack, dict) and stack.get(STOLEN))


def launder(stack: Dict) -> Dict:
    """Clear the stolen brand (a fence, a legitimate purchase, an amnesty)."""
    if isinstance(stack, dict):
        stack.pop(STOLEN, None)
        stack.pop(STOLEN_FROM, None)
    return stack


def theft_value(stack_or_props: Optional[Dict], default: int = MIN_THEFT_VALUE) -> int:
    """How much the taken goods were worth, for scaling the offence."""
    if not isinstance(stack_or_props, dict):
        return default
    for field in ("value", "item_value", "gold"):
        try:
            v = int(stack_or_props.get(field, 0) or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return max(default, v)
    try:
        qty = max(1, int(stack_or_props.get("quantity", 1) or 1))
    except (TypeError, ValueError):
        qty = 1
    return max(default, default * qty)


def describe(props: Optional[Dict]) -> str:
    """A one-line ownership summary for the object inspector."""
    if not is_owned(props):
        return "unowned"
    name = owner_name_of(props)
    fac = owner_faction_of(props)
    if name and fac:
        return f"owned by {name} ({fac})"
    if name:
        return f"owned by {name}"
    return f"owned by the {fac}"
