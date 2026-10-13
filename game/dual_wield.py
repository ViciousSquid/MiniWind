"""
Two weapons at once, for the NPCs who carry them.

The player's two hands are two buttons (game/runtime.py, ``do_attack``). An
NPC's off hand rides along with the combat AI instead: whenever its main hand
strikes in melee (Fio's ``MonsterAI`` shot, reaching MiniWind through the
shot hook in :mod:`game.npc_archery`), the second weapon strikes too -- as a
separate blow, with its own roll to hit and its own damage, so a poor
fighter's off hand often misses while the main hand lands.

Who has a second weapon is :func:`game.held_weapons.arm_fighters`'s choice,
recorded as ``properties['offhand_weapon']``; a torch or a two-handed weapon
in hand leaves no hand for it (:func:`game.held_weapons.offhand_in_use`).
"""

from __future__ import annotations

from . import fio

#: The off hand's chance to hit, before level, and what each level adds.
OFFHAND_HIT_BASE = 0.55
OFFHAND_HIT_PER_LEVEL = 0.04
OFFHAND_HIT_MAX = 0.9
#: How long the off hand's lunge shows over the head (seconds).
OFFHAND_ANIM = 0.2


def offhand_chance(props) -> float:
    try:
        level = int(props.get("creature_level", 1) or 1)
    except (TypeError, ValueError):
        level = 1
    return min(OFFHAND_HIT_MAX, OFFHAND_HIT_BASE + OFFHAND_HIT_PER_LEVEL * max(0, level - 1))


def offhand_damage(props, offhand_id) -> int:
    """The off-hand blow's damage: the actor's own ``damage`` (its main
    hand's), scaled by how the second weapon compares with the first."""
    from .rpg import items
    try:
        base = float(props.get("damage", 10) or 10)
    except (TypeError, ValueError):
        base = 10.0
    off = items.get(offhand_id)
    main = items.get(props.get("_active_weapon") or props.get("equipped_weapon") or "")
    try:
        if off is not None and main is not None and float(main.get("damage", 0)) > 0:
            base *= float(off.get("damage", 0)) / float(main.get("damage"))
        else:
            base *= 0.8
    except (TypeError, ValueError):
        base *= 0.8
    return max(1, int(round(base)))


def offhand_strike(session, thing, aggro_monster, rng) -> bool:
    """*thing*'s main hand has just struck in melee: strike with its second
    weapon too, if it holds one. Returns whether it hit."""
    from .held_weapons import offhand_in_use
    from .rpg import items
    props = thing.properties
    off = offhand_in_use(props)
    d = items.get(off) if off else None
    if d is None or d.get("kind", items.KIND_MELEE) != items.KIND_MELEE:
        return False
    props["_offhand_anim"] = OFFHAND_ANIM
    if rng.random() > offhand_chance(props):
        return False                          # the off hand's own roll: a miss
    damage = offhand_damage(props, off)
    logic = session.logic
    if aggro_monster is not None:
        ai = getattr(logic, "monster_ai", None)
        if ai is None or aggro_monster.properties.get("dead"):
            return False
        ai._apply_monster_damage(aggro_monster, damage, attacker=thing)
        return True
    triggers = getattr(logic, "trigger_runtime", None)
    if triggers is None or fio.player(logic) is None:
        return False
    triggers._apply_player_damage(damage)
    return True
