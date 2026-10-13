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

import collections
import contextlib
import json
import math
import os
import random
from itertools import chain as _chain
from typing import Dict, List, Optional

import numpy as np

from . import fio
from .facing import face_heading
from engine.change_journal import touch as _journal
from engine.spatial import (TIER_NEAR, TIER_ACTIVE, TIER_DISTANT,
                                TIER_DORMANT)
from .rpg import factions
from .rpg import gib
from .rpg import schedule as sched
from .rpg import combat as rpg_combat
from .rpg import equipment as eq
from .rpg import items as rpg_items
from . import warrior_fist
from . import held_weapons
from .rpg import magic as rpg_magic
from .rpg import guilds
from .rpg import disposition as disp
from .rpg import needs as rpg_needs
from .rpg import heads
from .rpg import charisma as rpg_cha
from .ui.arrows import arrow_sprite
from .rpg import daily as rpg_daily
from .rpg import quests as _quests
from .rpg.gametime import DEFAULT_MINUTES_PER_DAY, GameClock
from .world_index import WorldIndex
from . import sim
from .sim import appraisal as sim_appraisal
from .sim import crime as sim_crime
from .sim import knowledge as sim_knowledge
from .sim import ownership as sim_own
from .sim import production as sim_prod
from .sim.director import Director, PLAYER_KEY, actor_key
from .rpg.dialogue import DialogueRunner
from .rpg import inventory as inv
from .rpg.game_state import GameState
from .diceroll_anim import SHAKE_DURATION, ROLL_DURATION, FADE_DURATION
from . import npc_archery

_current_session = None

#: The editor's live settings (settings.ini), handed over by the editor
#: integration as the 3D view is built (game/integration.py). The logic thread
#: has no way back to the window, so this is how a session reads the GAME
#: settings; None outside the editor (tools, tests).
_editor_config = None


def set_editor_config(config) -> None:
    """Give sessions the editor's live settings (see :data:`_editor_config`)."""
    global _editor_config
    _editor_config = config

#: Below this many actors the vectorised index costs more to build than the
#: scalar scans it replaces, so the session leaves it unbuilt and every query
#: takes its scalar route. MiniWind's authored settlement sits under it; a
#: crowd, a streamed world or a spawner-fed map goes over.
WORLD_INDEX_MIN_ACTORS = 32

DECISION_INTERVAL = 0.4
#: When Big World's tiers are fitted to the overhead camera, ACTIVE means "off
#: screen": such an NPC decides on one decision pass in this many and moves on
#: one tick in this many, carrying the ticks it skipped.
OFFSCREEN_STRIDE = 4
#: The world's proximity checks (pickups, books, triggers, locations, quest
#: conditions) run this often rather than every tick.
PROXIMITY_INTERVAL = 0.1
NPC_WALK_SPEED = 90.0
#: How much quicker a frightened villager moves. Applied only while the NPC is
#: in the FLEE state, which the decision tick re-evaluates constantly and drops
#: as soon as no hostile is within FLEE_SIGHT — so the sprint lasts exactly as
#: long as the fright does, and they go back to a walk on their own.
FLEE_SPEED_MULTIPLIER = 2.0
ARRIVE_RADIUS = 48.0
#: How high an actor steps up onto a brush (a kerb, a floor, a low step);
#: anything taller over it is a roof or a wall, not its ground.
GROUND_STEP_UP = 24.0
#: Mouse-wheel zoom of the top-down camera: the nearest and furthest it goes
#: above the player (never above Big World's ceiling), how much one wheel
#: notch changes the height, and how quickly the camera eases there.
ZOOM_MIN_HEIGHT = 300.0
ZOOM_MAX_HEIGHT = 1600.0
ZOOM_STEP = 1.15
ZOOM_EASE_SECONDS = 0.12
#: Slack added to the zoomed-out view's ground reach when Big World is asked
#: to cover it.
ZOOM_REACH_MARGIN = 256.0
#: How far an actor moves across the ground before its height is worked out
#: again; standing still costs nothing.
GROUND_RECHECK_DIST = 4.0
#: How close a walking NPC may come to a wall. Close to the player's own half
#: width (TILE_SIZE/2 = 25) rather than the combat AI's much fatter monster
#: margin, so a villager fits through any doorway the player does.
NPC_WALL_MARGIN = 28.0
#: Ticks an NPC may spend jammed against a brush before it gives up on its
#: destination and lets the next decision pass choose a reachable one. About two
#: seconds at 30Hz — long enough to slide along a wall to a door, short enough
#: that nobody stands pressed into a corner for a whole day.
NPC_BLOCKED_GIVE_UP_TICKS = 60
#: How close the player must be to talk. Comfortably larger than a billboard so
#: walking up to an NPC (whose speech bubble is showing) and pressing E works.
TALK_RADIUS = 140.0
#: The inventory strip's width in slots, unless ``inventory_strip_size``
#: (console, saved as GAME/inventory_strip_size) says otherwise.
STRIP_DEFAULT_SIZE = 9
STRIP_MAX_SIZE = 30
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
#: How near a witness must stand to a guard to give their account (mirrors the
#: director's own TELL_RADIUS, which is what actually resolves the report).
REPORT_ARRIVE_RADIUS = 200.0
_RALLY_THRESHOLD = 0.5
_FLEE_THRESHOLD = -0.2
#: Seconds a struck actor flashes red (mirrors engine MONSTER_HIT_FLASH_TIME).
HIT_FLASH_TIME = 0.18
#: How far a melee swing reaches / a shot can pick a target.
MELEE_REACH = 170.0
BOW_REACH = 2400.0
#: Holding left mouse with a bow draws it: how long a full draw takes, and
#: how far an arrow flies loosed with the bow barely drawn and fully drawn.
BOW_FULL_DRAW_SECONDS = npc_archery.BOW_FULL_DRAW_SECONDS
BOW_MIN_RANGE = npc_archery.BOW_MIN_RANGE
BOW_MAX_RANGE = npc_archery.BOW_MAX_RANGE
#: How fast an arrow flies.
ARROW_SPEED = npc_archery.ARROW_SPEED
#: Frontal cone (dot threshold) for auto-target selection.
AIM_DOT = 0.55
# Melee is close-quarters and forgives a wider stance than ranged aiming —
# ~106 degrees full cone vs the ~67 degrees ranged weapons get.
MELEE_AIM_DOT = 0.30

#: Screens that deliberately refuse Escape (see game/ui/screens.py): character
#: creation walks back a step and then sits still, and the level-up screen makes
#: you choose. Escape inside them is *not* a way out, so whoever hosts the game
#: — the editor's play mode above all — must not hand Escape to the screen and
#: assume it will be consumed, or the player is trapped with no way to stop
#: playing. :meth:`MiniwindSession.escape_closes_modal` is that question.
ESCAPE_LOCKED_SCREENS = frozenset({"charcreate", "levelup"})

DICE_ANIMATION_SHAKE = SHAKE_DURATION
DICE_ANIMATION_ROLL = ROLL_DURATION
DICE_ANIMATION_FADE = FADE_DURATION
DICE_DISPLAY_DURATION = DICE_ANIMATION_SHAKE + DICE_ANIMATION_ROLL + DICE_ANIMATION_FADE + 1.0
DICE_TYPES = ("d4", "d6", "d8", "d10", "d12", "d20")

#: Probability an NPC/creature with no authored handedness is left-handed. Left
#: handedness is deliberately rare, so most actors wield on the right.
LEFT_HANDED_CHANCE = 0.2

#: A carried torch floats a warm dynamic light on its holder. Height above the
#: holder's feet, and the fallback light params a torch item may override.
TORCH_LIGHT_HEIGHT = 70.0
TORCH_DEFAULT_RADIUS = 380.0
TORCH_DEFAULT_INTENSITY = 1.5
TORCH_DEFAULT_COLOUR = [255, 170, 80]
#: How far a flame's brightness and reach waver around their base (fractions).
TORCH_FLICKER_INTENSITY = 0.18
TORCH_FLICKER_RADIUS = 0.06
#: Hostile factions whose members can be put off a fight by a repulsive
#: face, how near the player they must be to judge it, and for how many game
#: hours they stay put off.
REPEL_RADIUS = 520.0
REPEL_HOURS = 3.0
REPELLABLE_FACTIONS = frozenset({"bandits", "cultists"})
#: How long a quest's arrow target / guidance is reused before it is looked
#: up again (the HUD asks every frame).
QUEST_LOOKUP_SECONDS = 0.25
#: How long a guard's "!" shows when he reacts to something.
MARK_FLASH_SECONDS = 1.6
#: A brawler at or below this fraction of their health has had enough.
SUBDUE_FRACTION = 0.45
#: How long a spoken line hangs over a head, and how near the player it must
#: be said to be shown.
BARK_SECONDS = 3.0
BARK_RADIUS = 1800.0
STOP_SHOUTS = ("Stop right there!", "Halt! In the name of the law!",
               "You there! Stop!", "That's far enough, criminal.")
BREAK_UP_SHOUTS = ("Break it up!", "Oi! Enough of that!", "Stop this at once!",
                   "Hands off him!")
SUBDUED_SHOUTS = ("That's enough! Go home, the both of you.",
                  "Any more of that and it's the cells.", "Settle down. Now.")
CHARGE_SHOUTS = ("To arms!", "Raiders! With me!", "Not in my town!",
                 "Steel out, lads!")
#: How far inside the terrain's edge the player is stopped.
WORLD_EDGE_MARGIN = 900.0
#: How fast an over-encumbered player moves, as a fraction of normal.
ENCUMBERED_SPEED = 0.33
#: The light a spell bolt carries with it, in the spell's colour.
BOLT_LIGHT_RADIUS = 420.0
BOLT_LIGHT_INTENSITY = 2.2

#: Wisp companion light — how far it may wander from the player, and its four
#: possible hues (RGB 0-255). One is picked at cast time and never changes.
WISP_LEASH = 150.0
WISP_COLOURS = [
    [220, 235, 255],   # cool white
    [150, 190, 255],   # light blue
    [250, 240, 170],   # pale yellow
    [255, 180, 215],   # pink
]

# ---------------------------------------------------------------------------
# The reaper. One death in four is attended: Death fades in a little way off,
# walks over to the body, takes it with a stroke of his scythe and is gone
# again. He is pure spectacle — he damages nothing, cannot be attacked or
# talked to, is invisible to the simulation and leaves nothing behind. See
# _maybe_send_the_reaper.
# ---------------------------------------------------------------------------
#: How often a fallen NPC is visited at all: one death in eight.
REAPER_CHANCE = 1.0 / 8.0
#: He appears this far off -- beyond the edge of the overhead view -- on the
#: far side of the body from the player, and walks in.
REAPER_ARRIVE_DIST = (1150.0, 1400.0)
#: The most of him that is ever seen: he is never more than a shade.
REAPER_MAX_OPACITY = 0.7
#: Seconds to fade in on arrival, and to fade out on leaving.
REAPER_FADE_IN = 1.0
REAPER_FADE_OUT = 0.9
#: He glides — no pathfinding, no collision, no gravity.
REAPER_SPEED = 180.0
#: How close he comes before he swings.
REAPER_REACH = 70.0
#: The stroke of the scythe, and the very short pause after it before he goes.
REAPER_SWING = 0.5
REAPER_LINGER = (0.15, 0.8)
#: An approach that cannot finish (the body moved, or is walled off) gives up
#: and reaps from where it stands rather than gliding forever.
REAPER_APPROACH_TIMEOUT = 14.0
#: However bloody it gets, no more than this many at once.
REAPER_MAX = 3
#: His head and his weapon. He is drawn at the one head size, like everyone.
REAPER_HEAD = "reaper"
REAPER_WEAPON = "scythe"


_ARCHIVED_SOUNDS = None


def sound_available(name: str) -> bool:
    """Whether an interface sound *name* ships with the game: in any mounted
    ``assets/*.fiopak`` (sounds.fiopak, sounds2.fiopak, ...) or loose under
    ``assets/sounds``. (Checking only the loose folder silenced every
    interface sound once they were archived.)"""
    if os.path.isfile(os.path.join(SOUND_DIR, name)):
        return True
    if _ARCHIVED_SOUNDS is not None:          # pinned by a test
        return name in _ARCHIVED_SOUNDS
    from engine import asset_archives
    return asset_archives.in_archive(f"assets/sounds/{name}")


class _PlayerActor:
    """The player, wearing the same shape every other simulation actor has.

    :mod:`game.sim` reasons about anything with ``.pos`` and ``.properties``.
    Giving the player that shape is what lets an NPC witness the player, form a
    belief about the player, gossip about the player and appraise the player
    through exactly the same code paths it uses for a bandit — instead of the
    game carrying a parallel "what the player did" system.

    The properties dict is refreshed from the live character/session rather than
    copied once, so sneaking, the carried torch and the player's name are always
    current when perception asks.
    """

    def __init__(self, session):
        self._session = session
        self.properties = {"is_player": True, "faction": "player",
                           "team": "player", "display_name": "You",
                           "name": "player", "combatant": True, "courage": 1.0}

    @property
    def pos(self):
        return self._session._player_pos()

    def refresh(self):
        s = self._session
        p = self.properties
        try:
            char = s.game.character
            p["display_name"] = str(getattr(char, "name", "") or "You")
        except Exception:
            pass
        p["sneaking"] = bool(getattr(s.game, "sneaking", False))
        p["dead"] = bool(getattr(s.logic, "player_dead", False))
        return self


#: Where interface sounds live (the engine's sound folder), and the one a
#: purchase or sale makes.
SOUND_DIR = os.path.join("assets", "sounds")
TRANSACTION_SOUND = "transaction.mp3"
#: A guard stopping the player to arrest them says one of these, at random.
ARREST_SOUNDS = ("arrest1.mp3", "arrest2.mp3")

#: Marks an NPC can show above its head: "!" heightened (alarmed, startled,
#: coming for you), "?" puzzled (searching, unsure). game/ui/hud.py draws them.
HEAD_MARKS = ("!", "?")


class StateStore:
    """Adapter presenting a plugin ``GlobalStore`` as a string KV store."""

    def __init__(self, globals_store, store_name: str = "miniwind"):
        self._g = globals_store
        self._name = store_name
        # The registry Fio's GlobalStore reads, resolved once: the quest log,
        # the HUD and the dialogue read this store dozens of times a frame,
        # and GlobalStore.get looks the registry up (an import) on each.
        self._registry = None
        try:
            from plugins.api import GlobalStore
            if type(globals_store) is GlobalStore:
                self._registry = globals_store._registry()
        except Exception:
            self._registry = None

    def get(self, key, default="false"):
        if self._g is None:
            return default
        registry = self._registry
        if registry is not None:
            # GlobalStore.get, read straight from the registry it would use.
            data = registry.get(self._name)
            if data is None:
                return default
            key = str(key)
            if key not in data:
                return default
            value = data[key]
            if value is None or type(value) is str:
                return value
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
        mins_per_day = (float(cfg.get("minutes_per_day", DEFAULT_MINUTES_PER_DAY))
                        or DEFAULT_MINUTES_PER_DAY)
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
        #: Which map this is, for what it remembers (game/map_memory.py): the
        #: map's own settings entity, else its region's name.
        self._map_key = str(cfg.get("id") or cfg.get("region_name") or "")

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
        #: In-game day last seen by the tick, so a day rollover triggers the
        #: off-screen daily resolution (merchant restock, debts, mourning fade,
        #: harvest — see game.rpg.daily) exactly once per day.
        self._last_day = None
        self._attack_cooldown = 0.0
        #: The off hand's own swing timer, when dual wielding: each hand
        #: strikes on its own button and its own rhythm.
        self._offhand_cooldown = 0.0
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
        #: The full map was asked for (M, a quest's *Show on map*): "player"
        #: or (x, z, label); the host opens the pause menu's MAP page on it.
        self.map_request = None
        self.notifications: List[Dict] = []   # timed toast messages
        self.floaters: List[Dict] = []         # floating combat text
        self._blocking = False
        self._player_flash = 0.0               # red-flash timer when hurt
        self.merchant_npc = None
        #: Active arrest flow: one guard approaches, escorts, or starts pursuit.
        self._arrest_guard = None
        self._arrest_state = ""
        self._arrest_notice_sent = False
        #: Fights in progress, as (actor, who it is swinging at) pairs. Rebuilt
        #: once per decision pass by _refresh_actor_cache.
        self._fights = []
        #: The live watch, rebuilt alongside _actors. See _refresh_actor_cache.
        self._guards: List = []
        #: Markers grouped by their authored kind, rebuilt only when the scene
        #: changes. See _markers_of_kind.
        self._marker_kinds: Dict[str, list] = {}
        self._marker_kinds_token = None
        #: MiniWind's actor index (game/world_index.py), rebuilt at the top of
        #: every tick by _rebuild_world_index and resolved once per tick
        #: through _world_index. Fio decides relevance (Big World's _sim_tier
        #: stamps); this only snapshots positions/teams/liveness for queries.
        self.world_index = WorldIndex()
        self._wi_live = False
        self._wi_cache = None
        #: Alternates 0/1 each decision pass. TIER_ACTIVE NPCs decide on the
        #: pass matching their row parity, so half of the near world re-plans
        #: each pass and the cost is spread instead of spiking.
        self._decision_phase = 0
        self._offscreen_tick = 0
        #: id(actor) -> (x, z, y) where it was last stood on the ground.
        self._grounded = {}
        #: Routes round walls for every walker (game/navigation.py).
        from .navigation import Navigator
        self.nav = Navigator(self._blocked_by_wall)
        #: type name -> (bucket, len, frozenset of ids); see _type_ids.
        self._type_id_cache = {}
        #: The camera height the wheel asked for (None: never zoomed).
        self.zoom_height = None
        #: How far the bow is drawn (0..1) while left mouse is held, else
        #: None; the HUD draws it as a filling pie.
        self.bow_charge = None
        #: Right-mouse presses and releases from the view ("press", "release",
        #: "cancel"), handled on the logic thread by _update_bow_draw.
        self._bow_input = collections.deque()
        #: One-off effects (a fist's burst) and when each is cleared away.
        self._transient_effects = []
        #: Fio projectile tag -> sprite, for the arrows in flight: the game
        #: draws these itself, as arrows (see :meth:`_split_projectiles`).
        self._arrow_tags = {}
        #: Every NPC / creature archer mid-draw: they draw a bow by the
        #: player's own rules (game/npc_archery.py).
        self.archery = npc_archery.NpcArchery(self)
        from .held_weapons import HeldWeapons
        self.held = HeldWeapons(self)
        from .dragon_fire import DragonFire
        from .wildlife import Wildlife
        from .map_memory import MapMemory
        from .rewind import Rewind
        self.rewind = Rewind(self)
        self.memory = MapMemory(self)
        self.wildlife = Wildlife(self)
        self.dragon_fire = DragonFire(self)
        #: Spell bolts in flight that carry a light: Fio tag -> Light, and
        #: where each lit bolt was last published (tag -> (x, y, z)).
        self._bolt_lights = {}
        self._bolt_positions = {}
        #: ``((x, y, z), (vx, vy, vz), sprite)`` per arrow in flight, as last
        #: published for the renderer (read by game/ui/arrows.py).
        self.arrows_in_flight = ()
        self._proximity_accum = 0.0
        #: Guards currently running the player down (see _start_arrest_pursuit).
        self._arrest_pursuers = []
        #: NPCs given a mark above their head by set_head_mark: id -> npc.
        self._head_marked = {}
        #: Active Wisp companion light, or None. See _spawn_wisp / _update_wisp.
        self._wisp = None
        #: Reaper visits currently playing out, one per attended corpse. See
        #: _maybe_send_the_reaper / _update_reapers.
        self._reapers: List[Dict] = []
        #: Live torch lights, keyed by holder ("player" or an NPC's id): a
        #: dynamic Light that follows whoever carries a lit torch. See
        #: _update_torch_lights.
        self._torch_lights: Dict = {}
        self._torch_flicker_t = 0.0
        self.dice_type_index = len(DICE_TYPES) - 1
        self.dice_animation: Optional[Dict] = None
        self.game.add_roll_listener(self._on_dice_roll)
        self.game.add_xp_listener(self._on_xp)
        self._attack_anim_time = 0.0   # player stab animation remaining (seconds)
        self._offhand_anim_time = 0.0  # the off hand's, when dual wielding

        # ------------------------------------------------------------------
        # The reactive simulation (game.sim). Everything notable the player or
        # the world does is emitted here as a WorldEvent; the director runs
        # perception → knowledge → interpretation and hands back ranked intents
        # that _decide honours above the daily schedule. The session injects the
        # game's real faction matrix, opinion model and bounty purse so the sim
        # package itself stays engine- and rules-agnostic.
        self.director = Director(
            store=self.store, clock=self.clock, rng=self.rng,
            hostile=factions.is_hostile,
            disposition=self._sim_disposition,
            on_bounty=self._sim_on_bounty,
            on_message=self.game.message)
        #: Accumulated game-hours since the last simulation tick, so rumour
        #: propagation and production advance on world time rather than frames.
        self._sim_hours = 0.0
        self._sim_last_hour = float(self.clock.hour)
        #: The roads' population (game/living/world.py): travellers simulated
        #: as data far away and as actors near the player. Built at install.
        self.living = None

    def _editor_config(self):
        """The editor's live settings (settings.ini), or None without an editor."""
        return _editor_config

    def _visualise_dice_rolls_enabled(self) -> bool:
        """Read the live editor setting controlling automatic dice visuals."""
        try:
            config = self._editor_config()
            if config is None:
                return False
            return config.getboolean("GAME", "visualise_dice_rolls", fallback=False)
        except (AttributeError, TypeError, ValueError):
            return False

    def dialogue_heads_enabled(self) -> bool:
        """Whether to show the character head beside the conversation window
        (GAME → "Show dialogue heads"). Defaults to on when unset."""
        try:
            config = self._editor_config()
            if config is None:
                return True
            return config.getboolean("GAME", "show_dialogue_heads", fallback=True)
        except (AttributeError, TypeError, ValueError):
            return True

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
        self.game.add_xp_listener(self._on_xp)
        self.needs_char_creation = True
        self.open_screen = "charcreate"
        self.dialogue = None
        self.dialogue_npc = None
        self.merchant_npc = None
        self.show_loadout = False
        #: The inventory strip along the bottom of the screen
        #: (game/ui/inventory_strip.py): always up in free play. Kept for
        #: saves and tools that still ask.
        self.show_strip = True
        #: Its selected slot (a click or a number key picks it).
        self.strip_selected = 0
        self._remove_wisp()
        self._banish_reapers()
        self.notifications = []
        self.floaters = []
        self.dice_animation = None
        self._deaths_seen = set()
        # A new game means a world with no history and nobody who remembers
        # anything: the store wipe above already erased every actor's knowledge,
        # so only the in-memory event log and intent cache remain.
        self.director.bus.clear()
        self.director.invalidate()
        self._sim_hours = 0.0
        if self.logic is not None:
            try:
                fio.set_world_paused(self.logic, "miniwind.screen", True)
            except Exception:
                pass

    # -- difficulty scaling -------------------------------------------------
    @property
    def incoming_mult(self) -> float:
        return {"easy": 0.6, "normal": 1.0, "hard": 1.5}.get(self.difficulty, 1.0)

    # ================================================================= setup
    def install(self) -> None:
        """Attach the RPG to the logic thread (damage filter, faction model)."""
        global _current_session
        _current_session = self
        logic = self.logic
        logic._player_damage_filter = self._mitigate_incoming
        # Both mouse fire buttons are the engine's shooting: it queues the
        # press and hands it here, and the bow's arrows and the spell bolts
        # fly through its projectile pipeline.
        logic.player_fire_handler = self.fire_player_weapon
        # MiniWind has no jumping (Space still swims, in water).
        fio.set_jump_enabled(logic, False)
        # Arrows are drawn as arrows, by the game, not as Fio's projectile orb.
        fio.set_projectile_split(logic, self._split_projectiles)
        # Wound decals use MiniWind's gore art.
        try:
            logic.blood_stain_sprites = tuple(gib.stain_paths(magical=False))
        except Exception as exc:
            print(f"[MiniWind] blood stain art unavailable: {exc}")
        # Teach the engine's MonsterAI MiniWind's faction relationships and
        # who hunts the player (game/faction_ai.py), so wild animals stay
        # neutral to villagers while bandits are hostile to both, instead of
        # "every different team is an enemy, everyone hunts the player".
        from . import faction_ai
        faction_ai.install(logic)
        # Archers draw their bows over time, as the player does, rather than
        # the engine's instant hit-scan (game/npc_archery.py).
        from engine.monster_ai import MonsterAI
        MonsterAI.install_shot_hook(self.archery.shot_hook)
        # Chasers route round walls rather than pressing into them
        # (game/navigation.py); schedule walking uses the same routes.
        MonsterAI.install_steer_hook(self.nav.steer_many)
        self.memory.load(self._map_key)
        self.spawn_creature_points()   # materialise CreatureSpawn points once
        self.memory.apply()            # the dead stay dead; lairs refill after a day
        self._assign_npc_handedness()  # random handedness (left rare) where unset
        self._arm_fighters()           # a bow for the swordsman, a blade for the archer
        self.dragon_fire.install(fio.things(self.logic))
        self._assign_npc_stats()       # STRENGTH / ENDURANCE / CHARISMA for everyone
        self._wire_quest_givers()      # make quest givers offer their quests
        self._name_index()             # built now, not on the first quest's frame
        self._world_bounds = self._read_world_bounds()
        try:
            from .living.world import LivingWorld
            self.living = LivingWorld(self)
            if not self.living.build():
                self.living = None
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"[MiniWind] living world unavailable: {exc}")
            self.living = None
        self._sync_engine_health(full=True)

    def uninstall(self) -> None:
        global _current_session
        _current_session = None
        if self.living is not None:
            try:
                self.living.persist()
                self.living.shutdown()
            except Exception:
                pass
        self._remove_wisp()
        self._remove_all_torch_lights()
        self._bolt_positions = {}
        self._update_bolt_lights()          # no bolt is live: every light goes out
        if getattr(self.logic, "_player_damage_filter", None) is self._mitigate_incoming:
            self.logic._player_damage_filter = None
        if getattr(self.logic, "player_fire_handler", None) == self.fire_player_weapon:
            self.logic.player_fire_handler = None
        fio.set_jump_enabled(self.logic, True)
        fio.set_projectile_split(self.logic, None)
        try:
            from engine.monster_ai import MonsterAI
            MonsterAI.clear_steer_hook(self.nav.steer_many)
        except Exception:
            pass
        self.arrows_in_flight = ()
        from . import faction_ai
        faction_ai.uninstall(self.logic)
        from engine.monster_ai import MonsterAI
        MonsterAI.clear_shot_hook(self.archery.shot_hook)
        self.archery.clear()

    def _mitigate_incoming(self, raw_damage, damage_kind="physical") -> float:
        c = self.game.character
        if getattr(fio.player_runtime(self.logic), "god_mode", False):
            return 0.0
        res = rpg_combat.resolve_incoming(c, float(raw_damage) * self.incoming_mult,
                                          damage_kind=damage_kind,
                                          blocking=self._blocking, rng=self.rng)
        final = res["final"]
        # armour training whenever armour is tested -- a deflected blow too
        worn = res["armor_class"]
        if worn == "heavy":
            c.use_skill("heavy_armor", 1.0)
        elif worn == "light":
            c.use_skill("light_armor", 1.0)
        elif worn == "medium":
            c.use_skill("heavy_armor", 0.5)
            c.use_skill("light_armor", 0.5)
        if res.get("deflected"):
            self.add_floater("Deflected", kind="miss")
            return 0.0
        c.damage(final)
        if final > 0:
            self._player_flash = HIT_FLASH_TIME   # brief red flash on the head
        self.add_floater(f"-{int(round(final))}", kind="hurt")
        return final

    def _sync_engine_health(self, full=False) -> None:
        c = self.game.character
        try:
            fio.player_runtime(self.logic).player_max_health = int(round(c.max_health))
            if full:
                fio.player_runtime(self.logic).player_health = int(round(c.health))
            else:
                # character is authoritative; mirror into the engine pool
                fio.player_runtime(self.logic).player_health = int(round(max(0.0, c.health)))
        except Exception:
            pass

    # -- character creation result -----------------------------------------
    def begin_new_character(self, name, race_id, class_id, birthsign_id="none",
                            gender="male", custom_class=None, head="",
                            handed="right", rolls=None) -> None:
        self.game = GameState.new_game(self.store, name, race_id, class_id,
                                       birthsign_id, gender, custom_class, self.rng,
                                       head=head)
        if rolls:
            # STRENGTH, ENDURANCE and CHARISMA as the player rolled them.
            rpg_cha.apply_rolls(self.game.character, rolls)
        self.game.character.handed = "left" if str(handed).lower() == "left" else "right"
        self.game.add_roll_listener(self._on_dice_roll)
        self.game.add_xp_listener(self._on_xp)
        # Author-granted starting spells (Game Settings → Player Spells).
        c = self.game.character
        for sid in (self._player_start_spells if c.can_use_magic() else ()):
            if rpg_magic.get(sid) and sid not in c.known_spells:
                c.known_spells.append(sid)
        if c.known_spells and not c.active_spell:
            c.active_spell = c.known_spells[0]
        # A Warrior's fists are a weapon of their own, in quick slot 1.
        warrior_fist.ensure_fist(self)
        # The player is the chosen head; record it so NPCs never reuse it.
        self._ensure_player_head()
        # Give every NPC/creature a head that is never the player's.
        self._assign_npc_heads()
        self.needs_char_creation = False
        self.open_screen = None
        self._sync_engine_health(full=True)
        self.notify(f"Welcome to {self.region_name}, {name}.", 5.0)

    def _ensure_player_head(self) -> str:
        """Make sure the player is a head, and show it; returns the head id.

        Character creation always picks one, but a character without a valid
        head (an older save) is given a random regular head rather than being
        drawn as the stock player sprite. The head is recorded in the store and
        the player's overhead sprite pointed at it.
        """
        c = self.game.character
        head = str(getattr(c, "head", "") or "")
        if not heads.is_head(head):
            saved = str(self.store.get("player_head", "") or "")
            head = saved if heads.is_head(saved) else heads.random_head(self.rng)
            c.head = head
        try:
            self.store.set("player_head", head)
        except Exception:
            pass
        self._apply_player_head(head)
        return head

    def _assign_npc_heads(self) -> None:
        """Give every NPC/creature a head sprite — never the player's.

        A head explicitly set in the editor is respected — regular head,
        special guard head, or any browsed PNG under assets/sprites/heads/ —
        unless it is the player's head: no NPC ever wears that. A head is
        assigned when none was set (the '(random)' option, i.e. an
        empty/invalid head) or the set one is the player's:

        * an animal gets a head of its own kind (:func:`heads.animal_head`):
          its own image once drawn, the placeholder head until then;
        * an NPC whose name contains "guard" gets a random *guard* head
          (guard01…guard06), matching the editor's guard-head option;
        * everyone else gets a random regular head that is never the player's.
        """
        from .rpg import heads
        player_head = str(getattr(self.game.character, "head", "") or "")
        things = fio.things(self.logic)
        changed = False
        deck = {}           # animal heads are dealt, so a flock is mixed evenly
        for t in things:
            p = getattr(t, "properties", None)
            if not isinstance(p, dict):
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
                continue
            cur = str(p.get("head", "") or "")
            # Respect a head explicitly set in the editor (regular, guard, or
            # browsed) unless it is the player's. Otherwise roll one.
            role = str(p.get("npc_role", "") or "").lower()
            # An animal still on the stand-in (from a save made before its art
            # was drawn) looks again, so new art reaches it.
            stand_in = cur == heads.PLACEHOLDER_HEAD and role in heads.ANIMAL_ROLES
            if heads.is_any_head(cur) and cur != player_head and not stand_in:
                head = cur
            elif role in heads.ANIMAL_ROLES:
                head = heads.animal_head(role, self.rng, deck)
            elif heads.name_is_guard(p.get("name") or p.get("display_name")):
                head = heads.random_guard_head(self.rng)
            else:
                head = heads.random_head(self.rng, exclude={player_head})
            path = heads.any_head_path(head)
            size = heads.size_for(p, head)   # one size, bar giants and chickens
            if (p.get("head") != head or p.get("custom_idle") != path
                    or p.get("sprite_width") != size
                    or p.get("sprite_height") != size):
                p["head"] = head
                p["custom_idle"] = path
                p["custom_shoot"] = path
                p["sprite_width"] = p["sprite_height"] = size
                p.pop("custom_dead", None)   # no custom death sprite (removed)
                _journal(t)
                changed = True
        if changed:
            try:
                from editor.things import Monster
                Monster.clear_sprite_cache()
            except Exception:
                pass
            self._rebuild_entity_caches()

    def _assign_npc_stats(self) -> None:
        """Give every person in the world STRENGTH, ENDURANCE and CHARISMA.

        The same 3d6 the player rolls, seeded by name so a person always rolls
        the same, and leaning by trade (game.rpg.bios.ROLE_LEAN). They are
        ordinary properties -- ``strength`` / ``endurance`` / ``charisma``,
        3..18 -- so they save, show in the inspector, and are authorable. The
        first time they are given, they shape the body: Strength scales how
        hard the person hits and Endurance how much they can take (by up to
        about a quarter either way). Beasts and the undead have no such
        numbers.
        """
        from .rpg import bios
        for t in fio.things(self.logic):
            p = getattr(t, "properties", None)
            if not isinstance(p, dict):
                continue
            if str(p.get("type", "")) not in ("npc", "creature"):
                continue
            if p.get("monster_type", "human") != "human":
                continue
            role = str(p.get("npc_role", "") or "")
            if role in heads.ANIMAL_ROLES or role in ("skeleton", "skeleton_archer",
                                                      "wraith", "shroomling"):
                continue
            if not all(k in p for k in ("strength", "endurance", "charisma")):
                st, en, ch = bios.npc_rolls(str(p.get("name", "")), role)
                p.setdefault("strength", st)
                p.setdefault("endurance", en)
                p.setdefault("charisma", ch)
            if p.get("body_from_stats"):
                continue
            p["body_from_stats"] = True
            try:
                st = int(p["strength"])
                en = int(p["endurance"])
                p["damage"] = max(1, int(round(float(p.get("damage", 6))
                                               * (1.0 + (st - 10.5) * 0.03))))
                hp_scale = 1.0 + (en - 10.5) * 0.03
                p["max_health"] = max(1, int(round(float(p.get("max_health",
                                                               p.get("health", 60))) * hp_scale)))
                p["health"] = max(1, int(round(float(p.get("health", 60)) * hp_scale)))
            except (TypeError, ValueError):
                pass

    def _arm_fighters(self) -> None:
        from .held_weapons import arm_fighters
        try:
            arm_fighters(fio.things(self.logic), self.rng,
                         lambda iid: rpg_items.make(iid, 1))
        except Exception as exc:
            print(f"[MiniWind] arming fighters failed: {exc}")

    def overhead_actor_weapons(self):
        """What every actor near the player holds, for the viewport (see
        game/held_weapons.py)."""
        return self.held.overhead()

    def _assign_npc_handedness(self) -> None:
        """Give every NPC/creature a handedness where none was authored.

        A hand explicitly set in the editor (``handed`` = 'left'/'right') is
        always respected; only an unset (or '(random)') hand is rolled here, and
        left handedness is deliberately rare (see LEFT_HANDED_CHANCE). Stored on
        ``properties`` so it round-trips through save/load and the overhead
        renderer can draw the weapon on the correct side."""
        for t in fio.things(self.logic):
            p = getattr(t, "properties", None)
            if not isinstance(p, dict):
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
                continue
            cur = str(p.get("handed", "") or "").lower()
            if cur in ("left", "right"):
                continue
            p["handed"] = "left" if self.rng.random() < LEFT_HANDED_CHANCE else "right"

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
    def _rebuild_world_index(self) -> None:
        """Snapshot this tick's actors into :attr:`world_index`.

        The actor list is the engine's precomputed monster list; parked actors
        stay in it and are marked not-alive by the index itself, from Big
        World's parking markers. Below :data:`WORLD_INDEX_MIN_ACTORS` nothing
        is built and :meth:`_world_index` answers None.
        """
        actors = fio.monster_things(getattr(self, "logic", None))
        if len(actors) < WORLD_INDEX_MIN_ACTORS:
            self._wi_live = False
            return
        self.world_index.rebuild(list(actors))
        self._wi_live = True

    def tick(self, delta: float) -> None:
        # Rebuild the actor index once, then resolve it once here rather than
        # through an attribute chain at each of the tens of thousands of asks a
        # settlement tick makes.
        self._rebuild_world_index()
        self._wi_cache = None
        self._world_index()
        self._ground_actors()
        self._ease_zoom(delta)
        self._update_bow_draw(delta)
        self.archery.update(delta)
        warrior_fist.clear_spent(self)
        self.held.update()
        self.dragon_fire.update(delta)
        self.wildlife.update(delta)
        self.memory.update(delta)
        self.rewind.tick(delta)
        self._update_bolt_lights()
        if self.arrows_in_flight and not fio.projectile_count(self.logic):
            # Fio does not publish an empty store, so the last arrow to land
            # is cleared here.
            self.arrows_in_flight = ()
            self._arrow_tags.clear()
        self._keep_player_in_world()
        self.clock.advance(delta)
        self.game.tick(delta)
        self._announce_skill_raises()
        self._update_encumbrance()
        if self._attack_cooldown > 0:
            self._attack_cooldown -= delta
        if self._offhand_cooldown > 0:
            self._offhand_cooldown -= delta
        if self._cast_cooldown > 0:
            self._cast_cooldown -= delta
        if self._player_flash > 0:
            self._player_flash = max(0.0, self._player_flash - delta)

        # Bounty enforcement runs independently of normal NPC schedules so a guard
        # can approach, arrest, escort, or pursue the player immediately.
        self._update_arrest()

        # ---- decisions + movement, under simulation LOD --------------------
        # Fio's Big World has already stamped every actor with a tier by how
        # near the player it is (read through _tier_of). What each tier
        # costs per tick:
        #
        #   TIER_NEAR    full — decide every pass, move every tick
        #   TIER_ACTIVE  decide every other pass (staggered by row so the work
        #                spreads evenly), still move every tick so nothing the
        #                player can see stutters -- unless Big World's tiers are
        #                fitted to the camera (sim_tiers_fit_view), when ACTIVE
        #                is off screen: decide one pass in OFFSCREEN_STRIDE and
        #                move one tick in OFFSCREEN_STRIDE, carrying the rest
        #   TIER_DISTANT no per-tick work at all — one coarse movement step per
        #                decision pass, carrying the whole elapsed interval
        #   TIER_DORMANT nothing; the streamer has parked it
        #
        # Observable behaviour is unchanged: everything inside the overhead
        # camera's view moves every tick (NEAR when fitted, else NEAR or ACTIVE).
        hour_int = int(self.clock.hour)
        # The NPCs worth ticking at all: the engine's live actor set, which
        # already excludes anything the streamer has parked. On a streamed world
        # that is a handful of townsfolk rather than the whole population, and
        # the difference never reaches any of the loops below.
        npcs = self._live_npcs()
        # Tiers are fixed for the tick (the world index set them just before
        # this call), so read each actor's once and share it with every pass
        # below rather than asking again per pass per actor.
        tier_of = self._tier_of
        npc_tiers = [tier_of(n) for n in npcs]
        # Fitted to the camera, ACTIVE is off screen, and nobody can see an
        # off-screen NPC think or step less often.
        offscreen = bool(fio.sim_tiers_fit_view(self.logic))
        stride = OFFSCREEN_STRIDE if offscreen else 1
        self._offscreen_tick = (self._offscreen_tick + 1) % OFFSCREEN_STRIDE
        self._decision_accum += delta
        decided = (self._decision_accum >= DECISION_INTERVAL
                   or hour_int != self._last_hour_int)
        if decided:
            coarse_delta = max(self._decision_accum, delta)
            self._refresh_actor_cache()
            self._repel_hostiles()
            self._decision_accum = 0.0
            self._last_hour_int = hour_int
            self._decision_phase ^= 1
            phase = self._decision_phase
            pass_no = getattr(self, "_decision_pass", 0) + 1
            self._decision_pass = pass_no
            for i, npc in enumerate(npcs):
                tier = npc_tiers[i]
                if tier >= TIER_DORMANT:
                    continue
                if tier == TIER_DISTANT:
                    # Distant world: no perception, no combat reactions, no
                    # reactive-simulation appraisal — only the transitions that
                    # a clock or an event can cause. Then one coarse step that
                    # covers the whole interval since the last pass, still
                    # collision-checked so nobody walks into a wall off-screen.
                    self._decide_distant(npc)
                    self._move(npc, coarse_delta)
                    continue
                if tier == TIER_ACTIVE:
                    if offscreen:
                        if (i + pass_no) % OFFSCREEN_STRIDE:
                            continue
                    elif (i & 1) != phase:
                        continue
                self._decide(npc)
        for i, npc in enumerate(npcs):
            tier = npc_tiers[i]
            if tier >= TIER_DISTANT:
                continue          # moved coarsely on the decision pass above
            if tier == TIER_ACTIVE and stride > 1:
                if (i + self._offscreen_tick) % stride:
                    continue
                self._move(npc, delta * stride)
                continue
            self._move(npc, delta)

        # The roads: journeys advance off-screen on the clock, and parties
        # inside Big World's live region walk as actors (game/living).
        if self.living is not None:
            self.living.tick(delta)

        # Turn any NPC deaths (from player or engine combat) into persistent
        # settlement consequences — cheap: it walks the same cached actor list.
        self._reap_dead()

        # At each in-game day boundary, resolve one day of off-screen settlement
        # life (merchant restock, debts, mourning fade, harvest, memory decay)
        # and log it — the world moves on between the player's visits.
        self._resolve_day_rollover()

        # The reactive simulation: rumours spread on foot traffic, witnesses
        # reach the watch, and producing objects (a cow, a hen, a well) make
        # their goods. Runs on game hours, so it is unaffected by frame rate.
        self._tick_sim(delta)

        # world placeables: item pickups, spellbooks and quest triggers --
        # proximity checks, so a tenth of a second is soon enough.
        self._proximity_accum += delta
        if self._proximity_accum >= PROXIMITY_INTERVAL:
            self._proximity_accum = 0.0
            self._tick_pickups()
            self._tick_spellbooks()
            self._tick_triggers()
            self._tick_locations()
            self._tick_quests()

        # Decay player stab animation
        if self._attack_anim_time > 0:
            self._attack_anim_time = max(0.0, self._attack_anim_time - delta)
        if self._offhand_anim_time > 0:
            self._offhand_anim_time = max(0.0, self._offhand_anim_time - delta)

        # Detect NPC/creature attacks by watching the engine's is_shooting flag.
        # When it flips from False -> True we start a 0.2 s stab animation.
        # PERF: iterate only the actor buckets (npc/creature/monster) from the
        # cached type index instead of scanning + normalising the whole scene —
        # and only those the player could actually watch swing. An attack
        # animation is a purely visual 0.2 s decay; running it for an actor
        # outside the camera's reach changes nothing anyone sees.
        for t in self._live_actors():
            tp = t.properties
            if tp.get("_sim_tier", TIER_NEAR) > TIER_ACTIVE:
                continue
            was = tp.get("_was_shooting", False)
            now = tp.get("is_shooting", False)
            if now and not was:
                tp["_attack_anim"] = 0.2
            if tp.get("_attack_anim", 0.0) > 0:
                tp["_attack_anim"] = max(0.0, tp["_attack_anim"] - delta)
            if tp.get("_offhand_anim", 0.0) > 0:
                tp["_offhand_anim"] = max(0.0, tp["_offhand_anim"] - delta)
            tp["_was_shooting"] = now

        # keep the engine's health pool in step with the character
        self._sync_engine_health()

        # the wandering Wisp companion light
        self._update_wisp(delta)

        # Death, coming for whoever has just died
        self._update_reapers(delta)

        # carried torches (player + NPCs) float a warm light on their holder
        self._update_torch_lights(delta, npcs, npc_tiers)

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
            fio.things(self.logic).append(light)
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
            things = fio.things(self.logic)
            if things is not None and light in things:
                things.remove(light)
                self._rebuild_entity_caches()
        except Exception:
            pass

    # ------------------------------------------------------------- the reaper
    def _maybe_send_the_reaper(self, body) -> None:
        """One death in four is attended: Death comes to collect it.

        Called once per NPC death (see :meth:`_reap_dead`), so a townsperson cut
        down by a wolf is as likely to be visited as one the player kills. He is
        a piece of theatre and nothing else: he does no damage, cannot be
        attacked or spoken to, the combat AI never sees him (``disabled``), and
        when he is finished he takes himself out of the scene again.
        """
        if self.rng.random() >= REAPER_CHANCE:
            return
        if len(self._reapers) >= REAPER_MAX:
            return
        reaper = self._make_reaper(body)
        if reaper is None:
            return
        things = fio.things(self.logic)
        if things is None:
            return
        try:
            things.append(reaper)
        except Exception:
            return
        self._rebuild_entity_caches()
        self._reapers.append({
            "thing": reaper,
            "body": body,
            "phase": "arrive",
            "t": 0.0,
            "linger": self.rng.uniform(*REAPER_LINGER),
        })

    def _make_reaper(self, body):
        """Build the reaper actor, standing off a random way from *body*.

        Returns None where the entity types are unavailable (a headless build
        without them), which simply means no visit.
        """
        try:
            from .entities import Creature
        except Exception:
            return None
        try:
            bpos = [float(body.pos[0]), float(body.pos[1]), float(body.pos[2])]
        except (TypeError, ValueError, IndexError):
            return None
        # From beyond the edge of the view: on the far side of the body from
        # the player (give or take), and far enough out to be off screen.
        ppos = self._player_pos()
        if ppos is not None and (bpos[0] - ppos[0] or bpos[2] - ppos[2]):
            away = math.atan2(bpos[0] - ppos[0], bpos[2] - ppos[2])
            bearing = away + self.rng.uniform(-0.9, 0.9)
        else:
            bearing = self.rng.uniform(0.0, 2.0 * math.pi)
        distance = self.rng.uniform(*REAPER_ARRIVE_DIST)
        pos = [bpos[0] + math.sin(bearing) * distance,
               bpos[1],
               bpos[2] + math.cos(bearing) * distance]
        try:
            reaper = Creature(pos=pos, properties={
                "name": "Death",
                "display_name": "Death",
                "npc_role": "wraith",
                "head": REAPER_HEAD,
                "is_head": True,           # drawn like any other head actor
                "sprite_width": heads.HEAD_SIZE,
                "sprite_height": heads.HEAD_SIZE,
                "equipped_weapon": REAPER_WEAPON,
                "inventory": [],
                "aggression": "passive",
                "roam": False,
                "respawn": False,
                "persistent": False,
                # The core combat AI skips a disabled actor outright, so he is
                # never targeted, never targets, and is never moved by anything
                # but _advance_reaper below.
                "disabled": True,
                "health": 1,
                "max_health": 1,
                "_reaper": True,
                "_opacity": 0.0,
                "_facing": bearing + math.pi,   # already looking at the body
            })
        except Exception:
            return None
        reaper._respawn_fade_alpha = 0.0      # unseen until he fades in
        return reaper

    def _update_reapers(self, delta: float) -> None:
        """Advance every reaper visit; drop the ones that have finished."""
        if not self._reapers:
            return
        remaining = []
        for visit in self._reapers:
            try:
                alive = self._advance_reaper(visit, delta)
            except Exception:
                alive = False
            if alive:
                remaining.append(visit)
            else:
                self._despawn_reaper(visit)
        if len(remaining) != len(self._reapers):
            self._reapers = remaining
            self._rebuild_entity_caches()

    def _advance_reaper(self, visit, delta: float) -> bool:
        """One visit, one tick. False once he is gone and can be removed.

        The whole visit in order: fade in where he appeared, glide to the body,
        one stroke of the scythe, a very short pause, then fade out.
        """
        reaper = visit["thing"]
        props = reaper.properties
        visit["t"] += delta
        phase = visit["phase"]

        # The body is what he came for. If it is gone — resurrected, gibbed away,
        # streamed out — there is nothing to take, so he simply leaves.
        if phase in ("arrive", "approach", "reap") and not self._reaper_body_ok(visit["body"]):
            return self._reaper_phase(visit, "leave")

        if phase == "arrive":
            # Fading in as he starts toward the body, still off screen.
            self._set_reaper_opacity(reaper, visit["t"] / REAPER_FADE_IN)
            self._reaper_glide(visit, delta)
            if visit["t"] >= REAPER_FADE_IN:
                return self._reaper_phase(visit, "approach")
            return True

        if phase == "approach":
            self._set_reaper_opacity(reaper, 1.0)
            arrived = self._reaper_glide(visit, delta)
            if arrived or visit["t"] >= REAPER_APPROACH_TIMEOUT:
                return self._reaper_phase(visit, "reap")
            return True

        if phase == "reap":
            # The stroke goes through the same is_shooting / _attack_anim pair
            # every actor's weapon overlay animates from, so the scythe swings
            # exactly the way any other melee weapon does. Both are set here
            # rather than left to the shared decay pass, which only visits
            # actors the world index knows about — and it has never heard of him.
            swinging = visit["t"] < REAPER_SWING * 0.5
            props["is_shooting"] = swinging
            if swinging:
                props["_attack_anim"] = 0.2
            else:
                props.pop("_attack_anim", None)
            self._reaper_face_body(visit)
            if visit["t"] >= REAPER_SWING:
                props["is_shooting"] = False
                return self._reaper_phase(visit, "linger")
            return True

        if phase == "linger":
            if visit["t"] >= visit["linger"]:
                return self._reaper_phase(visit, "leave")
            return True

        # leave: he turns from the body and walks off, fading to nothing.
        props["is_shooting"] = False
        props.pop("_attack_anim", None)
        self._set_reaper_opacity(reaper, 1.0 - visit["t"] / REAPER_FADE_OUT)
        self._reaper_walk_off(visit, delta)
        return visit["t"] < REAPER_FADE_OUT

    @staticmethod
    def _set_reaper_opacity(reaper, fraction: float) -> None:
        """Show *reaper* at *fraction* of his full presence, which is itself
        at most REAPER_MAX_OPACITY. Drawn through the engine's per-entity
        render alpha, and journalled so the renderer re-reads it."""
        alpha = REAPER_MAX_OPACITY * max(0.0, min(1.0, float(fraction)))
        reaper.properties["_opacity"] = alpha
        if getattr(reaper, "_respawn_fade_alpha", None) != alpha:
            reaper._respawn_fade_alpha = alpha
            _journal(reaper)

    def _reaper_phase(self, visit, phase: str) -> bool:
        """Move a visit into *phase*, restarting its clock. Always still alive."""
        visit["phase"] = phase
        visit["t"] = 0.0
        return True

    def _reaper_body_ok(self, body) -> bool:
        """Whether the corpse he came for is still there to be taken."""
        props = getattr(body, "properties", None)
        if not isinstance(props, dict):
            return False
        return bool(props.get("dead")) and not props.get("gibbed")

    def _reaper_face_body(self, visit) -> None:
        reaper, body = visit["thing"], visit["body"]
        face_heading(reaper.properties,
                     float(body.pos[0]) - float(reaper.pos[0]),
                     float(body.pos[2]) - float(reaper.pos[2]))

    def _reaper_glide(self, visit, delta: float) -> bool:
        """Slide the reaper toward the body. True once he is close enough to reap.

        He glides: no collision, no gravity, no path. Death is not obstructed by
        a fence, and giving him the NPC mover would put him in queues for doors.
        """
        reaper, body = visit["thing"], visit["body"]
        dx = float(body.pos[0]) - float(reaper.pos[0])
        dz = float(body.pos[2]) - float(reaper.pos[2])
        distance = math.hypot(dx, dz)
        if distance <= REAPER_REACH:
            return True
        step = min(distance - REAPER_REACH, REAPER_SPEED * max(0.0, delta))
        # A new list, not an in-place edit: assigning pos is what tells the
        # renderer he moved. Ride at the body's height rather than the ground
        # he set out from, so he does not walk through another storey's floor.
        reaper.pos = [float(reaper.pos[0]) + dx / distance * step,
                      float(body.pos[1]),
                      float(reaper.pos[2]) + dz / distance * step]
        face_heading(reaper.properties, dx, dz)
        return distance - step <= REAPER_REACH

    def _reaper_walk_off(self, visit, delta: float) -> None:
        """Leaving: glide away from the body, the way he came."""
        reaper, body = visit["thing"], visit["body"]
        dx = float(reaper.pos[0]) - float(body.pos[0])
        dz = float(reaper.pos[2]) - float(body.pos[2])
        distance = math.hypot(dx, dz) or 1.0
        step = REAPER_SPEED * max(0.0, delta)
        reaper.pos = [float(reaper.pos[0]) + dx / distance * step,
                      float(reaper.pos[1]),
                      float(reaper.pos[2]) + dz / distance * step]
        face_heading(reaper.properties, dx, dz)

    def _despawn_reaper(self, visit) -> None:
        """Take one reaper out of the scene."""
        reaper = visit.get("thing")
        things = fio.things(self.logic)
        if reaper is None or things is None:
            return
        try:
            if reaper in things:
                things.remove(reaper)
        except Exception:
            pass

    def _banish_reapers(self) -> None:
        """Remove every reaper at once (a world reset mid-visit)."""
        if not self._reapers:
            return
        for visit in self._reapers:
            self._despawn_reaper(visit)
        self._reapers = []
        self._rebuild_entity_caches()

    # ------------------------------------------------------------ torches
    def _make_light(self, pos, props):
        """Create a Light entity for the scene (a torch/wisp light).

        Uses the engine ``Light`` in the real game; falls back to the Qt-free
        ``plugins.entitybase.Thing`` (tagged ``type='light'``) where PyQt is
        unavailable — the same fallback the entity module uses — so the runtime's
        light handling is exercisable headlessly. Returns None if neither exists."""
        try:
            from editor.things import Light
            return Light(pos=list(pos), properties=dict(props))
        except Exception:
            pass
        try:
            from plugins.entitybase import Thing
            t = Thing(pos=list(pos), properties=dict(props))
            if isinstance(getattr(t, "properties", None), dict):
                t.properties.setdefault("type", "light")
            return t
        except Exception:
            return None

    def _torch_light_props(self, item_def) -> Dict:
        """Light properties for a carried torch, from the item's own light fields
        (falling back to the defaults) — a warm, non-shadowing point light."""
        radius = intensity = None
        colour = None
        if item_def is not None:
            radius = item_def.get("light_radius")
            intensity = item_def.get("light_intensity")
            colour = item_def.get("light_color")
        base_intensity = float(intensity if intensity is not None else TORCH_DEFAULT_INTENSITY)
        return {
            "colour": list(colour) if colour else list(TORCH_DEFAULT_COLOUR),
            "intensity": base_intensity,
            "radius": float(radius if radius is not None else TORCH_DEFAULT_RADIUS),
            "state": "on",
            "casts_shadows": False,
            "hidden_in_game": False,
            "_torch": True,
            "_torch_base_intensity": base_intensity,
        }

    def _player_torch_def(self):
        """The torch item the player currently has equipped in the light slot,
        or None."""
        c = self.game.character
        if c.is_dead:
            return None
        return eq.light_source(c)

    def _npc_torch_def(self, props: Dict, night: bool):
        """The torch item an NPC is currently holding lit, or None.

        ``torch_always`` burns day and night; ``torch`` lights only after dark —
        so authoring ``torch: true`` gives the lovely "guards carry torches at
        night" behaviour with no schedule work. The specific item can be named
        via ``torch_item`` (defaults to the generic ``torch``). And anyone who
        simply *carries* a light (a torch in their inventory) holds it lit
        after dark too."""
        if props.get("dead") or props.get("hidden"):
            return None
        if props.get("torch_always") or (props.get("torch") and night):
            tid = props.get("torch_item") or "torch"
            return rpg_items.get(tid) or rpg_items.get("torch")
        if night:
            return self._carried_light(props)
        return None

    @staticmethod
    def _carried_light(props: Dict):
        """The first light source (torch, lantern) in *props*' inventory."""
        carried = props.get("inventory")
        if not isinstance(carried, list):
            return None
        for stack in carried:
            if not isinstance(stack, dict) or int(stack.get("qty", 1) or 0) <= 0:
                continue
            d = rpg_items.get(stack.get("id", ""))
            if d is not None and d.category == rpg_items.LIGHT:
                return d
        return None

    def torch_shadows_enabled(self) -> bool:
        """GAME → "Torch shadows": torches near the player cast shadows.
        Off unless set (shadow-casting point lights are costly)."""
        try:
            config = self._editor_config()
            if config is None:
                return False
            return config.getboolean("GAME", "torch_shadows", fallback=False)
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def _torch_flicker(t: float, phase: float):
        """(intensity, radius) multipliers for a torch flame at time *t*.

        Three incommensurate waves and a fast shimmer, offset per torch by
        *phase*, so neighbouring torches never pulse in step and none of them
        settles into an obvious rhythm."""
        a = math.sin(t * 7.3 + phase)
        b = math.sin(t * 12.9 + phase * 1.7)
        c = math.sin(t * 3.1 + phase * 0.6)
        d = math.sin(t * 23.0 + phase * 2.3)
        wave = 0.45 * a + 0.25 * b + 0.2 * c + 0.1 * d        # -1..1
        return 1.0 + TORCH_FLICKER_INTENSITY * wave, 1.0 + TORCH_FLICKER_RADIUS * (0.6 * a + 0.4 * c)

    def _update_torch_lights(self, delta: float, npcs=None, tiers=None) -> None:
        """Spawn / move / remove the dynamic lights carried by torch holders.

        Cheap and allocation-light: one pass builds the set of holders that
        should have a lit torch right now (the player if a torch is equipped,
        plus any NPC whose flags say so, or who carries one after dark),
        existing lights are repositioned in place onto their holder, new ones
        are spawned and vanished ones removed, and the engine caches are
        rebuilt only when the light set actually changes (a spawn/despawn),
        never on a mere reposition. Each flame flickers, and with GAME →
        "Torch shadows" on, the torches in the NEAR simulation tier cast
        shadows."""
        night = not self.clock.is_daytime
        shadows = self.torch_shadows_enabled()
        # holder key -> (holder position, torch item def, casts shadows)
        desired = {}
        ppos = self._player_pos()
        pdef = self._player_torch_def()
        if pdef is not None and ppos is not None:
            desired["player"] = (ppos, pdef, shadows)
        if npcs is None:
            npcs = self.npcs()
            tiers = [self._tier_of(n) for n in npcs]
        for i, npc in enumerate(npcs):
            p = npc.properties
            # A torch is a dynamic light. One carried beyond the player's
            # vicinity illuminates nothing the camera can see, and each costs a
            # Light entity plus a renderer light slot, so distant holders simply
            # do not carry a lit one. It relights the moment they come near.
            tdef = None if tiers[i] > TIER_ACTIVE else self._npc_torch_def(p, night)
            if tdef is not None and held_weapons.two_handed(
                    p.get("_active_weapon") or p.get("equipped_weapon")):
                tdef = None          # a bow takes both hands: no torch with it
            if tdef is not None:
                desired[id(npc)] = (list(npc.pos), tdef, shadows and tiers[i] == TIER_NEAR)
                if p.get("_torch_lit") != tdef.id:
                    p["_torch_lit"] = tdef.id       # drawn in the off hand
            elif "_torch_lit" in p:
                p.pop("_torch_lit", None)

        changed = False
        for key in list(self._torch_lights):
            if key not in desired:
                self._remove_torch_light(key)
                changed = True

        self._torch_flicker_t += delta
        t = self._torch_flicker_t
        for key, (pos, tdef, cast) in desired.items():
            light = self._torch_lights.get(key)
            if light is None:
                start = [pos[0], pos[1] + TORCH_LIGHT_HEIGHT, pos[2]]
                props = self._torch_light_props(tdef)
                props["casts_shadows"] = bool(cast)
                light = self._make_light(start, props)
                if light is None:
                    continue
                try:
                    fio.things(self.logic).append(light)
                except Exception:
                    continue
                self._torch_lights[key] = light
                changed = True
            else:
                lp = light.pos
                lp[0] = pos[0]
                lp[1] = pos[1] + TORCH_LIGHT_HEIGHT
                lp[2] = pos[2]
            lprops = light.properties
            lprops["casts_shadows"] = bool(cast)
            phase = lprops.get("_torch_phase")
            if phase is None:
                phase = lprops["_torch_phase"] = (hash(str(key)) % 6283) / 1000.0
            k_int, k_rad = self._torch_flicker(t, float(phase))
            base = float(lprops.get("_torch_base_intensity", TORCH_DEFAULT_INTENSITY))
            base_r = lprops.get("_torch_base_radius")
            if base_r is None:
                base_r = lprops["_torch_base_radius"] = lprops.get(
                    "radius", TORCH_DEFAULT_RADIUS)
            base_r = float(base_r)
            lprops["intensity"] = base * k_int
            lprops["radius"] = base_r * k_rad
            # The renderer copies a light's intensity, radius and shadow flag
            # into its tables; say they changed, or the flame holds still.
            _journal(light)
        if changed:
            self._rebuild_entity_caches()

    def _remove_torch_light(self, key) -> None:
        light = self._torch_lights.pop(key, None)
        if light is None:
            return
        try:
            things = fio.things(self.logic)
            if things is not None and light in things:
                things.remove(light)
        except Exception:
            pass

    def _remove_all_torch_lights(self) -> None:
        for key in list(self._torch_lights):
            self._remove_torch_light(key)
        self._rebuild_entity_caches()

    def _rebuild_entity_caches(self) -> None:
        try:
            fio.rebuild_entity_caches(self.logic)
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
        things = fio.things(self.logic)
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
            for slot in range(max(0, count)):
                ox = self.rng.uniform(-radius, radius) if radius else 0.0
                oz = self.rng.uniform(-radius, radius) if radius else 0.0
                pos = [sp.pos[0] + ox, sp.pos[1], sp.pos[2] + oz]
                props = {"npc_role": role,
                         # Remembered by spawner and slot (game/map_memory.py):
                         # killed today, back in about a day.
                         "_spawner": str(p.get("id") or p.get("name") or ""),
                         "_spawn_slot": slot,
                         "_spawner_respawn": p.get("respawn", True) is not False}
                if faction:
                    # Force the whole group onto one team (relationships/combat).
                    props["faction"] = faction
                    props["team"] = faction
                if inventory:
                    # Each member gets its own copy so looting one member's
                    # corpse never empties the rest of the group.
                    props["inventory"] = [dict(it) for it in inventory]
                try:
                    fio.things(self.logic).append(cls(pos=pos, properties=props))
                    made += 1
                except Exception:
                    pass
            p["_spawned"] = True
        if made:
            try:
                fio.rebuild_entity_caches(self.logic)
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
                name = stack.get("name", iid)
                # Taking an *owned* item is a theft, with everything that
                # follows: witnesses, a report, a bounty, an owner who
                # remembers. Taking an unowned one is just picking it up. One
                # call decides which, so no item needs special handling.
                event = self.director.take(
                    p, self.player_actor, target_thing=self._sim_actor_by_key(
                        sim_own.owner_of(p)),
                    observers=self._sim_observers(), item_id=iid, item_name=name,
                    value=int(stack.get("value", 0) or 0) * max(1, qty),
                    pos=list(it.pos))
                if event is not None and event.kind == "theft":
                    sim_own.mark_stolen(stack, sim_own.owner_of(p),
                                        sim_own.owner_name_of(p))
                    self.notify(f"Stole {name}")
                else:
                    self.notify(f"Picked up {name}")
                inv.add_item(self.game.character.inventory, stack)
                # Let a producer know one of its outstanding yields was taken so
                # it starts making the next one.
                producer = self._sim_producer_of(p)
                if producer is not None:
                    sim_prod.note_collected(producer.properties, 1)
                elif not p.get("respawn"):
                    self.memory.taken(it)       # gone for good from this map
                p["dead"] = True
                p["hidden"] = True
                _journal(it)

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
            elif not c.can_use_magic():
                self.notify("The arcane script means nothing to a warrior")
            elif spell_id in c.known_spells:
                self.notify(f"You already know {spell.name}")
            else:
                c.known_spells.append(spell_id)
                if not c.active_spell:
                    c.active_spell = spell_id
                self.notify(f"Learned {spell.name} from {title}")
            # A quest book: the reader carries it off as the quest item.
            quest_item = str(p.get("quest_item", "") or "").strip()
            if quest_item and not inv.has_item(c.inventory, quest_item, 1):
                self.game.pick_up(quest_item, 1)
            if not p.get("respawn"):
                p["dead"] = True
                p["hidden"] = True
                _journal(bk)

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
        # A first introduction warms an NPC to the player a touch (once).
        disp.remember(self.store, getattr(npc, "properties", {}) or {}, "greeted")

    def record_kill(self, target) -> None:
        """Bump per-identity kill counters (for quest 'kill' objectives).

        Also flags a named victim as *killed by the player*, so that when the
        death is reaped into a settlement consequence, the victim's kin can tell
        an honest bandit-slaying apart from a murder at the player's own hand and
        remember the player accordingly (see :meth:`_on_npc_death`)."""
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
        name = str(p.get("name", "") or "").strip()
        if name:
            self.store.set("killed_by_player." + name, "1")

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

        Resolves the *first active quest* to a world position (see
        :meth:`_arrow_destination`). Returns ``(pos, quest_name)`` or ``None``.
        Any active quest yields a destination — the objective when it resolves,
        otherwise the quest giver — so the arrow appears as soon as a quest is
        received and keeps pointing somewhere useful through every stage."""
        active = self.game.quests.active_quests()
        if not active:
            return None
        q = active[0]
        pos = self._arrow_destination(q)
        if pos is None:
            return None
        return (list(pos), q.name)

    def quest_arrow_targets(self):
        """Destinations for the orbiting arrows — one per active quest.

        The player can carry several quests at once; each gets its own arrow
        ringing the head (the HUD colours them apart). Returns a list of
        ``(pos, quest_id, quest_name)`` in the quests' active order, skipping
        any quest whose current stage resolves to no world position. The
        stable ``quest_id`` lets the HUD assign each quest a consistent
        colour regardless of how many are active.

        When the player has pinned one quest as *tracked* (see
        :meth:`set_tracked_quest`), only that quest's arrow is returned, so the
        other quests' arrows are hidden — unless the tracked quest is no longer
        active, in which case all active quests' arrows show again."""
        import time as _time
        now = _time.monotonic()
        active = self.game.quests.active_quests()
        tracked = self.tracked_quest_id()
        log = self.game.quests
        key = (tracked, tuple((q.id, log.stage_of(q.id)) for q in active))
        memo = getattr(self, "_arrow_memo", None)
        if (memo is not None and memo[2] == key
                and now - memo[0] < QUEST_LOOKUP_SECONDS):
            return list(memo[1])
        if tracked:
            focused = [q for q in active if q.id == tracked]
            if focused:
                active = focused
        out = []
        for q in active:
            pos = self._arrow_destination(q)
            if pos is not None:
                out.append((list(pos), q.id, q.name))
        # The HUD, the map and the quest panel ask every frame; where a quest
        # points cannot change faster than the things in it walk.
        self._arrow_memo = (now, out, key)
        return list(out)

    def tracked_quest_id(self) -> str:
        """The quest id the player pinned as active (only its arrow shows), or
        ``''`` when none is pinned (every active quest shows its arrow)."""
        try:
            v = self.store.get("quest.tracked", "")
        except Exception:
            v = ""
        return "" if v in (None, "", "false") else str(v)

    def set_tracked_quest(self, qid) -> str:
        """Pin *qid* as the tracked quest so only its arrow shows. Passing a
        falsy id — or the id that is already tracked — clears the pin, so every
        active quest's arrow shows again. Returns the new tracked id (``''``
        when cleared)."""
        qid = str(qid or "")
        new = "" if (not qid or qid == self.tracked_quest_id()) else qid
        try:
            self.store.set("quest.tracked", new)
        except Exception:
            pass
        return new

    def _arrow_destination(self, q):
        """Best-effort world position for *q*'s current stage, for the arrow.

        Priority: the stage's machine-readable objective (kill/fetch/visit/talk,
        via :meth:`_objective_world_pos`); then the stage's navigational
        ``waypoint`` hint; then the quest giver. Purely navigational — it never
        advances the quest, so a stage with no condition (e.g. "clear the mill",
        "return to the giver") still gets an arrow without changing progression.
        """
        pos = self._objective_world_pos(q)
        if pos is not None:
            return pos
        st = q.stage(self.game.quests.stage_of(q.id))
        wp = getattr(st, "waypoint", "") if st is not None else ""
        if wp:
            pos = self._resolve_world_target(wp)
            if pos is not None:
                return pos
        if getattr(q, "giver", ""):
            pos = self._resolve_world_target(q.giver)
            if pos is not None:
                return pos
        return None

    def _resolve_world_target(self, name):
        """World position of the nearest live thing matching *name*, or None.

        Matches *name* (slugged) against a marker place/name, an NPC
        name/display_name/role, a monster type, an item-pickup id or a thing id
        — so one call resolves quest givers, foes, visit markers and fetch
        items. Prefers the closest match to the player."""
        target = self._slug(name)
        if not target:
            return None
        ppos = self._player_pos()
        best, best_pos = None, None
        living = getattr(self, "living", None)
        if living is not None:
            # Someone on the roads (a gang leader with a price on his head)
            # is somewhere even while he is only a journey on the board.
            far = living.locate(target)
            if far is not None and ppos is not None:
                best, best_pos = self._dist2d(ppos, far), list(far)
        seen = set()
        for t, _field in self._name_index().get(target, ()):
            if id(t) in seen:
                continue
            seen.add(id(t))
            p = getattr(t, "properties", {}) or {}
            if p.get("dead"):
                continue
            pos = getattr(t, "pos", None)
            if pos is None:
                continue
            if ppos is None:
                return list(pos)
            d = self._dist2d(ppos, pos)
            if best is None or d < best:
                best, best_pos = d, list(pos)
        return best_pos

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
            # A pickup of the item, or a book that hands it over when read.
            sources = [(it, it.properties.get("item_id", ""))
                       for it in self._things_of_type("itempickup")]
            sources += [(bk, bk.properties.get("quest_item", ""))
                        for bk in self._things_of_type("spellbook")]
            for it, item_id in sources:
                if it.properties.get("dead"):
                    continue
                if self._slug(item_id) == raw:
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
        target_pos = None if complete else self._objective_pos_memo(q, log.stage_of(q.id))
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

    def _objective_pos_memo(self, q, stage):
        """:meth:`_objective_world_pos`, reused for :data:`QUEST_LOOKUP_SECONDS`
        per quest and stage (the HUD and the quest panel ask every frame)."""
        import time as _time
        now = _time.monotonic()
        memo = self.__dict__.setdefault("_objective_memo", {})
        key = (q.id, stage)
        got = memo.get(key)
        if got is not None and now - got[0] < QUEST_LOOKUP_SECONDS:
            return got[1]
        pos = self._objective_world_pos(q)
        if len(memo) > 64:
            memo.clear()
        memo[key] = (now, pos)
        return pos

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
            for t in fio.things(self.logic):
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
        if kind == _quests.COND_FETCH:
            from .rpg import items as rpg_items
            item = rpg_items.get(str(raw).strip())
            if item is not None and item.name:
                return item.name
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

    #: Fields a quest target may be named by, and the subset that names an
    #: actor for a 'kill' objective.
    _NAME_FIELDS = ("name", "display_name", "npc_role", "monster_type",
                    "item_id", "place_name")
    _ACTOR_FIELDS = ("name", "npc_role", "monster_type")

    def _name_index(self):
        """slug -> [(thing, field)] for every thing in the scene.

        Quest arrows, the quest panel and the map ask "where is the nearest
        wolf / Elowen / the Old Mill?" every frame. Answering that by walking
        and re-slugging the whole world (over a thousand things on the shipped
        map) cost several milliseconds per ask, several times a frame --
        the stutter felt as soon as a far-off quest became the tracked one.
        The index is rebuilt only when the scene's thing list changes (the
        same ``(id, len)`` token the type index uses), so a lookup visits only
        the handful of things that actually carry the name.
        """
        things = fio.things(self.logic)
        token = (id(things), len(things))
        cached = getattr(self, "_name_index_cache", None)
        if cached is not None and cached[0] == token:
            return cached[1]
        index: Dict[str, list] = {}
        slug = self._slug
        # Slugs per thing are kept between rebuilds, keyed by the raw values
        # they came from, so a rebuild after a torch light comes or goes only
        # slugs what actually changed.
        known = self.__dict__.setdefault("_name_slugs", {})
        fresh = {}
        fields = self._NAME_FIELDS
        for t in list(things):
            p = getattr(t, "properties", None)
            if not isinstance(p, dict):
                continue
            raw = tuple(p.get(f) for f in fields) + (p.get("id"),)
            got = known.get(id(t))
            if got is None or got[0] != raw:
                pairs = [(slug(v), f) for v, f in zip(raw, fields + ("id",)) if v]
                got = (raw, pairs)
            fresh[id(t)] = got
            for key, field in got[1]:
                index.setdefault(key, []).append((t, field))
        self._name_slugs = fresh
        self._name_index_cache = (token, index)
        return index

    def _nearest_matching_pos(self, target_slug):
        """Nearest alive actor whose type/role/name matches *target_slug*."""
        ppos = self._player_pos()
        best, best_pos = None, None
        seen = set()
        for t, field in self._name_index().get(target_slug, ()):
            if field not in self._ACTOR_FIELDS or id(t) in seen:
                continue
            seen.add(id(t))
            p = t.properties
            if p.get("dead"):
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype not in ("npc", "creature", "monster"):
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

    def escape_closes_modal(self) -> bool:
        """Would Escape close whatever the game currently has on screen?

        The host (the editor's play mode) asks this before handing Escape to the
        plugin. A conversation and most screens close on Escape, so the key
        belongs to the game. Character creation and the level-up screen do not
        (see :data:`ESCAPE_LOCKED_SCREENS`) — giving them the key would swallow
        it silently and leave the player with no way to stop play mode.
        """
        if self.dialogue is not None:
            return True
        if self.open_screen is None:
            return False
        return self.open_screen not in ESCAPE_LOCKED_SCREENS

    def modal_input_active(self) -> bool:
        """Whether MiniWind currently owns keyboard input for a modal UI.

        Fio uses this capability to leave number keys available to dialogue
        choices and screens instead of treating them as engine shortcuts.
        The engine does not need to know MiniWind's screen names.
        """
        return bool(
            self.needs_char_creation
            or self.open_screen is not None
            or self.dialogue is not None
        )

    def tick_ui(self, delta: float) -> None:
        """Age only the transient HUD (toasts/floaters) while the world is paused
        (a menu or character creation is open). No clock, NPC or combat sim."""
        self._announce_skill_raises()
        self._age_lists(delta)

    def _read_world_bounds(self):
        """``(min_x, max_x, min_z, max_z)`` the player may walk in: the
        terrain's extent, drawn in by :data:`WORLD_EDGE_MARGIN` so the rim of
        the map is a wall rather than a cliff into nothing. None without
        terrain (an interior map keeps its own walls)."""
        ter = fio.terrain(self.logic)
        if ter is not None and getattr(ter, "enabled", False):
            try:
                (x0, x1), (z0, z1) = ter.get_terrain_bounds()
            except Exception:
                return None
        else:
            # No live terrain object on this thread (yet): the map's own
            # terrain record says the same thing.
            state = getattr(self.logic, "editor_state", None)
            td = getattr(state, "terrain_data", None)
            if not isinstance(td, dict) or not td.get("enabled", True):
                return None
            try:
                size = float(td.get("chunk_size", 256.0))
                x0 = int(td["min_chunk_x"]) * size + float(td.get("offset_x", 0.0))
                x1 = (int(td["max_chunk_x"]) + 1) * size + float(td.get("offset_x", 0.0))
                z0 = int(td["min_chunk_z"]) * size + float(td.get("offset_z", 0.0))
                z1 = (int(td["max_chunk_z"]) + 1) * size + float(td.get("offset_z", 0.0))
            except (KeyError, TypeError, ValueError):
                return None
        m = WORLD_EDGE_MARGIN
        if x1 - x0 <= 4 * m or z1 - z0 <= 4 * m:
            return None
        return (x0 + m, x1 - m, z0 + m, z1 - m)

    def _keep_player_in_world(self) -> None:
        """The edges of the map are untraversable: the player is held inside
        the world's bounds, sliding along the edge rather than stopping dead."""
        bounds = getattr(self, "_world_bounds", None)
        player = fio.player(self.logic)
        if bounds is None or player is None:
            return
        x0, x1, z0, z1 = bounds
        pos = player.pos
        x, z = float(pos[0]), float(pos[2])
        cx, cz = min(max(x, x0), x1), min(max(z, z0), z1)
        if cx != x or cz != z:
            pos[0], pos[2] = cx, cz
            vel = getattr(player, "velocity", None)
            if vel is not None:
                if cx != x:
                    vel[0] = 0.0
                if cz != z:
                    vel[2] = 0.0
            if not getattr(self, "_edge_told", False):
                self._edge_told = True
                self.notify("The land beyond is impassable.", 2.5)
        else:
            self._edge_told = False

    def _update_encumbrance(self) -> None:
        """Carrying more than you can bear slows you to a third of your pace,
        and the game says so -- once when it happens, again every few seconds
        while you stay overloaded, and once more when you are free of it."""
        c = getattr(getattr(self, "game", None), "character", None)
        player = fio.player(self.logic)
        if c is None or player is None:
            return
        try:
            heavy = bool(c.is_overencumbered)
        except Exception:
            heavy = False
        player.move_speed_scale = ENCUMBERED_SPEED if heavy else 1.0
        was = getattr(self, "_encumbered", False)
        now = self.clock.day * 24.0 + self.clock.hour
        if heavy and (not was or now - getattr(self, "_encumbered_told", -99.0) > 0.08):
            self.notify("You are encumbered!", 2.5)
            self._encumbered_told = now
        elif was and not heavy:
            self.notify("You can move freely again.", 2.0)
        self._encumbered = heavy

    def _announce_skill_raises(self) -> None:
        """Toast each skill that rose through use ("Destruction increased to
        12"), so learning by doing is something the player sees happen, and
        say so when the rises have earned a level."""
        c = getattr(getattr(self, "game", None), "character", None)
        pop = getattr(c, "pop_skill_raises", None)
        if pop is None:
            return
        raised = pop()
        if not raised:
            return
        from .rpg import skills as _sk
        for skill_id, value in raised[-3:]:
            sd = _sk.SKILLS.get(skill_id)
            label = sd.label if sd is not None else str(skill_id).replace("_", " ").title()
            self.notify(f"{label} increased to {value}", 3.5)
            self.game.message(f"Your {label} skill increased to {value}.")
        if c.can_level_up and not getattr(self, "_level_up_announced", False):
            self._level_up_announced = True
            self.notify("You feel more experienced. Press L to level up.", 6.0)
        elif not c.can_level_up:
            self._level_up_announced = False

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

    def add_floater(self, text, kind="dmg", y=0.0):
        self.floaters.append({"text": text, "t": 1.2, "y": float(y), "kind": kind})

    def _on_xp(self, amount) -> None:
        """Experience earned (a kill, a quest): "+N XP" over the player, a
        line above the "SLAIN" a kill shows at the same moment."""
        self.add_floater(f"+{int(amount)} XP", kind="xp", y=-26.0)

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
        ``combatant`` property (defaulted from aggression/role by the entity).

        The rule itself lives in :func:`game.sim.appraisal.is_combatant` so the
        settlement AI and the reactive simulation cannot drift apart on who
        counts as a fighter."""
        return sim_appraisal.is_combatant(npc.properties)

    def _reap_dead(self) -> None:
        """Turn NPC deaths into persistent settlement consequences, once each.

        Deaths are caught by watching the ``dead`` flag rather than hooking every
        kill path, so a townsperson cut down by the engine's MonsterAI (a bandit,
        a wolf) counts the same as one the player kills. The consequence lives in
        the persistent KV store, so it survives save/load and dialogue can read
        it — the town remembers who is gone.
        """
        # PERF: only dead NPCs matter here. With the index that is its corpse
        # rows (a few) rather than every NPC; without it, the "npc" bucket.
        wi = self._world_index()
        if wi is None:
            pool = self._things_of_type("npc")
        else:
            npc_ids = self._type_ids("npc")
            actors = wi.actors
            pool = [actors[i] for i in np.flatnonzero(wi.dead[:wi.n]).tolist()
                    if id(actors[i]) in npc_ids]
        for t in pool:
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
            # Death may come for a fallen NPC (never for a creature).
            self._maybe_send_the_reaper(t)

    def _on_npc_death(self, npc) -> None:
        """Record the durable, save/load-persistent fallout of one NPC's death."""
        p = npc.properties
        name = str(p.get("name", ""))
        disp_name = p.get("display_name") or name or "Someone"
        already = str(self.store.get("dead." + name, "false")).lower() not in (
            "false", "", "none")
        if name:
            self.store.set("dead." + name, "1")
        self.game.message(f"{disp_name} has died.")
        self.notify(f"{disp_name} has died.", 5.0)
        if not already:
            try:
                n = int(self.store.get("town.deaths", "0"))
            except (TypeError, ValueError):
                n = 0
            self.store.set("town.deaths", n + 1)
        self.store.set("town.last_death", disp_name)
        self.store.set("town.mourning", "1")
        # Stamp the day of the death so the daily resolution can let active
        # mourning fade a couple of days later (game.rpg.daily._fade_mourning).
        try:
            self.store.set("town.last_death_day", int(self.clock.day))
        except Exception:
            pass
        # A fallen guard leaves the settlement less protected — a durable flag
        # other systems and dialogue can key off.
        if str(p.get("npc_role", "")).lower().startswith("guard"):
            self.store.set("town.unprotected", "1")
        # Emit the death into the reactive simulation. This is the same call
        # whoever did the killing — the player, a bandit, a wolf — so grief,
        # witnesses, rumour and the murder charge all fall out of one event
        # instead of a per-killer branch. Whether it is *murder* depends on
        # whether the victim was at war with the killer.
        by_player = str(self.store.get("killed_by_player." + name, "false")).lower() \
            in ("1", "true", "yes")
        # For a death the player had no hand in, attribute it to whoever was
        # standing over the body: the nearest actor hostile to the victim. It is
        # a heuristic rather than damage bookkeeping, but it is the same one a
        # bystander would use, and it is what lets a settlement blame the right
        # bandit without the engine tracking every blow.
        killer = (self.player_actor if by_player
                  else self._sim_actor_by_key(self._slug(p.get("_killed_by", "")))
                  or self._nearest_hostile(npc, DEFEND_SIGHT))
        self.director.emit(
            "death", actor=killer, target=npc, pos=list(npc.pos),
            observers=self._sim_observers(),
            crime=(self._sim_is_crime_against(npc) if by_player else
                   bool(killer is not None and self._sim_is_crime_against(npc))))
        # The kin-grief wound stays: it is the *authored relationship* reacting,
        # which the settlement already models, and it applies even to relatives
        # who were nowhere near and only hear of it later.
        if by_player:
            self._remember_kin_grief(name)

    def _remember_kin_grief(self, dead_name: str) -> None:
        """Drop the disposition of the slain NPC's living relatives toward the
        player (memory of a murder at the player's hand)."""
        if not dead_name:
            return
        for npc in self.npcs():
            rels = npc.properties.get("relationships")
            if isinstance(rels, dict) and dead_name in rels:
                disp.remember(self.store, npc.properties, "kin_slain")

    def _resolve_day_rollover(self) -> None:
        """On an in-game day boundary, resolve one day of off-screen settlement
        life and surface its event log. Cheap: only fires when the day integer
        actually changes, and the resolution is a single pass over the townsfolk
        property dicts (see :mod:`game.rpg.daily`)."""
        try:
            day = int(self.clock.day)
        except Exception:
            return
        if self._last_day is None:
            # First tick of this session: establish the baseline day without
            # resolving retroactively (resolve_pending records it and returns []).
            self._last_day = day
            rpg_daily.resolve_pending(self.store, day, [], self.rng)
            return
        if day == self._last_day:
            return
        self._last_day = day
        actors = [npc.properties for npc in self.npcs()]
        events = rpg_daily.resolve_pending(self.store, day, actors, self.rng)
        for line in events:
            self.game.message(line)
        if events:
            self.notify(events[-1], 5.0)

    def _is_arrest_guard(self, thing) -> bool:
        """Return whether *thing* is a living, non-hostile guard available for arrest duty."""
        if thing is None:
            return False
        p = getattr(thing, "properties", {})
        return (self._is_guard(thing) and not p.get("dead")
                and str(p.get("aggression", "")) != "hostile")

    def _prison_marker(self):
        """The map's prison marker, or None.

        A prison is a Marker with ``marker_kind = "prison"`` — that is what the
        editor authors and what the arrest flow watches for. This used to look
        the marker up by *name* instead, which almost never matched, so the
        escort fell through to the nearest guardpost: the guard walked you to
        his post and stood there. Name is still accepted as a fallback for maps
        that authored a plain entity called "prison".
        """
        for marker in self._markers_of_kind("prison"):
            return marker
        return self._find_named(PRISON_MARKER_NAME)

    def _prison_position(self):
        """Where an escorted prisoner is being taken, or None if the map has no
        prison. Never a guardpost: a guardpost is where the guard works, not
        where a prisoner goes."""
        prison = self._prison_marker()
        return list(prison.pos) if prison is not None else None

    def _update_arrest(self) -> None:
        """Drive bounty detection, guard approach, escort delivery, and escape."""
        player_pos = self._player_pos()
        if player_pos is None or self.game.character.is_dead:
            return

        guard = self._arrest_guard
        state = self._arrest_state

        # A chase runs on its own: it needs no prison, because nobody is being
        # delivered anywhere. Handled before the prison check so refusing arrest
        # on a map with no gaol still gets you run down.
        if state == "pursuit":
            self._update_arrest_pursuit()
            return

        # Resolve the prison once, through the same lookup the escort uses so
        # the two can never disagree about where the player is being taken.
        # A map with no prison still has a watch: the guard still comes for a
        # wanted player and still takes a fine or a fight -- only the escort
        # to a cell is off the table (see _arrest_tree).
        prison_pos = self._prison_position()

        if state == "escorting" and prison_pos is None:
            self._clear_arrest()
            return
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
                self.play_ui_sound(self.rng.choice(ARREST_SOUNDS))
                player = fio.player(self.logic)
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
            guard.properties["awake"] = False
            self.flash_head_mark(guard, "!")
            self.bark(guard, self.rng.choice(STOP_SHOUTS))
            # The law has it in hand now: whoever the player was fighting
            # stands down rather than brawling on round the guard.
            self._calm_player_brawl()

    def _calm_player_brawl(self) -> None:
        """Townsfolk who were fighting the player stop once a guard steps in.
        Real enemies (bandits, monsters) do not: they are not the watch's to
        calm, they are the watch's to fight."""
        player_id = id(self.player_actor)
        for t in self._actors:
            p = t.properties
            if p.get("triggered", True) or p.get("dead"):
                continue
            if self._is_guard(t) or p.get("_journey_hostile"):
                continue
            # Wolves, bears, monsters, bandits: hostile by nature, not
            # because of a brawl, so not the watch's to calm.
            if self._natively_hostile(p):
                continue
            # Only those actually fighting the player.
            if not (p.get("_aggro_target") == player_id
                    or str(p.get("aggression")) == "hostile"):
                continue
            p["triggered"] = True
            p["awake"] = False
            p.pop("_aggro_target", None)
            base = p.pop("_base_aggression", None)
            p["aggression"] = base if base else ("defensive" if p.get("combatant")
                                                 else "passive")

    @staticmethod
    def _natively_hostile(p) -> bool:
        """Hostile by nature (a wolf, a bandit) rather than provoked into it.
        Provocation records the aggression an actor had before
        (``_base_aggression``); without that, hostility toward the player is
        native for the factions at war with the player and for beasts and
        monsters."""
        if str(p.get("aggression")) != "hostile":
            return False
        base = p.get("_base_aggression")
        if base is not None:
            return str(base) == "hostile"
        team = str(p.get("faction") or p.get("team") or "")
        return factions.is_hostile("player", team) or team in ("wildlife", "monsters")

    @staticmethod
    def _provoke(p) -> None:
        """Remember an actor's own aggression before it turns hostile, so it
        can be restored when the fight is called off."""
        if str(p.get("aggression")) != "hostile":
            p.setdefault("_base_aggression", str(p.get("aggression") or "passive"))

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
        tree = self._arrest_tree_full(guard, bounty, name)
        if self._prison_position() is None:
            # No cell to be taken to: surrendering means paying what you can.
            for node in tree["nodes"].values():
                node["responses"] = [
                    r for r in node["responses"]
                    if not any(a.get("op") == "begin_escort" for a in r.get("actions", []))]
                if not any(any(a.get("op") == "pay_bounty" for a in r.get("actions", []))
                           for r in node["responses"]):
                    node["responses"].insert(0, {
                        "text": f"Pay what I owe ({min(bounty, self.game.character.gold)} gold).",
                        "goto": "END", "actions": [{"op": "pay_bounty"}]})
        return tree

    def _arrest_tree_full(self, guard, bounty, name):
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
        if getattr(self, "_arrest_pursuers", None):
            self._end_arrest_pursuit()
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
            if self._prison_position() is None:
                # Nowhere to lock you up: the watch takes every coin you have
                # and lets you go with a warning.
                taken = int(self.game.character.gold)
                self.game.add_gold(-taken)
                self.game.character.bounty = 0
                self.notify(f"The guard takes all you have ({taken} gold). "
                            "\"Don't let me see you again.\"", 4.5)
                self._clear_arrest()
                return
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
        """Run the player down after they break away from an escort or refuse arrest.

        Every guard within :data:`GUARD_PURSUIT_RADIUS` turns hostile, which
        hands them to the combat AI to fight with once they can see the player.
        But the combat AI only engages what it has line of sight to, so on its
        own a guard loses you the moment you round a corner and simply stands
        there. So the guards also enter a runtime-driven ``pursuit``: their
        destination is refreshed to the player's position every decision pass,
        and they keep coming — through doorways, round buildings — until the
        bounty is settled or they are put down.
        """
        player_pos = self._player_pos()
        if player_pos is None:
            return
        radius2 = GUARD_PURSUIT_RADIUS * GUARD_PURSUIT_RADIUS
        pursuers = []
        for guard in self.npcs():
            if not self._is_guard(guard) or guard.properties.get("dead"):
                continue
            dx = guard.pos[0] - player_pos[0]
            dz = guard.pos[2] - player_pos[2]
            if dx * dx + dz * dz > radius2:
                continue
            p = guard.properties
            p["_arrest_state"] = "pursuit"
            p["_dest"] = list(player_pos)
            p["aggression"] = "hostile"
            p["triggered"] = False
            p["awake"] = True
            p["wake_on_sight"] = True
            pursuers.append(guard)
        self._arrest_guard = None
        self._arrest_state = "pursuit" if pursuers else ""
        self._arrest_pursuers = pursuers
        self._arrest_notice_sent = False
        self.notify("You broke away from the escort. The guards give chase!", 5.0)

    def _update_arrest_pursuit(self) -> None:
        """Keep the chase alive, and call it off when it is over.

        Runs on the arrest pass, which is already once per tick, and does one
        dict lookup per pursuing guard — a handful at most. Where the guards are
        actually headed is only rewritten on the decision pass (see _decide), so
        this is not a per-tick path recompute.
        """
        alive = []
        for guard in self._arrest_pursuers:
            p = getattr(guard, "properties", None)
            if not isinstance(p, dict) or p.get("dead"):
                continue
            if p.get("_arrest_state") != "pursuit":
                continue        # something else claimed this guard
            alive.append(guard)
        self._arrest_pursuers = alive
        if not alive:
            self._arrest_state = ""
            return
        # The chase ends when the debt is settled — paid, served, or forgiven.
        if int(getattr(self.game.character, "bounty", 0) or 0) <= 0:
            self._end_arrest_pursuit()

    def _end_arrest_pursuit(self) -> None:
        """Call off the chase and send the guards back to their posts."""
        for guard in getattr(self, "_arrest_pursuers", []) or []:
            p = getattr(guard, "properties", None)
            if not isinstance(p, dict):
                continue
            p.pop("_arrest_state", None)
            p.pop("_dest", None)
            p["aggression"] = "defensive"
            p["triggered"] = True
            p["awake"] = False
        self._arrest_pursuers = []
        self._arrest_state = ""
        self._arrest_notice_sent = False

    def _complete_escort(self, prison_pos) -> None:
        """Deliver a player who stayed with the guard to the prison marker."""
        player = fio.player(self.logic)
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

    # ==================================================== reactive simulation
    # The seam between the live scene and :mod:`game.sim`. Everything below is
    # glue: identity, who can observe, emitting events at the points where the
    # game already knows something happened, and turning the director's ranked
    # intents into the same movement/combat handles the schedule already uses.
    # No scenario logic lives here — a new event kind or a new reaction needs
    # no change to this file beyond the one line that emits it.

    def _sim_disposition(self, observer_props: Dict, other_key: str) -> int:
        """How *observer_props* feels about another actor, for appraisal.

        Reuses the existing opinion model (:mod:`game.rpg.disposition`) rather
        than inventing a second one; only the player has a modelled standing, so
        anyone else reads as neutral."""
        if other_key == PLAYER_KEY:
            try:
                return disp.of(self.game.character, observer_props, self.store)
            except Exception:
                return 50
        return 50

    def _sim_on_bounty(self, amount: int, event, reporter_key: str) -> None:
        """A charge was laid against the player: add it to the existing bounty.

        The bounty purse, the arrest flow and the guard escort are all already
        MiniWind systems (see ``_update_arrest``); the simulation only decides
        *whether and when* a crime reaches them."""
        amount = max(0, int(amount))
        if amount <= 0:
            return
        self.game.character.bounty += amount
        kind = getattr(event, "kind", "crime")
        self.notify(f"Word reaches the watch: your bounty rises by {amount} gold "
                    f"({kind}).", 5.0)
        self.game.message(f"A witness reported the {kind} to the watch "
                          f"(+{amount} bounty).")

    @property
    def player_actor(self):
        """The player as an ordinary simulation actor.

        Wrapping the engine player in the same ``.pos`` / ``.properties`` shape
        every other actor has is what lets NPCs witness, remember and gossip
        about the player with no player-specific branch anywhere in
        :mod:`game.sim`."""
        actor = getattr(self, "_player_actor", None)
        if actor is None:
            actor = _PlayerActor(self)
            self._player_actor = actor
        actor.refresh()
        return actor

    def _sim_actors(self) -> List:
        """Everyone the simulation considers: living NPCs, creatures, the player.

        Built from the same cached type index the rest of the tick uses, so it
        costs no extra scan of the scene."""
        buckets = self._type_buckets()
        out = [t for t in _chain(buckets.get("npc", ()), buckets.get("creature", ()),
                                 buckets.get("monster", ()))
               if not t.properties.get("dead", False)]
        player = self.player_actor
        if player.pos is not None:
            out.append(player)
        return out

    def _sim_observers(self) -> List:
        """Who could perceive an event right now.

        The dead are excluded by ``_sim_actors``, and so are the DORMANT --
        actors the world streamer has parked are not there to see anything;
        perception itself decides who was near enough, awake enough and
        sighted enough."""
        tier_of = self._tier_of
        return [t for t in self._sim_actors() if tier_of(t) < TIER_DORMANT]

    def _sim_by_tier(self):
        """``(near, distant)``: the reactive simulation's two levels of detail.

        NEAR and ACTIVE actors (and the player, always) are simulated in full;
        DISTANT ones get the director's coarse pass; DORMANT ones -- parked by
        the streamer -- are in neither and catch up when they come back."""
        near, distant = [], []
        tier_of = self._tier_of
        player = self.player_actor
        for thing in self._sim_actors():
            tier = TIER_NEAR if thing is player else tier_of(thing)
            if tier <= TIER_ACTIVE:
                near.append(thing)
            elif tier == TIER_DISTANT:
                distant.append(thing)
        return near, distant

    def _sim_producer_of(self, item_props: Dict):
        """The producing object an item pickup came from, if it is still there.

        Used to tell a cow its milk was collected so it starts on the next one —
        the only coupling between production and the world item it made."""
        pid = item_props.get("_produced_by")
        if not pid:
            return None
        for thing in self._sim_actors():
            if id(thing) == pid:
                return thing
        return None

    def _sim_actor_by_key(self, key: str):
        """Resolve an identity key back to a live actor, or None if they are
        gone — which is exactly how a vendetta against a dead man expires."""
        if not key:
            return None
        if key == PLAYER_KEY:
            return self.player_actor
        for thing in self._sim_actors():
            if actor_key(thing) == key:
                return thing
        return None

    def _sim_is_crime_against(self, target) -> bool:
        """Whether harming *target* is an offence rather than legitimate combat.

        One rule for every attacker: hurting somebody your side is not at war
        with is a crime. A guard cutting down a bandit is not; the player
        cutting down a farmer is. No list of protected characters, no quest
        flags."""
        tp = getattr(target, "properties", {}) or {}
        if tp.get("aggression") == "hostile":
            return False
        team = tp.get("team") or tp.get("faction")
        return not factions.is_hostile("player", team)

    def emit_event(self, kind: str, actor=None, target=None, **data):
        """Emit a world event through the director (the one public entry point).

        Console commands, the editor's *Simulate Event* tool and the runtime's
        own choke points all come through here, so an injected event is
        indistinguishable from one the game produced."""
        if actor is None:
            actor = self.player_actor
        return self.director.emit(kind, actor=actor, target=target,
                                  observers=self._sim_observers(), **data)

    def _tick_sim(self, delta: float) -> None:
        """Advance rumour propagation, crime reporting and production.

        Driven by *game hours* rather than frames so the world's information
        network runs at the same pace whatever the frame rate or time scale."""
        hour = float(self.clock.hour)
        elapsed = hour - self._sim_last_hour
        if elapsed < 0:
            elapsed += 24.0          # midnight wrap
        self._sim_last_hour = hour
        self._sim_hours += elapsed
        if self._sim_hours < 0.01:
            return
        hours, self._sim_hours = self._sim_hours, 0.0
        near, distant = self._sim_by_tier()
        self.director.tick(near, hours, distant=distant)
        for producer, yielded in self.director.drain_yields():
            self._place_yield(producer, yielded)

    def _place_yield(self, producer, yielded) -> None:
        """Put a produced item into the world as an ordinary Item pickup.

        The yield is a normal MiniWind ``ItemPickup`` carrying the producer's
        owner, so from here on it is just an item: it can be taken, and taking
        it is a theft if it was not yours. No special "milk" handling exists
        anywhere in the game."""
        into = str(producer.properties.get("produce_into", sim_prod.INTO_WORLD))
        if into == sim_prod.INTO_SELF:
            stack = rpg_items.make(yielded.item_id, yielded.quantity) or \
                inv.make_item(yielded.item_id, qty=yielded.quantity)
            inv.add_item(inv.get_inventory(producer), stack)
            sim_prod.note_collected(producer.properties, 1)
            return
        try:
            from .entities import ItemPickup
        except Exception:
            return
        try:
            offset = self.rng.uniform(-40.0, 40.0)
            pos = [producer.pos[0] + offset, producer.pos[1],
                   producer.pos[2] + self.rng.uniform(-40.0, 40.0)]
            item = ItemPickup(pos)
            item.properties.update({
                "item_id": yielded.item_id,
                "quantity": yielded.quantity,
                "display_name": yielded.item_id.replace("_", " ").title(),
                "_produced_by": id(producer),
            })
            sim_own.set_owner(item.properties, yielded.owner, yielded.owner_name,
                              yielded.owner_faction)
            fio.things(self.logic).append(item)
            self._type_index_token = None      # force the type index to rebuild
        except Exception:
            return
        self.director.emit("produce", actor=producer, pos=list(producer.pos),
                           observers=self._sim_observers(),
                           item=yielded.item_id,
                           item_name=item.properties["display_name"])

    # -- turning intents into behaviour --------------------------------------
    def _apply_sim_intent(self, npc) -> bool:
        """Let what this NPC *knows* override its daily schedule.

        Returns True when the intent claimed this decision tick. Every branch
        reuses a movement/combat handle the settlement AI already has
        (``_aggro_target``, ``_dest``, ``aggression``, ``sched_state``), so the
        simulation never needs its own mover or its own combat."""
        p = npc.properties
        intent = self.director.top_intent(npc)
        if intent is None:
            p.pop("_sim_reason", None)
            p.pop("_sim_intent", None)
            return False
        # Always publish the reasoning, even for intents that do not seize
        # control — this is what the Live Simulation Inspector reads.
        p["_sim_intent"] = intent.reaction
        p["_sim_reason"] = intent.reason
        p["_sim_target"] = intent.target_name

        offender = self._sim_actor_by_key(intent.target)
        if offender is None:
            return False

        if intent.reaction in (sim_appraisal.FIGHT, sim_appraisal.ARREST):
            # An ARREST of the player is the existing bounty/arrest flow's job
            # (a guard should not simply murder a wanted man), so it is left to
            # ``_update_arrest``; everything else is ordinary combat.
            if intent.reaction == sim_appraisal.ARREST and offender is self.player_actor:
                return False
            return self._sim_engage(npc, offender)

        if intent.reaction == sim_appraisal.FLEE:
            p["sched_state"] = sched.FLEE
            p["_flee"] = True
            self._set_rally(npc, False)
            p["_dest"] = self._refuge_point(npc, offender)
            return True

        if intent.reaction == sim_appraisal.REPORT:
            return self._sim_go_report(npc)

        if intent.reaction == sim_appraisal.CONFRONT:
            if offender is self.player_actor or offender.properties.get("dead"):
                return False
            p["sched_state"] = sched.CONFRONT
            p["_dest"] = list(offender.pos)
            return True

        # MOURN / WARM / IGNORE colour how an NPC feels and reads in the
        # inspector, but they do not seize the body — grief should not freeze a
        # town for a week, and gratitude is expressed through disposition.
        return False

    def _sim_engage(self, npc, offender) -> bool:
        """Send *npc* after *offender* using the engine's live combat AI."""
        p = npc.properties
        p["awake"] = True
        p["triggered"] = False
        p["sched_state"] = sched.COMBAT
        p.pop("_flee", None)
        self._set_rally(npc, False)
        if offender is self.player_actor:
            # The engine MonsterAI hunts the player when an actor is hostile.
            self._provoke(p)
            p["aggression"] = "hostile"
            p["wake_on_sight"] = True
        else:
            p["_aggro_target"] = id(offender)
        return True

    def _sim_go_report(self, npc) -> bool:
        """Walk a witness to the nearest guard so they can give their account.

        The report itself is resolved by the director when the two are close
        enough — so a witness cut down on the way never testifies, and one who
        makes it does. That is the whole mechanism."""
        p = npc.properties
        guard = self._nearest_guard(npc)
        if guard is None:
            return False
        if self._dist2d(npc.pos, guard.pos) <= REPORT_ARRIVE_RADIUS:
            p["sched_state"] = sched.REPORT
            p.pop("_dest", None)
            return True
        p["sched_state"] = sched.REPORT
        p["_dest"] = list(guard.pos)
        return True

    def _decide(self, npc) -> None:
        p = npc.properties
        if p.get("_journey") and not p.get("_arrest_state") and self.living is not None:
            return          # a traveller: its party is driven by game/living
        if p.get("away_on_journey"):
            return          # away on a trip; a stand-in walks the road

        # Arrest movement is owned by the runtime, not the normal schedule or
        # MonsterAI. The guard remains visible and walks to the player/prison.
        arrest_state = p.get("_arrest_state")
        if arrest_state in ("approach", "ready", "escorting") and self._is_combatant(npc):
            # A real enemy outranks a warrant: a guard on his way to arrest
            # the player still cuts down the bandits chasing them first, and
            # picks the arrest up again afterwards.
            enemy = self._nearest_hostile(npc, self._defend_sight(p))
            if enemy is not None:
                if p.get("sched_state") != sched.COMBAT:
                    self.flash_head_mark(npc, "!")
                self._engage(npc, enemy)
                return
        if arrest_state == "pursuit":
            # A pursuing guard is hostile, so the combat AI owns him whenever he
            # can see the player. This only refreshes where he is headed, so he
            # keeps closing when sight is broken instead of stopping at the
            # corner the player ran round.
            player_pos = self._player_pos()
            if player_pos is not None:
                p["_dest"] = player_pos
            p["sched_state"] = "PURSUE"
            return
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
            defend_sight = self._defend_sight(p)
            subduing = p.get("_subduing")
            if subduing is not None:
                target = next((t for t in self._actors if id(t) == subduing), None)
                if target is None or self._subdued(target):
                    if target is not None:
                        self._break_up(npc, target)
                    else:
                        p.pop("_subduing", None)
                    return
            enemy = self._nearest_hostile(npc, defend_sight)
            brawler = None
            if enemy is None:
                # Nothing his faction calls an enemy — but a fight happening in
                # front of a guard is still his business, whoever is in it.
                brawler = enemy = self._fight_to_break_up(npc, defend_sight)
            if brawler is not None and self._is_guard(npc) and \
                    not factions.is_hostile(p.get("faction") or p.get("team"),
                                            brawler.properties.get("faction")
                                            or brawler.properties.get("team")):
                # One of his own townsfolk in a scuffle: he breaks it up --
                # wades in, and once the fight is knocked out of them, stops.
                # A watchman does not kill a man for a brawl.
                opponent_id = brawler.properties.get("_aggro_target")
                opponent = next((t for t in self._actors if id(t) == opponent_id), None)
                if self._subdued(brawler) or (opponent is not None
                                              and self._subdued(opponent)):
                    # Somebody is already down: the brawl is over.
                    self._break_up(npc, brawler)
                    return
                p["_subduing"] = id(brawler)
            else:
                p.pop("_subduing", None)
            if enemy is not None:
                # Give the core MonsterAI the exact intruder found by the
                # settlement scan. This avoids waiting for a second perception
                # pass and makes a returning bandit immediately actionable.
                if p.get("sched_state") != sched.COMBAT and self._is_guard(npc):
                    self.flash_head_mark(npc, "!")
                    self.bark(npc, self.rng.choice(
                        BREAK_UP_SHOUTS if brawler is not None else CHARGE_SHOUTS))
                self._engage(npc, enemy)
                return
            elif p.get("sched_state") == sched.COMBAT:
                p.pop("_aggro_target", None)
                p.pop("_subduing", None)
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
                    self._set_rally(npc, True)
                    p.pop("_flee", None)
                    return
                if conf >= _FLEE_THRESHOLD:
                    p["sched_state"] = sched.ALERT
                    self._set_rally(npc, False)
                    p.pop("_flee", None)
                    p.pop("_dest", None)
                    return
                p["sched_state"] = sched.FLEE
                p["_flee"] = True
                self._set_rally(npc, False)
                p["_dest"] = self._refuge_point(npc, threat)
                return
            if p.get("_rally"):
                p["triggered"] = True
                p["awake"] = False
                self._set_rally(npc, False)
            p.pop("_flee", None)

        # (c.7) REACTIVE SIMULATION: nothing physically urgent is happening —
        #     no arrest, no enemy in reach, nothing to flee from. Now what this
        #     actor *knows* gets its say. A witness walks to the watch; a
        #     grieving brother goes after the killer; a coward stays hidden.
        #     Deliberately placed after the immediate combat/flee reactions (a
        #     bandit in the square outranks a week-old grudge) and before the
        #     schedule, because a person with a reason does not go to work.
        if self._apply_sim_intent(npc):
            return

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

        entry = self._schedule_entry(npc)
        if entry is None:
            self._idle_or_wander(npc)
            return
        state = entry.get("state", sched.IDLE)
        loc_key = entry.get("location", "home")

        # (c.5) NEEDS: for civilian townsfolk, advance persistent fatigue/hunger
        #     with the hours that have passed and let a strong need bend the
        #     authored plan — an exhausted farmer naps, a hungry worker slips
        #     home to eat — so no two days play out identically. Combatants
        #     (guards on duty) are exempt: they hold their posts. The base state
        #     is re-read from the schedule every tick, so an override lapses on
        #     its own once the need is met.
        if not self._is_combatant(npc):
            self._advance_needs(npc, state)
            new_state, reason = rpg_needs.apply(p, state, self.clock.hour)
            if reason:
                state = new_state
                loc_key = "home"
                p["_need_reason"] = reason
            else:
                p.pop("_need_reason", None)

        # (d) PATROL: an on-duty guard/combatant with an authored patrol circuit
        #     walks between its markers rather than standing at one work spot, so
        #     the town has a visibly moving watch. Combat (b) pre-empts this; the
        #     guard resumes the circuit afterwards from where it left off.
        if state in (sched.WORKING, sched.GOING_TO_WORK) and p.get("patrol_markers"):
            if self._patrol(npc):
                return
        p["sched_state"] = state
        dest = self._resolve_location(npc, loc_key)
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

    @staticmethod
    def _defend_sight(p) -> float:
        try:
            return max(DEFEND_SIGHT, float(p.get("sight_range", DEFEND_SIGHT)))
        except (TypeError, ValueError):
            return DEFEND_SIGHT

    def _engage(self, npc, enemy) -> None:
        """Send a combatant at *enemy* through the core combat AI."""
        p = npc.properties
        p["_aggro_target"] = id(enemy)
        p["triggered"] = False
        p["awake"] = True
        p["sched_state"] = sched.COMBAT
        p.pop("_flee", None)

    @staticmethod
    def _subdued(actor) -> bool:
        """Whether a brawler has had the fight knocked out of them."""
        p = actor.properties
        if p.get("dead"):
            return True
        if p.get("health") is None:
            return False
        try:
            hp = float(p.get("health"))
            top = float(p.get("max_health") or hp or 1)
        except (TypeError, ValueError):
            return False
        return hp <= top * SUBDUE_FRACTION

    def _break_up(self, guard, brawler) -> None:
        """End a brawl: the brawler and whoever they were fighting stand down,
        and so does the guard. Nobody dies of it."""
        calm = [brawler]
        target_id = brawler.properties.get("_aggro_target")
        for t in self._actors:
            if id(t) == target_id or t.properties.get("_aggro_target") == id(brawler):
                calm.append(t)
        for t in calm:
            tp = t.properties
            if tp.get("dead") or t is self.player_actor:
                continue
            tp.pop("_aggro_target", None)
            if not self._natively_hostile(tp):
                tp["triggered"] = True
                tp["awake"] = False
                base = tp.pop("_base_aggression", None)
                tp["aggression"] = base if base else (
                    "defensive" if tp.get("combatant") else "passive")
        gp = guard.properties
        gp.pop("_aggro_target", None)
        gp.pop("_subduing", None)
        gp["triggered"] = True
        gp["awake"] = False
        gp["sched_state"] = sched.IDLE
        self.bark(guard, self.rng.choice(SUBDUED_SHOUTS))

    # ---------------------------------------------------------------- barks
    def bark(self, thing, text, seconds: float = BARK_SECONDS) -> None:
        """Have *thing* say *text* aloud for a moment, over its head. Only
        those near enough to be on screen bother; the HUD draws them."""
        if thing is None or not text:
            return
        ppos = self._player_pos()
        if ppos is not None and self._dist2d(thing.pos, ppos) > BARK_RADIUS:
            return
        import time as _time
        barks = self.__dict__.setdefault("barks", {})
        barks[id(thing)] = (thing, str(text), _time.monotonic() + float(seconds))

    def live_barks(self):
        """``[(thing, text, seconds_left)]`` still being said."""
        import time as _time
        now = _time.monotonic()
        barks = self.__dict__.get("barks") or {}
        out = []
        for key, (thing, text, until) in list(barks.items()):
            if until <= now or thing.properties.get("dead"):
                barks.pop(key, None)
                continue
            out.append((thing, text, until - now))
        return out

    def _decide_distant(self, npc) -> None:
        """The reduced decision path for an actor outside the player's vicinity.

        What a distant townsperson still does is what the *clock* makes them do:
        their schedule turns over, their needs advance with the hours, and they
        walk to wherever that puts them. What they no longer do is look around —
        no threat scan, no confidence calculation, no fight to break up, no
        appraisal of what they know. None of that can produce anything the
        player is in a position to observe, and all of it is per-actor work that
        scales with the size of the settlement.

        Deliberately *not* skipped: an arrest in progress (the flow owns those
        actors wherever they are) and a patrol circuit (a guard who stopped
        patrolling would be found standing still on arrival). Both are cheap.

        The moment the player comes near, the actor is promoted to a live tier
        and the full path resumes from whatever state this left them in — the
        state is the same state, only reached more coarsely.
        """
        p = npc.properties
        if p.get("_journey") or p.get("away_on_journey"):
            return

        if p.get("_arrest_state"):
            self._decide(npc)              # the arrest flow owns this one
            return

        if str(p.get("aggression")) == "hostile" and not p.get("triggered", False):
            p["sched_state"] = sched.COMBAT
            return

        entry = self._schedule_entry(npc)
        if entry is None:
            # Nothing authored: leave them where they are rather than paying for
            # a wander nobody can see.
            p.pop("_dest", None)
            return
        state = entry.get("state", sched.IDLE)
        loc_key = entry.get("location", "home")

        if not self._is_combatant(npc):
            self._advance_needs(npc, state)
            new_state, reason = rpg_needs.apply(p, state, self.clock.hour)
            if reason:
                state = new_state
                loc_key = "home"
                p["_need_reason"] = reason
            else:
                p.pop("_need_reason", None)

        if state in (sched.WORKING, sched.GOING_TO_WORK) and p.get("patrol_markers"):
            if self._patrol(npc):
                return
        p["sched_state"] = state
        dest = self._resolve_location(npc, loc_key)
        if dest is not None:
            p["_dest"] = list(dest)
            p.pop("_wander_dest", None)
        else:
            # An idle actor with nowhere authored simply stands: the local
            # wander exists to make the town look alive, and nobody is looking.
            p.pop("_dest", None)

    def _schedule_entry(self, npc):
        """The NPC's schedule entry in effect, cached until it can change.

        A schedule is a table of timestamps, so its answer only moves when the
        clock crosses the next entry's hour — but it used to be re-derived (and
        the table re-sorted) for every NPC on every decision pass. The entry and
        the window it holds for are cached on the NPC and re-asked only when the
        clock leaves that window, which is the difference between a schedule
        that transitions on events and one that is continuously recalculated.
        """
        p = npc.properties
        schedule = p.get("schedule") or ()
        hour = self.clock.hour
        cached = p.get("_sched_entry_cache")
        if (cached is not None and cached[3] == len(schedule)
                and sched.window_holds(hour, cached[1], cached[2])):
            return cached[0]
        entry, start, end = sched.evaluate_window(schedule, hour)
        p["_sched_entry_cache"] = (entry, start, end, len(schedule))
        return entry

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

    def _advance_needs(self, npc, current_state) -> None:
        """Advance a civilian NPC's persistent needs by the in-game hours passed
        since its last decision, using the state it was actually in.

        The last-advanced timestamp is a transient underscore field (dropped by
        the serializer), so a loaded save simply re-baselines on its first tick
        while the *needs themselves* — ``need_fatigue`` / ``need_hunger`` — persist
        as ordinary properties. Per-NPC appetite/stamina are seeded once here."""
        p = npc.properties
        rpg_needs.seed(p, self.rng)
        abs_now = float(self.clock.day) * 24.0 + float(self.clock.hour)
        last = p.get("_need_t")
        p["_need_t"] = abs_now
        if last is None:
            return
        try:
            hours = abs_now - float(last)
        except (TypeError, ValueError):
            return
        if hours <= 0.0:
            return
        # What the NPC has been doing since the last decision (this call runs
        # before p["sched_state"] is updated for the new decision).
        prev_state = str(p.get("sched_state") or current_state)
        rpg_needs.advance(p, hours, prev_state)

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
        guard = self._nearest_guard(npc)
        if guard is not None:
            candidates.append([guard.pos[0], npc.pos[1], guard.pos[2]])
        post = self._nearest_in(self._markers_of_kind("guardpost"), npc)
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
        """A living actor who acts on crime — the settlement's law.

        Recognised by :func:`game.sim.crime.is_lawful` (guard role, the guards
        faction, or an authored ``lawful`` flag), so an authored bailiff or a
        modded temple warden is a guard everywhere at once: refuge-seeking,
        arrests and crime reporting all ask the same question."""
        p = thing.properties
        return sim_crime.is_lawful(p) and not p.get("dead")

    @staticmethod
    def _marker_kind(thing) -> str:
        p = thing.properties
        if str(p.get("type", "")).replace("_", "").lower() != "marker":
            return ""
        return str(p.get("marker_kind", "")).lower()

    def _markers_of_kind(self, kind: str) -> list:
        """Markers with the given authored ``marker_kind``, grouped and cached.

        Markers are static scenery: their kinds only change when the scene does.
        Grouping them once turns "where is the nearest guard post" from a walk
        of every entity in the world — re-normalising each one's type string —
        into a lookup plus a short list, which matters because a panicking
        townsperson asks it every decision pass.
        """
        markers = self._things_of_type("marker")
        token = (id(markers), len(markers))
        if token != self._marker_kinds_token:
            groups: Dict[str, list] = {}
            for m in markers:
                k = str(m.properties.get("marker_kind", "")).lower()
                groups.setdefault(k, []).append(m)
            self._marker_kinds = groups
            self._marker_kinds_token = token
        return self._marker_kinds.get(kind, ())

    @staticmethod
    def _nearest_in(pool, npc):
        """Nearest thing in *pool* (2D XZ), excluding *npc* itself."""
        best, best_d = None, float("inf")
        npos = npc.pos
        for t in pool:
            if t is npc:
                continue
            dx = t.pos[0] - npos[0]
            dz = t.pos[2] - npos[2]
            d = dx * dx + dz * dz
            if d < best_d:
                best, best_d = t, d
        return best

    def _nearest_guard(self, npc):
        """The nearest member of the watch, from the decision pass's snapshot."""
        return self._nearest_in(self._guards, npc)

    def _nearest_of(self, npc, predicate):
        """Nearest live thing (2D) satisfying *predicate*, excluding *npc*.

        The general form, kept for callers with a one-off predicate. The two
        that ran every decision pass — "nearest guard" and "nearest guard post"
        — have their own indexed versions above and no longer come through here.
        """
        best, best_d = None, float("inf")
        npos = npc.pos
        for t in fio.things(self.logic):
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
        """The first thing called exactly *name*, or None.

        Schedules ask this for every NPC on every decision pass (work places,
        patrol markers), so it reads a name -> thing dict rebuilt only when the
        scene's thing list changes, not a walk of the whole world per ask. A
        renamed thing is caught by checking the hit still carries the name."""
        things = fio.things(self.logic)
        token = (id(things), len(things))
        cached = getattr(self, "_exact_name_cache", None)
        if cached is None or cached[0] != token:
            index = {}
            for t in list(things):
                props = getattr(t, "properties", None)
                if isinstance(props, dict):
                    index.setdefault(str(props.get("name", "")), t)
            cached = self._exact_name_cache = (token, index)
        hit = cached[1].get(str(name))
        if hit is not None and str(hit.properties.get("name", "")) == str(name):
            return hit
        if hit is not None:
            self._exact_name_cache = None            # stale: a rename; rebuild next ask
        for t in things:
            if str(t.properties.get("name", "")) == name:
                return t
        return None

    def _refresh_actor_cache(self) -> None:
        """Snapshot live and dead combat actors once per decision pass.

        Also indexes the fights currently going on. An actor swinging at another
        actor carries ``_aggro_target`` — the engine sets it both when the AI
        picks a target and when a struck actor rounds on whoever hit it — so the
        fights in a settlement are already written down; this just reads them
        into pairs. Done here, once, rather than per guard: with several guards
        on duty a per-guard scan would multiply the same walk.
        """
        actors = []
        dead = []
        by_id = {}
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
                by_id[id(t)] = t
        fights = []
        for t in actors:
            tp = t.properties
            # Parked actors are not run by the combat AI, so a mark left on one
            # is a memory of a fight rather than a fight. Only live ones count.
            if tp.get("triggered", False):
                continue
            target = by_id.get(tp.get("_aggro_target"))
            if target is not None:
                fights.append((t, target))
        self._actors = actors
        #: (the list above, id -> actor over it), for per-tick passes that
        #: resolve an ``_aggro_target`` id without building their own map.
        self._actors_by_id = (actors, by_id)
        self._dead_actors = dead
        self._fights = fights
        # The watch, indexed once. A frightened villager looks for the nearest
        # guard to shelter behind and a witness looks for one to report to, and
        # both used to walk every entity in the scene to find one.
        self._guards = [t for t in actors if self._is_guard(t)]

    def _fight_to_break_up(self, npc, radius: float):
        """Whom a guard should take on to stop a fight near him, or None.

        A guard only ever engaged actors his *own faction* counts as enemies, so
        two NPCs could brawl in the street right in front of two guards and
        neither would move — nothing in the fight was an enemy of the watch, so
        as far as the guards were concerned nothing was happening. This is the
        missing rule: a fight within a guard's sight is his business, whatever
        the combatants' factions.

        Who he grabs, in order: never one of the watch — guards do not wade in
        against each other — then a stranger over one of his own, so a wolf or
        an unaligned thug mauling a townsman is the one who gets it. Between two
        of his own townsfolk neither is more guilty than the other as far as the
        state here can tell (a struck actor and a deliberate attacker both carry
        the same aggro mark), so he goes for whoever is nearer, which is what
        wading into a brawl looks like anyway.

        A fight the player is in is left alone: that belongs to the arrest flow,
        which arrests rather than lynches.
        """
        fights = getattr(self, "_fights", None)
        if not fights:
            return None
        my_faction = npc.properties.get("faction") or npc.properties.get("team")
        player = self.player_actor
        npos = npc.pos

        def _dist2(actor):
            dx = actor.pos[0] - npos[0]
            dz = actor.pos[2] - npos[2]
            return dx * dx + dz * dz

        best, best_d = None, radius * radius
        for first, second in fights:
            if first is npc or second is npc:
                continue                    # he is already in this one
            if first is player or second is player:
                continue                    # the player's fights are the arrest flow's
            # Distance first: a brawl across the settlement is not this guard's
            # business, and finding that out with two subtractions is far
            # cheaper than reasoning about who is lawful and whose faction is
            # whose. With several guards on duty that reasoning was being redone
            # for every fight in the world, per guard, every decision pass.
            if _dist2(first) > best_d and _dist2(second) > best_d:
                continue
            candidates = [a for a in (first, second)
                          if not sim_crime.is_lawful(a.properties)]
            if not candidates:
                continue                    # two guards: already being handled
            if len(candidates) > 1:
                strangers = [a for a in candidates if not factions.is_friendly(
                    my_faction, a.properties.get("faction") or a.properties.get("team"))]
                candidates = strangers if len(strangers) == 1 else candidates
            offender = min(candidates, key=_dist2)
            d = _dist2(offender)
            if d < best_d:
                best, best_d = offender, d
        return best

    # ------------------------------------------------- spatial relevance
    @staticmethod
    def _tier_of(actor) -> int:
        """This actor's simulation tier.

        Read straight off the actor, where the world index stamped it during
        this tick's rebuild: a single dict get, rather than hashing ``id(actor)``
        into the index and indexing a NumPy array — which matters because the
        tick asks this once or twice for every actor in the world.

        An actor the index has not classified (a headless unit test, the very
        first tick, LOD switched off) reads TIER_NEAR — fully simulated, the
        pre-LOD behaviour — so nothing ever silently loses simulation.
        """
        return actor.properties.get("_sim_tier", TIER_NEAR)

    def _world_index(self):
        """This tick's actor index, or None.

        None when the cast is too small to be worth indexing, or when a headless
        test pokes the session through a stub with no index: the scalar scans
        below then run exactly as they would without one. A built index that
        holds no live actors is the opposite answer, and means nothing in the
        world is currently relevant.

        Resolved once per tick and cached on the session: this is asked tens of
        thousands of times a second, and a ``getattr`` chain per ask is real
        money at settlement scale.
        """
        wi = self._wi_cache
        if wi is not None:
            return wi
        if not getattr(self, "_wi_live", False):
            return None
        wi = getattr(self, "world_index", None)
        if wi is None:
            return None
        self._wi_cache = wi
        return wi

    def _rel_mask(self, wi, my_faction, want):
        """Per-row boolean: live actors whose team is *want* to *my_faction*.

        The faction predicate runs once per distinct team name in the world
        (a handful), never once per candidate pair — that collapse is why the
        settlement AI stopped spending 40% of its budget in
        :func:`game.rpg.factions.relationship`.
        """
        import numpy as _np
        key = ("rel", want, my_faction)

        def _build():
            pred = factions.is_hostile if want == "hostile" else factions.is_friendly
            tbl = wi.team_relation_table(
                lambda name: 1 if pred(my_faction, name) else 0)
            n = wi.n
            return wi.alive[:n] & (tbl[wi.team_ids[:n]] == 1)
        return wi.derived(key, _build)

    def _combatant_mask(self, wi):
        """Per-row boolean: this actor can and will fight. Game policy
        (:func:`game.sim.appraisal.is_combatant`) evaluated once per actor per
        tick and shared by every query, instead of per candidate per NPC."""
        import numpy as _np

        def _build():
            return _np.fromiter(
                (sim_appraisal.is_combatant(a.properties) for a in wi.actors),
                dtype=bool, count=wi.n)
        return wi.derived("combatant", _build)

    def _live_actors(self):
        """Every actor the engine still considers part of the live world.

        The world index is built from exactly that set, so its rows *are* the
        answer — no second walk of the scene, and nothing the streamer has
        parked is ever visited. With no index (a small world, or a headless
        test) it falls back to the cached type buckets, which is what the code
        did before tiers existed.
        """
        wi = self._world_index()
        if wi is not None:
            return wi.actors
        buckets = self._type_buckets()
        return list(_chain(buckets.get("npc", ()), buckets.get("creature", ()),
                           buckets.get("monster", ())))

    def _live_npcs(self) -> List:
        """The live actors that are NPCs and not dead — what the tick drives."""
        wi = self._world_index()
        if wi is None:
            return self.npcs()
        return self._live_of_type(wi, "npc")

    def _type_ids(self, type_name) -> frozenset:
        """``id()`` of every thing in the *type_name* bucket, cached until the
        bucket changes, so membership is one set lookup per actor rather than a
        set built per tick."""
        bucket = self._type_buckets().get(type_name, ())
        cache = self._type_id_cache
        cached = cache.get(type_name)
        if cached is None or cached[0] is not bucket or cached[1] != len(bucket):
            cached = cache[type_name] = (bucket, len(bucket),
                                         frozenset(id(t) for t in bucket))
        return cached[2]

    def _live_of_type(self, wi, type_name) -> List:
        """The index's alive rows of one type, in row order.

        The alive mask already excludes the dead and whatever Big World has
        parked, so only the resident rows are visited."""
        ids = self._type_ids(type_name)
        actors = wi.actors
        return [actors[i] for i in np.flatnonzero(wi.alive[:wi.n]).tolist()
                if id(actors[i]) in ids]

    def _rally_mask(self, wi):
        """Per-row boolean: this actor has rallied. Built once per tick, so the
        social-contagion term costs one array read per candidate rather than a
        dict probe per candidate per frightened villager."""
        import numpy as _np

        def _build():
            return _np.fromiter(
                (bool(a.properties.get("_rally")) for a in wi.actors),
                dtype=bool, count=wi.n)
        return wi.derived("rally", _build)

    def _set_rally(self, npc, rallied: bool) -> None:
        """Set/clear an NPC's rallied flag and keep the cached mask in step.

        Rally is socially contagious *within* a decision pass — a villager who
        stands his ground emboldens the next one the loop reaches — so the mask
        cannot simply be frozen at the start of the tick. Patching the one row
        keeps that immediacy at O(1) instead of rebuilding the array.
        """
        p = npc.properties
        if rallied:
            p["_rally"] = True
        else:
            p.pop("_rally", None)
        wi = self._world_index()
        if wi is None:
            return
        mask = wi._derived.get("rally")
        if mask is None:
            return
        row = wi.row_of(npc)
        if row >= 0:
            mask[row] = rallied

    def _nearest_hostile(self, npc, radius: float):
        my_faction = npc.properties.get("faction") or npc.properties.get("team")
        npos = npc.pos
        wi = self._world_index()
        if wi is not None:
            row = wi.nearest(npos[0], npos[2], radius,
                             mask=self._rel_mask(wi, my_faction, "hostile"),
                             exclude_row=wi.row_of(npc))
            return wi.actors[row] if row >= 0 else None
        best, best_d = None, radius * radius
        # Prefer the cached actor list; fall back to a full scan if a caller runs
        # outside the decision pass (e.g. a unit test poking a single tick).
        pool = self._actors or (fio.things(self.logic))
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
        npos = npc.pos
        wi = self._world_index()
        if wi is not None:
            mask = self._rel_mask(wi, my_faction, "friendly") & self._combatant_mask(wi)
            row = wi.nearest(npos[0], npos[2], radius, mask=mask,
                             exclude_row=wi.row_of(npc))
            return wi.actors[row] if row >= 0 else None
        best, best_d = None, radius * radius
        pool = self._actors or (fio.things(self.logic))
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

        wi = self._world_index()
        if wi is not None:
            # One radius query over the shared index, then five vectorised
            # tallies over the candidate rows — instead of a full Python walk
            # of every actor in the world per frightened villager.
            import numpy as _np
            rows = wi.rows_near(nx, nz, FLEE_SIGHT)
            self_row = wi.row_of(npc)
            if self_row >= 0 and rows.size:
                rows = rows[rows != self_row]
            hostile = self._rel_mask(wi, my_faction, "hostile")[rows]
            friendly = self._rel_mask(wi, my_faction, "friendly")[rows]
            n_hostile = int(_np.count_nonzero(hostile))
            n_friendly = int(_np.count_nonzero(friendly))
            n_guards = int(_np.count_nonzero(friendly & self._combatant_mask(wi)[rows]))
            n_rallied = int(_np.count_nonzero(friendly & self._rally_mask(wi)[rows]))
            # Casualties are corpses of his own side in sight — `alive` excludes
            # them, so they need the dead mask and their own friendliness test.
            dead_rows = rows[wi.dead[rows]]
            if dead_rows.size:
                tbl = wi.team_relation_table(
                    lambda name: 1 if factions.is_friendly(my_faction, name) else 0)
                n_casualties = int(_np.count_nonzero(tbl[wi.team_ids[dead_rows]] == 1))
            else:
                n_casualties = 0
        else:
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
            speed *= FLEE_SPEED_MULTIPLIER   # a fright doubles the step
        # Round a wall rather than into it: once a step has been blocked (or a
        # route is being followed) head for the next corner of a route.
        nav = getattr(self, "nav", None)
        key = id(npc)
        if nav is not None and (p.get("_blocked_ticks") or nav.has_route(key)):
            way = nav.steer(key, pos, dest)
            wx, wz = way[0] - pos[0], way[2] - pos[2]
            wd = math.hypot(wx, wz)
            if wd > 1e-3:
                dx, dz, dist = wx, wz, wd
        step = min(speed * delta, dist)
        nx = pos[0] + dx / dist * step
        nz = pos[2] + dz / dist * step
        if not self._step_to(npc, nx, nz):
            # Nose against a wall with no way round it. Drop the destination so
            # the next decision pass picks something reachable instead of
            # grinding into the brush forever.
            blocked = int(p.get("_blocked_ticks", 0)) + 1
            p["_blocked_ticks"] = blocked
            if blocked >= NPC_BLOCKED_GIVE_UP_TICKS:
                p.pop("_dest", None)
                p.pop("_wander_dest", None)
                p["_blocked_ticks"] = 0
            return
        p["_blocked_ticks"] = 0
        # Turn to face the way it is walking. This has to go through
        # engine.facing: the renderer reads an actor's heading from the
        # transient '_facing' property (that is what Monster.get_render_state
        # snapshots for the head billboard, the overhead ground sprite and the
        # weapon overlay), so writing a bare 'angle' here left schedule-driven
        # NPCs sliding around the world without ever rotating.
        face_heading(p, dx, dz, delta)

    # ============================================================ bow draw
    def fist_in_hand(self) -> bool:
        """Whether the weapon in hand is a warrior's fist (game/warrior_fist.py)."""
        c = getattr(getattr(self, "game", None), "character", None)
        return c is not None and eq.equipped_id(c, rpg_items.SLOT_WEAPON) == warrior_fist.FIST

    def charge_in_hand(self) -> bool:
        """Whether the left mouse charges what is in hand: a bow's draw or a
        fist's gathered blow (hold for the pie, release to loose)."""
        return self.bow_in_hand() or self.fist_in_hand()

    def bow_in_hand(self) -> bool:
        """Whether the weapon in hand is a bow."""
        c = getattr(getattr(self, "game", None), "character", None)
        w = eq.weapon(c) if c is not None else None
        return bool(w) and w.get("kind") == rpg_items.KIND_BOW

    def bow_draw_input(self, what) -> None:
        """The view's left mouse, for the bow: "press" starts drawing it,
        "release" looses the arrow, "cancel" lowers it. Handled next tick."""
        self._bow_input.append(str(what))

    def _cancel_bow_draw(self) -> None:
        self.bow_charge = None

    def _update_bow_draw(self, delta) -> None:
        """Draw the bow while left mouse is held; loose on release.

        The longer it is held (up to BOW_FULL_DRAW_SECONDS) the further the
        arrow flies. Switching weapons, opening a screen or a conversation, or
        dying lowers the bow without loosing.
        """
        while self._bow_input:
            what = self._bow_input.popleft()
            if what == "press":
                if self.bow_charge is None and self._can_draw_bow():
                    self.bow_charge = 0.0
            elif what == "release":
                charge = self.bow_charge
                self.bow_charge = None
                if charge is not None:
                    if self.fist_in_hand():
                        warrior_fist.strike(self, charge)
                    else:
                        self._loose_drawn_arrow(charge)
            else:
                self._cancel_bow_draw()
        if self.bow_charge is None:
            return
        c = self.game.character
        if (not self.charge_in_hand() or c.is_dead or self.open_screen is not None
                or self.dialogue is not None):
            self._cancel_bow_draw()
            return
        full = (warrior_fist.FULL_CHARGE_SECONDS if self.fist_in_hand()
                else BOW_FULL_DRAW_SECONDS)
        self.bow_charge = min(1.0, self.bow_charge + max(0.0, float(delta)) / full)

    def _can_draw_bow(self) -> bool:
        c = self.game.character
        if c.is_dead:
            return False
        if self.fist_in_hand():
            return True
        if not self.bow_in_hand():
            return False
        if eq.ammo_for(c, eq.weapon(c)) is None:
            self.notify("Out of arrows!")
            return False
        return True

    def _loose_drawn_arrow(self, charge) -> bool:
        """Loose an arrow from a bow drawn to *charge* (0..1): the further it
        was drawn, the further the arrow flies."""
        c = self.game.character
        if c.is_dead or self._attack_cooldown > 0:
            return False
        if c.stamina < 4:
            self.notify("Too exhausted to attack")
            return False
        w = eq.weapon(c)
        speed = float(w.get("speed", 1.0)) if w else 1.0
        if not self.game.fire_arrow():
            return False
        self._attack_cooldown = max(0.25, 1.0 / max(0.4, speed))
        self._attack_anim_time = 0.2
        charge = min(1.0, max(0.0, float(charge)))
        self._spawn_player_arrow_projectile(
            BOW_MIN_RANGE + (BOW_MAX_RANGE - BOW_MIN_RANGE) * charge)
        return True

    # ================================================================ zoom
    def _zoom_ceiling(self) -> float:
        cam = fio.camera(self.logic)
        limit = getattr(cam, "overhead_height_limit", None)
        top = ZOOM_MAX_HEIGHT
        if limit is not None and float(limit) > 0.0:
            top = min(top, float(limit))
        return max(ZOOM_MIN_HEIGHT, top)

    def zoom(self, notches) -> None:
        """Zoom the top-down camera by *notches* of the mouse wheel: positive
        closer to the player's head, negative further away. The camera follows
        the player, so the zoom is always centred on them."""
        cam = fio.camera(self.logic)
        if cam is None or not notches:
            return
        current = self.zoom_height
        if current is None:
            current = float(getattr(cam, "overhead_height", 800.0) or 800.0)
        target = current / (ZOOM_STEP ** float(notches))
        self.zoom_height = min(self._zoom_ceiling(), max(ZOOM_MIN_HEIGHT, target))

    def _ease_zoom(self, delta) -> None:
        """Glide the camera toward the height the wheel asked for, and have
        Big World cover what the camera will see from there."""
        target = self.zoom_height
        cam = fio.camera(self.logic)
        if target is None or cam is None:
            return
        if target != getattr(self, "_reach_for", None):
            self._reach_for = target
            self._fit_bigworld_reach(cam, target)
        target = min(target, self._zoom_ceiling())
        height = float(getattr(cam, "overhead_height", target) or target)
        if abs(target - height) < 0.5:
            cam.overhead_height = target
            return
        blend = 1.0 - math.exp(-max(0.0, float(delta)) / ZOOM_EASE_SECONDS)
        cam.overhead_height = height + (target - height) * blend

    def _fit_bigworld_reach(self, cam, height) -> None:
        """Size Big World's resident area for the camera at *height*: the
        ground the view reaches scales with the camera's height, so it is read
        off the current footprint and scaled. Back to the map's own radius when
        that covers it."""
        try:
            fp = cam.overhead_ground_footprint()
            now = float(cam.effective_overhead_height())
        except Exception:
            return
        if not fp or now <= 0.0:
            return
        reach = float(fp[2]) if len(fp) > 2 else math.hypot(fp[0], fp[1])
        fio.set_bigworld_reach(self.logic,
                               reach * float(height) / now + ZOOM_REACH_MARGIN)

    def _ground_actors(self) -> None:
        """Stand every walking actor on the ground under it.

        The engine's AI finds the ground through brushes only, and neither it
        nor :meth:`_move` changes an actor's height on terrain: an actor kept
        the height it was placed or spawned at, so one that walked downhill,
        or stood where the ground was sculpted after it was placed, floated.
        Each actor's feet are put on :func:`fio.ground_height` -- the terrain
        or a floor on it -- whenever it has moved since last time. Flyers are
        left in the air.
        """
        logic = self.logic
        # The index's rows are this tick's resident actors (and corpses): a
        # parked actor is hidden and still, and is grounded when it comes back.
        wi = self._world_index()
        actors = wi.actors if wi is not None else fio.monster_things(logic)
        if not actors:
            return
        seen = self._grounded
        near = GROUND_RECHECK_DIST
        with fio.monster_lock(logic) or contextlib.nullcontext():
            for t in actors:
                p = t.properties
                if p.get("monster_type") == "flying":
                    continue
                pos = t.pos
                x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
                last = seen.get(id(t))
                if (last is not None and abs(last[0] - x) < near
                        and abs(last[1] - z) < near and abs(last[2] - y) < 0.5):
                    continue
                half = float(p.get("sprite_height", 128) or 128) * 0.5
                ground = fio.ground_height(logic, x, z,
                                           below=y - half + GROUND_STEP_UP)
                if ground is not None:
                    y = ground + half
                    if abs(y - float(pos[1])) > 0.5:
                        t.pos = [pos[0], y, pos[2]]
                seen[id(t)] = (x, z, y)

    def _blocked_by_wall(self, x, y, z) -> bool:
        """Whether an NPC-sized body at (x, y, z) would be inside a solid brush.

        Answered by the engine's spatial grid — the same one the combat AI and
        the player's own physics use, so it is a cell lookup rather than a scan
        over every brush, cheap enough to run per walking NPC per tick. With no
        grid (no play session) nothing is solid, which keeps the schedule
        testable off a live map.
        """
        ai = getattr(self.logic, "monster_ai", None)
        if ai is None:
            return False
        try:
            return ai._monster_overlaps_wall(float(x), float(y), float(z),
                                             NPC_WALL_MARGIN)
        except Exception:
            return False

    def _step_to(self, npc, nx, nz) -> bool:
        """Move *npc* to (nx, nz) if it can get there. True if it moved at all.

        Schedule-driven NPCs used to walk straight through walls: this mover set
        a position with no collision test at all, so a villager heading home cut
        through the house rather than round to the door. The step now mirrors
        what the combat AI does — take it whole if it is clear, otherwise slide
        along whichever axis is, which is what carries an actor along a wall to
        a doorway instead of sticking it to the brush.
        """
        pos = npc.pos
        y = pos[1]
        if not self._blocked_by_wall(nx, y, nz):
            npc.pos = [nx, y, nz]
            return True
        if not self._blocked_by_wall(nx, y, pos[2]):
            npc.pos = [nx, y, pos[2]]
            return True
        if not self._blocked_by_wall(pos[0], y, nz):
            npc.pos = [pos[0], y, nz]
            return True
        return False

    # ============================================================== teleport
    def cave_entrances(self):
        """``[(name, (x, y, z))]`` for every cave mouth in the loaded world,
        in cave order: where the cave's exit start stands, just outside it."""
        things = fio.things(self.logic)
        token = (id(things), len(things))
        cached = self.__dict__.get("_cave_entrances")
        if cached is not None and cached[0] == token:
            return cached[1]
        names, starts = {}, {}
        for t in things:
            p = getattr(t, "properties", None) or {}
            slug = p.get("_cave")
            if not slug:
                continue
            ttype = str(p.get("type", "")).replace("_", "").lower()
            if ttype == "marker" and p.get("place_name"):
                names[slug] = str(p["place_name"])
            elif ttype == "playerstart" or str(p.get("name", "")) == f"{slug}_exit":
                starts[slug] = (float(t.pos[0]), float(t.pos[1]), float(t.pos[2]))
        out = [(names.get(slug, slug), starts[slug]) for slug in sorted(starts)]
        self._cave_entrances = (token, out)
        return out

    def teleport_player(self, pos) -> bool:
        """Put the player at *pos* (x, y, z) at once, standing still."""
        import glm
        player = fio.player(self.logic)
        if player is None:
            return False
        player.pos = glm.vec3(float(pos[0]), float(pos[1]), float(pos[2]))
        player.velocity = glm.vec3(0, 0, 0)
        portals = getattr(self.logic, "portal_runtime", None)
        if portals is not None and hasattr(portals, "note_player_teleported"):
            portals.note_player_teleported()
        self._cancel_bow_draw()
        return True

    # ========================================================= player combat
    def _player_pos(self):
        p = fio.player(self.logic)
        if p is None:
            return None
        return [float(p.pos[0]), float(p.pos[1]), float(p.pos[2])]

    def _player_forward(self):
        p = fio.player(self.logic)
        if p is None:
            return (0.0, 0.0, 1.0)
        a = getattr(p, "angle", 0.0)
        return (math.sin(a), 0.0, math.cos(a))

    def _projectile_aim_point(self, start):
        """Where a projectile fired from *start* is sent: straight ahead, the
        way the player is facing, level with the ground (the game is played
        top-down). With mouse control on the player already faces the pointer,
        so this is the pointer's direction too. Damage resolves where the
        projectile actually lands.
        """
        fwd = self._player_forward()
        return (start[0] + fwd[0] * 1500.0, start[1], start[2] + fwd[2] * 1500.0)

    def _attackable(self, thing) -> bool:
        tp = thing.properties
        if tp.get("dead") or tp.get("hidden"):
            return False
        if tp.get("_reaper"):
            return False      # you do not get to swing at Death
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
        px, pz = ppos[0], ppos[2]
        reach2 = reach * reach
        # Only actors can be attackable, and the HUD asks this every frame:
        # walk the resident actors, not the whole scene, and measure before
        # asking who they are.
        for t in self._live_actors():
            pos = t.pos
            dx = pos[0] - px
            dz = pos[2] - pz
            d2 = dx * dx + dz * dz
            if d2 > reach2 or not self._attackable(t):
                continue
            dist = math.sqrt(d2)
            if dist < 1e-3:
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

    def fire_player_weapon(self, logic, mode: str) -> bool:
        """The engine's fire buttons, given MiniWind meaning.

        One button per hand. Primary fire (left) uses the main hand -- a bow
        looses an arrow, a crossbow a bolt, a staff channels its spell, a blade
        swings. Secondary fire (right) uses the off hand: the weapon in the
        shield slot when there is one, else it casts the active spell (which a
        Warrior cannot). Returns True: MiniWind always owns the shot, so Fio's
        hitscan weapon path never runs underneath it.
        """
        c = self.game.character
        if getattr(c, "is_dead", False):
            return True
        if mode == "secondary":
            if eq.offhand_weapon(c) is not None:
                self.do_attack("off")
            else:
                self.do_cast()
        else:
            self.do_attack()
        return True

    def do_attack(self, hand: str = "main") -> bool:
        """Strike with the weapon in *hand* ("main", or "off" when dual
        wielding): swing a blade, loose an arrow or a crossbow bolt, or
        channel a staff.

        Each hand is its own attack -- its own cooldown, hit roll and damage.
        A lone weapon's swing at a close, faced target always connects; a dual
        wielder's two blades each roll to hit, so an unpractised fighter can
        land one and miss with the other."""
        c = self.game.character
        off = hand == "off"
        cooldown = self._offhand_cooldown if off else self._attack_cooldown
        if c.is_dead or cooldown > 0:
            return False
        w = eq.hand_weapon(c, hand)
        if off and w is None:
            return False
        kind = w.get("kind", rpg_items.KIND_MELEE) if w else rpg_items.KIND_MELEE
        speed = float(w.get("speed", 1.0)) if w else 1.2
        reach = MELEE_REACH
        if kind in rpg_items.RANGED_KINDS:
            reach = BOW_REACH
        elif kind == rpg_items.KIND_STAFF:
            # a staff channels its bound spell
            return self._staff_attack(w)
        wait = max(0.25, 1.0 / max(0.4, speed))
        if off:
            self._offhand_cooldown = wait
            self._offhand_anim_time = 0.2
        else:
            self._attack_cooldown = wait
            self._attack_anim_time = 0.2   # quick forward stab, independent of cooldown
        if c.stamina < 4:
            self.notify("Too exhausted to attack")
            return False

        if kind in rpg_items.RANGED_KINDS:
            # A bow (from the keyboard) or a crossbow looses a real, physical
            # shot (see _spawn_player_arrow_projectile) rather than resolving
            # instantly: it flies, can miss by sailing past a moving target,
            # gets stopped by walls, and lands (and its damage is rolled) only
            # once it actually strikes something. A crossbow needs no draw.
            if not self.game.fire_arrow(hand=hand):
                return False   # out of ammunition: fire_arrow already said so
            self._spawn_player_arrow_projectile(hand=hand)
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
        # plane, so a lone weapon's swing is guaranteed to connect. Two weapons
        # are two attacks, and each rolls to hit for itself.
        res = self.game.attack_creature(target.properties, hand=hand,
                                        guaranteed=not eq.dual_wielding(c))
        self._land_player_hit(target, res)
        return True

    def attack_with_both(self) -> bool:
        """The attack key: strike with the main hand, then -- dual wielding --
        with the off hand as well, each a separate attack."""
        struck = self.do_attack()
        if eq.offhand_weapon(self.game.character) is not None:
            struck = self.do_attack("off") or struck
        return struck

    def _land_player_hit(self, target, res, heavy=False) -> None:
        """What a landed (or missed) melee blow does: the number over the
        target, the target's anger, a kill."""
        _journal(target)     # a kill/gib changes how the target is drawn
        if res.get("hit"):
            tag = ("sneak" if res.get("sneak")
                   else "crit" if (res.get("crit") or heavy) else "dmg")
            self.add_floater(f"-{int(res['damage'])}", kind=tag)
            self._provoke(target)
            if res.get("killed"):
                self._on_creature_killed(target)
        else:
            self.add_floater("miss", kind="miss")

    def _spawn_player_arrow_projectile(self, max_dist=BOW_MAX_RANGE, hand="main") -> None:
        """Loose a physical arrow the way the player is facing, to fly up to
        *max_dist*. Travels and collides through the same engine
        projectile pipeline a spell bolt uses, but — unlike a spell bolt —
        embeds where it lands (``embeds=True``) and resolves its own RPG
        damage on impact via an ``on_hit`` callback instead of a flat number
        baked in at fire time, so the roll happens at the moment of the
        actual physical hit."""
        lt = self.logic
        ppos = self._player_pos()
        if lt is None or ppos is None:
            return
        max_dist = float(max_dist)
        c = self.game.character
        shot = eq.ammo_for(c, eq.hand_weapon(c, hand))
        sprite = arrow_sprite(shot.id if shot is not None else
                              eq.equipped_id(c, "ammo"))

        start = [ppos[0], ppos[1] + 48.0, ppos[2]]
        aim = self._projectile_aim_point(start)

        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        dlen = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        vel = [dx / dlen * ARROW_SPEED, dy / dlen * ARROW_SPEED, dz / dlen * ARROW_SPEED]

        game = self.game

        def _on_hit(hit_monster):
            res = game.resolve_arrow_hit(hit_monster.properties, hand=hand)
            _journal(hit_monster)
            if res.get("hit"):
                tag = "sneak" if res.get("sneak") else ("crit" if res.get("crit") else "dmg")
                self.add_floater(f"-{int(res['damage'])}", kind=tag)
                self._provoke(hit_monster)
                if res.get("killed"):
                    self._on_creature_killed(hit_monster)
            else:
                self.add_floater("miss", kind="miss")

        # A player-owned arrow: it flies past the archer, stops at its own
        # range, and resolves its RPG damage at the moment it actually hits.
        row = fio.spawn_projectile(lt, start, vel,
                                   lifetime=max_dist / ARROW_SPEED,
                                   max_dist=max_dist, on_hit=_on_hit)
        tag = fio.projectile_tag(lt, row)
        if tag:
            self._arrow_tags[tag] = sprite

    def _split_projectiles(self, store, count):
        """Which projectiles Fio draws: all but the arrows, which the game
        draws itself. Publishes the arrows in flight as it goes.

        Called by Fio, under the monster lock, when it publishes a frame's
        projectiles (fio.set_projectile_split).
        """
        arrows = self._arrow_tags
        tags = store.tag[:count]
        bolts = self._bolt_lights
        if bolts:
            lit = np.flatnonzero(np.isin(
                tags, np.fromiter(bolts, dtype=np.int64, count=len(bolts)))).tolist()
            self._bolt_positions = {int(tags[r]): tuple(store.pos[r].tolist())
                                    for r in lit}
        if not arrows:
            self.arrows_in_flight = ()
            return None
        is_arrow = np.isin(tags, np.fromiter(arrows, dtype=np.int64, count=len(arrows)))
        rows = np.flatnonzero(is_arrow).tolist()
        self.arrows_in_flight = tuple(
            (tuple(store.pos[r].tolist()), tuple(store.vel[r].tolist()),
             arrows[int(tags[r])])
            for r in rows)
        live = set(int(t) for t in tags[rows])
        for tag in [t for t in arrows if t not in live]:
            del arrows[tag]
        return ~is_arrow

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
            _journal(target)
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
        if not c.can_use_magic():
            # A Warrior works no magic: the right hand does nothing.
            return False
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
                _journal(target)
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
        for t in fio.things(self.logic):
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
        _journal(thing)
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
        from engine.monster_constants import (
            MONSTER_PROJECTILE_SPEED, MONSTER_PROJECTILE_MAX_DIST)

        start = [ppos[0], ppos[1] + 48.0, ppos[2]]
        aim = self._projectile_aim_point(start)

        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        dlen = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        speed = float(getattr(spell, "projectile_speed", 0) or MONSTER_PROJECTILE_SPEED)
        vel = [dx / dlen * speed, dy / dlen * speed, dz / dlen * speed]

        # A player-owned bolt: it flies past the caster and strikes creatures
        # with the spell's damage.
        row = fio.spawn_projectile(lt, start, vel,
                                   lifetime=MONSTER_PROJECTILE_MAX_DIST / speed,
                                   damage=int(getattr(spell, "damage", 0) or 0))
        self._attach_bolt_light(row, start, spell)

    def _attach_bolt_light(self, row, start, spell) -> None:
        """Give a spell bolt its own moving light, in the spell's colour.

        The light rides the bolt (see :meth:`_split_projectiles`, which reads
        where every lit bolt is as Fio publishes the projectiles) and goes out
        the moment the bolt strikes or fizzles out of range."""
        if row is None:
            return
        tag = fio.projectile_tag(self.logic, row)
        if not tag:
            return
        try:
            colour = list(spell.color)
        except Exception:
            colour = list(rpg_magic.DEFAULT_SPELL_COLOR)
        light = self._make_light(start, {
            "colour": colour, "intensity": BOLT_LIGHT_INTENSITY,
            "radius": BOLT_LIGHT_RADIUS, "state": "on", "casts_shadows": False,
            "hidden_in_game": False, "_bolt": True})
        if light is None:
            return
        try:
            fio.things(self.logic).append(light)
        except Exception:
            return
        self._bolt_lights[tag] = light
        self._rebuild_entity_caches()

    def _update_bolt_lights(self) -> None:
        """Move each spell bolt's light onto its bolt; put out the spent ones."""
        lights = self._bolt_lights
        if not lights:
            return
        live = self._bolt_positions if fio.projectile_count(self.logic) else {}
        changed = False
        for tag in list(lights):
            light = lights[tag]
            pos = live.get(tag)
            if pos is None:
                del lights[tag]
                try:
                    things = fio.things(self.logic)
                    if light in things:
                        things.remove(light)
                except Exception:
                    pass
                changed = True
                continue
            lp = light.pos
            lp[0], lp[1], lp[2] = pos[0], pos[1], pos[2]
        if changed:
            self._rebuild_entity_caches()

    def overhead_player_weapon(self):
        """What the player holds, for the viewport's overhead overlay:
        ``[(item_id, side, attacking)]``, one per hand.

        The weapon on the wielding side; on the other side the second weapon
        when dual wielding, else a lit torch. Each hand animates its own
        attacks."""
        c = self.game.character
        handed = str(getattr(c, "handed", "right") or "right")
        other = "left" if handed == "right" else "right"
        # Each hand trails a turn on its own spring (game/weapon_sway.py): the
        # fourth field is that hand's offset from the head's facing.
        import time as _time
        sway = self.__dict__.get("_weapon_sway")
        if sway is None:
            from .weapon_sway import WeaponSway
            sway = self._weapon_sway = WeaponSway()
        player = fio.player(self.logic)
        facing = float(getattr(player, "angle", 0.0) or 0.0)
        now = _time.perf_counter()
        held = [(eq.equipped_id(c, "weapon") or "", handed,
                 self._attack_anim_time > 0.0
                 or getattr(self, "_cast_cooldown", 0.0) > 0.05,
                 sway.offset("main", facing, now))]
        off_lag = sway.offset("off", facing, now)
        off = eq.offhand_weapon(c)
        if off is not None:
            held.append((off.id, other, self._offhand_anim_time > 0.0, off_lag))
        else:
            torch = self._player_torch_def()
            if torch is not None:
                held.append((torch.id, other, False, off_lag))
        return held

    @staticmethod
    def overhead_weapon_kind(weapon_id) -> str:
        """``"melee"``, ``"bow"`` or ``"staff"``: how the viewport animates a
        held weapon's attack, from the item database's own classification."""
        from . import combat_loadout
        style = combat_loadout._item_style(weapon_id)
        if style == combat_loadout.MAGIC:
            return "staff"
        if style in (combat_loadout.MELEE, combat_loadout.BOW):
            return style
        return ""

    def overhead_player_flash(self) -> float:
        """Seconds left of the player's red hurt flash (0 when none)."""
        return float(self._player_flash or 0.0)

    def overhead_pose(self):
        c = self.game.character
        armed = bool(eq.equipped_id(c, "weapon")) or bool(c.active_spell)
        attacking = (getattr(self, "_attack_anim_time", 0.0) > 0.0
                     or getattr(self, "_offhand_anim_time", 0.0) > 0.0
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
        player = fio.player(self.logic)
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
        # The strike is emitted as a world event rather than being punished on
        # the spot: whether it costs a bounty now depends on who saw it and
        # whether word reaches the watch (game.sim.crime). The victim's own
        # memory of the assault is written by the director when they perceive
        # it — which they always do, being the one who was hit.
        self.director.emit("attack", actor=self.player_actor, target=target,
                           observers=self._sim_observers(),
                           crime=self._sim_is_crime_against(target))
        self._provoke(tp)
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
            self._set_rally(npc, False)

    def _on_creature_killed(self, target):
        self.add_floater("SLAIN", kind="kill")
        # The kill's experience (its xp_value), shown as "+N XP" by _on_xp.
        try:
            xp = int(float(target.properties.get("xp_value", 0) or 0))
        except (TypeError, ValueError, AttributeError):
            xp = 0
        if xp > 0:
            self.game.award_xp(xp)
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

    # -- weapon slots -------------------------------------------------------
    def _carried_weapons(self) -> List[Dict]:
        """Every distinct weapon in the pack, in pack order, as slot entries."""
        character = getattr(self.game, "character", None)
        if character is None:
            return []
        out, seen = [], set()
        for stack in getattr(character, "inventory", []) or []:
            item_id = stack.get("id")
            if not item_id or item_id in seen:
                continue
            category = stack.get("type") or stack.get("category")
            if category is None:
                definition = rpg_items.get(item_id)
                category = definition.category if definition else None
            if str(category).lower() != rpg_items.WEAPON:
                continue
            seen.add(item_id)
            out.append({
                "id": item_id,
                "name": stack.get("name") or item_id.replace("_", " ").title(),
                "stack": stack,
            })
        return out

    def quick_weapon_slots(self) -> List[Optional[Dict]]:
        """The four quick-weapon slots, each a slot entry or None.

        Kept honest against the pack every time it is asked: a weapon no
        longer carried (sold, dropped) leaves its slot, and a weapon picked up
        for the first time drops into the first free slot by itself — the
        convenience of the old "every weapon is a slot" — while one the player
        deliberately took out of the slots stays out.
        """
        character = getattr(self.game, "character", None)
        if character is None:
            return [None] * 4
        quick = getattr(character, "quick_weapons", None)
        if not isinstance(quick, list):
            quick = character.quick_weapons = [None] * 4
        seen = getattr(character, "_quick_seen", None)
        if seen is None:
            seen = character._quick_seen = set()
        carried = {e["id"]: e for e in self._carried_weapons()}
        for i, iid in enumerate(quick):
            if iid and iid not in carried:
                quick[i] = None
        for iid in carried:
            if iid in seen:
                continue
            seen.add(iid)
            if iid in quick:
                continue
            try:
                quick[quick.index(None)] = iid
            except ValueError:
                pass                     # every slot is taken: it waits in the pack
        return [carried.get(iid) if iid else None for iid in quick]

    def weapon_slots(self) -> List[Dict]:
        """The filled quick-weapon slots, in slot order (what 1-4 draw)."""
        return [e for e in self.quick_weapon_slots() if e]

    def set_quick_weapon(self, index: int, item_id) -> bool:
        """Put *item_id* (a carried weapon) in quick slot *index* (0-3), or
        empty the slot with None. A weapon already in another slot moves."""
        character = self.game.character
        self.quick_weapon_slots()                # sync first
        quick = character.quick_weapons
        if not 0 <= int(index) < len(quick):
            return False
        if item_id is None:
            quick[index] = None
            return True
        d = rpg_items.get(item_id)
        if d is None or d.category != rpg_items.WEAPON:
            return False
        if not inv.has_item(character.inventory, item_id, 1):
            return False
        if item_id in quick:
            quick[quick.index(item_id)] = quick[index]
        quick[index] = item_id
        character._quick_seen.add(item_id)
        return True

    def select_weapon_slot(self, number: int) -> bool:
        """Draw the weapon in quick slot *number* (1-4). True if anything changed.

        Pressing the slot a weapon is already in puts it away, so the same key
        both draws and sheathes and you can go unarmed without opening
        anything. The weapon in hand changes on the spot.
        """
        slots = self.quick_weapon_slots()
        index = int(number) - 1
        if index < 0 or index >= len(slots) or slots[index] is None:
            self.notify(f"Nothing in weapon slot {int(number)}", 1.5)
            return False
        entry = slots[index]
        character = self.game.character
        self._cancel_bow_draw()
        if eq.equipped_id(character, rpg_items.SLOT_WEAPON) == entry["id"]:
            eq.unequip(character, rpg_items.SLOT_WEAPON)
            self.notify("Unarmed", 1.5)
            return True
        self.game.equip(entry["id"])
        self.notify(f"{entry['name']} ({int(number)})", 1.5)
        return True

    # ------------------------------------------------- inventory window verbs
    # Called from the game tick with what the inventory window queued
    # (game/ui/inventory_window.py), so the character only ever changes on
    # the logic thread.
    def inventory_move(self, source, target, item_id) -> bool:
        """Carry out one drag and drop: *source* and *target* are the window's
        ``(kind, key, ...)`` tuples. Only what fits goes in a slot. A change
        of Armour Class is announced."""
        before = eq.armour_class(self.game.character)
        done = self._inventory_move(source, target, item_id)
        self._announce_ac(before)
        return done

    def _announce_ac(self, before) -> None:
        after = eq.armour_class(self.game.character)
        if after != before:
            arrow = "▲" if after > before else "▼"
            self.notify(f"Armour Class {before} → {after} {arrow}", 2.5)

    def _inventory_move(self, source, target, item_id) -> bool:
        from .ui import inventory_window as iw
        c = self.game.character
        d = rpg_items.get(item_id)
        if d is None or not inv.has_item(c.inventory, item_id, 1):
            return False
        kind, key = target[0], target[1]
        if not iw.fits((kind, key), d):
            self.notify(iw.why_not((kind, key), d), 2.5)
            return False
        if kind == "equip":
            if key == rpg_items.SLOT_WEAPON:
                # In hand: it rides a quick slot too, so a number key finds it.
                if item_id not in [e["id"] for e in self.weapon_slots()]:
                    self.inventory_assign_quick(item_id)
                self._cancel_bow_draw()
            if key == rpg_items.SLOT_SHIELD and d.category == rpg_items.WEAPON:
                # A second weapon in the off hand: dual wielding.
                self._cancel_bow_draw()
                if self.game.equip(item_id, rpg_items.SLOT_SHIELD):
                    self.notify(f"{d.name} in your off hand", 1.5)
                    return True
                if eq.equipped_id(c, rpg_items.SLOT_WEAPON) == item_id:
                    self.notify(f"You carry only one {d.name}", 2.5)
                return False
            if self.game.equip(item_id):
                self.notify(f"Equipped {d.name}", 1.5)
                return True
            return False
        if kind == "quick":
            # Between quick slots the two weapons swap (set_quick_weapon
            # moves whatever was there into the slot the dragged one left).
            return self.set_quick_weapon(int(key), item_id)
        # Back to the pack: take it off, or out of its quick slot.
        if source[0] == "equip":
            if source[1] == rpg_items.SLOT_WEAPON:
                self._cancel_bow_draw()
            self.game.unequip(source[1])
            self.notify(f"Took off {d.name}", 1.5)
            return True
        if source[0] == "quick":
            if warrior_fist.innate(item_id):
                self.notify("Your fists stay in your first weapon slot", 2.0)
                return False
            self.set_quick_weapon(int(source[1]), None)
            if eq.equipped_id(c, rpg_items.SLOT_WEAPON) == item_id:
                eq.unequip(c, rpg_items.SLOT_WEAPON)
                self._cancel_bow_draw()
            return True
        return False

    def inventory_use(self, item_id) -> bool:
        """Double-click / Use: wear or take off what is worn, draw a weapon,
        drink a potion, read a book."""
        before = eq.armour_class(self.game.character)
        done = self._inventory_use(item_id)
        self._announce_ac(before)
        return done

    def _inventory_use(self, item_id) -> bool:
        c = self.game.character
        d = rpg_items.get(item_id)
        if d is None:
            return False
        worn = {v: k for k, v in c.equipment.items() if v}
        if item_id in worn:
            self.game.unequip(worn[item_id])
            if worn[item_id] == rpg_items.SLOT_WEAPON:
                self._cancel_bow_draw()
            self.notify(f"Took off {d.name}", 1.5)
            return True
        if d.category == rpg_items.WEAPON:
            if item_id not in [e["id"] for e in self.weapon_slots()]:
                self.inventory_assign_quick(item_id)
            self._cancel_bow_draw()
        if d.get("slot") or d.category in (rpg_items.WEAPON, rpg_items.AMMO):
            if self.game.equip(item_id):
                self.notify(f"Equipped {d.name}", 1.5)
                return True
            return False
        used = bool(self.game.use_item(item_id))
        if used and d.category == rpg_items.BOOK and d.get("book"):
            self.open_book(item_id)
        return used

    # ============================================================== books
    def open_book(self, item_id) -> bool:
        """Open a book item to read it (game/ui/book_window.py), from
        whatever screen the player was on, which comes back when it closes."""
        from . import books as lib
        book = lib.book_of_item(item_id)
        if book is None:
            self.notify("The pages are blank", 2.0)
            return False
        self.reading = {"item": item_id, "book": book.id, "spread": 0, "spreads": 1}
        self._book_return = self.open_screen if self.open_screen != "book" else None
        self.open_screen = "book"
        self.play_ui_sound("page")
        return True

    def turn_book(self, step) -> None:
        r = getattr(self, "reading", None)
        if not r:
            return
        spread = max(0, min(int(r.get("spreads", 1)) - 1, int(r.get("spread", 0)) + int(step)))
        if spread != r.get("spread"):
            r["spread"] = spread
            self.play_ui_sound("page")

    def close_book(self) -> None:
        self.reading = None
        self.open_screen = getattr(self, "_book_return", None)
        self._book_return = None

    # ------------------------------------------------------ inventory strip
    # The Minecraft-style bar along the bottom of the screen (I, and
    # game/ui/inventory_strip.py). Its slots hold carried item ids, like the
    # quick-weapon slots; ``inventory_strip_size`` (console) sets how many.
    def strip_size(self) -> int:
        n = getattr(self, "_strip_size", None)
        if n is None:
            n = STRIP_DEFAULT_SIZE
            try:
                config = self._editor_config()
                if config is not None:
                    n = config.getint("GAME", "inventory_strip_size",
                                      fallback=STRIP_DEFAULT_SIZE)
            except (AttributeError, TypeError, ValueError):
                n = STRIP_DEFAULT_SIZE
            n = self._strip_size = max(1, min(STRIP_MAX_SIZE, int(n)))
        return n

    def set_strip_size(self, n) -> int:
        """Make the strip *n* slots wide (clamped). Things in slots that go
        stay in the pack. Returns the size set."""
        self._strip_size = max(1, min(STRIP_MAX_SIZE, int(n)))
        self.strip_slots()
        return self._strip_size

    @staticmethod
    def _strip_copies(stack) -> int:
        """How many strip slots a carried *stack* may take: one per copy of a
        weapon -- each blade is drawn from a slot of its own, so a pair to
        dual wield costs two -- and one for anything else (its count shows)."""
        if not stack:
            return 0
        d = rpg_items.get(stack.get("id"))
        if d is not None and d.category == rpg_items.WEAPON:
            return max(1, int(stack.get("qty", 1) or 1))
        return 1

    def strip_slots(self) -> List[Optional[Dict]]:
        """The strip's slots, each the carried stack in it or None. A weapon
        carried more than once is in a slot per copy, each shown as one.

        Kept honest on every ask, as the quick slots are: a thing no longer
        carried leaves its slot (a copy sold, the slot of the last one), and
        one picked up -- or another copy of a weapon -- takes the first free
        slot by itself."""
        c = getattr(self.game, "character", None)
        if c is None:
            return []
        size = self.strip_size()
        strip = getattr(c, "strip", None)
        if not isinstance(strip, list):
            strip = c.strip = []
        if len(strip) > size:
            del strip[size:]
        strip.extend([None] * (size - len(strip)))
        seen = getattr(c, "_strip_seen", None)
        if seen is None:
            seen = c._strip_seen = set()
        #: Copies of each item offered a slot so far (a weapon's can be more
        #: than one); an id only in *seen* (an older save) counts as one.
        offered = getattr(c, "_strip_offered", None)
        if offered is None:
            offered = c._strip_offered = {}
        carried = {}
        for stack in c.inventory or ():
            if isinstance(stack, dict) and stack.get("id") and int(stack.get("qty", 1) or 0) > 0:
                carried.setdefault(str(stack["id"]), stack)
        placed = {}
        for i, iid in enumerate(strip):
            if not iid:
                continue
            n = placed.get(iid, 0) + 1
            if n > self._strip_copies(carried.get(iid)):
                strip[i] = None
            else:
                placed[iid] = n
        for iid, stack in carried.items():
            want = self._strip_copies(stack)
            done = offered.get(iid, 1 if iid in seen else 0)
            while done < want:
                done += 1
                if placed.get(iid, 0) < want and None in strip:
                    strip[strip.index(None)] = iid
                    placed[iid] = placed.get(iid, 0) + 1
            offered[iid] = min(done, want)
            seen.add(iid)
        # Forget what has gone, so it is offered a slot again when it comes back.
        seen.intersection_update(carried)
        for iid in [k for k in offered if k not in carried]:
            del offered[iid]
        out = []
        for iid in strip:
            stack = carried.get(iid) if iid else None
            if stack is not None and self._strip_copies(stack) > 1:
                stack = dict(stack, qty=1)       # one copy per slot
            out.append(stack)
        return out

    def strip_hands(self) -> List[Optional[str]]:
        """Per strip slot, the hand its weapon copy is held in: ``"main"``,
        ``"off"`` or None. Copies of one weapon map to the hands in order --
        the first slot holding it is the main hand's copy when the main hand
        holds it, the next the off hand's."""
        c = self.game.character
        main = eq.weapon(c)
        off = eq.offhand_weapon(c)
        out, seen = [], {}
        for stack in self.strip_slots():
            iid = stack.get("id") if stack else None
            hand = None
            if iid:
                copy = seen.get(iid, 0)
                seen[iid] = copy + 1
                hands = [h for h, d in (("main", main), ("off", off))
                         if d is not None and d.id == iid]
                hand = hands[copy] if copy < len(hands) else None
            out.append(hand)
        return out

    def set_strip_slot(self, index: int, item_id, from_index=None) -> bool:
        """Put *item_id* (carried) in strip slot *index*, or empty it with
        None. Dragged from another strip slot (*from_index*), the two swap.
        From elsewhere, a copy without a slot yet takes this one; otherwise
        the slot it was in swaps with this one."""
        self.strip_slots()
        c = self.game.character
        strip = c.strip
        index = int(index)
        if not 0 <= index < len(strip):
            return False
        if item_id is None:
            strip[index] = None
            return True
        if not inv.has_item(c.inventory, item_id, 1):
            return False
        if from_index is not None and 0 <= int(from_index) < len(strip) \
                and strip[int(from_index)] == item_id:
            strip[int(from_index)], strip[index] = strip[index], item_id
            return True
        if strip[index] == item_id:
            return True
        copies = self._strip_copies(inv.find(c.inventory, item_id))
        if item_id in strip and strip.count(item_id) >= copies:
            strip[strip.index(item_id)] = strip[index]
        strip[index] = item_id
        c._strip_seen.add(item_id)
        return True

    def select_strip_slot(self, index: int) -> bool:
        """A strip slot picked, by a click or its number key: selected, and a
        weapon in it taken in hand at once (see :meth:`ready_weapon`).
        True if anything changed in hand."""
        slots = self.strip_slots()
        index = int(index)
        if not 0 <= index < len(slots):
            return False
        self.strip_selected = index
        stack = slots[index]
        if not stack:
            return False
        d = rpg_items.get(stack.get("id"))
        if d is None or d.category != rpg_items.WEAPON:
            return False
        copy = sum(1 for st in slots[:index] if st and st.get("id") == d.id)
        return self.ready_weapon(d.id, copy)

    def ready_weapon(self, item_id, copy=None) -> bool:
        """Take a carried weapon in hand at once, or put it away if it is
        already there. *copy* is which copy of it (0, 1 ...) on the strip:
        a pair of the same blade is two copies, one per hand (see
        :meth:`strip_hands`); None means whichever is in hand.

        The main hand first. With the main hand already holding a weapon, a
        one-handed weapon goes to the off hand (the shield slot) and the two
        are dual wielded. A bow or a two-handed weapon can't be held in the
        off hand, so it takes the main hand -- and both. Neither can anything
        go beside a two-hander: the new weapon replaces it instead."""
        c = self.game.character
        d = rpg_items.get(item_id)
        if d is None or d.category != rpg_items.WEAPON \
                or not inv.has_item(c.inventory, item_id, 1):
            return False
        before = eq.armour_class(c)
        self._cancel_bow_draw()
        main = eq.weapon(c)
        off = eq.offhand_weapon(c)
        hands = [h for h, w in (("main", main), ("off", off))
                 if w is not None and w.id == item_id]
        if copy is None:
            held = hands[0] if hands else None
        else:
            held = hands[copy] if 0 <= copy < len(hands) else None
        if held == "main":
            eq.unequip(c, rpg_items.SLOT_WEAPON)
            if off is not None:
                # The off hand's weapon moves over: never a hand left empty
                # beside a held blade.
                eq.unequip(c, rpg_items.SLOT_SHIELD)
                self.game.equip(off.id)
            self.notify(f"Put away {d.name}", 1.5)
            self._announce_ac(before)
            return True
        if held == "off":
            eq.unequip(c, rpg_items.SLOT_SHIELD)
            self.notify(f"Put away {d.name}", 1.5)
            self._announce_ac(before)
            return True
        main_free = main is None or bool(main.get("innate"))
        if (not main_free and eq.can_dual_wield(d) and not eq.is_two_handed(main)
                and self.game.equip(item_id, rpg_items.SLOT_SHIELD)):
            self.notify(f"{d.name} in your off hand", 1.5)
        elif self.game.equip(item_id):
            self.notify(f"{d.name} in hand", 1.5)
        else:
            return False
        self._announce_ac(before)
        return True

    def _forget_in_slots(self, item_id) -> None:
        """*item_id* is leaving the pack: off the body, out of every slot."""
        c = self.game.character
        for slot, iid in list(c.equipment.items()):
            if iid == item_id:
                if slot == rpg_items.SLOT_WEAPON:
                    self._cancel_bow_draw()
                self.game.unequip(slot)
        quick = getattr(c, "quick_weapons", None) or []
        for i, iid in enumerate(quick):
            if iid == item_id:
                quick[i] = None
        strip = getattr(c, "strip", None) or []
        for i, iid in enumerate(strip):
            if iid == item_id:
                strip[i] = None

    def store_item_in_container(self, item_id) -> bool:
        """Put the whole carried stack of *item_id* in the open container."""
        if self.container_thing is None:
            return False
        pinv = self.game.character.inventory
        index = next((i for i, st in enumerate(pinv) if st.get("id") == item_id), None)
        if index is None:
            return False
        return self.store_in_container(index)

    def item_drop(self, source, target) -> bool:
        """One drag and drop between any of the item windows: the pack and the
        body (C), the strip, and an open container or corpse.

        *source* is ``(kind, key, item id)`` and *target* ``(kind, key)``,
        where kind is ``pack``, ``equip``, ``quick``, ``strip`` or
        ``container`` (key: a slot, a slot index, or a container row)."""
        skind, skey, iid = source[0], source[1], source[2]
        tkind, tkey = target[0], target[1]
        if not iid:
            return False
        if skind == "container":
            if tkind == "container":
                return False
            items = self.container_inventory()
            row = skey if (isinstance(skey, int) and 0 <= skey < len(items)
                           and items[skey].get("id") == iid) else next(
                (i for i, st in enumerate(items) if st.get("id") == iid), None)
            if row is None or not self.take_from_container(row):
                return False
            if iid == rpg_items.GOLD:
                return True                          # coin goes to the purse
            if tkind == "strip":
                return self.set_strip_slot(int(tkey), iid)
            if tkind in ("equip", "quick"):
                return self.inventory_move(("pack", None, iid), (tkind, tkey), iid)
            return True
        if tkind == "container":
            return self.store_item_in_container(iid)
        if tkind == "strip":
            return self.set_strip_slot(int(tkey), iid,
                                       from_index=skey if skind == "strip" else None)
        if skind == "strip":
            if tkind == "pack":
                return self.set_strip_slot(int(skey), None)
            return self.inventory_move(("pack", None, iid), (tkind, tkey), iid)
        return self.inventory_move(source, (tkind, tkey), iid)

    def inventory_assign_quick(self, item_id) -> bool:
        """Assign: put a weapon in the first free quick slot."""
        slots = self.quick_weapon_slots()
        if any(e and e["id"] == item_id for e in slots):
            return True
        for i, e in enumerate(slots):
            if e is None:
                if self.set_quick_weapon(i, item_id):
                    self.notify(f"Quick slot {i + 1}", 1.5)
                    return True
                return False
        self.notify("The quick slots are full: drag it onto one to swap.", 2.5)
        return False

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
        """Quest ids a dialogue tree can start (for the '!' available-quest cue).

        Asked for every NPC near the player every frame (the speech bubbles),
        so the walk is kept per tree object: a tree is authored data, and the
        cache holds the tree itself, so an id is never mistaken for a new one."""
        if not isinstance(tree, dict):
            return []
        memo = self.__dict__.setdefault("_dialogue_quest_ids", {})
        nodes = tree.get("nodes")
        size = len(nodes) if isinstance(nodes, dict) else 0
        hit = memo.get(id(tree))
        if hit is not None and hit[0] is tree and hit[1] == size:
            return hit[2]
        if len(memo) > 512:
            memo.clear()
        out = self._walk_quest_ids(tree)
        memo[id(tree)] = (tree, size, out)
        return out

    @staticmethod
    def _walk_quest_ids(tree) -> List[str]:
        out = []
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

    # -- marks above heads ---------------------------------------------------
    def set_head_mark(self, npc, mark) -> None:
        """Show *mark* ("!" heightened, "?" puzzled) above *npc*'s head, or
        clear it with None. What a mood system sets; a mark set here wins
        over the ones the game derives (see :meth:`head_mark`)."""
        if npc is None:
            return
        props = npc.properties
        if mark in HEAD_MARKS:
            props["_head_mark"] = mark
            self._head_marked[id(npc)] = npc
        else:
            props.pop("_head_mark", None)
            self._head_marked.pop(id(npc), None)

    def flash_head_mark(self, npc, mark="!", seconds: float = MARK_FLASH_SECONDS) -> None:
        """Show *mark* over *npc* for a moment: the guard who has just seen
        something and is about to do something about it."""
        if npc is None or mark not in HEAD_MARKS:
            return
        import time as _time
        npc.properties["_head_mark"] = mark
        npc.properties["_head_mark_until"] = _time.monotonic() + float(seconds)
        self._head_marked[id(npc)] = npc

    def head_mark(self, npc):
        """The mark over *npc* now, or None.

        Set explicitly (:meth:`set_head_mark`), or heightened by what the NPC
        is doing: a guard coming to arrest the player, stopping them, or
        running them down shows "!". Escorting a prisoner is calm.
        """
        props = getattr(npc, "properties", None) or {}
        if props.get("dead"):
            return None
        mark = props.get("_head_mark")
        until = props.get("_head_mark_until")
        if until is not None:
            import time as _time
            if _time.monotonic() >= float(until):
                props.pop("_head_mark", None)
                props.pop("_head_mark_until", None)
                self._head_marked.pop(id(npc), None)
                mark = None
        if mark in HEAD_MARKS:
            return mark
        if npc is self._arrest_guard and self._arrest_state in ("approach", "ready"):
            return "!"
        if npc in self._arrest_pursuers:
            return "!"
        return None

    def head_marks(self):
        """(npc, mark) for every NPC with a mark over its head right now."""
        seen = set()
        out = []
        candidates = list(self._head_marked.values())
        candidates.append(self._arrest_guard)
        candidates.extend(self._arrest_pursuers)
        for npc in candidates:
            if npc is None or id(npc) in seen:
                continue
            seen.add(id(npc))
            mark = self.head_mark(npc)
            if mark is not None:
                out.append((npc, mark))
        return out

    def bubble_npcs(self, player_pos, radius: float = BUBBLE_RADIUS):
        """(npc, kind) for nearby NPCs that have something to say, nearest first.

        An NPC with a mark over its head (see :meth:`head_mark`) shows that
        instead of a speech bubble."""
        out = []
        r2 = radius * radius
        px, pz = player_pos[0], player_pos[2]
        for npc in self.npcs():
            # Distance first: the HUD asks every frame, and only the few NPCs
            # in reach are worth reading a dialogue tree for.
            dx = npc.pos[0] - px
            dz = npc.pos[2] - pz
            d = dx * dx + dz * dz
            if d > r2:
                continue
            kind = self.bubble_kind(npc)
            if kind is None or self.head_mark(npc) is not None:
                continue
            out.append((d, npc, kind))
        out.sort(key=lambda t: t[0])
        return [(npc, kind) for _d, npc, kind in out]

    # -- dialogue -----------------------------------------------------------
    def _actors_near(self, pos, radius: float):
        """The actors within *radius* (XZ) of *pos*, as candidates: one index
        query rather than a walk of every actor. Positions are this tick's
        snapshot, so callers re-measure the few that come back.

        Logic thread only (the index is rebuilt there); None without an index,
        when callers fall back to their full scans."""
        wi = self._world_index()
        if wi is None:
            return None
        actors = wi.actors
        return [actors[i] for i in wi.rows_near(float(pos[0]), float(pos[2]),
                                                radius).tolist()]

    def nearest_talkable(self, player_pos, radius: float = TALK_RADIUS):
        best, best_d = None, radius * radius
        near = self._actors_near(player_pos, radius)
        if near is None:
            pool = self.npcs()
        else:
            npc_ids = self._type_ids("npc")
            pool = [t for t in near
                    if id(t) in npc_ids and not t.properties.get("dead", False)]
        for npc in pool:
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
        # Publish the partner's remembered standing under generic talk.* keys so
        # both the synthesised greeting below and authored dialogue can react to
        # this NPC's memory of the player (talk.tier / talk.wronged / …).
        disp.write_talk_keys(self.store, self.game.character, npc.properties)
        if not tree:
            # a bare merchant/greeter: synthesise a tiny greeting tree
            tree = self._default_tree(npc)
        tree = self._with_first_impression(tree, npc)
        if getattr(self, "living", None) is not None:
            tree = self.living.prepare_tree(tree, npc)
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

    def _with_first_impression(self, tree, npc):
        """*tree* with the NPC's reaction to the player's face put in front of
        its opening line -- a copy, never the authored tree itself. Plain faces
        draw no comment. Hostile-looking strangers aside, only someone meeting
        the player afresh remarks on it; an old friend has seen it before."""
        c = self.game.character
        line = rpg_cha.greeting_line(rpg_cha.charisma_of(c),
                                     npc.properties.get("name", ""))
        if not line or not isinstance(tree, dict):
            return tree
        if disp.of(c, npc.properties, self.store) >= 75:
            return tree
        start = tree.get("start")
        nodes = tree.get("nodes") or {}
        node = nodes.get(start)
        if not isinstance(node, dict):
            return tree
        import copy
        tree = copy.deepcopy(tree)
        node = tree["nodes"][start]
        node["text"] = f"{line} {node.get('text', '')}".strip()
        return tree

    def _repel_hostiles(self) -> None:
        """A truly repulsive face can end a fight before it starts: a hostile
        brigand or cultist who gets a proper look at the player may decide it
        wants no part of them, lower its weapon and back off for a few hours.
        Each actor makes that judgement once per meeting; monsters and beasts
        do not care what anyone looks like."""
        c = self.game.character
        chance = rpg_cha.repel_chance(rpg_cha.charisma_of(c))
        if chance <= 0.0:
            return
        ppos = self._player_pos()
        if ppos is None:
            return
        now = self.clock.day * 24.0 + self.clock.hour
        for t in self._actors:
            p = t.properties
            if str(p.get("aggression")) != "hostile" or p.get("triggered", False):
                continue
            if p.get("monster_type", "human") != "human":
                continue
            if str(p.get("faction") or p.get("team")) not in REPELLABLE_FACTIONS:
                continue
            if self._dist2d(t.pos, ppos) > REPEL_RADIUS:
                p.pop("_repel_judged", None)
                continue
            if p.get("_repel_judged"):
                continue
            p["_repel_judged"] = True
            if self.rng.random() >= chance:
                continue
            p["aggression"] = "passive"
            p["triggered"] = True
            p["awake"] = False
            p.pop("_aggro_target", None)
            p["_repelled_until"] = now + REPEL_HOURS
            name = p.get("display_name", "The brigand")
            self.notify(f"{name} takes one look at your face and wants no part of you.", 3.5)
        # Courage returns with time.
        for t in self._actors:
            p = t.properties
            until = p.get("_repelled_until")
            if until is not None and now >= float(until):
                p.pop("_repelled_until", None)
                p.pop("_repel_judged", None)
                p["aggression"] = "hostile"
                p["triggered"] = False

    def _default_tree(self, npc):
        name = npc.properties.get("display_name", "Villager")
        # Effective disposition includes this NPC's memory of the player, so the
        # greeting reflects a history of kindness or of wrongs, not just a base.
        value = disp.of(self.game.character, npc.properties, self.store)
        if disp.has_flag(self.store, npc.properties, "wronged"):
            greeting = "You. I've not forgotten what you did. State your business and go."
        elif value >= 80:
            greeting = "Ah, it's you! Always good to see a friend of mine."
        elif value >= 55:
            greeting = "Well met, friend. What can I do for you?"
        elif value >= 30:
            greeting = "Well met, traveller."
        else:
            greeting = "What do you want?"
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
            c = self.game.character
            if rpg_cha.merchant_refuses(rpg_cha.charisma_of(c),
                                        disp.of(c, npc.properties, self.store)):
                self.end_dialogue()
                self.merchant_npc = None
                name = npc.properties.get("display_name", "The merchant")
                self.notify(f"{name} won't trade with you: \"Not with that face. "
                            f"You'll scare off my real customers.\"", 4.5)
                return
            self.merchant_npc = npc
            self.end_dialogue()
            self.open_screen = "trade"
        elif op == "persuade":
            r = guilds.persuade(self.game.character, npc.properties, self.rng)
            self.notify("They warm to you." if r["success"] else "That didn't help.")
        elif op == "start_quest":
            self.game.start_quest(action.get("quest", action.get("value", "")))
            disp.remember(self.store, npc.properties, "quest_accepted")
        elif op == "advance_quest":
            self.game.quests.advance(action.get("quest", ""))
        elif op == "complete_quest":
            self.game.complete_quest(action.get("quest", ""))
            # Finishing a quest for this NPC is a lasting good turn they remember.
            disp.remember(self.store, npc.properties, "quest_helped")
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
        px, pz = player_pos[0], player_pos[2]
        for c in self._things_of_type("container"):
            r = float(c.properties.get("use_radius", radius))
            pos = c.pos
            dx = px - pos[0]
            dz = pz - pos[2]
            d = dx * dx + dz * dz          # squared: compared, never shown
            if r >= 0.0 and d <= r * r and (best_d is None or d < best_d):
                best, best_d = c, d
        return best

    # -- corpses ------------------------------------------------------------
    def nearest_corpse(self, player_pos, radius: float = TALK_RADIUS):
        """The nearest dead NPC or creature within *radius* with anything on
        it to take (or a loot table not yet rolled), else None."""
        best, best_d = None, radius * radius
        pool = self._actors_near(player_pos, radius)
        if pool is None:
            buckets = self._type_buckets()
            pool = _chain(buckets.get("npc", ()), buckets.get("creature", ()),
                          buckets.get("monster", ()))
        for t in pool:
            p = t.properties
            if not p.get("dead") or p.get("hidden"):
                continue
            dx = t.pos[0] - player_pos[0]
            dz = t.pos[2] - player_pos[2]
            d = dx * dx + dz * dz
            if d >= best_d or not self._corpse_has_loot(p):
                continue
            best, best_d = t, d
        return best

    @staticmethod
    def _corpse_has_loot(props) -> bool:
        if not props.get("loot_rolled"):
            return True                    # its loot table is still to be rolled
        carried = props.get("inventory")
        if isinstance(carried, str):
            return bool(carried.strip())
        return any(not warrior_fist.innate(s.get("id", "")) and int(s.get("qty", 1) or 0) > 0
                   for s in (carried or ()) if isinstance(s, dict))

    def corpse_name(self, thing) -> str:
        p = thing.properties
        return str(p.get("display_name") or p.get("name") or "the body")

    def loot_corpse(self, thing) -> bool:
        """Open a body's belongings in the container screen (E on a corpse).

        A death the player caused was stocked from its loot table at the kill;
        any other is stocked now, the first time it is searched."""
        if thing is None:
            return False
        p = thing.properties
        carried = p.get("inventory")
        if not isinstance(carried, list):
            p["inventory"] = self._spawn_inventory(carried)
        self.game.stock_corpse(p)
        # Nothing innate (a warrior's fists) is left on a body to be taken.
        p["inventory"] = [s for s in p["inventory"]
                          if isinstance(s, dict) and not warrior_fist.innate(s.get("id", ""))]
        return self.open_container(thing)

    def take_all_from_container(self) -> int:
        """Take every stack from the open container. Returns how many."""
        n = 0
        while self.container_inventory() and self.take_from_container(0):
            n += 1
        return n

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
        if t.properties.get("dead"):
            return f"{self.corpse_name(t)} (dead)"
        return str(t.properties.get("display_name") or "Container")

    def take_from_container(self, index: int) -> bool:
        """Move one stack from the open container into the player's inventory."""
        items = self.container_inventory()
        if not (0 <= index < len(items)):
            return False
        stack = items.pop(index)
        name = stack.get("name", stack.get("id", ""))
        # A chest with an owner makes emptying it a theft, exactly like a world
        # item — the container needed no code of its own to become stealable.
        props = self.container_thing.properties if self.container_thing else {}
        event = self.director.take(
            props, self.player_actor,
            target_thing=self._sim_actor_by_key(sim_own.owner_of(props)),
            observers=self._sim_observers(), item_id=str(stack.get("id", "")),
            item_name=name, value=int(stack.get("value", 0) or 0),
            pos=list(self.container_thing.pos) if self.container_thing else None)
        if event is not None and event.kind == "theft":
            sim_own.mark_stolen(stack, sim_own.owner_of(props),
                                sim_own.owner_name_of(props))
            self.notify(f"Stole {name}")
        else:
            self.notify(f"Took {name}" if stack.get("id") != rpg_items.GOLD
                        else f"Took {int(stack.get('qty', 1))} gold")
        if stack.get("id") == rpg_items.GOLD:
            # Coin is counted, not carried as an item.
            self.game.character.gold += int(stack.get("qty", 1) or 0)
        else:
            inv.add_item(self.game.character.inventory, stack)
        return True

    def store_in_container(self, index: int) -> bool:
        """Move one stack from the player's inventory into the open container."""
        if self.container_thing is None:
            return False
        pinv = self.game.character.inventory
        if not (0 <= index < len(pinv)):
            return False
        iid = pinv[index].get("id", "")
        if warrior_fist.innate(iid):
            self.notify("Your fists stay with you", 2.0)
            return False
        # Whatever is worn or slotted comes off first, so nothing points at a
        # stack that is no longer carried.
        before = eq.armour_class(self.game.character)
        self._forget_in_slots(iid)
        self._announce_ac(before)
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
    @staticmethod
    def stock_entry(npc, item_id):
        """*npc*'s own stock row for *item_id* (a dict), or None.

        A row with a ``qty`` is limited: buying takes one, at none it is sold
        out, and the daily resolution fills it back to its ``restock`` count
        (game/rpg/daily.py). A row without one -- or a plain item id -- is an
        endless supply, as all stock used to be."""
        stock = getattr(npc, "properties", {}).get("stock") if npc is not None else None
        if not isinstance(stock, list):
            return None
        for entry in stock:
            if isinstance(entry, dict) and entry.get("id") == item_id:
                return entry
        return None

    @staticmethod
    def stock_left(entry):
        """How many of a stock row are left, or None for an endless one."""
        if not isinstance(entry, dict) or "qty" not in entry:
            return None
        try:
            return max(0, int(entry.get("qty") or 0))
        except (TypeError, ValueError):
            return 0

    def buy(self, item_id: str) -> bool:
        c = self.game.character
        d = rpg_items.get(item_id)
        if not d:
            return False
        entry = self.stock_entry(self.merchant_npc, item_id)
        left = self.stock_left(entry)
        if left == 0:
            self.notify(f"{d.name}: sold out until tomorrow")
            return False
        price = self._price(d.value, buying=True, npc=self.merchant_npc)
        if c.gold < price:
            self.notify("Not enough gold")
            return False
        if left is not None:
            # The full shelf, remembered the first time one is sold.
            entry.setdefault("restock", left)
            entry["qty"] = left - 1
        c.gold -= price
        self.game.pick_up(item_id, 1)
        c.use_skill("mercantile", 0.5)
        self._remember_trade()
        self.play_ui_sound(TRANSACTION_SOUND)
        return True

    def sell(self, item_id: str) -> bool:
        c = self.game.character
        d = rpg_items.get(item_id)
        if not d or not inv.has_item(c.inventory, item_id):
            return False
        if warrior_fist.innate(item_id):
            self.notify("Your fists are not for sale")
            return False
        price = self._price(d.value, buying=False, npc=self.merchant_npc)
        inv.remove_item(c.inventory, item_id, 1)
        c.gold += price
        c.use_skill("mercantile", 0.5)
        self._remember_trade()
        self.play_ui_sound(TRANSACTION_SOUND)
        return True

    def play_ui_sound(self, name: str, volume: float = 1.0) -> bool:
        """Play an interface sound from ``assets/sounds`` (heard everywhere).

        Goes through the engine's sound queue like every other effect. A file
        that is not there is skipped silently rather than reported on every
        use. Returns whether it was queued.
        """
        game_state = getattr(self.logic, "game_state", None)
        queue = getattr(game_state, "queue_sound", None)
        if queue is None or not sound_available(name):
            return False
        queue({"file": name, "volume": float(volume), "global": True})
        return True

    def _remember_trade(self) -> None:
        """Honest business slowly warms a merchant to the player (memory), and
        is seen by whoever is in the shop — which is how an alibi works."""
        npc = self.merchant_npc
        if npc is not None:
            disp.remember(self.store, getattr(npc, "properties", {}) or {}, "traded")
            self.director.emit("trade", actor=self.player_actor, target=npc,
                               observers=self._sim_observers())

    def _price(self, base_value: int, buying: bool, npc=None) -> int:
        c = self.game.character
        merc = c.skill("mercantile")
        pers = c.attrs.get("personality", 40)
        factor = 1.0 - (merc + (pers - 40)) / 300.0
        # A trader who likes the player shaves coin off the asking price and
        # pays a little more for goods; a wary one does the opposite.
        like = disp.price_factor(c, npc.properties, self.store) if npc is not None else 1.0
        # What the merchant thinks of your face, on top of everything else.
        face = rpg_cha.price_multiplier(rpg_cha.charisma_of(c), buying)
        if buying:
            return max(1, int(base_value * (2.0 - factor) * like * face))
        return max(1, int(base_value * factor * 0.8 / like * face))

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
            if force:
                self.memory.save()
            if force and getattr(self, "living", None) is not None:
                self.living.persist()
            # The world's event history rides along in the same store, so a
            # save carries what happened and what it caused — everything else
            # the simulation knows (who believes what, who was wronged, which
            # crimes were charged) already lives in the store as it is written.
            self.director.persist()

    def restore(self) -> None:
        # The event history first, so anything that reads it during the rest of
        # the restore sees the world's past rather than an empty log.
        self.director.restore()
        if getattr(self, "living", None) is not None:
            self.living.restore()
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
            warrior_fist.ensure_fist(self)
            self._sync_engine_health(full=True)
            # Re-apply the saved head so the player billboard matches on load.
            self._ensure_player_head()
            self._assign_npc_heads()
