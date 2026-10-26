"""
What every person nearby is holding, which way they face, and a second
weapon for the fighters who should have one.

* :func:`arm_fighters` gives fighters a weapon for the other range, once per
  actor: guards, bandits, mercenaries, adventurers and hunters with a blade
  often carry a bow too, and archers and casters carry a dagger or short
  sword for when the enemy is on top of them. Combat then switches between
  them on its own (:mod:`game.combat_loadout`, through the archery shot
  hook).
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
#: How often a fighter given a ranged weapon gets a crossbow instead of a bow.
CROSSBOW_CHANCE = 0.3
SIDEARMS = ("iron_dagger", "iron_shortsword")
#: A caster's blade for when the enemy is on top of it, and the creatures (by
#: role) that are people enough to carry one; any NPC caster does.
CASTER_SIDEARM = "iron_dagger"
CASTER_ROLES = ("cultist", "mage", "necromancer", "witch", "sorcer", "wizard",
                "warlock", "priest", "shaman", "acolyte")
#: Fighters with a one-handed blade in hand who carry a second for the other
#: hand, by faction and by role (the larger chance wins), and how often that
#: second weapon is a twin of the first.
DUAL_WIELD_FACTIONS = {"bandits": 0.45, "mercenaries": 0.45, "adventurers": 0.4,
                       "guards": 0.25}
DUAL_WIELD_ROLES = {"bandit": 0.45, "mercenary": 0.45, "adventurer": 0.4,
                    "duelist": 0.9, "guard": 0.25, "warrior": 0.4,
                    "thief": 0.5, "pirate": 0.5, "assassin": 0.6}
#: Any other armed fighter with a one-handed blade, of no faction or role
#: above, still sometimes carries a second.
DUAL_WIELD_ANY = 0.15
TWIN_CHANCE = 0.5
#: Two weapons cost accuracy (game.rpg.combat.DUAL_WIELD_ACCURACY), so not
#: everyone pairs them: a crossbowman takes a second crossbow at this share of
#: the chance above, and a marksman, who trusts one well-aimed shot, never.
CROSSBOW_PAIR_SHARE = 0.5
MARKSMAN_ROLES = ("hunter", "ranger", "marksman", "sniper")

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
        if not isinstance(p, dict):
            continue
        ttype = str(p.get("type", "")).replace("_", "").lower()
        if ttype not in ("npc", "creature", "monster") or p.get("dead"):
            continue
        role = str(p.get("npc_role", "") or "").lower()
        if _arm_caster(p, ttype, role, make_stack):
            armed += 1
        # Some casters know a ward to raise before a fight (game/npc_magic.py).
        from .npc_magic import roll_ward
        roll_ward(p, rng)
        if p.get("_second_weapon_rolled"):
            continue
        p["_second_weapon_rolled"] = True
        if not p.get("combatant"):
            continue
        team = str(p.get("faction") or p.get("team") or "").lower()
        equipped = p.get("equipped_weapon") or ""
        if _arm_off_hand(p, role, team, equipped, rng, make_stack):
            armed += 1
        chance = max(SECOND_WEAPON_FACTIONS.get(team, 0.0),
                     max((c for r, c in SECOND_WEAPON_ROLES.items() if r in role), default=0.0))
        if chance <= 0.0 or rng.random() >= chance:
            continue
        styles = {_style(equipped)} | {_style(i) for i in _carried(p)}
        if "melee" in styles and "bow" not in styles:
            extra = ("crossbow" if rng.random() < CROSSBOW_CHANCE
                     else BOWS[int(rng.random() * len(BOWS))])
        elif "bow" in styles and "melee" not in styles:
            extra = SIDEARMS[int(rng.random() * len(SIDEARMS))]
        else:
            continue
        stack = make_stack(extra)
        if stack:
            p.setdefault("inventory", []).append(stack)
            armed += 1
    return armed


def _arm_caster(p, ttype, role, make_stack) -> bool:
    """Give a fighting caster with no blade a dagger, once: it casts while the
    enemy is at range and stabs when it closes (game/combat_loadout.py)."""
    if p.get("_caster_sidearm_rolled"):
        return False
    p["_caster_sidearm_rolled"] = True
    if not p.get("combatant") or (ttype != "npc" and not any(r in role for r in CASTER_ROLES)):
        return False
    from .npc_magic import attacks
    if not attacks(p):
        return False
    if "melee" in {_style(p.get("equipped_weapon"))} | {_style(i) for i in _carried(p)}:
        return False
    stack = make_stack(CASTER_SIDEARM)
    if not stack:
        return False
    p.setdefault("inventory", []).append(stack)
    return True


def _arm_off_hand(p, role, team, equipped, rng, make_stack) -> bool:
    """Perhaps give a fighter with a one-handed weapon a second for the other
    hand (``offhand_weapon``): a twin of a blade, or a sidearm; a crossbowman
    a second crossbow. Bows take both hands and never pair."""
    if p.get("offhand_weapon") or not equipped:
        return False
    from .rpg import equipment, items
    main = items.get(equipped)
    if main is None or not equipment.can_dual_wield(main) \
            or main.get("kind") not in (items.KIND_MELEE, items.KIND_CROSSBOW):
        return False
    chance = max(DUAL_WIELD_FACTIONS.get(team, 0.0),
                 max((c for r, c in DUAL_WIELD_ROLES.items() if r in role), default=0.0),
                 DUAL_WIELD_ANY)
    if main.get("kind") == items.KIND_CROSSBOW:
        if any(r in role for r in MARKSMAN_ROLES):
            return False
        chance *= CROSSBOW_PAIR_SHARE
    if chance <= 0.0 or rng.random() >= chance:
        return False
    twin = main.get("kind") == items.KIND_CROSSBOW or rng.random() < TWIN_CHANCE
    off = equipped if twin else SIDEARMS[int(rng.random() * len(SIDEARMS))]
    stack = make_stack(off)
    if not stack:
        return False
    p.setdefault("inventory", []).append(stack)
    p["offhand_weapon"] = off
    return True


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
        #: id(actor) -> the heading last told to the renderer, so a head
        #: sprite turns with its actor (engine.change_journal.FACING).
        self._published = {}
        #: id(actor) -> its weapons' springs (game/weapon_sway.py): an NPC's
        #: blades trail and overshoot a turn just as the player's do.
        self._sway = {}
        self._clock = None

    def update(self) -> None:
        """Facing for every actor near the player, eased into each turn and
        handed on to the renderer, which turns the actor's head with it."""
        import time
        from engine.change_journal import FACING, touch
        from .facing import face_heading
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        now = time.perf_counter()
        delta = None if self._clock is None else max(0.0, min(0.1, now - self._clock))
        self._clock = now
        published = {}
        r2 = DRAW_RADIUS * DRAW_RADIUS
        actors = s._actors
        cached = getattr(s, "_actors_by_id", None)
        by_id = (cached[1] if cached is not None and cached[0] is actors
                 else {id(t): t for t in actors})
        last = {}
        for t in actors:
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
                    fx = fz = 0.0
            if fx or fz:
                face_heading(p, fx, fz, delta)
            # Whoever turned it (this, the schedule mover, a bow's aim), the
            # head sprite turns too.
            facing = p.get("_facing")
            if facing is not None:
                published[key] = facing
                if self._published.get(key) != facing:
                    touch(t, FACING)
        self._last = last
        self._published = published
        # overhead() (UI thread) adds springs; drop those of actors gone out
        # of range, from a copy of the keys.
        for key in [k for k in list(self._sway) if k not in last]:
            self._sway.pop(key, None)

    def overhead(self):
        """``[(pos, facing, weapon_id, handed, attacking, size)]`` for the
        actors near the player who hold something."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return []
        r2 = DRAW_RADIUS * DRAW_RADIUS
        out = []
        import time
        from .weapon_sway import WeaponSway
        now = time.perf_counter()
        for t in s._actors:
            p = t.properties
            if p.get("dead") or p.get("hidden") or p.get("_bw_parked_hidden") \
                    or p.get("away_on_journey"):
                continue
            if p.get("_reaper") and float(p.get("_opacity", 1.0) or 0.0) < 0.3:
                continue          # Death's scythe comes and goes with him
            x, y, z = float(t.pos[0]), float(t.pos[1]), float(t.pos[2])
            if (x - ppos[0]) ** 2 + (z - ppos[2]) ** 2 > r2:
                continue
            size = float(p.get("sprite_width", 128) or 128)
            handed = str(p.get("handed", "right"))
            facing = float(p.get("_facing", 0.0))
            weapon = p.get("_active_weapon") or p.get("equipped_weapon") or ""
            attacking = bool(p.get("is_shooting") or p.get("_bow_charge") is not None)
            # Each hand trails a turn on its own spring, as the player's do.
            sway = self._sway.get(id(t))
            if sway is None:
                sway = self._sway[id(t)] = WeaponSway()
            main_facing = facing + sway.offset("main", facing, now)
            off_facing = facing + sway.offset("off", facing, now)
            if weapon:
                out.append(((x, y, z), main_facing, weapon, handed, attacking, size))
            # The other hand: a lit torch (the runtime marks who holds one:
            # game/runtime.py, _update_torch_lights), else a second weapon.
            # A two-handed weapon in hand (a bow) leaves neither.
            off_item = p.get("_torch_lit") or offhand_in_use(p)
            if off_item and not two_handed(weapon):
                other = "left" if handed == "right" else "right"
                striking = bool(p.get("_offhand_anim", 0.0)) and not p.get("_torch_lit")
                out.append(((x, y, z), off_facing, off_item, other, striking, size))
        return out


def two_handed(item_id) -> bool:
    """Whether the weapon *item_id* needs both hands (every bow)."""
    if not item_id:
        return False
    from .rpg import equipment, items
    return equipment.is_two_handed(items.get(item_id))


def offhand_in_use(props) -> str:
    """The second weapon an actor fights with in its off hand, or ''.

    Its authored ``offhand_weapon``, while the weapon in hand is a one-handed
    one and no torch has the hand."""
    off = str(props.get("offhand_weapon") or "")
    if not off or props.get("_torch_lit"):
        return ""
    weapon = props.get("_active_weapon") or props.get("equipped_weapon") or ""
    if two_handed(weapon):
        return ""
    return off
