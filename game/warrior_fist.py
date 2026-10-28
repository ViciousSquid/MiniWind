"""
The warrior's fist: an innate weapon and a charged blow.

A Warrior works no magic; instead their fists are a weapon of their own.
The **Fist** (item ``fist``) is innate: every Warrior carries it, it sits in
quick slot 1, and it can be neither sold nor dropped.

With the Fist in hand the left mouse is a charge, like a bow's draw: hold it
and the pie fills beside the head (:data:`FULL_CHARGE_SECONDS`), let go and
the blow lands -- on everything in an arc in front, harder and wider the
longer it was gathered (up to :data:`MAX_POWER` times a plain punch), knocking
foes back, with an EXPLOSION effect where it strikes. A quick click is an
ordinary punch.
"""

from __future__ import annotations

import math
import time

FIST = "fist"
#: Seconds to gather a full blow.
FULL_CHARGE_SECONDS = 1.3
#: Damage multiplier at full charge (1 at none).
MAX_POWER = 5.0
#: Reach (units) of a plain punch, and how much a full charge adds.
REACH = 120.0
REACH_BONUS = 110.0
#: The arc in front that is struck: cosine of its half-angle, from a plain
#: punch (narrow) to a full blow (wide).
ARC_DOT = (0.55, 0.05)
#: Stamina a blow costs: a plain punch, plus this much more at full charge.
STAMINA = (4.0, 22.0)
#: How far a full blow throws a foe back.
KNOCKBACK = 170.0
#: Seconds the burst lingers before it is cleared away.
EFFECT_SECONDS = 1.4


def is_warrior(character) -> bool:
    """Whose fists are a weapon: anyone whose class works no magic."""
    can = getattr(character, "can_use_magic", None)
    return can is not None and not can()


def ensure_fist(session) -> bool:
    """Give a Warrior their fist, in quick slot 1. True if anything changed."""
    from .rpg import inventory as inv, items as rpg_items
    c = session.game.character
    if not is_warrior(c):
        return False
    changed = False
    if not inv.has_item(c.inventory, FIST, 1):
        stack = rpg_items.make(FIST, 1)
        if stack:
            inv.add_item(c.inventory, stack)
            changed = True
    try:
        slots = session.quick_weapon_slots()
        if not slots or not slots[0] or slots[0].get("id") != FIST:
            displaced = slots[0].get("id") if slots and slots[0] else None
            session.set_quick_weapon(0, FIST)
            if displaced and displaced != FIST:
                # Whatever was in slot 1 moves along to the next free one.
                quick = session.game.character.quick_weapons
                if displaced not in quick and None in quick:
                    session.set_quick_weapon(quick.index(None), displaced)
            changed = True
    except Exception:
        pass
    return changed


def innate(item_id) -> bool:
    """Whether *item_id* is part of its owner (never sold or dropped)."""
    from .rpg import items as rpg_items
    d = rpg_items.get(item_id)
    return bool(d is not None and d.get("innate"))


def strike(session, charge: float) -> bool:
    """Land a blow gathered to *charge* (0..1). True if it was thrown."""
    s = session
    c = s.game.character
    if c.is_dead or s._attack_cooldown > 0:
        return False
    charge = max(0.0, min(1.0, float(charge)))
    cost = STAMINA[0] + STAMINA[1] * charge
    if c.stamina < STAMINA[0]:
        s.notify("Too exhausted to strike")
        return False
    ppos = s._player_pos()
    if ppos is None:
        return False
    fwd = s._player_forward()
    reach = REACH + REACH_BONUS * charge
    arc = ARC_DOT[0] + (ARC_DOT[1] - ARC_DOT[0]) * charge
    power = 1.0 + (MAX_POWER - 1.0) * charge * charge
    struck = []
    from . import fio
    for t in fio.things(s.logic):
        if not s._attackable(t):
            continue
        dx, dz = t.pos[0] - ppos[0], t.pos[2] - ppos[2]
        dist = math.hypot(dx, dz)
        if dist < 1e-3 or dist > reach:
            continue
        if (fwd[0] * dx + fwd[2] * dz) / dist < arc:
            continue
        struck.append((t, dx / dist, dz / dist))
    s._attack_cooldown = 0.45 + 0.45 * charge
    s._attack_anim_time = 0.2 + 0.2 * charge
    for t, nx, nz in struck:
        res = s.game.attack_creature(t.properties, guaranteed=True, power=power)
        s._land_player_hit(t, res, heavy=charge >= 0.6)
        if res.get("hit") and charge > 0.2 and not t.properties.get("dead"):
            push = KNOCKBACK * charge
            s._step_to(t, t.pos[0] + nx * push, t.pos[2] + nz * push)
    # The blow costs what it costs whether or not it found anyone.
    c.spend_stamina(max(0.0, cost - (6.0 * len(struck))))
    if charge >= 0.35:
        # A physical blow must not create the gold magical explosion/ring.
        if struck:
            s.add_floater("SMASH!" if charge < 0.95 else "CRUSHING BLOW!", kind="crit")
    return True


def burst(session, at, charge) -> None:
    """The blow's effect: a one-off EXPLOSION Effect where it lands, sized by
    the charge, with its sound. Cleared away after :data:`EFFECT_SECONDS`."""
    from . import fio
    logic = session.logic
    try:
        from engine.effect_entity import Effect
    except Exception:
        return
    y = float(session._player_pos()[1]) + 10.0
    size = 70.0 + 130.0 * charge
    props = {"type": "effect", "name": "FistBlow", "effect_type": "EXPLOSION",
             "preview": False, "silent": True, "width": size, "height": size,
             "intensity": 1.0 + charge, "colour": [255, 200, 120], "lifetime": 0.6,
             "light_enabled": True, "light_radius": 160.0 + 240.0 * charge,
             "light_intensity": 2.0 + 2.0 * charge, "light_colour": [255, 190, 110]}
    try:
        effect = Effect(pos=[float(at[0]), y, float(at[1])], properties=props)
        fio.things(logic).append(effect)
        fio.rebuild_entity_caches(logic)
        store = logic.session_runtime.effect_store
        store.trigger_explosion(effect, time.perf_counter())
    except Exception as exc:
        print(f"[MiniWind] fist burst failed: {exc}")
        return
    session._transient_effects.append((time.monotonic() + EFFECT_SECONDS, effect))
    try:
        logic.game_state.queue_sound({"action": "play", "file": "assets/sounds/explode.mp3",
                                      "volume": 0.5 + 0.5 * charge,
                                      "position": [float(at[0]), y, float(at[1])]})
    except Exception:
        pass


def clear_spent(session) -> None:
    """Take away bursts whose moment has passed."""
    pending = session._transient_effects
    if not pending:
        return
    now = time.monotonic()
    spent = [e for t, e in pending if t <= now]
    if not spent:
        return
    session._transient_effects = [(t, e) for t, e in pending if t > now]
    from . import fio
    things = fio.things(session.logic)
    for e in spent:
        try:
            things.remove(e)
        except ValueError:
            pass
    fio.rebuild_entity_caches(session.logic)
