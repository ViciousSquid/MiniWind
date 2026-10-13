"""
What every person nearby is holding, which way they face, and a second
weapon for the fighters who should have one.

* :func:`arm_fighters` gives fighters a weapon for the other range, once per
  actor: guards, bandits, mercenaries, adventurers and hunters with a blade
  often carry a bow too, and archers carry a dagger or short sword for when
  the enemy is on top of them. Combat then switches between them on its own
  (:mod:`game.combat_loadout`, through the archery shot hook).
* :class:`HeldWeapons` keeps, per tick, each nearby actor's facing -- toward
  whatever it is fighting, else the way it is walking -- and answers the
  viewport's ``overhead_actor_weapons`` hook: the weapon in hand (the one
  last chosen in a fight, else the equipped one), beside the head on the
  wielding side, lunging or drawing while it attacks.
"""

from __future__ import annotations

import math

from . import combat_loadout

#: Fighters who may carry a second weapon, and the chance they do.
SECOND_WEAPON_FACTIONS = {"guards": 0.7, "bandits": 0.55, "mercenaries": 0.8,
                          "adventurers": 0.8}
SECOND_WEAPON_ROLES = {"guard": 0.7, "hunter": 0.9, "bandit": 0.55,
                       "mercenary": 0.8, "adventurer": 0.8, "ranger": 0.9}
BOWS = ("hunting_bow", "short_bow", "long_bow")
SIDEARMS = ("iron_dagger", "iron_shortsword")

#: Held weapons are drawn for actors within this distance of the player.
DRAW_RADIUS = 2600.0
#: How far an actor must move in a tick to turn to face its walk.
TURN_MIN_STEP = 0.5


def _style(item_id) -> str:
    return combat_loadout._item_style(item_id) or ""


def _carried(props):
    out = []
    for stack in props.get("inventory") or ():
        iid = combat_loadout._stack_id(stack)
        if iid:
            out.append(iid)
    return out


def arm_fighters(things, rng, make_stack) -> int:
    """Give fighters a weapon for the other range (see the module doc).
    *make_stack(item_id)* builds an inventory entry. Returns how many."""
    armed = 0
    for t in things:
        p = getattr(t, "properties", None)
        if not isinstance(p, dict) or p.get("_second_weapon_rolled"):
            continue
        ttype = str(p.get("type", "")).replace("_", "").lower()
        if ttype not in ("npc", "creature", "monster") or p.get("dead"):
            continue
        p["_second_weapon_rolled"] = True
        if not p.get("combatant"):
            continue
        role = str(p.get("npc_role", "") or "").lower()
        team = str(p.get("faction") or p.get("team") or "").lower()
        chance = max(SECOND_WEAPON_FACTIONS.get(team, 0.0),
                     max((c for r, c in SECOND_WEAPON_ROLES.items() if r in role), default=0.0))
        if chance <= 0.0 or rng.random() >= chance:
            continue
        equipped = p.get("equipped_weapon") or ""
        styles = {_style(equipped)} | {_style(i) for i in _carried(p)}
        if "melee" in styles and "bow" not in styles:
            extra = BOWS[int(rng.random() * len(BOWS))]
        elif "bow" in styles and "melee" not in styles:
            extra = SIDEARMS[int(rng.random() * len(SIDEARMS))]
        else:
            continue
        stack = make_stack(extra)
        if stack:
            p.setdefault("inventory", []).append(stack)
            armed += 1
    return armed


def choose_in_hand(props, distance: float, melee_band: float) -> str:
    """The weapon *props*' actor fights with at *distance*; records it as the
    one in hand (``_active_weapon``)."""
    loadout = combat_loadout.build_loadout(props)
    style = combat_loadout.choose_style(loadout, distance <= melee_band)
    weapon = combat_loadout.weapon_for(loadout, style)
    if weapon:
        props["_active_weapon"] = weapon
    return style


class HeldWeapons:
    def __init__(self, session):
        self.session = session
        self._last = {}               # id(actor) -> (x, z)

    def update(self) -> None:
        """Facing for every actor near the player."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        r2 = DRAW_RADIUS * DRAW_RADIUS
        by_id = {id(t): t for t in s._actors}
        last = {}
        for t in s._actors:
            x, z = float(t.pos[0]), float(t.pos[2])
            dx, dz = x - ppos[0], z - ppos[2]
            if dx * dx + dz * dz > r2:
                continue
            p = t.properties
            key = id(t)
            last[key] = (x, z)
            target = None
            if not p.get("triggered", True):
                aggro = by_id.get(p.get("_aggro_target"))
                if aggro is not None:
                    target = (aggro.pos[0], aggro.pos[2])
                elif str(p.get("aggression")) == "hostile" and p.get("awake"):
                    target = (ppos[0], ppos[2])
            if target is not None:
                fx, fz = target[0] - x, target[1] - z
            else:
                px, pz = self._last.get(key, (x, z))
                fx, fz = x - px, z - pz
                if fx * fx + fz * fz < TURN_MIN_STEP * TURN_MIN_STEP:
                    continue
            if fx or fz:
                p["_facing"] = math.atan2(fx, fz)
        self._last = last

    def overhead(self):
        """``[(pos, facing, weapon_id, handed, attacking, size)]`` for the
        actors near the player who hold something."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return []
        r2 = DRAW_RADIUS * DRAW_RADIUS
        out = []
        for t in s._actors:
            p = t.properties
            if p.get("dead") or p.get("hidden") or p.get("_bw_parked_hidden") \
                    or p.get("away_on_journey"):
                continue
            x, y, z = float(t.pos[0]), float(t.pos[1]), float(t.pos[2])
            if (x - ppos[0]) ** 2 + (z - ppos[2]) ** 2 > r2:
                continue
            size = float(p.get("sprite_width", 128) or 128)
            handed = str(p.get("handed", "right"))
            facing = float(p.get("_facing", 0.0))
            weapon = p.get("_active_weapon") or p.get("equipped_weapon") or ""
            if weapon:
                attacking = bool(p.get("is_shooting") or p.get("_bow_charge") is not None)
                out.append(((x, y, z), facing, weapon, handed, attacking, size))
            # A lit torch (the runtime marks who holds one: game/runtime.py,
            # _update_torch_lights) is held in the other hand.
            torch = p.get("_torch_lit")
            if torch:
                off = "left" if handed == "right" else "right"
                out.append(((x, y, z), facing, torch, off, False, size))
        return out
