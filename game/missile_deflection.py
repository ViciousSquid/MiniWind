"""A fortunate shield bearer can ricochet a real missile before it impacts."""

import math

from . import fio
from .facing import heading
from .rpg import attributes, blocking, equipment


def deflect(session, projectiles, row, target):
    coop = getattr(session, "coop", None)
    context = (getattr(coop, "players", {}).get(target.properties.get("player_id"))
               if target is not None and target.properties.get("multiplayer_player") else None)
    character_session = context.session if context is not None else session if target is None else None
    if character_session is not None:
        c = character_session.game.character
        if (c.is_dead or not character_session._blocking or c.stamina <= 0
                or equipment.shield(c) is None or equipment.is_two_handed(equipment.weapon(c))):
            return False
        luck = c.attrs.get(attributes.LUCK, 40)
        facing = float(fio.player(character_session.logic).angle)
        actor = character_session.player_actor
        name = c.name or "You"
        dice = character_session.game.dice
    else:
        p = target.properties
        if (p.get("dead") or not p.get("_shield_blocking") or blocking.npc_shield(p) is None
                or float(p.get("_stamina", 1)) <= 0):
            return False
        luck = p.get("luck", 40)
        facing = heading(target)
        actor = target
        name = str(p.get("display_name") or p.get("name") or "NPC")
        dice = session.game.dice
    if blocking.deflection_target(luck) is None:
        return False

    nx, nz = math.sin(facing), math.cos(facing)
    vx, vy, vz = (float(v) for v in projectiles.vel[row])
    speed = math.hypot(vx, vz)
    dot = vx * nx + vz * nz
    if speed < 1 or dot >= -speed * 0.25:
        return False  # the back or side of a shield cannot catch the missile
    roll = blocking.deflection_save(
        luck, dice, name, npc=character_session is None,
        against_player=character_session is None and int(projectiles.owner_id[row]) == 0,
    )
    if not roll["success"]:
        return False

    # Keep the same projectile/tag, range and remaining lifetime. It really
    # changes course, and its new owner cannot immediately be struck again.
    projectiles.vel[row] = (vx - 2 * dot * nx, vy, vz - 2 * dot * nz)
    radius = 32 if target is None else 64
    centre = fio.player(character_session.logic).pos if target is None else target.pos
    outward = ((float(projectiles.pos[row, 0]) - centre[0]) * nx
               + (float(projectiles.pos[row, 2]) - centre[2]) * nz)
    advance = max(0.0, radius + 4 - outward)
    projectiles.pos[row, 0] += nx * advance
    projectiles.pos[row, 2] += nz * advance
    projectiles.owner_id[row] = 0 if character_session is not None and coop is None else id(actor)
    metadata = projectiles.metadata_of(row, create=True)
    kind = metadata.get("damage_kind", "physical")
    damage = float(projectiles.damage[row])
    spell = metadata.get("spell")
    _old_hit, old_impact = projectiles.hooks_of(row)

    def on_hit(victim):
        if coop is not None and victim.properties.get("multiplayer_player"):
            return coop.damage(victim.properties["player_id"], damage, kind, actor, "projectile")
        return session.logic.monster_ai._apply_monster_damage(
            victim, damage, attacker=actor, damage_kind=kind,
        )

    def on_impact(pos, victim):
        if spell is not None:
            session.burning.landed(spell, list(pos), victim, by=actor)
        elif old_impact is not None:
            old_impact(pos, victim)

    projectiles.hooks[int(projectiles.tag[row])] = (on_hit, on_impact)
    if character_session is not None:
        character_session.add_floater("Deflected", kind="miss")
    return True
