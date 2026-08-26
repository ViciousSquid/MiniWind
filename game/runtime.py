"""
Runtime session for the Miniwind RPG.

Qt-free and player-safe: this is the per-play-session brain that ties the pure
:mod:`rpg` game to the live Fio scene. It owns the player
:class:`~game.rpg.game_state.GameState`, the game clock, NPC schedule
& combat AI, and the *verbs* the input/HUD layer calls (attack, cast, interact,
use item). The Qt-side wiring (drawing, key input) lives in the native game host
``host.py``; the screens live in ``ui/``.

Player defence is routed through the RPG: a damage filter installed on the logic
thread turns raw incoming damage into a post-armour/-resistance amount, and the
player's health/magicka/stamina live on the character (mirrored into the engine's
``player_health`` so the engine's death check and any fallback HUD stay correct).
"""

from __future__ import annotations

import json
import math
import random
from typing import Dict, List, Optional

from .rpg import factions
from .rpg import schedule as sched
from .rpg import combat as rpg_combat
from .rpg import equipment as eq
from .rpg import items as rpg_items
from .rpg import magic as rpg_magic
from .rpg import guilds
from .rpg.gametime import GameClock
from .rpg.dialogue import DialogueRunner
from .rpg import inventory as inv
from .rpg.game_state import GameState

DECISION_INTERVAL = 0.4
NPC_WALK_SPEED = 90.0
ARRIVE_RADIUS = 48.0
#: How close the player must be to talk. Comfortably larger than a billboard so
#: walking up to an NPC (whose speech bubble is showing) and pressing E works.
TALK_RADIUS = 140.0
#: How near a talkable NPC must be for its speech bubble to appear — a locator
#: cue at a wider range than the interaction range above.
BUBBLE_RADIUS = 280.0
DEFEND_SIGHT = 700.0
#: How close a hostile must be before a non-combatant NPC breaks off and flees.
FLEE_SIGHT = 480.0
_RALLY_THRESHOLD = 0.5
_FLEE_THRESHOLD = -0.2
#: Seconds a struck actor flashes red (mirrors engine MONSTER_HIT_FLASH_TIME).
HIT_FLASH_TIME = 0.18
#: How far a melee swing reaches / a shot can pick a target.
MELEE_REACH = 170.0
BOW_REACH = 2400.0
#: Frontal cone (dot threshold) for auto-target selection.
AIM_DOT = 0.55


class StateStore:
    """Adapter presenting a plugin ``GlobalStore`` as a string KV store."""

    def __init__(self, globals_store, store_name: str = "miniwind"):
        self._g = globals_store
        self._name = store_name

    def get(self, key, default="false"):
        if self._g is None:
            return default
        try:
            return self._g.get(key, default, store=self._name)
        except Exception:
            return default

    def set(self, key, value):
        if self._g is None:
            return
        try:
            self._g.set(key, value, store=self._name)
        except Exception:
            pass

    def all(self):
        if self._g is None:
            return {}
        try:
            return self._g.all(store=self._name)
        except Exception:
            return {}

    def clear(self):
        """Delete every key in this store (used by 'Reset All Progress')."""
        if self._g is None:
            return
        try:
            for k in list(self._g.all(store=self._name).keys()):
                self._g.delete(k, store=self._name)
        except Exception:
            pass


class MiniwindSession:
    """Owns the clock, the player character, NPC AI and dialogue state."""

    def __init__(self, logic, cfg: Dict = None, globals_store=None):
        self.logic = logic
        cfg = cfg or {}
        mins_per_day = float(cfg.get("minutes_per_day", 20.0)) or 20.0
        self.clock = GameClock(
            hour=float(cfg.get("start_hour", 8.0)),
            day=int(cfg.get("start_day", 1)),
            hours_per_second=24.0 / (mins_per_day * 60.0),
        )
        self.show_clock = bool(cfg.get("show_clock", True))
        self.difficulty = str(cfg.get("difficulty", "normal"))
        self.region_name = str(cfg.get("region_name", "The Vale of Miniwind"))
        self.store = StateStore(globals_store, str(cfg.get("state_store", "miniwind")))

        self.rng = random.Random()
        self.game = GameState(self.store, rng=self.rng)
        self.needs_char_creation = str(cfg.get("start_scenario", "prompt")) == "prompt"

        # Register any quests the map author defined on the GameSettings entity
        # (these override built-ins of the same id) so levels can add quests
        # without touching code.
        from .rpg import quests as _quests
        map_quests = cfg.get("quests")
        if isinstance(map_quests, list):
            _quests.load_definitions(map_quests)

        self._decision_accum = 0.0
        self._last_hour_int = -1
        self._attack_cooldown = 0.0
        self._cast_cooldown = 0.0
        #: Live combat actors (NPCs/creatures), refreshed once per decision pass
        #: so per-NPC threat lookups iterate a short cached list instead of
        #: re-scanning the whole scene (markers, lights, brushes…) for each NPC.
        self._actors: List = []
        #: Recently dead actors, refreshed alongside _actors so the confidence
        #: calculation can penalise for visible casualties without a global scan.
        self._dead_actors: List = []
        #: Names of NPCs already reaped, so a death is turned into a settlement
        #: consequence exactly once (even across the low-frequency tick).
        self._deaths_seen = set()

        # transient UI state (driven by plugin/input, read by overlays)
        self.interact_prompt = ""       # e.g. "Press E to talk to Thalen"
        self.dialogue: Optional[DialogueRunner] = None
        self.dialogue_npc = None
        self.dialogue_options = []      # for merchant/persuade extra options
        self.open_screen = None         # None | 'inventory' | 'character' | 'journal' | 'spells' | 'charcreate' | 'map' | 'levelup'
        self.notifications: List[Dict] = []   # timed toast messages
        self.floaters: List[Dict] = []         # floating combat text
        self._blocking = False
        self.merchant_npc = None

    def reset_progress(self) -> None:
        """Erase all saved progress and return the session to a clean slate.

        Wipes the persistent KV store (character, quests, inventory, world
        flags), rebuilds a fresh game state, and re-arms character creation so
        the next moment of play starts a brand-new game."""
        try:
            self.store.clear()
        except Exception:
            pass
        self.rng = random.Random()
        self.game = GameState(self.store, rng=self.rng)
        self.needs_char_creation = True
        self.open_screen = "charcreate"
        self.dialogue = None
        self.dialogue_npc = None
        self.merchant_npc = None
        self.show_loadout = False
        self.notifications = []
        self.floaters = []
        self._deaths_seen = set()
        if self.logic is not None:
            try:
                self.logic.gameplay_paused = True
            except Exception:
                pass

    # -- difficulty scaling -------------------------------------------------
    @property
    def incoming_mult(self) -> float:
        return {"easy": 0.6, "normal": 1.0, "hard": 1.5}.get(self.difficulty, 1.0)

    # ================================================================= setup
    def install(self) -> None:
        """Attach the RPG to the logic thread (damage filter, faction model)."""
        logic = self.logic
        logic._player_damage_filter = self._mitigate_incoming
        # Teach the engine's team-aware MonsterAI MiniWind's faction relationships
        # so wild animals stay neutral to villagers while bandits are hostile to
        # both — instead of "every different team is an enemy".
        logic._faction_hostile = factions.is_hostile
        self.spawn_creature_points()   # materialise CreatureSpawn points once
        self._sync_engine_health(full=True)

    def uninstall(self) -> None:
        if getattr(self.logic, "_player_damage_filter", None) is self._mitigate_incoming:
            self.logic._player_damage_filter = None
        if getattr(self.logic, "_faction_hostile", None) is factions.is_hostile:
            self.logic._faction_hostile = None

    def _mitigate_incoming(self, raw_damage, damage_kind="physical") -> float:
        c = self.game.character
        if getattr(self.logic, "god_mode", False):
            return 0.0
        res = rpg_combat.resolve_incoming(c, float(raw_damage) * self.incoming_mult,
                                          damage_kind=damage_kind,
                                          blocking=self._blocking, rng=self.rng)
        final = res["final"]
        c.damage(final)
        # armour training when actually hit
        ac = res["armor_class"]
        if ac == "heavy":
            c.use_skill("heavy_armor", 1.0)
        elif ac == "light":
            c.use_skill("light_armor", 1.0)
        self.add_floater(f"-{int(round(final))}", kind="hurt")
        return final

    def _sync_engine_health(self, full=False) -> None:
        c = self.game.character
        try:
            self.logic.player_max_health = int(round(c.max_health))
            if full:
                self.logic.player_health = int(round(c.health))
            else:
                # character is authoritative; mirror into the engine pool
                self.logic.player_health = int(round(max(0.0, c.health)))
        except Exception:
            pass

    # -- character creation result -----------------------------------------
    def begin_new_character(self, name, race_id, class_id, birthsign_id="none",
                            gender="male", custom_class=None) -> None:
        self.game = GameState.new_game(self.store, name, race_id, class_id,
                                       birthsign_id, gender, custom_class, self.rng)
        self.needs_char_creation = False
        self.open_screen = None
        self._sync_engine_health(full=True)
        self.notify(f"Welcome to {self.region_name}, {name}.", 5.0)

    # ================================================================= tick
    def tick(self, delta: float) -> None:
        self.clock.advance(delta)
        self.game.tick(delta)
        if self._attack_cooldown > 0:
            self._attack_cooldown -= delta
        if self._cast_cooldown > 0:
            self._cast_cooldown -= delta

        # decisions (low frequency) + movement (every tick)
        hour_int = int(self.clock.hour)
        self._decision_accum += delta
        if self._decision_accum >= DECISION_INTERVAL or hour_int != self._last_hour_int:
            self._decision_accum = 0.0
            self._last_hour_int = hour_int
            self._refresh_actor_cache()
            for npc in self.npcs():
                self._decide(npc)
        for npc in self.npcs():
            self._move(npc, delta)

        # Turn any NPC deaths (from player or engine combat) into persistent
        # settlement consequences — cheap: it walks the same cached actor list.
        self._reap_dead()

        # world placeables: item pickups and quest triggers (cheap proximity)
        self._tick_pickups()
        self._tick_triggers()

        # keep the engine's health pool in step with the character
        self._sync_engine_health()

        # age transient UI
        self._age_lists(delta)

    # ---------------------------------------------------------- world placeables
    def _things_of_type(self, type_name):
        tt = type_name.replace("_", "").lower()
        return [x for x in (getattr(self.logic, "things", None) or [])
                if str(x.properties.get("type", "")).replace("_", "").lower() == tt]

    def spawn_creature_points(self) -> int:
        """Materialise actors from spawn points (once, at play start).

        A spawn point (the 'logicspawner', type ``creaturespawn``) can create a
        single actor or a whole same-faction GROUP of them, of either kind — a
        Creature (monster/animal) or an NPC (townsperson / guard / bandit) —
        with full authored control over role/appearance, faction and starting
        inventory. Spawned actors are appended to the scene and the engine's
        monster cache is rebuilt so the core AI drives them — MiniWind only says
        *what* to spawn; the engine does the rest."""
        try:
            from .entities import Creature, NPC
        except Exception:
            return 0
        made = 0
        for sp in self._things_of_type("creaturespawn"):
            p = sp.properties
            if p.get("_spawned"):
                continue
            role = p.get("creature_role", "wolf")
            cls = NPC if str(p.get("spawn_kind", "creature")).lower() == "npc" else Creature
            count = int(p.get("count", 1))
            radius = float(p.get("spawn_radius", 0.0))
            faction = str(p.get("faction", "") or "").strip()
            inventory = self._spawn_inventory(p.get("inventory"))
            for _ in range(max(0, count)):
                ox = self.rng.uniform(-radius, radius) if radius else 0.0
                oz = self.rng.uniform(-radius, radius) if radius else 0.0
                pos = [sp.pos[0] + ox, sp.pos[1], sp.pos[2] + oz]
                props = {"npc_role": role}
                if faction:
                    # Force the whole group onto one team (relationships/combat).
                    props["faction"] = faction
                    props["team"] = faction
                if inventory:
                    # Each member gets its own copy so looting one member's
                    # corpse never empties the rest of the group.
                    props["inventory"] = [dict(it) for it in inventory]
                try:
                    self.logic.things.append(cls(pos=pos, properties=props))
                    made += 1
                except Exception:
                    pass
            p["_spawned"] = True
        if made:
            rebuild = getattr(self.logic, "_build_entity_caches", None)
            if callable(rebuild):
                try:
                    rebuild()
                except Exception:
                    pass
        return made

    @staticmethod
    def _spawn_inventory(spec) -> list:
        """Build a list of item stacks from a spawn point's ``inventory``.

        Accepts either a compact ``"id:qty, id:qty"`` string (``qty`` optional,
        defaulting to 1) or an authored list of ``{"id","qty"}`` shorthands /
        already-built stacks. Ids are expanded through the item DB; unknown ids
        are skipped so a typo can never crash a spawn."""
        if not spec:
            return []
        raw = []
        if isinstance(spec, str):
            for part in spec.split(","):
                part = part.strip()
                if not part:
                    continue
                iid, sep, qty = part.partition(":")
                iid = iid.strip()
                if not iid:
                    continue
                try:
                    qty = int(qty.strip()) if sep else 1
                except ValueError:
                    qty = 1
                raw.append((iid, qty))
        elif isinstance(spec, (list, tuple)):
            for e in spec:
                if isinstance(e, dict) and e.get("name") and e.get("type"):
                    raw.append(dict(e))          # already a full stack
                elif isinstance(e, dict) and e.get("id"):
                    raw.append((e["id"], int(e.get("qty", 1))))
        out = []
        for e in raw:
            if isinstance(e, dict):
                out.append(e)
                continue
            iid, qty = e
            stack = rpg_items.make(iid, qty)
            if stack:                             # unknown id -> skipped
                out.append(stack)
        return out

    def _tick_pickups(self) -> None:
        ppos = self._player_pos()
        if ppos is None:
            return
        for it in self._things_of_type("itempickup"):
            p = it.properties
            if p.get("dead"):
                continue
            if self._dist2d(ppos, it.pos) <= float(p.get("pickup_radius", 60.0)):
                iid = p.get("item_id", "gold")
                qty = int(p.get("quantity", 1))
                stack = rpg_items.make(iid, qty) or inv.make_item(iid, qty=qty)
                inv.add_item(self.game.character.inventory, stack)
                self.notify(f"Picked up {stack.get('name', iid)}")
                p["dead"] = True
                p["hidden"] = True

    def _tick_triggers(self) -> None:
        ppos = self._player_pos()
        if ppos is None:
            return
        for tr in self._things_of_type("miniwindtrigger"):
            p = tr.properties
            if p.get("_fired") and p.get("once", True):
                continue
            if self._dist2d(ppos, tr.pos) <= float(p.get("trigger_radius", 120.0)):
                flag = str(p.get("set_flag", "")).strip()
                if "=" in flag:
                    k, v = flag.split("=", 1)
                    self.store.set(k.strip(), v.strip())
                quest = str(p.get("start_quest", "")).strip()
                if quest:
                    self.game.start_quest(quest)
                p["_fired"] = True

    def tick_ui(self, delta: float) -> None:
        """Age only the transient HUD (toasts/floaters) while the world is paused
        (a menu or character creation is open). No clock, NPC or combat sim."""
        self._age_lists(delta)

    def _age_lists(self, delta):
        for n in self.notifications:
            n["t"] -= delta
        self.notifications = [n for n in self.notifications if n["t"] > 0]
        for f in self.floaters:
            f["t"] -= delta
            f["y"] -= 30 * delta
        self.floaters = [f for f in self.floaters if f["t"] > 0]

    def notify(self, text, seconds=3.0):
        self.notifications.append({"text": text, "t": seconds})
        if len(self.notifications) > 6:
            self.notifications = self.notifications[-6:]

    def add_floater(self, text, kind="dmg"):
        self.floaters.append({"text": text, "t": 1.2, "y": 0.0, "kind": kind})

    # ============================================================= NPC AI
    def npcs(self) -> List:
        things = getattr(self.logic, "things", None) or []
        return [t for t in things
                if str(t.properties.get("type", "")).replace("_", "").lower() == "npc"
                and not t.properties.get("dead", False)]

    @staticmethod
    def _is_combatant(npc) -> bool:
        """Whether an NPC can and will fight — a capability that is deliberately
        *separate* from its faction (who counts as an enemy) and from the
        civilian flee reaction. A guard is a combatant; a merchant is not, even
        though both share the villagers/guards side. Authored via the
        ``combatant`` property (defaulted from aggression/role by the entity)."""
        p = npc.properties
        if "combatant" in p:
            return bool(p.get("combatant"))
        return (str(p.get("aggression")) in ("defensive", "hostile")
                or p.get("can_defend")
                or str(p.get("npc_role", "")).lower().startswith("guard"))

    def _reap_dead(self) -> None:
        """Turn NPC deaths into persistent settlement consequences, once each.

        Deaths are caught by watching the ``dead`` flag rather than hooking every
        kill path, so a townsperson cut down by the engine's MonsterAI (a bandit,
        a wolf) counts the same as one the player kills. The consequence lives in
        the persistent KV store, so it survives save/load and dialogue can read
        it — the town remembers who is gone.
        """
        for t in getattr(self.logic, "things", None) or []:
            tp = t.properties
            if not tp.get("dead"):
                continue
            if str(tp.get("type", "")).replace("_", "").lower() != "npc":
                continue
            name = str(tp.get("name", ""))
            if name in self._deaths_seen:
                continue
            self._deaths_seen.add(name)
            if tp.get("_death_noted"):
                continue          # already recorded before a save/load
            tp["_death_noted"] = True
            self._on_npc_death(t)

    def _on_npc_death(self, npc) -> None:
        """Record the durable, save/load-persistent fallout of one NPC's death."""
        p = npc.properties
        name = str(p.get("name", ""))
        disp = p.get("display_name") or name or "Someone"
        already = str(self.store.get("dead." + name, "false")).lower() not in (
            "false", "", "none")
        if name:
            self.store.set("dead." + name, "1")
        self.game.message(f"{disp} has died.")
        self.notify(f"{disp} has died.", 5.0)
        if not already:
            try:
                n = int(self.store.get("town.deaths", "0"))
            except (TypeError, ValueError):
                n = 0
            self.store.set("town.deaths", n + 1)
        self.store.set("town.last_death", disp)
        self.store.set("town.mourning", "1")
        # A fallen guard leaves the settlement less protected — a durable flag
        # other systems and dialogue can key off.
        if str(p.get("npc_role", "")).lower().startswith("guard"):
            self.store.set("town.unprotected", "1")

    def _decide(self, npc) -> None:
        p = npc.properties

        # (a) FACTION + COMBAT CAPABILITY: an actively hostile combatant is the
        #     engine MonsterAI's job (it is live), so leave it be.
        if str(p.get("aggression")) == "hostile" and not p.get("triggered", False):
            p["sched_state"] = sched.COMBAT
            return

        combatant = self._is_combatant(npc)

        # (b) A defending combatant (e.g. a guard) un-parks into the core AI when
        #     a faction-hostile enemy is near, and re-parks to its post after.
        if combatant:
            enemy = self._nearest_hostile(npc, DEFEND_SIGHT)
            if enemy is not None:
                p["triggered"] = False
                p["awake"] = True
                p["sched_state"] = sched.COMBAT
                p.pop("_flee", None)
                return
            elif p.get("sched_state") == sched.COMBAT:
                p["triggered"] = True
                p["awake"] = False
        else:
            # (c) CIVILIAN CONFIDENCE: a non-combatant's response to threats
            #     is driven by a per-NPC confidence score, not a binary guard
            #     check.  Confidence depends on courage, nearby friendlies,
            #     guards, already-rallied civilians, hostiles, and casualties.
            threat = self._nearest_hostile(npc, FLEE_SIGHT)
            if threat is not None:
                conf = self._civilian_confidence(npc, threat)
                was_rallied = p.get("_rally", False)
                rally_thresh = _RALLY_THRESHOLD - (0.15 if was_rallied else 0.0)
                if conf >= rally_thresh:
                    p["triggered"] = False
                    p["awake"] = True
                    p["sched_state"] = sched.RALLY
                    p["_rally"] = True
                    p.pop("_flee", None)
                    return
                if conf >= _FLEE_THRESHOLD:
                    p["sched_state"] = sched.ALERT
                    p.pop("_rally", None)
                    p.pop("_flee", None)
                    p.pop("_dest", None)
                    return
                p["sched_state"] = sched.FLEE
                p["_flee"] = True
                p.pop("_rally", None)
                p["_dest"] = self._refuge_point(npc, threat)
                return
            if p.get("_rally"):
                p["triggered"] = True
                p["awake"] = False
                p.pop("_rally", None)
            p.pop("_flee", None)

        entry = sched.evaluate(p.get("schedule", []), self.clock.hour)
        if entry is None:
            self._idle_or_wander(npc)
            return
        state = entry.get("state", sched.IDLE)
        # (d) PATROL: an on-duty guard/combatant with an authored patrol circuit
        #     walks between its markers rather than standing at one work spot, so
        #     the town has a visibly moving watch. Combat (b) pre-empts this; the
        #     guard resumes the circuit afterwards from where it left off.
        if state in (sched.WORKING, sched.GOING_TO_WORK) and p.get("patrol_markers"):
            if self._patrol(npc):
                return
        p["sched_state"] = state
        dest = self._resolve_location(npc, entry.get("location", "home"))
        if state == sched.IDLE:
            # At an idle point: allow a little local wandering so the town looks
            # alive rather than frozen in place.
            p["_anchor"] = list(dest) if dest is not None else list(npc.pos)
            self._idle_or_wander(npc)
        elif dest is not None:
            p["_dest"] = list(dest)
            p.pop("_wander_dest", None)
        else:
            p.pop("_dest", None)

    def _idle_or_wander(self, npc) -> None:
        """Pick a nearby stroll target around the NPC's idle anchor (autonomy)."""
        p = npc.properties
        p["sched_state"] = p.get("sched_state", sched.IDLE)
        if not p.get("autonomy", True):
            p.pop("_dest", None)
            return
        anchor = p.get("_anchor") or p.get("home") or list(npc.pos)
        radius = float(p.get("wander_radius", 220.0))
        cur = p.get("_wander_dest")
        # Re-pick only when we have arrived (or have no target), so NPCs amble
        # instead of jittering — expensive decisions stay low-frequency.
        if cur is not None and self._dist2d(npc.pos, cur) > ARRIVE_RADIUS:
            p["_dest"] = list(cur)
            p["sched_state"] = sched.WANDER
            return
        ang = self.rng.uniform(0, 2 * math.pi)
        r = self.rng.uniform(0.2, 1.0) * radius
        dest = [anchor[0] + math.cos(ang) * r, npc.pos[1], anchor[2] + math.sin(ang) * r]
        p["_wander_dest"] = dest
        p["_dest"] = dest
        p["sched_state"] = sched.WANDER

    def _patrol_points(self, npc) -> List[List[float]]:
        """Resolve (and cache) an NPC's ``patrol_markers`` to world points.

        Markers are static, so the resolved circuit is cached on the NPC after
        the first lookup — no per-decision name scan of the scene. The cache
        travels in ``properties`` (a couple of coords), so it round-trips through
        save/load like any other authored state.
        """
        p = npc.properties
        cached = p.get("_patrol_pts")
        if cached:
            return cached
        pts: List[List[float]] = []
        for nm in (p.get("patrol_markers") or []):
            ent = self._find_named(str(nm))
            if ent is not None:
                pts.append([ent.pos[0], npc.pos[1], ent.pos[2]])
        if pts:
            p["_patrol_pts"] = pts
        return pts

    def _patrol(self, npc) -> bool:
        """Advance a guard along its patrol circuit; True if it set the dest.

        The waypoint index only advances on *arrival*, so the choice of where to
        walk is made once per leg — not reconsidered every decision tick — which
        keeps patrolling a low-frequency decision and stops the guard dithering.
        """
        p = npc.properties
        pts = self._patrol_points(npc)
        if not pts:
            return False
        i = int(p.get("_patrol_i", 0)) % len(pts)
        if self._dist2d(npc.pos, pts[i]) <= ARRIVE_RADIUS * 1.25:
            i = (i + 1) % len(pts)
            p["_patrol_i"] = i
        p["_dest"] = list(pts[i])
        p["sched_state"] = sched.PATROL
        p.pop("_wander_dest", None)
        return True

    def _refuge_point(self, npc, threat) -> List[float]:
        """Where a fleeing civilian runs to: the safest *real* refuge — its home,
        the nearest guard, or the nearest guard post — chosen to put the most
        distance between it and the threat. This keeps flight spatially bounded
        (a refuge inside the settlement) instead of an unbounded run away.

        If no refuge is safer than standing still (threat sits on every refuge),
        it steps a short, capped distance directly away as a last resort.
        """
        tx, tz = threat.pos[0], threat.pos[2]

        def _away(c):
            return (c[0] - tx) ** 2 + (c[2] - tz) ** 2

        home = npc.properties.get("home")
        candidates: List[List[float]] = []
        if isinstance(home, (list, tuple)) and len(home) == 3:
            candidates.append([home[0], npc.pos[1], home[2]])
        guard = self._nearest_of(npc, lambda t: self._is_guard(t))
        if guard is not None:
            candidates.append([guard.pos[0], npc.pos[1], guard.pos[2]])
        post = self._nearest_of(npc, lambda t: self._marker_kind(t) == "guardpost")
        if post is not None:
            candidates.append([post.pos[0], npc.pos[1], post.pos[2]])

        here = _away([npc.pos[0], npc.pos[1], npc.pos[2]])
        safe = [c for c in candidates if _away(c) >= here]
        if safe:
            return max(safe, key=_away)

        # Last resort: a short, capped step away (still bounded, ~1 tile).
        px, pz = npc.pos[0], npc.pos[2]
        dx, dz = px - tx, pz - tz
        d = math.hypot(dx, dz) or 1.0
        step = min(200.0, FLEE_SIGHT)
        return [px + dx / d * step, npc.pos[1], pz + dz / d * step]

    @staticmethod
    def _is_guard(thing) -> bool:
        p = thing.properties
        return (str(p.get("npc_role", "")).lower().startswith("guard")
                and not p.get("dead"))

    @staticmethod
    def _marker_kind(thing) -> str:
        p = thing.properties
        if str(p.get("type", "")).replace("_", "").lower() != "marker":
            return ""
        return str(p.get("marker_kind", "")).lower()

    def _nearest_of(self, npc, predicate):
        """Nearest live thing (2D) satisfying *predicate*, excluding *npc*."""
        best, best_d = None, float("inf")
        npos = npc.pos
        for t in getattr(self.logic, "things", None) or []:
            if t is npc:
                continue
            try:
                if not predicate(t):
                    continue
            except Exception:
                continue
            dx = t.pos[0] - npos[0]
            dz = t.pos[2] - npos[2]
            d = dx * dx + dz * dz
            if d < best_d:
                best, best_d = t, d
        return best

    @staticmethod
    def _dist2d(a, b) -> float:
        return math.hypot(a[0] - b[0], a[2] - b[2])

    def _resolve_location(self, npc, key: str) -> Optional[List[float]]:
        p = npc.properties
        key = str(key or "").lower()
        if key == "home":
            home = p.get("home")
            return list(home) if isinstance(home, (list, tuple)) and len(home) == 3 else list(npc.pos)
        target = p.get("work_location") if key in ("work", "market") else key
        if isinstance(target, (list, tuple)) and len(target) == 3:
            return list(target)
        if isinstance(target, str) and target:
            ent = self._find_named(target)
            if ent is not None:
                return list(ent.pos)
        home = p.get("home")
        return list(home) if isinstance(home, (list, tuple)) and len(home) == 3 else list(npc.pos)

    def _find_named(self, name: str):
        for t in getattr(self.logic, "things", None) or []:
            if str(t.properties.get("name", "")) == name:
                return t
        return None

    def _refresh_actor_cache(self) -> None:
        """Snapshot live and dead combat actors once per decision pass."""
        actors = []
        dead = []
        for t in getattr(self.logic, "things", None) or []:
            tp = t.properties
            if tp.get("hidden"):
                continue
            ttype = str(tp.get("type", "")).replace("_", "").lower()
            if ttype in ("npc", "creature", "monster"):
                if tp.get("dead"):
                    dead.append(t)
                else:
                    actors.append(t)
        self._actors = actors
        self._dead_actors = dead

    def _nearest_hostile(self, npc, radius: float):
        my_faction = npc.properties.get("faction") or npc.properties.get("team")
        best, best_d = None, radius * radius
        npos = npc.pos
        # Prefer the cached actor list; fall back to a full scan if a caller runs
        # outside the decision pass (e.g. a unit test poking a single tick).
        pool = self._actors or (getattr(self.logic, "things", None) or [])
        for t in pool:
            if t is npc:
                continue
            tp = t.properties
            if tp.get("dead") or tp.get("hidden"):
                continue
            other = tp.get("team") or tp.get("faction")
            if not factions.is_hostile(my_faction, other):
                continue
            dx = t.pos[0] - npos[0]
            dz = t.pos[2] - npos[2]
            d = dx * dx + dz * dz
            if d < best_d:
                best, best_d = t, d
        return best

    def _nearest_friendly_combatant(self, npc, radius: float):
        """Find the nearest living friendly combatant (e.g. a guard) that could
        protect this NPC.  Returns None if no protector is within *radius*."""
        my_faction = npc.properties.get("faction") or npc.properties.get("team")
        best, best_d = None, radius * radius
        npos = npc.pos
        pool = self._actors or (getattr(self.logic, "things", None) or [])
        for t in pool:
            if t is npc:
                continue
            tp = t.properties
            if tp.get("dead") or tp.get("hidden"):
                continue
            if not self._is_combatant(t):
                continue
            other = tp.get("team") or tp.get("faction")
            if not factions.is_friendly(my_faction, other):
                continue
            dx = t.pos[0] - npos[0]
            dz = t.pos[2] - npos[2]
            d = dx * dx + dz * dz
            if d < best_d:
                best, best_d = t, d
        return best

    def _civilian_confidence(self, npc, threat) -> float:
        """Per-NPC confidence score that drives flee / alert / rally decisions."""
        p = npc.properties
        my_faction = p.get("faction") or p.get("team")
        nx, nz = npc.pos[0], npc.pos[2]
        sight2 = FLEE_SIGHT * FLEE_SIGHT

        courage = float(p.get("courage", 0.3))
        dist = self._dist2d(npc.pos, threat.pos)
        distance_factor = min(dist / FLEE_SIGHT, 1.0) * 0.25

        n_guards = 0
        n_rallied = 0
        n_friendly = 0
        n_hostile = 0
        pool = self._actors or []
        for t in pool:
            if t is npc:
                continue
            tp = t.properties
            dx = t.pos[0] - nx
            dz = t.pos[2] - nz
            if dx * dx + dz * dz > sight2:
                continue
            other = tp.get("team") or tp.get("faction")
            if factions.is_hostile(my_faction, other):
                n_hostile += 1
            elif factions.is_friendly(my_faction, other):
                n_friendly += 1
                if self._is_combatant(t):
                    n_guards += 1
                if tp.get("_rally"):
                    n_rallied += 1

        n_casualties = 0
        for t in self._dead_actors:
            tp = t.properties
            other = tp.get("team") or tp.get("faction")
            if not factions.is_friendly(my_faction, other):
                continue
            dx = t.pos[0] - nx
            dz = t.pos[2] - nz
            if dx * dx + dz * dz <= sight2:
                n_casualties += 1

        # Group bonus is based on total nearby friendlies only. Rallied NPCs
        # are already counted in n_friendly, so adding n_rallied here would
        # double-count them; their extra influence is applied separately below
        # via the explicit n_rallied social-contagion term.
        group_bonus = min(n_friendly * 0.1, 0.45) if n_friendly >= 2 else 0.0

        return (courage
                + distance_factor
                + n_guards * 0.35
                + n_rallied * 0.2
                + group_bonus
                - n_hostile * 0.55
                - n_casualties * 0.25)

    def _move(self, npc, delta: float) -> None:
        p = npc.properties
        # An un-parked NPC (triggered False) is being driven by the core combat
        # AI; the runtime doesn't also push it around.
        if p.get("triggered") is False:
            return
        dest = p.get("_dest")
        if not dest:
            return
        pos = npc.pos
        dx = dest[0] - pos[0]
        dz = dest[2] - pos[2]
        dist = math.hypot(dx, dz)
        if dist <= ARRIVE_RADIUS:
            return
        speed = float(p.get("move_speed", NPC_WALK_SPEED)) or NPC_WALK_SPEED
        if p.get("sched_state") == sched.FLEE:
            speed *= 1.6          # a fright quickens the step
        step = min(speed * delta, dist)
        nx = pos[0] + dx / dist * step
        nz = pos[2] + dz / dist * step
        npc.pos = [nx, pos[1], nz]

    # ========================================================= player combat
    def _player_pos(self):
        p = getattr(self.logic, "player", None)
        if p is None:
            return None
        return [float(p.pos[0]), float(p.pos[1]), float(p.pos[2])]

    def _player_forward(self):
        p = getattr(self.logic, "player", None)
        if p is None:
            return (0.0, 0.0, 1.0)
        a = getattr(p, "angle", 0.0)
        return (math.sin(a), 0.0, math.cos(a))

    def _attackable(self, thing) -> bool:
        tp = thing.properties
        if tp.get("dead") or tp.get("hidden"):
            return False
        t = str(tp.get("type", "")).replace("_", "").lower()
        if t not in ("npc", "creature", "monster"):
            return False
        team = tp.get("team") or tp.get("faction")
        # Don't auto-target friends unless they've turned hostile.
        if factions.is_friendly("player", team) and str(tp.get("aggression")) != "hostile":
            # still allow if the player is deliberately aiming right at them:
            return True
        return True

    def _acquire_target(self, reach: float):
        """Nearest attackable creature within *reach* and the frontal cone."""
        ppos = self._player_pos()
        if ppos is None:
            return None
        fwd = self._player_forward()
        best, best_d = None, reach
        for t in getattr(self.logic, "things", None) or []:
            if not self._attackable(t):
                continue
            dx = t.pos[0] - ppos[0]
            dz = t.pos[2] - ppos[2]
            dist = math.hypot(dx, dz)
            if dist < 1e-3 or dist > reach:
                continue
            # frontal cone
            dot = (fwd[0] * dx + fwd[2] * dz) / dist
            if dot < AIM_DOT:
                continue
            # rank by distance, tighter cone breaks ties toward the aim
            score = dist * (1.2 - dot * 0.2)
            if score < best_d:
                best_d = score
                best = t
        return best

    def do_attack(self) -> bool:
        """Player swings a melee weapon / looses an arrow / casts if staff."""
        c = self.game.character
        if c.is_dead or self._attack_cooldown > 0:
            return False
        w = eq.weapon(c)
        kind = w.get("kind", rpg_items.KIND_MELEE) if w else rpg_items.KIND_MELEE
        speed = float(w.get("speed", 1.0)) if w else 1.2
        reach = MELEE_REACH
        if kind == rpg_items.KIND_BOW:
            reach = BOW_REACH
        elif kind == rpg_items.KIND_STAFF:
            # a staff channels its bound spell
            return self._staff_attack(w)
        self._attack_cooldown = max(0.25, 1.0 / max(0.4, speed))
        if c.stamina < 4:
            self.notify("Too exhausted to attack")
            return False
        target = self._acquire_target(reach)
        if target is None:
            # a swing at nothing still trains the weapon a touch (and costs stamina)
            c.spend_stamina(4.0)
            if w and kind == rpg_items.KIND_BOW and eq.ammo(c) is None:
                self.notify("Out of arrows!")
            return True
        res = self.game.attack_creature(target.properties)
        if res.get("hit"):
            tag = "sneak" if res.get("sneak") else ("crit" if res.get("crit") else "dmg")
            self.add_floater(f"-{int(res['damage'])}", kind=tag)
            self._provoke(target)
            if res.get("killed"):
                self._on_creature_killed(target)
        elif res.get("no_ammo"):
            self.notify("Out of arrows!")
        else:
            self.add_floater("miss", kind="miss")
        return True

    def _staff_attack(self, w) -> bool:
        c = self.game.character
        spell_id = w.get("staff_spell", "flare")
        spell = rpg_magic.get(spell_id)
        if spell is None:
            return False
        self._attack_cooldown = 0.8
        target = self._acquire_target(BOW_REACH)
        cost = rpg_magic.cast_cost(c, spell) * 0.5   # staves are cheaper
        if not c.spend_magicka(cost):
            self.notify("Not enough magicka")
            return False
        c.use_skill("destruction", 1.0)
        if target is not None:
            r = self.game.resolve_spell_on_creature(spell, target.properties)
            self.add_floater(f"-{int(r['damage'])}", kind="fire")
            self._provoke(target)
            if r.get("killed"):
                self._on_creature_killed(target)
        return True

    def do_cast(self) -> bool:
        """Cast the active spell. PROJECTILE spells launch a visible bolt that
        flies from the player and damages the first creature it strikes;
        TARGET/TOUCH spells resolve instantly on the aimed creature; SELF spells
        are applied to the caster by ``cast_active_spell``."""
        c = self.game.character
        if c.is_dead or self._cast_cooldown > 0 or not c.active_spell:
            return False
        self._cast_cooldown = 0.7
        spell = rpg_magic.get(c.active_spell)
        res = self.game.cast_active_spell()
        if not res.cast:
            if res.reason == "not enough magicka":
                self.notify("Not enough magicka")
            elif res.reason == "fizzle":
                self.notify("The spell fizzles")
            return False
        if spell is None:
            return True
        if spell.delivery == rpg_magic.PROJECTILE:
            self._spawn_player_spell_projectile(spell)
            return True
        if spell.delivery in (rpg_magic.TARGET, rpg_magic.TOUCH):
            target = self._acquire_target(BOW_REACH if spell.delivery != rpg_magic.TOUCH else MELEE_REACH)
            if target is not None:
                r = self.game.resolve_spell_on_creature(spell, target.properties)
                if r.get("damage"):
                    self.add_floater(f"-{int(r['damage'])}", kind=spell.element)
                self._apply_nondamage_spell(spell, target)
                self._provoke(target)
                if r.get("killed"):
                    self._on_creature_killed(target)
        return True

    def _spawn_player_spell_projectile(self, spell) -> None:
        """Launch a visible spell bolt from the player toward the aim point (a
        creature in front, else straight ahead). It reuses the engine's
        projectile pipeline — flagged as player-owned so it flies past the
        caster and strikes creatures with the spell's damage and element tint."""
        lt = self.logic
        ppos = self._player_pos()
        if lt is None or ppos is None:
            return
        try:
            from engine.monster_constants import (
                MONSTER_PROJECTILE_SPEED, MONSTER_PROJECTILE_MAX_DIST,
                MONSTER_PROJECTILE_SPRITE_SIZE)
        except Exception:
            MONSTER_PROJECTILE_SPEED, MONSTER_PROJECTILE_MAX_DIST = 900.0, 4000.0
            MONSTER_PROJECTILE_SPRITE_SIZE = (48, 48)

        start = [ppos[0], ppos[1] + 48.0, ppos[2]]
        target = self._acquire_target(BOW_REACH)
        if target is not None:
            tp = target.pos
            aim = (float(tp[0]), float(tp[1]) + 64.0, float(tp[2]))
        else:
            fwd = self._player_forward()
            aim = (start[0] + fwd[0] * 1500.0, start[1], start[2] + fwd[2] * 1500.0)

        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        dlen = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        speed = float(getattr(spell, "projectile_speed", 0) or MONSTER_PROJECTILE_SPEED)
        vel = [dx / dlen * speed, dy / dlen * speed, dz / dlen * speed]
        color = list(spell.color) if getattr(spell, "color", None) else None

        proj = {
            "pos": list(start),
            "vel": vel,
            "owner_id": id(getattr(lt, "player", None)),
            "owner_is_player": True,
            "sprite": "assets/sprites/miniwind/magicbolt.png",
            "lifetime": MONSTER_PROJECTILE_MAX_DIST / speed,
            "damage": int(getattr(spell, "damage", 0) or 0),
            "size": MONSTER_PROJECTILE_SPRITE_SIZE,
            "color": color,
            "distance_travelled": 0.0,
        }
        if not hasattr(lt, "_monster_projectiles"):
            lt._monster_projectiles = []
        lt._monster_projectiles.append(proj)

    def overhead_pose(self):
        """(armed, attacking) for the player's overhead sprite, so it visibly
        reflects the RPG loadout: 'armed' when a weapon is equipped or a spell is
        readied, 'attacking' briefly after a swing/cast. Read by the engine's
        overhead sprite renderer (which stays game-agnostic)."""
        c = self.game.character
        armed = bool(eq.equipped_id(c, "weapon")) or bool(c.active_spell)
        attacking = (getattr(self, "_attack_cooldown", 0.0) > 0.05
                     or getattr(self, "_cast_cooldown", 0.0) > 0.05)
        return armed, attacking

    def _apply_nondamage_spell(self, spell, target):
        for e in spell.effects:
            k = e.get("kind")
            if k == "calm":
                target.properties["triggered"] = True
                target.properties["awake"] = False
            elif k == "command":
                target.properties["team"] = "player"
                target.properties["faction"] = "player"

    def _provoke(self, target):
        """A struck NPC (and its nearby allies) turns hostile and fights back."""
        tp = target.properties
        tp["_hit_flash"] = HIT_FLASH_TIME    # red flash on a landed player hit
        team = tp.get("team") or tp.get("faction")
        if factions.is_friendly("player", team) and str(tp.get("aggression")) != "hostile":
            # attacking innocents earns a bounty and their wrath
            self.game.character.bounty += 40
            self.notify("Your bounty has increased!")
        tp["aggression"] = "hostile"
        tp["triggered"] = False
        tp["awake"] = True
        tp["wake_on_sight"] = True

    def _on_creature_killed(self, target):
        self.add_floater("SLAIN", kind="kill")
        # guards react to murder of innocents nearby handled by faction hostility

    # ========================================================= interaction
    def toggle_block(self, down: bool):
        self._blocking = bool(down)

    def toggle_sneak(self):
        self.game.sneaking = not self.game.sneaking
        self.notify("Sneaking" if self.game.sneaking else "Standing")

    def next_spell(self):
        s = self.game.select_next_spell()
        if s:
            spell = rpg_magic.get(s)
            self.notify(f"Spell: {spell.name if spell else s}")

    def use_health_potion(self):
        for pid in ("potion_heal", "potion_heal_minor"):
            if inv.has_item(self.game.character.inventory, pid):
                self.game.use_item(pid)
                self.notify("Drank a healing potion")
                return True
        self.notify("No healing potions")
        return False

    # -- overhead speech bubbles -------------------------------------------
    def _quest_ids_in_dialogue(self, tree) -> List[str]:
        """Quest ids a dialogue tree can start (for the '!' available-quest cue)."""
        out = []
        if not isinstance(tree, dict):
            return out
        for node in (tree.get("nodes", {}) or {}).values():
            actions = list(node.get("on_enter", []) or [])
            for r in node.get("responses", []) or []:
                actions.extend(r.get("actions", []) or [])
            for a in actions:
                if isinstance(a, dict) and a.get("op") == "start_quest":
                    qid = a.get("quest") or a.get("value")
                    if qid:
                        out.append(str(qid))
        return out

    def bubble_kind(self, npc):
        """What speech bubble (if any) belongs over *npc*: 'quest' (an available
        quest, '!'), 'talk' (dialogue/trade, '…'), or None (nothing to say)."""
        p = npc.properties
        if str(p.get("aggression")) == "hostile":
            return None
        tree = p.get("dialogue")
        for qid in self._quest_ids_in_dialogue(tree):
            if not self.game.quests.is_active(qid) and not self.game.quests.is_complete(qid):
                return "quest"
        if tree or p.get("merchant"):
            return "talk"
        return None

    def bubble_npcs(self, player_pos, radius: float = BUBBLE_RADIUS):
        """(npc, kind) for nearby NPCs that have something to say, nearest first."""
        out = []
        r2 = radius * radius
        for npc in self.npcs():
            kind = self.bubble_kind(npc)
            if kind is None:
                continue
            dx = npc.pos[0] - player_pos[0]
            dz = npc.pos[2] - player_pos[2]
            d = dx * dx + dz * dz
            if d <= r2:
                out.append((d, npc, kind))
        out.sort(key=lambda t: t[0])
        return [(npc, kind) for _d, npc, kind in out]

    # -- dialogue -----------------------------------------------------------
    def nearest_talkable(self, player_pos, radius: float = TALK_RADIUS):
        best, best_d = None, radius * radius
        for npc in self.npcs():
            if not npc.properties.get("dialogue") and not npc.properties.get("merchant"):
                continue
            if str(npc.properties.get("aggression")) == "hostile":
                continue
            dx = npc.pos[0] - player_pos[0]
            dz = npc.pos[2] - player_pos[2]
            d = dx * dx + dz * dz
            if d < best_d:
                best, best_d = npc, d
        return best

    def start_dialogue(self, npc, player) -> bool:
        tree = npc.properties.get("dialogue")
        self.dialogue_npc = npc
        if npc.properties.get("merchant"):
            self.merchant_npc = npc
        if not tree:
            # a bare merchant/greeter: synthesise a tiny greeting tree
            tree = self._default_tree(npc)
        self.dialogue = DialogueRunner(
            tree, store=self.store,
            give_item=lambda item: inv.add_item(self.game.character.inventory, item),
            take_item=lambda iid, q: inv.remove_item(self.game.character.inventory, iid, q) > 0,
            has_item=lambda iid, q: inv.has_item(self.game.character.inventory, iid, q),
            on_action=lambda a: self._dialogue_action(npc, a),
        )
        view = self.dialogue.start()
        if view is None:
            self.end_dialogue()
            return False
        return True

    def _default_tree(self, npc):
        name = npc.properties.get("display_name", "Villager")
        disp = guilds.disposition(self.game.character, npc.properties)
        greeting = "Well met, traveller." if disp >= 40 else "What do you want?"
        responses = [{"text": "Just passing through. Farewell.", "goto": "END"}]
        if npc.properties.get("merchant"):
            responses.insert(0, {"text": "Let's trade.", "goto": "END",
                                 "actions": [{"op": "open_trade"}]})
        responses.insert(0 if not npc.properties.get("merchant") else 1,
                         {"text": "(Persuade)", "goto": "END",
                          "actions": [{"op": "persuade"}]})
        return {"start": "g", "nodes": {"g": {"text": greeting, "responses": responses}}}

    def _dialogue_action(self, npc, action):
        op = action.get("op")
        if op == "open_trade":
            self.merchant_npc = npc
            self.end_dialogue()
            self.open_screen = "trade"
        elif op == "persuade":
            r = guilds.persuade(self.game.character, npc.properties, self.rng)
            self.notify("They warm to you." if r["success"] else "That didn't help.")
        elif op == "start_quest":
            self.game.start_quest(action.get("quest", action.get("value", "")))
        elif op == "advance_quest":
            self.game.quests.advance(action.get("quest", ""))
        elif op == "complete_quest":
            self.game.complete_quest(action.get("quest", ""))
        elif op == "join_guild":
            if guilds.join(self.game.character, action.get("guild", "")):
                self.notify(f"You have joined the {guilds.get(action.get('guild','')).name}.")

    def choose(self, index: int) -> None:
        if self.dialogue is None:
            return
        view = self.dialogue.choose(index)
        if view is None:
            self.end_dialogue()

    def end_dialogue(self) -> None:
        self.dialogue = None
        self.dialogue_npc = None

    def current_view(self):
        return self.dialogue.view() if self.dialogue is not None else None

    # -- merchant trade -----------------------------------------------------
    def buy(self, item_id: str) -> bool:
        c = self.game.character
        d = rpg_items.get(item_id)
        if not d:
            return False
        price = self._price(d.value, buying=True)
        if c.gold < price:
            self.notify("Not enough gold")
            return False
        c.gold -= price
        self.game.pick_up(item_id, 1)
        c.use_skill("mercantile", 0.5)
        return True

    def sell(self, item_id: str) -> bool:
        c = self.game.character
        d = rpg_items.get(item_id)
        if not d or not inv.has_item(c.inventory, item_id):
            return False
        price = self._price(d.value, buying=False)
        inv.remove_item(c.inventory, item_id, 1)
        c.gold += price
        c.use_skill("mercantile", 0.5)
        return True

    def _price(self, base_value: int, buying: bool) -> int:
        c = self.game.character
        merc = c.skill("mercantile")
        pers = c.attrs.get("personality", 40)
        factor = 1.0 - (merc + (pers - 40)) / 300.0
        if buying:
            return max(1, int(base_value * (2.0 - factor)))
        return max(1, int(base_value * factor * 0.8))

    # -- persistence --------------------------------------------------------
    _last_persist = 0.0

    def persist(self, force: bool = False) -> None:
        # Mirror clock + full character into the KV store so a mid-play save
        # captures them. The character is a JSON blob, so throttle it to ~1 Hz
        # rather than dumping every frame.
        import time as _t
        c = self.clock
        self.store.set("_clock_hour", c.hour)
        self.store.set("_clock_day", c.day)
        now = _t.monotonic()
        if force or (now - self._last_persist) >= 1.0:
            self._last_persist = now
            self.game.save_to_store()

    def restore(self) -> None:
        hour = self.store.get("_clock_hour", None)
        day = self.store.get("_clock_day", None)
        if hour not in (None, "false"):
            try:
                self.clock.hour = float(hour) % 24.0
            except Exception:
                pass
        if day not in (None, "false"):
            try:
                self.clock.day = int(float(day))
            except Exception:
                pass
        if self.game.load_from_store():
            self.needs_char_creation = False
            self._sync_engine_health(full=True)
