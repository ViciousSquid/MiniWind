"""Shield equipment and d20 block saves shared by characters and NPCs."""

from . import attributes, charisma, equipment, items, skills
from ..diceroll import DiceRoller, roll_check


def npc_shield(props):
    """An actual shield in a free off hand; bows, torches and spells occupy it."""
    shield = items.get(props.get("offhand_weapon") or props.get("equipped_shield"))
    if shield is None or shield.category != items.ARMOUR or shield.get("slot") != items.SLOT_SHIELD:
        return None
    main = items.get(props.get("_active_weapon") or props.get("equipped_weapon"))
    if (equipment.is_two_handed(main) or props.get("_torch_lit")
            or (props.get("hand_spells") or {}).get("off")):
        return None
    return shield


def ready_npc_shield(props):
    """Equip a carried shield in an empty off hand during loadout preparation."""
    if (props.get("offhand_weapon") or props.get("equipped_shield")
            or props.get("hand_spell_off") or (props.get("hand_spells") or {}).get("off")):
        return
    choices = []
    for stack in props.get("inventory") or ():
        if isinstance(stack, dict) and stack.get("qty", 1) <= 0:
            continue
        item = items.get(stack if isinstance(stack, str) else stack.get("id"))
        if item is not None and item.category == items.ARMOUR \
                and item.get("slot") == items.SLOT_SHIELD:
            choices.append(item)
    if choices:
        props["offhand_weapon"] = max(choices, key=lambda d: d.get("armor_rating", 0)).id


def block_save(damage, skill, endurance, fatigue=1.0, *, shield=None,
               dice=None, rng=None, defender="You", npc=False, against_player=False):
    """A successful saving throw reduces damage; a failed save reduces none."""
    damage = max(0.0, float(damage))
    fatigue = max(0.0, min(1.0, float(fatigue)))
    skill = max(0, min(100, float(skill)))
    chance = max(0.05, min(0.9, (0.2 + skill * 0.006 + endurance * 0.0015)
                          * (0.5 + fatigue * 0.5)))
    fraction = min(0.75, (0.2 if shield is not None else 0.05) + skill / 200.0)
    roll = roll_check(
        dice if dice is not None else DiceRoller(rng=rng), chance,
        f"{defender}: {'shield' if shield is not None else 'block'} saving throw",
        source="combat.block",
        why=f"Block {skill:g}, Endurance {endurance:g}, stamina {fatigue:.0%}; "
            f"a save blocks {fraction:.0%} of the blow",
        context={"quiet": npc, "npc": npc, "against_player": against_player,
                 "saving_throw": True},
    )
    blocked = damage * fraction if roll["success"] else 0.0
    return {"damage": max(0.0, damage - blocked), "blocked": round(blocked, 1),
            "block_roll": roll}


def npc_block(props, damage, *, damage_kind="physical", dice=None, rng=None,
              against_player=False):
    shield = npc_shield(props)
    if (damage <= 0 or damage_kind != "physical" or shield is None
            or not props.get("_shield_blocking") or props.get("dead")
            or props.get("multiplayer_player")):
        return {"damage": damage, "blocked": 0.0}
    level = max(1, int(props.get("creature_level", 1) or 1))
    skill = (props.get("skills") or {}).get(skills.BLOCK, props.get("block_skill", 15 + level * 3))
    top = max(1.0, float(props.get("max_stamina", 60 + level * 8)))
    fatigue = float(props.get("_stamina", top)) / top
    if fatigue <= 0:
        return {"damage": damage, "blocked": 0.0}
    return block_save(
        damage, skill, charisma.core(props, attributes.ENDURANCE), fatigue,
        shield=shield, dice=dice, rng=rng,
        defender=str(props.get("display_name") or props.get("name") or "NPC"),
        npc=True, against_player=against_player,
    )


def deflection_target(luck):
    """A rare 2d20 save: 0.25% at Luck 60, rising to 5.25% at Luck 100."""
    luck = max(0, min(100, int(luck)))
    return None if luck < 60 else 40 - (luck - 60) // 8


def deflection_chance(luck):
    target = deflection_target(luck)
    return 0.0 if target is None else (41 - target) * (42 - target) / 800.0


def deflection_save(luck, dice, defender, *, npc=False, against_player=False):
    target = deflection_target(luck)
    if target is None:
        return None
    return dice.request_roll(
        "2d20", target=target, source="combat.deflect",
        context={"label": f"{defender}: lucky shield deflection",
                 "why": f"Luck {int(luck)}; a rare save ricochets the missile off the shield",
                 "quiet": npc, "npc": npc, "against_player": against_player,
                 "saving_throw": True},
    )
