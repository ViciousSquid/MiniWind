"""
What each map remembers, and how its lairs fill up again.

A map is loaded from its file every time the player enters it, so without
this a cave was full again the moment you walked back in, and the overworld
forgot every kill as soon as you came out of a cave. Each map now keeps a
small record in the game's state store (which travels with the character
and the clock across level changes and saves):

* **Deaths** -- who died and when (game hours). On entering the map the dead
  stay dead: a fresh corpse lies where it fell, an older one has been
  cleared away.
* **Taken** -- pickups the player picked up (a gold pile does not come back).
* **Containers** -- contents, unlocked/jammed locks and latched pin progress.
* **Raised** -- who the player's necromancy brought back. A raised body has
  had its second life: it is never raised again, and it is no lair's stock
  (it does not come back on its own). While it lives it is the caster's
  follower, whenever the player is in its map.
* **Departed** -- raised followers who left the map with the player
  (game/party.py): they travel with the player now, and are never also
  standing here.
* **Kits** -- what a searched corpse still has on it, and what a raised
  follower carries and knows (:data:`KIT_FIELDS`), so neither is restocked
  from the map file.

**Repopulation.** Generic hostile creatures -- a wolf, a skeleton, a
bandit, anything whose kind appears more than once in the map, and every
creature of a spawner -- come back about a day after they died
(:data:`RESPAWN_HOURS` plus up to :data:`RESPAWN_JITTER`): clear a cave and
it may be full again tomorrow. One-of-a-kind creatures (the dragon, the
Barrow Wight) and townsfolk never come back. Nothing reappears in front of
the player: in the map they are standing in, a creature returns only while
the player is out of sight of its home (:data:`HIDDEN_DISTANCE`); otherwise
it returns the next time the map is entered.

Spawner members are remembered by spawner and slot (each slot's member also
keeps the same uuid every load, game/runtime.py ``spawn_creature_points``),
so a spawner whose wolves were killed today spawns fewer of them until their
day is up.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Dict, Optional

from . import fio

STORE_PREFIX = "mapmem."
RESPAWN_HOURS = 22.0
RESPAWN_JITTER = 10.0
#: A corpse lies this long before it has been cleared away.
CORPSE_HOURS = 6.0
#: A creature only returns while the player is at least this far from home.
HIDDEN_DISTANCE = 2600.0
#: How often (real seconds) the live map is checked for returns and deaths.
CHECK_SECONDS = 1.5
ACTOR_TYPES = ("npc", "creature", "monster")
#: What a body carries and knows, kept for a looted corpse and for a raised
#: follower so neither comes back from the map file whole: its pack (and
#: what it carried in life, game_state.stock_corpse), the weapons in its
#: hands, its spells and the spells it holds ready, and its one-time rolls.
KIT_FIELDS = ("inventory", "living_inventory", "loot_rolled", "equipped_weapon",
              "offhand_weapon", "spells", "hand_spells", "_ward_rolled",
              "_second_weapon_rolled", "_caster_sidearm_rolled")


def _kind(t) -> str:
    return str(t.properties.get("type", "")).replace("_", "").lower()


def _hours(clock) -> float:
    return float(clock.day) * 24.0 + float(clock.hour)


def _kit(props) -> Dict:
    return {k: copy.deepcopy(props[k]) for k in KIT_FIELDS if k in props}


def _restore_kit(props, kit) -> None:
    """Lay a remembered *kit* over freshly loaded *props* (a field it lacks,
    a looted weapon say, is gone)."""
    if not isinstance(kit, dict):
        return
    for k in KIT_FIELDS:
        if k in kit:
            props[k] = copy.deepcopy(kit[k])
        else:
            props.pop(k, None)


def _clean_props(props) -> Dict:
    """Authored properties, without the runtime's scratch (``_...``) state."""
    return {k: copy.deepcopy(v) for k, v in props.items() if not str(k).startswith("_")}


class MapMemory:
    def __init__(self, session):
        self.session = session
        self.key = ""
        self.record = {"dead": {}, "taken": [], "containers": {}, "locks": {},
                       "raised": {}, "departed": {}, "supply": {}}
        self._originals: Dict[str, Dict] = {}     # memory key -> (props, pos)
        self._known_dead = set()
        self._accum = 0.0
        self._dirty = False

    # -- identity --------------------------------------------------------------
    @staticmethod
    def actor_key(t) -> str:
        p = t.properties
        sp = p.get("_spawner")
        if sp:
            return f"{sp}#{int(p.get('_spawn_slot', 0))}"
        return str(p.get("id") or "")

    def _respawns(self, t, generic) -> bool:
        p = t.properties
        if p.get("_spawner"):
            return bool(p.get("_spawner_respawn", True))
        if p.get("respawn_lair") is False or _kind(t) != "creature":
            return False
        if str(p.get("aggression")) != "hostile":
            return False
        return generic.get(str(p.get("display_name") or p.get("npc_role") or ""), 0) > 1

    def _delay(self, key) -> float:
        """Pace new deaths only; saved deadlines remain stable across states."""
        jitter = (sum(map(ord, key)) % 97) / 96.0
        storyteller = getattr(self.session, "storyteller", None)
        scale = storyteller.board_levers().get("lair_refill_scale", 1.0) if storyteller is not None else 1.0
        return (RESPAWN_HOURS + RESPAWN_JITTER * jitter) * scale

    # -- entering a map --------------------------------------------------------
    def load(self, map_key: str) -> None:
        self.key = str(map_key or "")
        raw = self.session.store.get(STORE_PREFIX + self.key, "")
        if raw and raw != "false":
            try:
                rec = json.loads(raw)
                if isinstance(rec, dict):
                    self.record = {"dead": dict(rec.get("dead") or {}),
                                   "taken": list(rec.get("taken") or []),
                                   "containers": dict(rec.get("containers") or {}),
                                   "locks": dict(rec.get("locks") or {}),
                                   "raised": dict(rec.get("raised") or {}),
                                   "departed": dict(rec.get("departed") or {}),
                                   "supply": dict(rec.get("supply") or {})}
            except ValueError:
                pass

    def spawner_slot_gone(self, spawner_id, slot) -> bool:
        """Whether a spawner's member in *slot* is still dead (its day not up)."""
        rec = self.record["dead"].get(f"{spawner_id}#{int(slot)}")
        if not rec:
            return False
        now = _hours(self.session.clock)
        return not rec.get("r") or now - float(rec["t"]) < float(rec.get("d", RESPAWN_HOURS))

    def apply(self) -> None:
        """Lay what this map remembers over the freshly loaded scene."""
        things = list(fio.things(self.session.logic))
        now = _hours(self.session.clock)
        generic: Dict[str, int] = {}
        for t in things:
            if _kind(t) == "creature":
                name = str(t.properties.get("display_name") or t.properties.get("npc_role") or "")
                generic[name] = generic.get(name, 0) + 1
        self._generic = generic
        dead = self.record["dead"]
        taken = set(self.record["taken"])
        conts = self.record["containers"]
        changed = False
        departed = self.record["departed"]
        if departed:
            # (Not the follower itself, back home with the player.)
            gone = [t for t in things
                    if _kind(t) in ACTOR_TYPES and self.actor_key(t) in departed
                    and not t.properties.get("travelling")]
            if gone:
                live = fio.things(self.session.logic)
                for t in gone:
                    live.remove(t)
                    things.remove(t)
                changed = True
        for t in things:
            kind = _kind(t)
            p = t.properties
            supply = self.record["supply"].get(self.actor_key(t))
            if isinstance(supply, dict):
                from .flour_supply import MEMORY_FIELDS
                for field in MEMORY_FIELDS:
                    if field in supply.get("props", {}):
                        p[field] = copy.deepcopy(supply["props"][field])
                    else:
                        p.pop(field, None)
                if supply.get("pos") is not None:
                    t.pos = list(supply["pos"])
                changed = True
            if kind in ACTOR_TYPES:
                key = self.actor_key(t)
                if not key:
                    continue
                p["_respawns"] = self._respawns(t, generic)
                self._originals[key] = (_clean_props(p), list(t.pos))
                rec = dead.get(key)
                if key in self.record["raised"]:
                    # Its second life is spent, whatever the map file says;
                    # alive, it is the caster's follower again, with what it
                    # carried and knew when the map was left.
                    _restore_kit(p, self.record["raised"][key])
                    p["_respawns"] = False
                    bind = getattr(self.session, "_bind_raised", None)
                    if bind is not None:
                        bind(p)
                    if rec is not None:
                        p["follow_player"] = False
                    changed = True
                if rec is None:
                    continue
                if rec.get("r") and now - float(rec["t"]) >= float(rec.get("d", RESPAWN_HOURS)):
                    dead.pop(key, None)          # its day is up: back, fresh
                    self._dirty = True
                    continue
                p["dead"] = True
                p["health"] = 0
                if "kit" in rec and key not in self.record["raised"]:
                    _restore_kit(p, rec["kit"])  # what is left on the body
                if rec.get("pos"):
                    t.pos = list(rec["pos"])
                if now - float(rec["t"]) >= CORPSE_HOURS:
                    p["hidden"] = True           # long since cleared away
                self._known_dead.add(key)
                changed = True
            elif kind == "itempickup" and str(p.get("id")) in taken:
                p["dead"] = True
                p["hidden"] = True
                changed = True
            elif kind == "container" or p.get("windmill"):
                cid = str(p.get("id"))
                if cid in conts:
                    p["inventory"] = copy.deepcopy(conts[cid])
                    changed = True
                lock = self.record["locks"].get(cid)
                if isinstance(lock, dict):
                    for field in ("locked", "lock_jammed", "lockpick_state"):
                        if field in lock:
                            p[field] = copy.deepcopy(lock[field])
                        else:
                            p.pop(field, None)
                    changed = True
        if changed:
            fio.rebuild_entity_caches(self.session.logic)
        # Anyone already dead in the file counts as known (not a new death).
        for t in things:
            if _kind(t) in ACTOR_TYPES and t.properties.get("dead"):
                self._known_dead.add(self.actor_key(t))

    # -- while in the map ------------------------------------------------------
    def update(self, delta: float) -> None:
        self._accum += delta
        if self._accum < CHECK_SECONDS or not self.key:
            return
        self._accum = 0.0
        s = self.session
        now = _hours(s.clock)
        things = fio.things(s.logic)
        dead = self.record["dead"]
        for t in list(things):
            kind = _kind(t)
            if kind not in ACTOR_TYPES:
                continue
            p = t.properties
            if not p.get("dead"):
                continue
            key = self.actor_key(t)
            if not key or key in self._known_dead:
                continue
            self._known_dead.add(key)
            respawns = bool(p.get("_respawns"))
            dead[key] = {"t": round(now, 2), "r": respawns,
                         "d": round(self._delay(key), 2),
                         "pos": [round(float(v), 1) for v in t.pos]}
            self._dirty = True
        self._return_due(now)
        if self._dirty:
            self.save()

    def _return_due(self, now) -> None:
        """Bring back whoever's day is up, out of the player's sight."""
        s = self.session
        ppos = s._player_pos()
        dead = self.record["dead"]
        due = [k for k, r in dead.items() if r.get("r")
               and now - float(r["t"]) >= float(r.get("d", RESPAWN_HOURS))]
        if not due:
            return
        by_key = {}
        for t in fio.things(s.logic):
            if _kind(t) in ACTOR_TYPES:
                by_key[self.actor_key(t)] = t
        revived = 0
        for key in due:
            orig = self._originals.get(key)
            t = by_key.get(key)
            if orig is None or t is None:
                continue
            props, pos = orig
            if ppos is not None and math.hypot(pos[0] - ppos[0], pos[2] - ppos[2]) < HIDDEN_DISTANCE:
                continue
            fresh = copy.deepcopy(props)
            fresh["dead"] = False
            fresh["hidden"] = False
            if fresh.get("max_health"):
                fresh["health"] = fresh["max_health"]
            t.properties.clear()
            t.properties.update(fresh)
            t.properties["_respawns"] = True
            if key.find("#") > 0:
                spawner, slot = key.split("#", 1)
                t.properties["_spawner"] = spawner
                t.properties["_spawn_slot"] = int(slot)
            t.pos = list(pos)
            try:
                from engine.change_journal import touch
                touch(t)
            except Exception:
                pass
            dead.pop(key, None)
            self._known_dead.discard(key)
            revived += 1
        if revived:
            self._dirty = True
            fio.rebuild_entity_caches(s.logic)

    def raised(self, actor) -> None:
        """The player raised *actor*: it is no longer among this map's dead,
        and its second life is spent (see the module docstring)."""
        key = self.actor_key(actor)
        if not key:
            return
        self.record["dead"].pop(key, None)
        self._known_dead.discard(key)
        self.record["raised"][key] = _kit(actor.properties)
        actor.properties["_respawns"] = False
        self._dirty = True

    def departed(self, actor) -> None:
        """*actor*, a raised follower, leaves the map with the player for good
        (game/party.py)."""
        key = self.actor_key(actor)
        if not key:
            return
        self.record["departed"][key] = True
        self.record["raised"].pop(key, None)
        self.record["dead"].pop(key, None)
        self._dirty = True

    def taken(self, pickup) -> None:
        """The player picked *pickup* up: it stays gone."""
        pid = str(pickup.properties.get("id") or "")
        if pid and pid not in self.record["taken"]:
            self.record["taken"].append(pid)
            self._dirty = True

    def save(self) -> None:
        if not self.key:
            return
        supply = getattr(self.session, "flour_supply", None)
        if supply is not None and supply.roads is not None:
            supply.roads.sync_live()
        for t in self.session._container_things():
            cid = str(t.properties.get("id") or "")
            if cid:
                self.record["containers"][cid] = t.properties.get("inventory") or []
                self.record["locks"][cid] = {
                    field: copy.deepcopy(t.properties[field])
                    for field in ("locked", "lock_jammed", "lockpick_state")
                    if field in t.properties}
        # A searched corpse keeps what is left on it; a raised follower what
        # it carries now.
        dead, raised = self.record["dead"], self.record["raised"]
        for t in fio.things(self.session.logic):
            p = t.properties
            if (not p.get("_journey") and (p.get("flour_dependent") or p.get("flour_target")
                    or p.get("flour_runner") or p.get("flour_job") or p.get("windmill"))):
                from .flour_supply import MEMORY_FIELDS
                self.record["supply"][self.actor_key(t)] = {
                    "props": {k: copy.deepcopy(p[k]) for k in MEMORY_FIELDS if k in p},
                    "pos": list(t.pos)}
            if _kind(t) not in ACTOR_TYPES:
                continue
            key = self.actor_key(t)
            if key in raised:
                raised[key] = _kit(t.properties)
            elif isinstance(dead.get(key), dict) and t.properties.get("loot_rolled"):
                dead[key]["kit"] = _kit(t.properties)
        self.session.store.set(STORE_PREFIX + self.key, json.dumps(self.record,
                                                                   separators=(",", ":")))
        self._dirty = False

    def summary(self, now: Optional[float] = None):
        now = _hours(self.session.clock) if now is None else now
        dead = self.record["dead"]
        back = [k for k, r in dead.items() if r.get("r")]
        nxt = min((float(r["t"]) + float(r.get("d", RESPAWN_HOURS)) - now
                   for r in dead.values() if r.get("r")), default=None)
        return {"map": self.key, "dead": len(dead), "will_return": len(back),
                "next_return_in_hours": None if nxt is None else round(max(0.0, nxt), 1),
                "taken": len(self.record["taken"])}
