"""
Spellcasting for NPCs and creatures: the spells they know, cast as the player
casts them.

An actor's ``spells`` (assigned in the editor's NPC spell picker: entries of
``{"id", "damage", "speed", "color"}``, or bare spell ids) and a staff in its
kit are what it can cast. When the combat AI says a shot is due
(:meth:`game.npc_archery.NpcArchery.shot_hook`):

* a caster hurt below :data:`HEAL_BELOW` of its health first heals itself, if
  it knows a healing spell and has the magicka;
* otherwise, when its loadout picks magic for this range
  (:mod:`game.combat_loadout`), it looses its strongest affordable attack
  spell as a real bolt -- the player's projectile pipeline, lit in the spell's
  colour -- at whoever it is fighting.

Spells cost magicka. An actor's pool is its authored ``max_magicka`` (else
:data:`MAGICKA_BASE` plus :data:`MAGICKA_PER_LEVEL` a level) and refills at
:data:`MAGICKA_REGEN` a second. It is settled only when asked about, so idle
casters cost nothing per tick. A caster that cannot afford a spell no longer
counts magic as a way to fight (:func:`can_attack_with_magic`, the combat
loadout's magic check), so it draws its blade or bow until the magicka is back.
"""

from __future__ import annotations

import math
import weakref
from types import SimpleNamespace

from . import fio

#: Below this fraction of its health, a caster that can heals before fighting on.
HEAL_BELOW = 0.4
#: An actor's magicka when the map authors none: a base and a share per level.
MAGICKA_BASE = 40.0
MAGICKA_PER_LEVEL = 12.0
#: Magicka refilled per second of play.
MAGICKA_REGEN = 3.0
#: A staff channels its bound spell at this share of the spell's cost.
STAFF_COST_SCALE = 0.5
#: Bolts leave the caster this far above its origin.
CAST_LIFT = 48.0
#: Fio's hit sphere is lifted this far above an actor's origin.
EYE_LIFT = 64.0
#: Bolts fizzle beyond this range.
SPELL_MAX_RANGE = 2048.0

#: The session clock magicka refills against (seconds of unpaused play).
#: :class:`NpcMagic` points it at its session; 0 with none.
clock = lambda: 0.0      # noqa: E731


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _known(props):
    """``(spell, entry)`` for every spell *props*' actor knows."""
    from .rpg import magic
    spells = props.get("spells")
    if not isinstance(spells, list):
        return
    for entry in spells:
        if isinstance(entry, str):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            continue
        spell = magic.get(entry.get("id", ""))
        if spell is not None:
            yield spell, entry


def _heals(spell) -> float:
    """How much health *spell* restores to its caster (0 when it doesn't)."""
    from .rpg import magic
    if spell.delivery != magic.SELF:
        return 0.0
    total = 0.0
    for effect in spell.effects or ():
        if effect.get("kind") == "restore_health":
            total += _float(effect.get("magnitude")) * max(1.0, _float(effect.get("duration")))
    return total


def _staff_spell(props):
    """The spell a staff in *props*' kit channels, or None."""
    from .rpg import items, magic
    weapons = [props.get("_active_weapon"), props.get("equipped_weapon")]
    for stack in props.get("inventory") or ():
        weapons.append(stack.get("id") if isinstance(stack, dict) else stack)
    for item_id in weapons:
        definition = items.get(str(item_id or ""))
        if definition is not None and definition.get("kind") == items.KIND_STAFF:
            spell = magic.get(definition.get("staff_spell", "flare"))
            if spell is not None:
                return spell
    return None


def attacks(props):
    """Every attack ``(spell, damage, speed, colour, cost)`` *props* can cast,
    strongest first. Per-actor overrides on the spell entry win."""
    from .rpg import magic
    found = []
    for spell, entry in _known(props):
        damage = _float(entry.get("damage", spell.damage))
        if spell.delivery != magic.PROJECTILE or damage <= 0:
            continue
        found.append((spell, damage, _float(entry.get("speed", spell.projectile_speed), 900.0),
                      list(entry.get("color") or spell.color), spell.base_cost))
    staff = _staff_spell(props)
    if staff is not None and staff.damage > 0 and not any(f[0] is staff for f in found):
        found.append((staff, staff.damage, staff.projectile_speed, list(staff.color),
                      staff.base_cost * STAFF_COST_SCALE))
    found.sort(key=lambda f: f[1], reverse=True)
    return found


def max_magicka(props) -> float:
    authored = props.get("max_magicka")
    if authored is not None:
        return max(0.0, _float(authored))
    level = max(1, int(_float(props.get("creature_level", 1), 1)))
    return MAGICKA_BASE + MAGICKA_PER_LEVEL * level


def magicka(props, now=None) -> float:
    """*props*' actor's magicka now, refilled for the time since it was last
    settled (and stored, so the next question starts from here)."""
    now = clock() if now is None else now
    top = max_magicka(props)
    if "_magicka" not in props:
        current = top if props.get("magicka") is None else _float(props.get("magicka"), top)
    else:
        elapsed = max(0.0, now - _float(props.get("_magicka_at"), now))
        current = _float(props.get("_magicka")) + elapsed * MAGICKA_REGEN
    current = min(top, max(0.0, current))
    props["_magicka"] = current
    props["_magicka_at"] = now
    return current


def spend(props, cost, now=None) -> bool:
    """Take *cost* magicka from *props*' actor; False (and nothing taken) when
    it hasn't that much."""
    current = magicka(props, now)
    if current + 1e-6 < cost:
        return False
    props["_magicka"] = current - cost
    return True


def can_attack_with_magic(props) -> bool:
    """Whether *props*' actor can cast an attack spell right now: the combat
    loadout's magic check (see the module doc)."""
    found = attacks(props)
    return bool(found) and magicka(props) + 1e-6 >= min(f[4] for f in found)


class NpcMagic:
    """Casting for one session's actors (see the module doc)."""

    def __init__(self, session):
        global clock
        self.session = session
        # Weakly: the clock must not keep a finished session alive.
        ref = weakref.ref(session)
        clock = lambda: float(getattr(ref(), "_archery_clock", 0.0))   # noqa: E731

    def try_heal(self, thing) -> bool:
        """Heal *thing* if it is badly hurt and can; True when it cast."""
        p = thing.properties
        health = _float(p.get("health"))
        top = _float(p.get("max_health") or p.get("_max_health"), health)
        if top <= 0 or health <= 0 or health >= top * HEAL_BELOW:
            return False
        heals = sorted(((_heals(spell), spell) for spell, _entry in _known(p)),
                       key=lambda h: h[0], reverse=True)
        current = magicka(p)
        for amount, spell in heals:
            if amount > 0 and current + 1e-6 >= spell.base_cost and spend(p, spell.base_cost):
                p["health"] = min(top, health + amount)
                p["_attack_anim"] = 0.2
                self._journal(thing)
                return True
        return False

    def cast_attack(self, thing, target) -> bool:
        """Loose *thing*'s strongest affordable attack spell at *target* (an
        actor, or ``"player"``); True when a bolt flew."""
        p = thing.properties
        target_pos = self.session.archery._target_pos(target)
        if target_pos is None:
            return False
        current = magicka(p)
        for spell, damage, speed, colour, cost in attacks(p):
            if current + 1e-6 >= cost and spend(p, cost):
                self._loose(thing, target, target_pos, spell, damage, speed, colour)
                return True
        return False

    # -- internals ------------------------------------------------------------
    def _loose(self, thing, target, target_pos, spell, damage, speed, colour) -> None:
        session = self.session
        logic = session.logic
        p = thing.properties
        p["_attack_anim"] = 0.2
        start = [float(thing.pos[0]), float(thing.pos[1]) + CAST_LIFT, float(thing.pos[2])]
        lift = EYE_LIFT
        if target == "player":
            player = fio.player(logic)
            lift = float(getattr(player, "camera_height", 48.0) or 48.0) * 0.6
        aim = [target_pos[0], target_pos[1] + lift, target_pos[2]]
        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        if dx or dz:
            p["_facing"] = math.atan2(dx, dz)
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        speed = max(1.0, speed)
        vel = [dx / dist * speed, dy / dist * speed, dz / dist * speed]
        ai = getattr(logic, "monster_ai", None)

        def _on_hit(victim, caster=thing, dmg=damage):
            if ai is not None:
                ai._apply_monster_damage(victim, dmg, attacker=caster)

        row = fio.spawn_projectile(logic, start, vel, lifetime=SPELL_MAX_RANGE / speed,
                                   damage=damage, owner_id=id(thing),
                                   max_dist=SPELL_MAX_RANGE, on_hit=_on_hit)
        attach = getattr(session, "_attach_bolt_light", None)
        if row is not None and attach is not None:
            attach(row, start, SimpleNamespace(color=colour))

    def _journal(self, thing) -> None:
        try:
            from engine.change_journal import touch
            touch(thing)
        except Exception:
            pass
