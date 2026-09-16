"""
MiniWind's weapon knowledge, handed to the engine's combat loadout.

:mod:`engine.combat_loadout` decides *when* an actor switches between blade,
bow and spell; which carried items are weapons, and which style each drives,
comes from MiniWind's item database. :func:`register` installs that lookup on
the engine, and runs when the ``game`` package is imported.
"""

from __future__ import annotations

from engine import combat_loadout

#: Weapon ``kind`` in the item database -> the engine's attack style.
KIND_STYLES = {
    "melee": combat_loadout.MELEE,
    "bow": combat_loadout.BOW,
    "staff": combat_loadout.MAGIC,
}


def weapon_attack_style(item_id):
    """The attack style *item_id* drives, or None when it is not a weapon."""
    from .rpg import items
    definition = items.get(str(item_id))
    if definition is None or definition.category != items.WEAPON:
        return None
    return KIND_STYLES.get(str(definition.get("kind", "")).lower())


def register() -> None:
    """Install :func:`weapon_attack_style` as the engine's item-style resolver."""
    combat_loadout.set_item_style_resolver(weapon_attack_style)
