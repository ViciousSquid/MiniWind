"""
MiniWind's weapon knowledge, handed to the engine's combat loadout.

:mod:`engine.combat_loadout` decides *when* an actor switches between blade,
bow and spell; which carried items are weapons, and which style each drives,
comes from MiniWind's item database. :func:`register` installs that lookup on
the engine, and runs when the ``game`` package is imported.
"""

from __future__ import annotations

from . import combat_loadout

#: Weapon ``kind`` in the item database -> the engine's attack style.
KIND_STYLES = {
    "melee": combat_loadout.MELEE,
    "bow": combat_loadout.BOW,
    "crossbow": combat_loadout.BOW,      # shot from range, like a bow
    "staff": combat_loadout.MAGIC,
}


def weapon_attack_style(item_id):
    """The attack style *item_id* drives, or None when it is not a weapon."""
    from .rpg import items
    definition = items.get(str(item_id))
    if definition is None or definition.category != items.WEAPON:
        return None
    return KIND_STYLES.get(str(definition.get("kind", "")).lower())


def weapon_rating(item_id) -> float:
    """How hard *item_id* hits over time: its damage times its swing speed."""
    from .rpg import items
    definition = items.get(str(item_id))
    if definition is None or definition.category != items.WEAPON:
        return 0.0
    try:
        return float(definition.get("damage", 0) or 0) * float(definition.get("speed", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 0.0


def register() -> None:
    """Install MiniWind's weapon styles, weapon ratings and can-cast check on
    the combat loadout."""
    from .npc_magic import can_attack_with_magic
    combat_loadout.set_item_style_resolver(weapon_attack_style)
    combat_loadout.set_item_rating_resolver(weapon_rating)
    combat_loadout.set_magic_resolver(can_attack_with_magic)
