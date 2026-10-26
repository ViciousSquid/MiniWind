"""
Archery for everyone: NPCs and creatures draw a bow by the player's own rules.

The player draws by holding the left mouse: the draw fills over
:data:`game.runtime.BOW_FULL_DRAW_SECONDS`, and a fuller draw flies further
(:data:`BOW_MIN_RANGE` → :data:`BOW_MAX_RANGE`) and hits harder (``0.5 + 0.5 *
draw`` of the shot's damage — :func:`game.rpg.combat.player_attack`). An actor
with a bow in hand now plays by exactly the same rules, instead of the engine's
instant hit-scan:

* When the combat AI says a shot is due (Fio's ``MonsterAI._shot_hook``), the
  archer *starts drawing* rather than hitting. It chooses how far to draw: at
  least enough for the arrow to reach its target, and sometimes — a power shot —
  much further, which is slower but harder-hitting. Skilled archers power-draw
  more often.
* While it draws, the same charge pie the player sees is drawn beside its head
  (``properties['_bow_charge']``, read by :func:`game.ui.hud.draw_npc_bow_charges`).
* At the planned draw it looses a real arrow through the same projectile
  pipeline the player's arrows use. It flies, can be dodged, stops in walls and
  hits whoever is in the way — friend or foe — and is drawn as an arrow.

Only archers the player could watch ever draw at all: a parked or hidden actor
(Big World's DORMANT, or a park by the game) cancels its draw on the next tick,
and Fio runs no combat AI for it in the first place.

Pure Python apart from the Fio calls made through :mod:`game.fio`.
"""

from __future__ import annotations

import math

from . import combat_loadout
from . import fio

#: The same numbers the player's bow uses (game.runtime re-exports these so
#: there is one definition): a full draw, and the range it buys.
BOW_FULL_DRAW_SECONDS = 2.5
BOW_MIN_RANGE = 450.0
BOW_MAX_RANGE = 3000.0
ARROW_SPEED = 1600.0
#: Inside this, an actor with a blade too fights with the blade.
MELEE_BAND = 230.0
#: After loosing, the next arrow takes this long to nock.
NOCK_SECONDS = 0.55
#: How often an ordinary archer chooses a power draw, and how much a point of
#: creature level adds to that.
POWER_DRAW_CHANCE = 0.3
POWER_DRAW_PER_LEVEL = 0.03
#: Fio's hit sphere is lifted this far above an actor's origin.
EYE_LIFT = 64.0


def range_for(charge: float) -> float:
    """How far an arrow drawn to *charge* (0..1) flies."""
    c = min(1.0, max(0.0, float(charge)))
    return BOW_MIN_RANGE + (BOW_MAX_RANGE - BOW_MIN_RANGE) * c


def charge_to_reach(distance: float) -> float:
    """The least draw (0..1) whose arrow still reaches *distance*."""
    span = BOW_MAX_RANGE - BOW_MIN_RANGE
    return min(1.0, max(0.0, (float(distance) - BOW_MIN_RANGE) / span))


def damage_for(base_damage: float, charge: float) -> float:
    """A shot's damage at draw *charge*: the player's rule, 0.5 .. 1.0 of base."""
    c = min(1.0, max(0.0, float(charge)))
    return max(1.0, float(base_damage) * (0.5 + 0.5 * c))


def plan_draw(distance: float, level: int, roll: float, extra: float) -> float:
    """How far an archer will draw for a target *distance* away.

    Enough to reach, plus a small margin; and with probability
    ``POWER_DRAW_CHANCE + level * POWER_DRAW_PER_LEVEL`` (*roll* is the uniform
    draw deciding it) a power shot: at least 70% of a full draw, *extra*
    (0..1) deciding how far beyond that.
    """
    need = min(1.0, charge_to_reach(distance) + 0.08)
    need = max(0.15, need)
    chance = POWER_DRAW_CHANCE + max(0, int(level)) * POWER_DRAW_PER_LEVEL
    if roll < chance:
        need = max(need, 0.7 + 0.3 * min(1.0, max(0.0, extra)))
    return min(1.0, need)


#: A crossbow shoots at once rather than drawing, then takes this long to
#: wind back; its bolt does this fraction of a full bow draw's damage.
CROSSBOW_RELOAD_SECONDS = 1.4
CROSSBOW_DAMAGE = 0.85


def is_crossbow(props) -> bool:
    """Whether the ranged weapon in *props*' hand is a crossbow."""
    from .rpg import items
    d = items.get(props.get("_active_weapon") or props.get("equipped_weapon") or "")
    return d is not None and d.get("kind") == items.KIND_CROSSBOW


def crossbow_in_kit(props):
    """The crossbow *props*' actor would fight with at range, or ''."""
    from .rpg import items
    try:
        weapon = combat_loadout.weapon_for(combat_loadout.build_loadout(props),
                                           combat_loadout.BOW)
    except Exception:
        return ""
    d = items.get(weapon) if weapon else None
    return weapon if d is not None and d.get("kind") == items.KIND_CROSSBOW else ""


def is_bow_shot(props, distance: float) -> bool:
    """Whether an actor fights this shot with a bow.

    Its loadout decides (a blade inside :data:`MELEE_BAND`, a bow beyond it,
    when it carries both); an actor with nothing to choose between keeps its
    authored ``attack_style``.
    """
    try:
        loadout = combat_loadout.build_loadout(props)
        style = combat_loadout.choose_style(loadout, distance <= MELEE_BAND)
    except Exception:
        style = ""
    if not style:
        style = str(props.get("attack_style", "") or "").lower()
    return style == combat_loadout.BOW


class NpcArchery:
    """Every actor currently drawing a bow, and what each will do with it."""

    def __init__(self, session):
        self.session = session
        #: id(actor) -> (actor, draw record). Small: only archers mid-draw.
        self.drawing = {}

    # -- the engine's shot hook ---------------------------------------------
    def shot_hook(self, thing, target_pos, aggro_monster, distance_sq) -> bool:
        """A shot fell due for *thing*: draw a bow for it, or leave it alone."""
        props = getattr(thing, "properties", None)
        if not isinstance(props, dict):
            return False
        distance = math.sqrt(max(0.0, float(distance_sq)))
        # The weapon for this range is the one in hand from now on: drawn
        # beside the head, and what the next shot is fought with.
        style = ""
        try:
            from .held_weapons import choose_in_hand
            style = choose_in_hand(props, distance, MELEE_BAND)
        except Exception:
            pass
        session = self.session
        # A crossbow needs no draw: a loaded one is shot from the hip, on the
        # move or point-blank, where a bow would need a stand and a blade a
        # step closer.
        now = getattr(session, "_archery_clock", 0.0)
        hip = ""
        if now >= float(props.get("_bow_ready_at", 0.0) or 0.0):
            hip = crossbow_in_kit(props)
        tactics = getattr(session, "tactics", None)
        backing = False
        if tactics is not None:
            tactics.note_shot(thing)
            backing = tactics.retreating(thing)
            if backing and not hip:
                return True               # backing away: no shot this time
        # A caster heals itself when badly hurt, and fights with its spells
        # wherever its loadout picks magic (game/npc_magic.py).
        magic = getattr(session, "npc_magic", None)
        if magic is not None and not backing:
            target = aggro_monster if aggro_monster is not None else "player"
            try:
                # Seen its foe: a caster with a ward raises it before engaging.
                if magic.try_ward(thing):
                    return True
                if magic.try_heal(thing):
                    return True
                if style == combat_loadout.MAGIC:
                    if magic.cast_attack(thing, target):
                        return True
                    if distance > MELEE_BAND:
                        return True       # no spell to cast: close in instead
            except Exception as exc:
                print(f"[MiniWind] NPC spell failed: {exc}")
        point_blank = bool(hip) and distance <= MELEE_BAND
        if point_blank:
            props["_active_weapon"] = hip
        if not point_blank and not is_bow_shot(props, distance):
            # A fighter without a ranged weapon has to close the distance;
            # extending pursuit must not turn a dagger into a hitscan rifle.
            loadout = combat_loadout.build_loadout(props)
            if (combat_loadout.choose_style(loadout, distance <= MELEE_BAND)
                    == combat_loadout.MELEE and distance > MELEE_BAND):
                return True
            # A melee blow: the engine lands the main hand's; a second
            # weapon strikes after it, on its own roll (game/dual_wield.py).
            try:
                from .dual_wield import offhand_strike
                offhand_strike(session, thing, aggro_monster, session.rng)
            except Exception as exc:
                print(f"[MiniWind] off-hand strike failed: {exc}")
            return False
        if id(thing) in self.drawing:
            return True               # already drawing: this shot is that one
        if now < float(props.get("_bow_ready_at", 0.0) or 0.0):
            return True               # still nocking the next arrow
        target = aggro_monster if aggro_monster is not None else "player"
        if is_crossbow(props):
            # A crossbow needs no draw: it shoots now, then winds back.
            target_pos = self._target_pos(target)
            if target_pos is not None:
                self._loose(thing, {"charge": 1.0, "plan": 1.0, "target": target,
                                    "crossbow": True}, target_pos)
            return True
        rng = session.rng
        try:
            level = int(props.get("creature_level", 1) or 1)
        except (TypeError, ValueError):
            level = 1
        plan = plan_draw(distance, level, rng.random(), rng.random())
        self.drawing[id(thing)] = (thing, {"charge": 0.0, "plan": plan,
                                           "target": target})
        props["_bow_charge"] = 0.0
        return True

    # -- per tick -------------------------------------------------------------
    def update(self, delta: float) -> None:
        """Advance every draw; loose the ones that have reached their plan."""
        session = self.session
        session._archery_clock = getattr(session, "_archery_clock", 0.0) + max(0.0, float(delta))
        if not self.drawing:
            return
        rate = max(0.0, float(delta)) / BOW_FULL_DRAW_SECONDS
        for key, (thing, draw) in list(self.drawing.items()):
            p = thing.properties
            if (p.get("dead") or p.get("hidden") or p.get("disabled")
                    or p.get("triggered", False)):
                self.cancel(thing)
                continue
            target_pos = self._target_pos(draw["target"])
            if target_pos is None:
                self.cancel(thing)
                continue
            draw["charge"] = min(1.0, draw["charge"] + rate)
            p["_bow_charge"] = draw["charge"]
            dx = target_pos[0] - thing.pos[0]
            dz = target_pos[2] - thing.pos[2]
            if dx or dz:
                p["_facing"] = math.atan2(dx, dz)
            if draw["charge"] >= draw["plan"]:
                self._loose(thing, draw, target_pos)

    def cancel(self, thing) -> None:
        """Lower *thing*'s bow without loosing."""
        self.drawing.pop(id(thing), None)
        thing.properties.pop("_bow_charge", None)

    def clear(self) -> None:
        for thing, _draw in list(self.drawing.values()):
            thing.properties.pop("_bow_charge", None)
        self.drawing.clear()

    def archers(self):
        """The actors mid-draw (for the HUD's pies)."""
        return [thing for thing, _d in list(self.drawing.values())]

    # -- internals ------------------------------------------------------------
    def _target_pos(self, target):
        if target == "player":
            return self.session._player_pos()
        tp = getattr(target, "properties", None)
        if not isinstance(tp, dict) or tp.get("dead") or tp.get("hidden"):
            return None
        return [float(target.pos[0]), float(target.pos[1]), float(target.pos[2])]

    def _loose(self, thing, draw, target_pos) -> None:
        session = self.session
        logic = session.logic
        p = thing.properties
        crossbow = bool(draw.get("crossbow"))
        self.drawing.pop(id(thing), None)
        p.pop("_bow_charge", None)
        p["_bow_ready_at"] = session._archery_clock + (
            CROSSBOW_RELOAD_SECONDS if crossbow else NOCK_SECONDS)
        p["_attack_anim"] = 0.2
        charge = draw["charge"]
        start = [float(thing.pos[0]), float(thing.pos[1]) + 48.0, float(thing.pos[2])]
        lift = EYE_LIFT
        if draw["target"] == "player":
            player = fio.player(logic)
            lift = float(getattr(player, "camera_height", 48.0) or 48.0) * 0.6
        aim = [target_pos[0], target_pos[1] + lift, target_pos[2]]
        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        vel = [dx / dist * ARROW_SPEED, dy / dist * ARROW_SPEED, dz / dist * ARROW_SPEED]
        try:
            base = float(p.get("damage", 12) or 12)
        except (TypeError, ValueError):
            base = 12.0
        damage = damage_for(base, charge)
        if crossbow:
            damage = max(1.0, damage * CROSSBOW_DAMAGE)   # a little under a bow
        max_dist = range_for(charge)
        ai = getattr(logic, "monster_ai", None)

        def _on_hit(victim, shooter=thing, dmg=damage):
            if ai is not None:
                ai._apply_monster_damage(victim, dmg, attacker=shooter)

        row = fio.spawn_projectile(logic, start, vel, lifetime=max_dist / ARROW_SPEED,
                                   damage=damage, owner_id=id(thing),
                                   max_dist=max_dist, on_hit=_on_hit)
        if row is None:
            return
        tag = fio.projectile_tag(logic, row)
        if tag:
            from .ui.arrows import arrow_sprite
            session._arrow_tags[tag] = arrow_sprite("iron_bolt" if crossbow else "iron_arrow")
            trace = getattr(session, "trace_arrow", None)
            if trace is not None:
                trace(tag, start)
