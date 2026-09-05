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
from itertools import chain as _chain
from typing import Dict, List, Optional

from .rpg import factions
from .rpg import schedule as sched
from .rpg import combat as rpg_combat
from .rpg import equipment as eq
from .rpg import items as rpg_items
from .rpg import magic as rpg_magic
from .rpg import guilds
from .rpg import quests as _quests
from .rpg.gametime import GameClock
from .rpg.dialogue import DialogueRunner
from .rpg import inventory as inv
from .rpg.game_state import GameState
from .diceroll_anim import SHAKE_DURATION, ROLL_DURATION, FADE_DURATION

_current_session = None

DECISION_INTERVAL = 0.4
NPC_WALK_SPEED = 90.0
ARRIVE_RADIUS = 48.0
#: How close the player must be to talk. Comfortably larger than a billboard so
#: walking up to an NPC (whose speech bubble is showing) and pressing E works.
TALK_RADIUS = 140.0
#: How near a talkable NPC must be for its speech bubble to appear. Kept a short
#: step beyond the interaction range so a bubble means "you are close enough to
#: talk", rather than floating over every NPC across the settlement — the cue
#: should only show when the player is genuinely near a character with dialogue.
BUBBLE_RADIUS = 190.0
DEFEND_SIGHT = 700.0
#: A follow_player companion tries to stay within this distance of the
#: player when it isn't fighting (see _follow_player_dest / _decide).
FOLLOW_DISTANCE = 220.0
#: How far a companion will look for a target the *player* just struck
#: before joining in (see _provoke's follower-alert pass).
FOLLOW_ASSIST_RADIUS = 900.0
#: A bounty below this value can be resolved by paying gold instead of serving jail time.
BOUNTY_FINE_THRESHOLD = 1000
#: Guards notice a wanted player when the player enters this radius.
BOUNTY_NOTICE_RADIUS = 700.0
#: Maximum distance the player may get from the escort guard before resisting arrest.
ESCORT_BREAKAWAY_DISTANCE = 320.0
#: Nearby guards who join the pursuit after an escort escape.
GUARD_PURSUIT_RADIUS = 1200.0
#: A surrendered player is considered delivered when close to the prison marker.
PRISON_ARRIVE_RADIUS = 96.0
PRISON_MARKER_NAME = "prison"
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
# Melee is close-quarters and forgives a wider stance than ranged aiming —
# ~106 degrees full cone vs the ~67 degrees ranged weapons get.
MELEE_AIM_DOT = 0.30

DICE_ANIMATION_SHAKE = SHAKE_DURATION
DICE_ANIMATION_ROLL = ROLL_DURATION
DICE_ANIMATION_FADE = FADE_DURATION
DICE_DISPLAY_DURATION = DICE_ANIMATION_SHAKE + DICE_ANIMATION_ROLL + DICE_ANIMATION_FADE + 1.0
DICE_TYPES = ("d4", "d6", "d8", "d10", "d12", "d20")

#: Wisp companion light — how far it may wander from the player, and its four
#: possible hues (RGB 0-255). One is picked at cast time and never changes.
WISP_LEASH = 150.0
WISP_COLOURS = [
    [220, 235, 255],   # cool white
    [150, 190, 255],   # light blue
    [250, 240, 170],   # pale yellow
    [255, 180, 215],   # pink
]


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
        #: Spell ids the map author grants the player at creation (Game Settings
        #: → "Player Spells"). Accepts a list or a comma-separated string.
        _ps = cfg.get("player_spells", [])
        if isinstance(_ps, str):
            _ps = [s.strip() for s in _ps.split(",") if s.strip()]
        self._player_start_spells = list(_ps) if isinstance(_ps, list) else []
        self.region_name = str(cfg.get("region_name", "The Vale of Miniwind"))
        self.store = StateStore(globals_store, str(cfg.get("state_store", "miniwind")))

        self.rng = random.Random()
        self.game = GameState(self.store, rng=self.rng)
        self.needs_char_creation = str(cfg.get("start_scenario", "prompt")) == "prompt"

        # Register quests. Precedence (later wins): built-ins < legacy map quests
        # < external .quest files. Quests now live as human-readable .quest files
        # in the project's quests/ folder (game.rpg.quest_files); any list still
        # authored on an old GameSettings entity is honoured first for backward
        # compatibility, then the folder overrides it.
        from .rpg import quests as _quests
        from .rpg import quest_files
        map_quests = cfg.get("quests")
        if isinstance(map_quests, list):
            _quests.load_definitions(map_quests)
        try:
            file_defs = quest_files.load_quest_defs()
            if file_defs:
                _quests.load_definitions(file_defs)
        except Exception:
            pass

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

        #: PERF: per-tick the runtime used to scan the whole ``logic.things``
        #: list ~8 times (pickups, spellbooks, triggers, locations, arrest,
        #: reap, movement, attack-anim), each time re-normalising every thing's
        #: type string. Instead we build one normalised type -> [things] index
        #: and reuse it, rebuilding only when the things list actually changes
        #: (membership add/remove changes its length; a whole-list swap changes
        #: its identity — both are caught by the cheap ``(id, len)`` token).
        self._type_index: Dict[str, list] = {}
        self._type_index_token = None

        # transient UI state (driven by plugin/input, read by overlays)
        self.interact_prompt = ""       # e.g. "Press E to talk to Thalen"
        self.dialogue: Optional[DialogueRunner] = None
        self.dialogue_npc = None
        self.dialogue_options = []      # for merchant/persuade extra options
        self.container_thing = None     # the world Container the player has open
        self.open_screen = None         # None | 'inventory' | 'character' | 'journal' | 'spells' | 'charcreate' | 'map' | 'levelup' | 'container'
        self.notifications: List[Dict] = []   # timed toast messages
        self.floaters: List[Dict] = []         # floating combat text
        self._blocking = False
        self._player_flash = 0.0               # red-flash timer when hurt
        self.merchant_npc = None
        #: Active arrest flow: one guard approaches, escorts, or starts pursuit.
        self._arrest_guard = None
        self._arrest_state = ""
        self._arrest_notice_sent = False
        #: Active Wisp companion light, or None. See _spawn_wisp / _update_wisp.
        self._wisp = None
        self.dice_type_index = len(DICE_TYPES) - 1
        self.dice_animation: Optional[Dict] = None
        self.game.add_roll_listener(self._on_dice_roll)
        self._attack_anim_time = 0.0   # player stab animation remaining (seconds)

    def _visualise_dice_rolls_enabled(self) -> bool:
        """Read the live editor setting controlling automatic dice visuals."""
        try:
            config = getattr(self.logic, "editor_config", None)
            if config is None:
                editor_state = getattr(self.logic, "editor_state", None)
                config = getattr(editor_state, "config", None)
            if config is None:
                return False
            return config.getboolean("GAME", "visualise_dice_rolls", fallback=False)
        except (AttributeError, TypeError, ValueError):
            return False

    def _on_dice_roll(self, result: Dict, _source: str, _context: Dict) -> None:
        """Start the HUD presentation for every roll when visualisation is enabled."""
        if not self._visualise_dice_rolls_enabled():
            return
        self.dice_animation = {
            "result": result,
            "elapsed": 0.0,
            "duration": DICE_DISPLAY_DURATION,
        }
        return

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
        self.game.add_roll_listener(self._on_dice_roll)
        self._bind_dice_service()
        self.needs_char_creation = True
        self.open_screen = "charcreate"
        self.dialogue = None
        self.dialogue_npc = None
        self.merchant_npc = None
        self.show_loadout = False
        self._remove_wisp()
        self.notifications = []
        self.floaters = []
        self.dice_animation = None
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
    def _bind_dice_service(self) -> None:
        """Expose this session's dice service to the engine I/O manager."""
        io_manager = getattr(self.logic, "io_manager", None)
        if io_manager is not None:
            try:
                io_manager.set_dice_roller(self.game.dice)
            except AttributeError:
                pass

    def install(self) -> None:
        """Attach the RPG to the logic thread (damage filter, faction model)."""
        global _current_session
        _current_session = self
        logic = self.logic
        logic._player_damage_filter = self._mitigate_incoming
        # Teach the engine's team-aware MonsterAI MiniWind's faction relationships
        # so wild animals stay neutral to villagers while bandits are hostile to
        # both — instead of "every different team is an enemy".
        logic._faction_hostile = factions.is_hostile
        self._bind_dice_service()
        self.spawn_creature_points()   # materialise CreatureSpawn points once
        self._wire_quest_givers()      # make quest givers offer their quests
        self._sync_engine_health(full=True)

    def uninstall(self) -> None:
        global _current_session
        _current_session = None
        self._remove_wisp()
        io_manager = getattr(self.logic, "io_manager", None)
        if io_manager is not None:
            try:
                io_manager.set_dice_roller(None)
            except AttributeError:
                pass
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
        if final > 0:
            self._player_flash = HIT_FLASH_TIME   # brief red flash on the head
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
                            gender="male", custom_class=None, head="") -> None:
        self.game = GameState.new_game(self.store, name, race_id, class_id,
                                       birthsign_id, gender, custom_class, self.rng,
                                       head=head)
        self.game.add_roll_listener(self._on_dice_roll)
        self._bind_dice_service()
        # Author-granted starting spells (Game Settings → Player Spells).
        c = self.game.character
        for sid in self._player_start_spells:
            if rpg_magic.get(sid) and sid not in c.known_spells:
                c.known_spells.append(sid)
        if c.known_spells and not c.active_spell:
            c.active_spell = c.known_spells[0]
        # Record the chosen head so NPCs never reuse it (and force the player
        # billboard to it).
        if c.head:
            try:
                self.store.set("player_head", c.head)
            except Exception:
                pass
            self._apply_player_head(c.head)
        # Give every NPC/creature a head that is never the player's.
        self._assign_npc_heads()
        self.needs_char_creation = False
        self.open_screen = None
        self._sync_engine_health(full=True)
        self.notify(f"Welcome to {self.region_name}, {name}.", 5.0)

    def _assign_npc_heads(self) -> None:
        """Give every NPC/creature a head sprite.

        A head explicitly set in the editor is always respected — regular head,
        special guard head, or any browsed PNG under assets/sprites/heads/. Only
        when no head was set (the '(random)' option, i.e. an empty/invalid head)
        is one assigned automatically:

        * an NPC whose name contains "guard" gets a random *guard* head
          (guard01…guard06), matching the editor's guard-head option;
        * everyone else gets a random regular head that is never the player's.
        """
        from .rpg import heads
        player_head = str(getattr(self.game.character, "head", "") or "")
        things = getattr(self.logic, "things", None) or []
        changed = False
        for t in things:
            p = getattr(t, "properties", None)
            if not isinstance(p, dict):
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
                continue
            cur = str(p.get("head", "") or "")
            # Always respect a head explicitly set in the editor (regular, guard,
            # or browsed). Only roll a random head when none was set.
            if heads.is_any_head(cur):
                head = cur
            elif heads.name_is_guard(p.get("name") or p.get("display_name")):
                head = heads.random_guard_head(self.rng)
            else:
                head = heads.random_head(self.rng, exclude={player_head})
            path = heads.any_head_path(head)
            if p.get("head") != head or p.get("custom_idle") != path:
                p["head"] = head
                p["custom_idle"] = path
                p["custom_shoot"] = path
                p.pop("custom_dead", None)   # no custom death sprite (removed)
                changed = True
        if changed:
            try:
                from editor.things import Monster
                Monster.clear_sprite_cache()
            except Exception:
                pass
            self._rebuild_entity_caches()

    def _apply_player_head(self, head_id) -> None:
        """Force the player's overhead sprite to the chosen head image."""
        try:
            from .rpg import heads
            path = heads.head_path(head_id)
            # The viewport reads this to point its overhead sprite renderer at
            # the head (a single static frame, no animation).
            setattr(self.logic, "player_head_sprite", path)
        except Exception:
            pass

    # ================================================================= tick
    def tick(self, delta: float) -> None:
        self.clock.advance(delta)
        self.game.tick(delta)
        if self._attack_cooldown > 0:
            self._attack_cooldown -= delta
        if self._cast_cooldown > 0:
            self._cast_cooldown -= delta
        if self._player_flash > 0:
            self._player_flash = max(0.0, self._player_flash - delta)

        # Bounty enforcement runs independently of normal NPC schedules so a guard
        # can approach, arrest, escort, or pursue the player immediately.
        self._update_arrest()

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

        # world placeables: item pickups, spellbooks and quest triggers
        self._tick_pickups()
        self._tick_spellbooks()
        self._tick_triggers()
        self._tick_locations()
        self._tick_quests()

        # Decay player stab animation
        if self._attack_anim_time > 0:
            self._attack_anim_time = max(0.0, self._attack_anim_time - delta)

        # Detect NPC/creature attacks by watching the engine's is_shooting flag.
        # When it flips from False -> True we start a 0.2 s stab animation.
        # PERF: iterate only the actor buckets (npc/creature/monster) from the
        # cached type index instead of scanning + normalising the whole scene.
        buckets = self._type_buckets()
        for t in _chain(buckets.get("npc", ()), buckets.get("creature", ()),
                        buckets.get("monster", ())):
            tp = t.properties
            was = tp.get("_was_shooting", False)
            now = tp.get("is_shooting", False)
            if now and not was:
                tp["_attack_anim"] = 0.2
            if tp.get("_attack_anim", 0.0) > 0:
                tp["_attack_anim"] = max(0.0, tp["_attack_anim"] - delta)
            tp["_was_shooting"] = now

        # keep the engine's health pool in step with the character
        self._sync_engine_health()

        # the wandering Wisp companion light
        self._update_wisp(delta)

        # age transient UI
        self._age_lists(delta)

    # ------------------------------------------------------------------ wisp
    def _spawn_wisp(self, spell) -> None:
        """Conjure a fairy-light companion that flits about the player. Only one
        exists at a time; its colour is chosen once here and never changes."""
        try:
            from editor.things import Light
        except Exception:
            self.notify("A wisp flickers, then fades")
            return
        self._remove_wisp()
        ppos = self._player_pos()
        if ppos is None:
            return
        colour = list(self.rng.choice(WISP_COLOURS))
        light = Light(pos=[ppos[0] + 40.0, ppos[1] + 90.0, ppos[2] + 40.0],
                      properties={
                          "colour": colour,
                          "intensity": 1.3,
                          "radius": 360.0,
                          "state": "on",
                          "casts_shadows": False,
                          "hidden_in_game": False,
                          "_wisp": True,
                      })
        try:
            self.logic.things.append(light)
            self._rebuild_entity_caches()
        except Exception:
            return
        dur = 120.0
        for e in (spell.effects or []):
            if e.get("kind") == "wisp":
                dur = float(e.get("duration", 120) or 120)
        # target = the point the wisp is drifting toward; retimer picks a new one.
        self._wisp = {"light": light, "colour": colour, "life": dur,
                      "tx": ppos[0], "tz": ppos[2], "retarget": 0.0, "t": 0.0}
        self.notify("A wisp appears at your side")

    def _update_wisp(self, delta: float) -> None:
        w = self._wisp
        if not w:
            return
        w["life"] -= delta
        c = self.game.character
        ppos = self._player_pos()
        if w["life"] <= 0.0 or ppos is None or c.is_dead:
            self._remove_wisp()
            return
        light = w["light"]
        # Occasionally choose a new wander target — a random point near the
        # player — so the wisp drifts about rather than tracking rigidly.
        w["retarget"] -= delta
        if w["retarget"] <= 0.0:
            ang = self.rng.uniform(0.0, 2.0 * math.pi)
            rad = self.rng.uniform(30.0, WISP_LEASH * 0.75)
            w["tx"] = ppos[0] + math.cos(ang) * rad
            w["tz"] = ppos[2] + math.sin(ang) * rad
            w["retarget"] = self.rng.uniform(0.8, 2.2)
        # Ease toward the target; keep a gentle vertical bob.
        pos = light.pos
        ease = min(1.0, delta * 2.2)
        pos[0] += (w["tx"] - pos[0]) * ease
        pos[2] += (w["tz"] - pos[2]) * ease
        w["t"] += delta
        pos[1] = ppos[1] + 90.0 + math.sin(w["t"] * 2.0) * 18.0
        # Hard leash: never let it stray beyond WISP_LEASH of the player.
        dx, dz = pos[0] - ppos[0], pos[2] - ppos[2]
        dist = math.hypot(dx, dz)
        if dist > WISP_LEASH and dist > 1e-3:
            k = WISP_LEASH / dist
            pos[0] = ppos[0] + dx * k
            pos[2] = ppos[2] + dz * k
            w["retarget"] = 0.0   # pick a fresh inward target next tick

    def _remove_wisp(self) -> None:
        w = self._wisp
        self._wisp = None
        if not w:
            return
        light = w.get("light")
        try:
            things = getattr(self.logic, "things", None)
            if things is not None and light in things:
                things.remove(light)
                self._rebuild_entity_caches()
        except Exception:
            pass

    def _rebuild_entity_caches(self) -> None:
        rebuild = getattr(self.logic, "_build_entity_caches", None)
        if callable(rebuild):
            try:
                rebuild()
            except Exception:
                pass
        # Force the type index to rebuild on next use — the scene membership
        # just changed (spawn/despawn). The (id,len) token catches this too,
        # but invalidating here keeps it correct even for a same-length swap.
        self._type_index_token = None

    # ---------------------------------------------------------- world placeables
    def _rebuild_type_index(self, things) -> None:
        """(Re)build the normalised-type -> [things] index in scene order."""
        idx: Dict[str, list] = {}
        for x in things:
            tt = str(x.properties.get("type", "")).replace("_", "").lower()
            bucket = idx.get(tt)
            if bucket is None:
                idx[tt] = [x]
            else:
                bucket.append(x)
        self._type_index = idx
        self._type_index_token = (id(things), len(things))

    def _type_buckets(self) -> Dict[str, list]:
        """Return the current normalised-type index, rebuilding it only when the
        things list has changed (see the token comment in __init__)."""
        things = getattr(self.logic, "things", None) or ()
        if (id(things), len(things)) != self._type_index_token:
            self._rebuild_type_index(things)
        return self._type_index

    def _things_of_type(self, type_name):
        # Returns the cached bucket (scene order preserved). Callers only read
        # it; the list must not be mutated in place.
        tt = type_name.replace("_", "").lower()
        return self._type_buckets().get(tt, ())

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

    def _tick_spellbooks(self) -> None:
        """Reading a world Spellbook (walking over it) teaches its spell."""
        ppos = self._player_pos()
        if ppos is None:
            return
        c = self.game.character
        for bk in self._things_of_type("spellbook"):
            p = bk.properties
            if p.get("dead"):
                continue
            if self._dist2d(ppos, bk.pos) > float(p.get("pickup_radius", 70.0)):
                continue
            spell_id = str(p.get("spell", "") or "")
            spell = rpg_magic.get(spell_id)
            title = p.get("title") or (spell.name if spell else spell_id)
            if spell is None:
                self.notify("The book's script is unreadable")
            elif spell_id in c.known_spells:
                self.notify(f"You already know {spell.name}")
            else:
                c.known_spells.append(spell_id)
                if not c.active_spell:
                    c.active_spell = spell_id
                self.notify(f"Learned {spell.name} from {title}")
            if not p.get("respawn"):
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

    # ---- discoverable locations & quest objectives -----------------------
    def _tick_locations(self) -> None:
        """Announce a place the first time the player walks into its marker.

        A *location* Marker (``marker_kind == 'location'``) carries a place name
        and a discovery radius; entering it once shows 'Location X discovered'
        and records ``visited.<location>`` so a quest 'visit' objective can use
        it. Locations also drive the quest compass (nearest active target)."""
        ppos = self._player_pos()
        if ppos is None:
            return
        for mk in self._things_of_type("marker"):
            p = mk.properties
            if str(p.get("marker_kind", "")).lower() != "location":
                continue
            name = str(p.get("place_name") or p.get("name") or "").strip()
            if not name or p.get("_discovered"):
                continue
            if self._dist2d(ppos, mk.pos) <= float(p.get("discover_radius", 200.0)):
                p["_discovered"] = True
                self.store.set(f"visited.{self._slug(name)}", "1")
                self.notify(f"{name} discovered", 4.0)

    @staticmethod
    def _slug(text) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_"
                       for ch in str(text)).strip("_")

    @staticmethod
    def _thing_id(thing) -> str:
        """The entity's stable UUID (``properties['id']``), or ``''``."""
        p = getattr(thing, "properties", None)
        if isinstance(p, dict) and p.get("id"):
            return str(p.get("id"))
        return str(getattr(thing, "id", "") or "")

    def _wire_quest_givers(self) -> None:
        """Make every quest's giver actually offer that quest in play.

        This is the *easy way to assign a quest to a giver*: a quest names its
        ``giver`` — an NPC's stable **entity id (UUID)**, or its name, display
        name or role — and, at play start, the matching NPC in the scene
        automatically gains a dialogue branch that offers and starts the quest.
        Matching by id is unambiguous (two NPCs can share the name "Guard"), so
        it is preferred where the author picked a specific entity; the readable
        name/role matching still works for hand-written quests. No manual
        dialogue editing is needed — which is what previously left quest givers
        un-talkable and quests impossible to accept. Idempotent (a giver that
        already offers a quest is untouched), so an author who *did* wire
        dialogue by hand keeps their version.
        """
        from .rpg import quests as _quests
        # Two lookups: by slugged name/display/role, and by exact entity id.
        givers_by_key: Dict[str, list] = {}
        givers_by_id: Dict[str, list] = {}
        for quest in _quests.QUESTS.values():
            g = str(getattr(quest, "giver", "") or "").strip()
            if not g:
                continue
            # The giver string may be an id or a name/role; register it under
            # both so whichever the scene matches resolves the quest.
            givers_by_key.setdefault(self._slug(g), []).append(quest)
            givers_by_id.setdefault(g.lower(), []).append(quest)
        if not givers_by_key and not givers_by_id:
            return
        for npc in self.npcs():
            p = npc.properties
            keys = {self._slug(p.get("name", "")),
                    self._slug(p.get("display_name", "")),
                    self._slug(p.get("npc_role", ""))}
            keys.discard("")
            matches = []
            for key in keys:
                matches.extend(givers_by_key.get(key, []))
            npc_id = self._thing_id(npc).lower()
            if npc_id:
                matches.extend(givers_by_id.get(npc_id, []))
            seen = set()
            for quest in matches:
                if quest.id in seen:
                    continue
                seen.add(quest.id)
                dlg = p.get("dialogue")
                dlg, _changed = _quests.offer_dialogue_branch(
                    dlg if isinstance(dlg, dict) else None,
                    quest.id, quest.name, quest.desc)
                p["dialogue"] = dlg

    def record_talk(self, npc) -> None:
        """Note that the player has spoken with *npc* (for quest 'talk' aims).

        Records the NPC's name, display name and role, and also its entity id,
        so a 'talk' objective whose target was assigned by id (UUID) completes
        the same as one assigned by name."""
        p = getattr(npc, "properties", {}) or {}
        for field in ("name", "display_name", "npc_role"):
            v = str(p.get(field, "") or "").strip()
            if v:
                self.store.set(f"talked.{self._slug(v)}", "1")
        npc_id = self._thing_id(npc)
        if npc_id:
            self.store.set(f"talked.{self._slug(npc_id)}", "1")

    def record_kill(self, target) -> None:
        """Bump per-identity kill counters (for quest 'kill' objectives)."""
        p = getattr(target, "properties", {}) or {}
        for field in ("name", "npc_role", "monster_type"):
            v = str(p.get(field, "") or "").strip()
            if not v:
                continue
            key = f"kills.{self._slug(v)}"
            try:
                n = int(self.store.get(key, "0"))
            except (TypeError, ValueError):
                n = 0
            self.store.set(key, n + 1)

    def _condition_met(self, stage, qid: Optional[str] = None) -> bool:
        """True when *stage*'s completion condition is satisfied right now."""
        kind = stage.condition_kind()
        if kind == _quests.COND_NONE:
            return False
        target = self._slug(stage.condition_target())
        if kind == _quests.COND_ROLL:
            if not qid:
                return False
            saved = self.game.quests.last_roll(qid)
            try:
                saved_stage = int(saved.get("stage", -1)) if saved else -1
            except (TypeError, ValueError):
                return False
            if not saved or saved_stage != self.game.quests.stage_of(qid):
                return False
            result = saved.get("result") or {}
            if str(result.get("dice_notation", "")).strip() != stage.condition_notation():
                return False
            threshold = stage.condition_target_value()
            if threshold is None:
                return bool(result.get("success", False))
            try:
                return int(result.get("roll_result", 0)) >= threshold
            except (TypeError, ValueError):
                return False
        if not target:
            return False
        count = stage.condition_count()
        if kind == _quests.COND_FETCH:
            raw = str(stage.condition_target()).strip()
            return inv.has_item(self.game.character.inventory, raw, count)
        if kind == _quests.COND_TALK:
            return str(self.store.get(f"talked.{target}", "")) in ("1", "true")
        if kind == _quests.COND_VISIT:
            return str(self.store.get(f"visited.{target}", "")) in ("1", "true")
        if kind == _quests.COND_KILL:
            try:
                return int(self.store.get(f"kills.{target}", "0")) >= count
            except (TypeError, ValueError):
                return False
        return False

    def quest_arrow_target(self):
        """World position the quest compass arrow should point at, or None.

        Resolves the *first active quest*'s current-stage objective to a world
        position (see :meth:`_objective_world_pos`). Returns ``(pos,
        quest_name)`` or ``None``."""
        active = self.game.quests.active_quests()
        if not active:
            return None
        q = active[0]
        pos = self._objective_world_pos(q)
        if pos is None:
            return None
        return (list(pos), q.name)

    def _objective_world_pos(self, q):
        """World position of *q*'s current-stage objective, or None.

        Resolves the objective to the named location marker (visit), the named
        NPC (talk), the nearest matching foe (kill) or the nearest matching item
        pickup (fetch). ``roll``/``none`` objectives have no world target."""
        log = self.game.quests
        st = q.stage(log.stage_of(q.id))
        if st is None:
            return None
        kind = st.condition_kind()
        target = self._slug(st.condition_target())
        if kind == _quests.COND_NONE or not target:
            return None
        pos = None
        if kind == _quests.COND_VISIT:
            for mk in self._things_of_type("marker"):
                nm = mk.properties.get("place_name") or mk.properties.get("name") or ""
                if self._slug(nm) == target:
                    pos = mk.pos
                    break
        elif kind == _quests.COND_TALK:
            for npc in self.npcs():
                p = npc.properties
                if target in (self._slug(p.get("name", "")),
                              self._slug(p.get("display_name", "")),
                              self._slug(p.get("npc_role", "")),
                              self._slug(self._thing_id(npc))):
                    pos = npc.pos
                    break
        elif kind == _quests.COND_KILL:
            pos = self._nearest_matching_pos(target)
        elif kind == _quests.COND_FETCH:
            raw = self._slug(st.condition_target())
            best = None
            ppos = self._player_pos()
            for it in self._things_of_type("itempickup"):
                if it.properties.get("dead"):
                    continue
                if self._slug(it.properties.get("item_id", "")) == raw:
                    if ppos is None:
                        pos = it.pos
                        break
                    d = self._dist2d(ppos, it.pos)
                    if best is None or d < best:
                        best, pos = d, it.pos
        return list(pos) if pos is not None else None

    def quest_guidance(self, q=None):
        """A plain-language summary of how to complete a quest's current stage.

        Used by the quest panel (Q) and the on-screen quest arrow so the player
        can see *what* to do, *how far* the objective is and *which way* to go.
        Defaults to the first active quest. Returns a dict, or ``None`` when
        there is no active quest::

            {"quest": Quest, "name", "objective", "detail",
             "action",           # short imperative, e.g. "Defeat 5 wolves"
             "progress",         # "2 / 5" or "" when not countable
             "target_pos",       # [x,y,z] or None (roll/return objectives)
             "distance",         # world units to target, or None
             "complete": bool}
        """
        log = self.game.quests
        if q is None:
            active = log.active_quests()
            if not active:
                return None
            q = active[0]
        st = q.stage(log.stage_of(q.id))
        objective = st.objective if st else ""
        detail = st.journal if st else q.desc
        complete = log.is_complete(q.id)
        action, progress = self._objective_action(st) if st else ("", "")
        target_pos = None if complete else self._objective_world_pos(q)
        distance = None
        if target_pos is not None:
            ppos = self._player_pos()
            if ppos is not None:
                distance = self._dist2d(ppos, target_pos)
        return {
            "quest": q,
            "name": q.name,
            "objective": objective,
            "detail": detail,
            "action": action,
            "progress": progress,
            "target_pos": target_pos,
            "distance": distance,
            "complete": complete,
        }

    def _objective_action(self, st):
        """Build a short imperative + progress string from a stage's condition.

        Falls back to the authored objective text for objectives with no
        machine-readable condition (roll checks, or 'return to giver' stages)."""
        kind = st.condition_kind()
        target = st.condition_target()
        tslug = self._slug(target)
        count = st.condition_count()
        name = self._objective_target_name(kind, tslug, target)
        if kind == _quests.COND_KILL:
            have = self._safe_int(self.store.get(f"kills.{tslug}", "0"))
            plural = name if count == 1 else self._pluralise(name)
            return (f"Defeat {count} {plural}", f"{min(have, count)} / {count}")
        if kind == _quests.COND_FETCH:
            from .rpg import inventory as inv
            have = inv.quantity(self.game.character.inventory, target)
            return (f"Gather {count}× {name}", f"{min(have, count)} / {count}")
        if kind == _quests.COND_TALK:
            return (f"Speak with {name}", "")
        if kind == _quests.COND_VISIT:
            return (f"Travel to {name}", "")
        if kind == _quests.COND_ROLL:
            note = st.condition_notation()
            thr = st.condition_target_value()
            tail = f" (need {thr}+)" if thr is not None else ""
            return (f"Pass a {note} check{tail}", "")
        # No structured condition — lean on the authored objective line.
        return (st.objective or "Return to the quest giver", "")

    def _objective_target_name(self, kind, tslug, raw):
        """Best display name for an objective target (NPC/marker/foe/item)."""
        if kind in (_quests.COND_TALK, _quests.COND_KILL):
            for t in getattr(self.logic, "things", None) or []:
                p = getattr(t, "properties", {}) or {}
                if tslug in (self._slug(p.get("name", "")),
                             self._slug(p.get("display_name", "")),
                             self._slug(p.get("npc_role", "")),
                             self._slug(p.get("monster_type", ""))):
                    return (p.get("display_name") or p.get("name")
                            or p.get("npc_role") or p.get("monster_type")
                            or str(raw))
        if kind == _quests.COND_VISIT:
            for mk in self._things_of_type("marker"):
                nm = mk.properties.get("place_name") or mk.properties.get("name") or ""
                if self._slug(nm) == tslug:
                    return nm
        # Fall back to a de-slugged, title-cased version of the raw target.
        return str(raw).replace("_", " ").strip() or "the objective"

    @staticmethod
    def _pluralise(word):
        w = str(word)
        if not w:
            return w
        if w.endswith(("s", "x", "z", "ch", "sh")):
            return w + "es"
        if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
            return w[:-1] + "ies"
        return w + "s"

    @staticmethod
    def _safe_int(v, default=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _nearest_matching_pos(self, target_slug):
        """Nearest alive actor whose type/role/name matches *target_slug*."""
        ppos = self._player_pos()
        best, best_pos = None, None
        for t in getattr(self.logic, "things", None) or []:
            p = t.properties
            if p.get("dead"):
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
                continue
            if target_slug not in (self._slug(p.get("name", "")),
                                   self._slug(p.get("npc_role", "")),
                                   self._slug(p.get("monster_type", ""))):
                continue
            if ppos is None:
                return list(t.pos)
            d = self._dist2d(ppos, t.pos)
            if best is None or d < best:
                best, best_pos = d, list(t.pos)
        return best_pos

    def _next_stage_index(self, q, cur: int):
        """The index of the stage after *cur*, or None if *cur* is the last."""
        for s in sorted(q.stages, key=lambda s: s.index):
            if s.index > cur:
                return s.index
        return None

    def _tick_quests(self) -> None:
        """Auto-advance any active quest whose current stage's condition is met.

        Meeting a stage's condition moves the quest to the next stage; if that
        stage (or the current one, when it is the last) *finishes* the quest,
        rewards are granted through the game so gold/items/rep are paid out."""
        log = self.game.quests
        for q in list(log.active_quests()):
            cur = log.stage_of(q.id)
            st = q.stage(cur)
            if st is None or st.condition_kind() == _quests.COND_NONE:
                continue
            if not self._condition_met(st, q.id):
                continue
            nxt = self._next_stage_index(q, cur)
            nxt_stage = q.stage(nxt) if nxt is not None else None
            finishing = (nxt is None) or (nxt_stage is not None and nxt_stage.finishes) \
                or st.finishes
            if finishing:
                # Grant rewards while still active, then move the journal pointer.
                self.game.complete_quest(q.id)
                if nxt is not None:
                    log.set_stage(q.id, nxt)
                self.notify(f"Quest complete: {q.name}", 5.0)
            elif nxt is not None:
                log.set_stage(q.id, nxt)
                obj = log.current_objective(q.id)
                self.notify(f"{q.name}: {obj}" if obj else f"{q.name} updated", 4.0)

    @property
    def selected_dice_type(self) -> str:
        """Return the die type selected for the next keyboard roll."""
        return DICE_TYPES[self.dice_type_index]

    def cycle_dice_type(self) -> str:
        """Advance the keyboard dice selector and announce the new die type."""
        self.dice_type_index = (self.dice_type_index + 1) % len(DICE_TYPES)
        selected = self.selected_dice_type
        self.notify(f"Selected {selected}", 1.5)
        return selected

    def request_roll(self, dice_notation: str, target: Optional[int] = None,
                     event: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Request a gameplay roll from the session's shared dice service."""
        return self.game.roll_for_event(dice_notation, target=target,
                                         event=event, context=context)

    def roll_dice(self, dice_notation: Optional[str] = None) -> Dict:
        """Roll dice and start the native HUD shake/roll/fade presentation."""
        notation = dice_notation or f"1{self.selected_dice_type}"
        result = self.game.roll_dice(notation)
        self.dice_animation = {
            "result": result,
            "elapsed": 0.0,
            "duration": DICE_DISPLAY_DURATION,
        }
        return result

    def _tick_dice_animation(self, delta: float) -> None:
        """Advance and expire the transient dice presentation."""
        if self.dice_animation is None:
            return
        self.dice_animation["elapsed"] += max(0.0, float(delta))
        if self.dice_animation["elapsed"] >= self.dice_animation["duration"]:
            self.dice_animation = None

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
        self._tick_dice_animation(delta)

    def notify(self, text, seconds=3.0):
        self.notifications.append({"text": text, "t": seconds})
        if len(self.notifications) > 6:
            self.notifications = self.notifications[-6:]

    def add_floater(self, text, kind="dmg"):
        self.floaters.append({"text": text, "t": 1.2, "y": 0.0, "kind": kind})

    # ============================================================= NPC AI
    def npcs(self) -> List:
        # PERF: iterate the cached "npc" bucket instead of scanning + string-
        # normalising the whole scene; only the live (not-dead) ones are returned.
        return [t for t in self._things_of_type("npc")
                if not t.properties.get("dead", False)]

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
        # PERF: only NPCs matter here — walk the cached "npc" bucket instead of
        # re-scanning + normalising every thing in the scene each tick.
        for t in self._things_of_type("npc"):
            tp = t.properties
            if not tp.get("dead"):
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

    def _is_arrest_guard(self, thing) -> bool:
        """Return whether *thing* is a living, non-hostile guard available for arrest duty."""
        if thing is None:
            return False
        p = getattr(thing, "properties", {})
        return (self._is_guard(thing) and not p.get("dead")
                and str(p.get("aggression", "")) != "hostile")

    def _prison_position(self):
        """Resolve the authored prison marker, or fall back to the guard post."""
        prison = self._find_named(PRISON_MARKER_NAME)
        if prison is not None:
            return list(prison.pos)
        post = self._nearest_of(self._arrest_guard, lambda t:
                                self._marker_kind(t) == "guardpost") \
            if self._arrest_guard is not None else None
        return list(post.pos) if post is not None else None

    def _update_arrest(self) -> None:
        """Drive bounty detection, guard approach, escort delivery, and escape."""
        player_pos = self._player_pos()
        if player_pos is None or self.game.character.is_dead:
            return

        # Resolve prison marker once; bail out if the map has none.
        prison_pos = None
        for mk in self._things_of_type("marker"):
            if str(mk.properties.get("marker_kind", "")).lower() == "prison":
                prison_pos = mk.pos
                break
        if prison_pos is None:
            # No prison on this map — clear any stale arrest state and skip.
            if self._arrest_state:
                self._clear_arrest()
            return

        guard = self._arrest_guard
        state = self._arrest_state
        if state == "escorting":
            if not self._is_arrest_guard(guard):
                self._start_arrest_pursuit()
                return
            distance = self._dist2d(guard.pos, player_pos)
            if distance > ESCORT_BREAKAWAY_DISTANCE:
                self._start_arrest_pursuit()
                return
            prison_distance = self._dist2d(guard.pos, prison_pos)
            if prison_distance <= PRISON_ARRIVE_RADIUS:
                if self._dist2d(player_pos, prison_pos) <= PRISON_ARRIVE_RADIUS:
                    self._complete_escort(prison_pos)
                else:
                    self._start_arrest_pursuit()
            return

        bounty = int(getattr(self.game.character, "bounty", 0) or 0)
        if bounty <= 0:
            if state:
                self._clear_arrest()
            return

        if state in ("approach", "ready") and self._is_arrest_guard(guard):
            if state == "approach" and self._dist2d(guard.pos, player_pos) <= TALK_RADIUS:
                self._arrest_state = "ready"
                guard.properties["_arrest_state"] = "ready"
                guard.properties.pop("_dest", None)
                self.notify("The guard stops you: you are wanted for a crime.", 4.0)
                player = getattr(self.logic, "player", None)
                if player is not None:
                    self.start_dialogue(guard, player)
            return

        self._arrest_guard = None
        self._arrest_state = ""
        candidates = []
        radius2 = BOUNTY_NOTICE_RADIUS * BOUNTY_NOTICE_RADIUS
        for candidate in self.npcs():
            if not self._is_arrest_guard(candidate):
                continue
            dx = candidate.pos[0] - player_pos[0]
            dz = candidate.pos[2] - player_pos[2]
            d = dx * dx + dz * dz
            if d <= radius2:
                candidates.append((d, candidate))
        if candidates:
            _, guard = min(candidates, key=lambda item: item[0])
            self._arrest_guard = guard
            self._arrest_state = "approach"
            guard.properties["_arrest_state"] = "approach"
            guard.properties["triggered"] = True
            guard.properties["awake"]

    def nearest_arrest_guard(self, player_pos, radius: float = TALK_RADIUS):
        """Return the guard currently waiting to discuss the player's arrest."""
        guard = self._arrest_guard
        if self._arrest_state != "ready" or not self._is_arrest_guard(guard):
            return None
        if self._dist2d(guard.pos, player_pos) <= radius:
            return guard
        return None

    def _arrest_tree(self, guard):
        """Build the short guard conversation for the current bounty."""
        bounty = max(1, int(self.game.character.bounty))
        name = guard.properties.get("display_name", "Guard")
        if bounty < BOUNTY_FINE_THRESHOLD:
            responses = []
            if self.game.character.gold >= bounty:
                responses.append({
                    "text": f"Pay the {bounty} gold fine.",
                    "goto": "END",
                    "actions": [{"op": "pay_bounty"}],
                })
            else:
                responses.append({
                    "text": "I cannot pay. Take me to prison.",
                    "goto": "END",
                    "actions": [{"op": "begin_escort"}],
                })
            responses.extend([
                {"text": "I surrender. Take me to prison.", "goto": "END",
                 "actions": [{"op": "begin_escort"}]},
                {"text": "I refuse and run.", "goto": "END",
                 "actions": [{"op": "resist_arrest"}]},
            ])
        else:
            responses = [
                {"text": "I surrender. Take me to prison.", "goto": "END",
                 "actions": [{"op": "begin_escort"}]},
                {"text": "I refuse and run.", "goto": "END",
                 "actions": [{"op": "resist_arrest"}]},
            ]
        return {
            "start": "arrest",
            "nodes": {
                "arrest": {
                    "text": f"{name}: You have an outstanding bounty of {bounty} gold. "
                            "Surrender and answer for your crimes.",
                    "responses": responses,
                },
            },
        }

    def _clear_arrest(self) -> None:
        """Release the arrest guard back to normal settlement AI."""
        guard = self._arrest_guard
        if guard is not None:
            p = guard.properties
            p.pop("_arrest_state", None)
            p.pop("_dest", None)
            if str(p.get("aggression", "")) != "hostile":
                p["triggered"] = True
                p["awake"] = False
        self._arrest_guard = None
        self._arrest_state = ""
        self._arrest_notice_sent = False

    def _pay_bounty(self) -> None:
        """Pay a low bounty in gold and end the arrest."""
        amount = max(1, int(self.game.character.bounty))
        if self.game.character.gold < amount:
            self.notify("You cannot afford the fine. You will be escorted to prison.")
            self._begin_escort()
            return
        self.game.add_gold(-amount)
        self.game.character.bounty = 0
        self.notify(f"You paid the {amount} gold fine.", 4.0)
        self._clear_arrest()

    def _begin_escort(self) -> None:
        """Put the active guard into the authored prison escort state."""
        guard = self._arrest_guard
        if not self._is_arrest_guard(guard):
            return
        if self._prison_position() is None:
            self.notify("No prison marker is placed in this settlement.")
            return
        self._arrest_state = "escorting"
        guard.properties["_arrest_state"] = "escorting"
        guard.properties["triggered"] = True
        guard.properties["awake"] = False
        guard.properties["sched_state"] = "ESCORT"
        self.notify("You are being escorted to prison. Stay with the guard.", 5.0)

    def _start_arrest_pursuit(self) -> None:
        """Make nearby guards hostile when the player breaks away from an escort."""
        player_pos = self._player_pos()
        if player_pos is None:
            return
        radius2 = GUARD_PURSUIT_RADIUS * GUARD_PURSUIT_RADIUS
        for guard in self.npcs():
            if not self._is_guard(guard) or guard.properties.get("dead"):
                continue
            dx = guard.pos[0] - player_pos[0]
            dz = guard.pos[2] - player_pos[2]
            if dx * dx + dz * dz > radius2:
                continue
            p = guard.properties
            p.pop("_arrest_state", None)
            p.pop("_dest", None)
            p["aggression"] = "hostile"
            p["triggered"] = False
            p["awake"] = True
            p["wake_on_sight"] = True
        self._arrest_guard = None
        self._arrest_state = ""
        self._arrest_notice_sent = False
        self.notify("You broke away from the escort. The guards attack!", 5.0)

    def _complete_escort(self, prison_pos) -> None:
        """Deliver a player who stayed with the guard to the prison marker."""
        player = getattr(self.logic, "player", None)
        if player is not None:
            try:
                player.pos.x = float(prison_pos[0])
                player.pos.y = float(prison_pos[1])
                player.pos.z = float(prison_pos[2])
            except Exception:
                pass
        self.game.character.bounty = 0
        self.notify("You have been escorted to prison. Your bounty is cleared.", 5.0)
        self._clear_arrest()

    def _decide(self, npc) -> None:
        p = npc.properties

        # Arrest movement is owned by the runtime, not the normal schedule or
        # MonsterAI. The guard remains visible and walks to the player/prison.
        arrest_state = p.get("_arrest_state")
        if arrest_state in ("approach", "ready", "escorting"):
            p["triggered"] = True
            p["awake"] = False
            p["sched_state"] = ("ARREST_APPROACH" if arrest_state == "approach"
                                  else "ARREST_READY" if arrest_state == "ready"
                                  else "ESCORT")
            if arrest_state == "approach":
                player_pos = self._player_pos()
                if player_pos is not None:
                    p["_dest"] = player_pos
            elif arrest_state == "ready":
                p.pop("_dest", None)
            else:
                prison_pos = self._prison_position()
                if prison_pos is not None:
                    p["_dest"] = prison_pos
            return

        # (a) FACTION + COMBAT CAPABILITY: an actively hostile combatant is the
        #     engine MonsterAI's job (it is live), so leave it be.
        if str(p.get("aggression")) == "hostile" and not p.get("triggered", False):
            p["sched_state"] = sched.COMBAT
            return

        combatant = self._is_combatant(npc)

        # (b) A defending combatant (e.g. a guard) un-parks into the core AI when
        #     a faction-hostile enemy is near, and re-parks to its post after.
        if combatant:
            try:
                defend_sight = max(DEFEND_SIGHT, float(
                    p.get("sight_range", DEFEND_SIGHT)))
            except (TypeError, ValueError):
                defend_sight = DEFEND_SIGHT
            enemy = self._nearest_hostile(npc, defend_sight)
            if enemy is not None:
                # Give the core MonsterAI the exact intruder found by the
                # settlement scan. This avoids waiting for a second perception
                # pass and makes a returning bandit immediately actionable.
                p["_aggro_target"] = id(enemy)
                p["triggered"] = False
                p["awake"] = True
                p["sched_state"] = sched.COMBAT
                p.pop("_flee", None)
                return
            elif p.get("sched_state") == sched.COMBAT:
                p.pop("_aggro_target", None)
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

        # (b.5) COMPANION FOLLOW: nothing more urgent above claimed this tick
        #     (not arrested, not itself hostile, no nearby enemy to defend
        #     against/flee from) — a follow_player NPC walks to keep pace
        #     with the player instead of running its normal schedule. This is
        #     deliberately placed *after* the combat/flee returns above so a
        #     fight or flight response always wins, and *before* the normal
        #     schedule evaluation below so it isn't overridden by e.g. a
        #     work/home schedule entry.
        if p.get("follow_player", False):
            self._follow_player_dest(npc)
            return

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

    def _follow_player_dest(self, npc) -> None:
        """Set (or clear) a follow_player companion's destination so it keeps
        pace with the player. Called from _decide once combat/flee checks
        for this tick have already run and found nothing to react to.

        Walks to just inside its leash (``follow_distance``) rather than
        exactly onto the player's position, so a companion settles beside
        the player instead of jostling for the same spot.
        """
        p = npc.properties
        p["sched_state"] = sched.FOLLOW
        ppos = self._player_pos()
        if ppos is None:
            p.pop("_dest", None)
            return
        leash = float(p.get("follow_distance", FOLLOW_DISTANCE))
        dx = ppos[0] - npc.pos[0]
        dz = ppos[2] - npc.pos[2]
        dist = math.hypot(dx, dz)
        if dist <= leash:
            p.pop("_dest", None)
            return
        ux, uz = dx / dist, dz / dist
        stop_at = leash * 0.6
        p["_dest"] = [ppos[0] - ux * stop_at, npc.pos[1], ppos[2] - uz * stop_at]

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
        # PERF: walk only the actor buckets from the cached type index.
        buckets = self._type_buckets()
        for t in _chain(buckets.get("npc", ()), buckets.get("creature", ()),
                        buckets.get("monster", ())):
            tp = t.properties
            if tp.get("hidden"):
                continue
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
        # Track a facing heading (engine convention: forward at 0 is +z) so the
        # overhead view can rotate this actor's head to face where it walks.
        p["angle"] = math.atan2(dx, dz)

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

    def _acquire_target(self, reach: float, aim_dot: float = AIM_DOT):
        """Nearest attackable creature within *reach* and the frontal cone.

        Deliberately ground-plane only: distance and facing are both computed
        from (x, z) alone. Camera pitch (looking up/down) never enters this
        check, so tilting the view can't affect who is targetable.
        """
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
            # frontal cone (horizontal only — see docstring)
            dot = (fwd[0] * dx + fwd[2] * dz) / dist
            if dot < aim_dot:
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
        self._attack_anim_time = 0.2   # quick forward stab, independent of cooldown
        if c.stamina < 4:
            self.notify("Too exhausted to attack")
            return False

        if kind == rpg_items.KIND_BOW:
            # A bow looses a real, physical arrow (see
            # _spawn_player_arrow_projectile) rather than resolving instantly —
            # it flies, can miss by sailing past a moving target, gets stopped
            # by walls, and lands (and its damage is rolled) only once it
            # actually strikes something.
            target = self._acquire_target(reach, aim_dot=AIM_DOT)
            if not self.game.fire_arrow():
                return False   # out of arrows — fire_arrow already notified
            self._spawn_player_arrow_projectile(target)
            return True

        # Melee gets a more forgiving cone than ranged weapons: close-quarters
        # aiming is fiddly (especially while adjusting camera pitch), so being
        # near an enemy and roughly facing them should be enough to engage.
        target = self._acquire_target(reach, aim_dot=MELEE_AIM_DOT)
        if target is None:
            # a swing at nothing still trains the weapon a touch (and costs stamina)
            c.spend_stamina(4.0)
            return True
        # Target acquisition already confirmed "near + facing" on the ground
        # plane, so a melee swing is guaranteed to connect — no separate miss
        # roll to be foiled by camera pitch or anything else.
        res = self.game.attack_creature(target.properties, guaranteed=True)
        if res.get("hit"):
            tag = "sneak" if res.get("sneak") else ("crit" if res.get("crit") else "dmg")
            self.add_floater(f"-{int(res['damage'])}", kind=tag)
            self._provoke(target)
            if res.get("killed"):
                self._on_creature_killed(target)
        else:
            self.add_floater("miss", kind="miss")
        return True

    def _spawn_player_arrow_projectile(self, target=None) -> None:
        """Loose a physical arrow toward *target* (or straight ahead if none
        was locked on). Travels and collides through the same engine
        projectile pipeline a spell bolt uses, but — unlike a spell bolt —
        embeds where it lands (``embeds=True``) and resolves its own RPG
        damage on impact via an ``on_hit`` callback instead of a flat number
        baked in at fire time, so the roll happens at the moment of the
        actual physical hit."""
        lt = self.logic
        ppos = self._player_pos()
        if lt is None or ppos is None:
            return
        try:
            from engine.monster_constants import (
                ARROW_SPEED, ARROW_MAX_DIST, ARROW_SPRITE_SIZE)
        except Exception:
            ARROW_SPEED, ARROW_MAX_DIST, ARROW_SPRITE_SIZE = 1600.0, 3000.0, (40.0, 40.0)

        start = [ppos[0], ppos[1] + 48.0, ppos[2]]
        if target is not None:
            tp = target.pos
            aim = (float(tp[0]), float(tp[1]) + 64.0, float(tp[2]))
        else:
            fwd = self._player_forward()
            aim = (start[0] + fwd[0] * 1500.0, start[1], start[2] + fwd[2] * 1500.0)

        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        dlen = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        vel = [dx / dlen * ARROW_SPEED, dy / dlen * ARROW_SPEED, dz / dlen * ARROW_SPEED]

        game = self.game

        def _on_hit(hit_monster):
            res = game.resolve_arrow_hit(hit_monster.properties)
            if res.get("hit"):
                tag = "sneak" if res.get("sneak") else ("crit" if res.get("crit") else "dmg")
                self.add_floater(f"-{int(res['damage'])}", kind=tag)
                self._provoke(hit_monster)
                if res.get("killed"):
                    self._on_creature_killed(hit_monster)
            else:
                self.add_floater("miss", kind="miss")

        proj = {
            "pos": list(start),
            "vel": vel,
            "owner_id": id(getattr(lt, "player", None)),
            "owner_is_player": True,
            "sprite": "assets/sprites/monsters/arrow.png",
            "lifetime": ARROW_MAX_DIST / ARROW_SPEED,
            "damage": 0,   # unused for player arrows — on_hit resolves real damage
            "size": ARROW_SPRITE_SIZE,
            "color": [214, 175, 105],   # warm wood/fletching tint
            "distance_travelled": 0.0,
            "max_dist": ARROW_MAX_DIST,
            "kind": "arrow",
            "embeds": True,
            "on_hit": _on_hit,
        }
        if not hasattr(lt, "_monster_projectiles"):
            lt._monster_projectiles = []
        lt._monster_projectiles.append(proj)

    def _staff_attack(self, w) -> bool:
        """Channel a staff's bound spell (called from do_attack for KIND_STAFF)."""
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
        # Resurrection is special: it targets a *fallen* character, drains all
        # magicka and can be worked only once per in-game day.
        if spell is not None and any(e.get("kind") == "resurrect"
                                     for e in (spell.effects or [])):
            return self._do_resurrect(spell)
        res = self.game.cast_active_spell()
        if not res.cast:
            if res.reason == "not enough magicka":
                self.notify("Not enough magicka")
            elif res.reason == "fizzle":
                roll = res.roll or {}
                if roll:
                    self.notify(
                        f"{spell.name if spell else 'Spell'} fizzles: "
                        f"rolled {roll.get('roll_result', '?')} "
                        f"(need {roll.get('target', '?')} or higher)")
                else:
                    self.notify("The spell fizzles")
            return False
        if spell is None:
            return True
        # A "wisp" effect conjures the wandering companion light (a SELF spell).
        if any(e.get("kind") == "wisp" for e in (spell.effects or [])):
            self._spawn_wisp(spell)
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

    def _resurrect_day(self) -> int:
        """The current in-game day (for the once-per-day resurrection limit)."""
        try:
            return int(getattr(self.game.clock, "day", 0))
        except Exception:
            return 0

    def _nearest_dead_actor(self, reach: float):
        """The nearest slain (revivable) NPC/creature within *reach*.

        A gibbed body is destroyed — blown apart or disintegrated — so it is
        never a resurrection target."""
        ppos = self._player_pos()
        if ppos is None:
            return None
        best, best_d = None, reach
        for t in getattr(self.logic, "things", None) or []:
            tp = t.properties
            if not tp.get("dead"):
                continue
            if tp.get("gibbed"):
                continue          # gibbed corpses cannot be resurrected
            ttype = str(tp.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
                continue
            d = self._dist2d(ppos, t.pos)
            if d < best_d:
                best_d = d
                best = t
        return best

    def _do_resurrect(self, spell) -> bool:
        """Cast Resurrection: revive the nearest fallen character.

        Special rules (not the normal cast pipeline): it drains ALL of the
        caster's magicka and may be worked only once per in-game day."""
        c = self.game.character
        # Once per day.
        today = self._resurrect_day()
        try:
            last = int(self.store.get("resurrect.last_day", "-1"))
        except (TypeError, ValueError):
            last = -1
        if last == today:
            self.notify("You cannot resurrect again today")
            return False
        if c.magicka < 1.0:
            self.notify("Not enough magicka to resurrect")
            return False
        target = self._nearest_dead_actor(BOW_REACH)
        if target is None:
            self.notify("No fallen soul is close enough to resurrect")
            return False
        # Drain all magicka and spend the day's single casting.
        c.magicka = 0.0
        self.store.set("resurrect.last_day", today)
        c.use_skill(spell.school, 1.0 + spell.base_cost / 40.0)
        if not self._revive_actor(target):
            # Defensive: _nearest_dead_actor already skips gibbed bodies.
            self.notify("The body is too destroyed to resurrect")
            return False
        name = target.properties.get("name") or target.properties.get("npc_role") \
            or target.properties.get("monster_type") or "The fallen"
        self.notify(f"{name} rises again!")
        self.add_floater("RAISED", kind="heal")
        return True

    def _revive_actor(self, thing) -> bool:
        """Bring a slain actor back to life: clear death flags, restore health
        and its living (head) sprite, and rebuild the engine caches.

        A gibbed body (blown apart / disintegrated) cannot be revived — the flag
        is never cleared and the actor stays dead. Returns whether it revived."""
        p = thing.properties
        if p.get("gibbed"):
            return False
        p["dead"] = False
        p["hidden"] = False
        p["is_shooting"] = False
        try:
            mh = float(p.get("max_health", p.get("health", 100)) or 100)
        except (TypeError, ValueError):
            mh = 100.0
        p["health"] = mh
        # Living sprite follows the head again (custom_idle set at spawn/authoring).
        try:
            from editor.things import Monster
            Monster.clear_sprite_cache()
        except Exception:
            pass
        self._rebuild_entity_caches()
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
        c = self.game.character
        armed = bool(eq.equipped_id(c, "weapon")) or bool(c.active_spell)
        attacking = (getattr(self, "_attack_anim_time", 0.0) > 0.0
                     or getattr(self, "_cast_cooldown", 0.0) > 0.05)
        return armed, attacking

    def on_actor_attack(self, actor) -> None:
        """Explicit hook for the engine to call when any actor begins an attack."""
        p = getattr(actor, "properties", None)
        if p is not None:
            p["_attack_anim"] = 0.2

    def get_actor_attack_anim(self, actor):
        """Return (is_attacking, progress) for any actor.
        
        progress is 0.0 at rest, rises to 1.0 at full thrust, then falls back
        to 0.0 — a single quick stab. The overhead renderer should sample this
        every frame to offset the weapon sprite forward from the head.
        """
        # Player
        player = getattr(self.logic, "player", None)
        if actor is player:
            t = getattr(self, "_attack_anim_time", 0.0)
            if t > 0:
                prog = 1.0 - (t / 0.2)
                # 0.0 -> 1.0 in first half of window, 1.0 -> 0.0 in second half
                if prog < 0.5:
                    return True, prog * 2.0
                else:
                    return True, 2.0 - prog * 2.0
            return False, 0.0

        # NPC / creature
        p = getattr(actor, "properties", {})
        t = p.get("_attack_anim", 0.0)
        if t > 0:
            prog = 1.0 - (t / 0.2)
            if prog < 0.5:
                return True, prog * 2.0
            else:
                return True, 2.0 - prog * 2.0
        return False, 0.0


    def get_actor_weapon_draw_info(self, actor):
        """
        For a given actor (NPC/Creature), find the first weapon in its inventory
        and return (sprite_path, is_attacking, thrust_progress).
        Returns (None, False, 0.0) if no weapon.
        """
        # Get the inventory list; for players, we could handle separately, but we focus on NPCs/creatures.
        inv = actor.properties.get("inventory", [])
        if not inv:
            return None, False, 0.0

        # Resolve the first weapon
        from .rpg import items as rpg_items
        import os

        for stack in inv:
            item_id = stack.get("id")
            if not item_id:
                continue
            item_def = rpg_items.get(item_id)
            if not item_def:
                continue
            # Check if it's a weapon
            if item_def.category != rpg_items.WEAPON:
                continue
            kind = item_def.get("kind", "melee")
            kind_to_filename = {
                "melee": "sword.png",
                "bow": "bow.png",
                "staff": "staff.png",
            }
            filename = kind_to_filename.get(kind)
            if not filename:
                continue
            # Build absolute path
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, "assets", "sprites", "items", filename)
            # Check attack state for this actor
            is_attacking, progress = self.get_actor_attack_anim(actor)
            return path, is_attacking, progress
        return None, False, 0.0

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
        """A struck NPC turns hostile and fights back, and any nearby
        follow_player companion joins in against that same target."""
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
        self._alert_followers(target)

    def _alert_followers(self, target) -> None:
        """Un-park every follow_player companion near the player and send it
        after *target* — the same thing the player just struck.

        Reuses the exact hand-off the settlement defend logic already uses
        (``_aggro_target`` + ``triggered=False`` + ``awake=True``) to give
        the engine MonsterAI's live combat/movement to the companion, so
        chasing and attacking *target* needs no new engine-side code. The
        companion re-parks itself the usual way once ``target`` is dead or
        out of range (see the combatant branch in ``_decide``) — which is
        why a follower should generally also be authored ``combatant=True``.
        """
        if target.properties.get("dead", False):
            return
        ppos = self._player_pos()
        if ppos is None:
            return
        target_id = id(target)
        for npc in self.npcs():
            p = npc.properties
            if npc is target or not p.get("follow_player", False):
                continue
            if self._dist2d(ppos, npc.pos) > FOLLOW_ASSIST_RADIUS:
                continue
            p["_aggro_target"] = target_id
            p["triggered"] = False
            p["awake"] = True
            p["sched_state"] = sched.COMBAT
            p.pop("_flee", None)
            p.pop("_rally", None)

    def _on_creature_killed(self, target):
        self.add_floater("SLAIN", kind="kill")
        # Count the kill so a quest 'kill' objective can complete.
        self.record_kill(target)
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
        if (npc is self._arrest_guard and self._arrest_state == "ready"
                and int(self.game.character.bounty or 0) > 0):
            tree = self._arrest_tree(npc)
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
        # Note the conversation for any quest 'talk to X' objective.
        self.record_talk(npc)
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
        if op == "pay_bounty":
            self._pay_bounty()
        elif op == "begin_escort":
            self._begin_escort()
        elif op == "resist_arrest":
            self._start_arrest_pursuit()
        elif op == "open_trade":
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

    # -- containers ---------------------------------------------------------
    def nearest_container(self, player_pos, radius: float = TALK_RADIUS):
        """The nearest usable container within its own use radius."""
        best, best_d = None, None
        for c in self._things_of_type("container"):
            r = float(c.properties.get("use_radius", radius))
            d = self._dist2d(player_pos, c.pos)
            if d <= r and (best_d is None or d < best_d):
                best, best_d = c, d
        return best

    def open_container(self, thing) -> bool:
        """Open *thing*'s graphical inventory (a screen separate from the player)."""
        if thing is None:
            return False
        p = thing.properties
        inv_list = p.get("inventory")
        if not isinstance(inv_list, list):
            # Accept authored shorthand ("id:qty, ...") the spawner also accepts.
            inv_list = self._spawn_inventory(inv_list)
            p["inventory"] = inv_list
        self.container_thing = thing
        self.open_screen = "container"
        return True

    def container_inventory(self) -> list:
        t = self.container_thing
        if t is None:
            return []
        inv_list = t.properties.get("inventory")
        if not isinstance(inv_list, list):
            inv_list = []
            t.properties["inventory"] = inv_list
        return inv_list

    def container_name(self) -> str:
        t = self.container_thing
        if t is None:
            return "Container"
        return str(t.properties.get("display_name") or "Container")

    def take_from_container(self, index: int) -> bool:
        """Move one stack from the open container into the player's inventory."""
        items = self.container_inventory()
        if not (0 <= index < len(items)):
            return False
        stack = items.pop(index)
        inv.add_item(self.game.character.inventory, stack)
        self.notify(f"Took {stack.get('name', stack.get('id',''))}")
        return True

    def store_in_container(self, index: int) -> bool:
        """Move one stack from the player's inventory into the open container."""
        if self.container_thing is None:
            return False
        pinv = self.game.character.inventory
        if not (0 <= index < len(pinv)):
            return False
        stack = pinv.pop(index)
        self.container_inventory().append(stack)
        self.notify(f"Stored {stack.get('name', stack.get('id',''))}")
        return True

    def close_container(self) -> None:
        self.container_thing = None
        if self.open_screen == "container":
            self.open_screen = None

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
            # Re-apply the saved head so the player billboard matches on load.
            head = getattr(self.game.character, "head", "") or self.store.get("player_head", "")
            if head and head != "false":
                self._apply_player_head(head)
            self._assign_npc_heads()
