"""One authoritative world, explicit per-character RPG/physics contexts.

Extra characters reuse MiniwindSession's verbs through their own logic adapter;
no global active-player swap is used. The host alone runs world/AI/quests. Client
sessions render replicas and submit only validated actions for owned characters.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import math
import threading
import time
import types
from dataclasses import dataclass, field

from .. import fio
from ..rpg import equipment, heads
from ..rpg.character import Character
from .companion_behavior import CompanionMind
from .model import InputFrame, LobbyError
from .quests import CoopGameState, PartyQuests


@dataclass
class PlayerContext:
    player_id: str
    owner: str
    profile: dict
    session: object
    physics: object
    actor: object = None
    frame: InputFrame = field(default_factory=InputFrame)
    previous: InputFrame = field(default_factory=InputFrame)
    last_input: float = field(default_factory=time.monotonic)
    sequence: int = -1
    simulated_sequence: int = -1
    local_sequence: int = -1
    prediction: object = field(default_factory=lambda: collections.deque(maxlen=128))
    connected: bool = True
    bot: bool = False
    task: str = ""
    bot_target: object = None
    returning: bool = False
    mind: CompanionMind | None = None


class PlayerLogic:
    """Explicit player ownership over shared world runtimes."""

    def __init__(self, world, physics):
        object.__setattr__(self, "world", world)
        object.__setattr__(
            self,
            "player_runtime",
            types.SimpleNamespace(
                player=physics,
                player_health=100,
                player_max_health=100,
                player_armor=0,
                player_max_armor=100,
                player_dead=False,
                god_mode=False,
                buddha_mode=False,
                notarget=False,
                last_damage=None,
                damage_lock=threading.RLock(),
                collected_keys=set(),
            ),
        )
        from engine.logic_interaction import LogicInteraction
        from engine.logic_triggers import LogicTriggers

        object.__setattr__(self, "interaction_runtime", LogicInteraction(self))
        object.__setattr__(self, "trigger_runtime", LogicTriggers(self))

    def __getattr__(self, name):
        return getattr(self.world, name)


class CoopSession:
    SNAPSHOT_INTERVAL = 0.05
    INPUT_TIMEOUT = 0.6
    MAX_SEPARATION = 650.0
    REVIVE_SECONDS = 3.0
    BOT_RESPAWN_SECONDS = 3.0
    ACTIONS = frozenset(
        {
            "attack",
            "interact",
            "cast",
            "next_spell",
            "sneak",
            "heal",
            "inventory",
            "character",
            "journal",
            "quest",
            "spells",
            "map",
            "levelup",
            "pause",
            "menu_key",
            "choose",
            "inventory_use",
            "inventory_assign_quick",
            "inventory_move",
            "item_drop",
            "drop_item",
            "take_from_container",
            "store_in_container",
            "take_all_from_container",
            "close_container",
            "buy",
            "sell",
            "ready_spell",
            "ready_weapon",
            "select_strip_slot",
            "lockpick_action",
            "train_with_teacher",
            "learn_from_teacher",
            "set_tracked_quest",
            "set_waypoint",
            "clear_waypoint",
            "toggle_waypoint",
            "toggle_loadout",
            "travel_ready",
            "revive",
            "reload_checkpoint",
            "screen",
            "character_level_up",
            "rpg_action",
            "cast_at",
            "cancel_spell_aim",
            "strip_prev",
            "strip_next",
        }
    )

    def __init__(self, root, lobby, cfg=None):
        self.root, self.logic, self.lobby = root, root.logic, lobby
        self.map_name = lobby.map_name
        self.authority = lobby.lobby is not None
        self.players = {}
        self.party_quests = PartyQuests(root.store)
        self.input_queue = collections.deque(maxlen=512)
        self.input_lock = threading.Lock()
        #: The party's state lock. Never take it on its own: use
        #: :meth:`_locked`, which takes the engine's ``monster_lock`` first.
        self.lock = threading.RLock()
        self.sequence = 0
        self._snapshot_at = 0.0
        self._received_sequence = -1
        self._entity_baseline = {}
        self._replica_entities = {}
        self._ui_owner = None
        self._ui_requests = collections.deque()
        self._checkpoint = None
        self._wipe_at = None
        self._reviving = {}
        self._bot_deaths = {}
        self.travel = None
        self.paused = False
        self._last_keys = frozenset()
        self._devices_installed = False
        self._mouse_held = set()
        self._applying = False
        self.disconnected = False
        self._persist_at = 0.0
        self._world_bindings = None
        self._viewports = {}
        self._party_radius = self.MAX_SEPARATION
        self._sounds = collections.deque(maxlen=128)
        self._old_sound_observer = None
        self._device_reader = None
        self._settings = cfg or {}
        root.coop = self
        state = lobby.state or lobby.lobby.snapshot()
        self.respawn_at_village = bool(state.get("respawn_at_village", False))
        start = self.logic.session_runtime._primary_start()
        origin = start.pos if start is not None else fio.player(self.logic).pos
        self._village_spawn = tuple(origin)
        saved = getattr(lobby, "campaign_state", None) or {}
        saved_players = saved.get("players", {})
        members = sorted(
            state.get("members", []),
            key=lambda m: (m["owner"] != "host", bool(m.get("bot"))),
        )
        for i, member in enumerate(members):
            self._create_player(
                member, primary=i == 0, saved=saved_players.get(member["player_id"])
            )
        self.primary_id = next(iter(self.players), None)
        if self.primary_id is None:
            raise LobbyError("The party has no characters.")
        self._ui_owner = next(
            (p.player_id for p in self.local_players), self.primary_id
        )
        root.needs_char_creation = False
        root.open_screen = None
        root.head_registry.set_players(
            {p.player_id: p.profile["head"] for p in self.players.values()}
        )
        if saved.get("world"):
            for key, value in saved["world"].items():
                root.store.set(key, value)
        for player in self.players.values():
            self.party_quests.attach(player.player_id, player.session.game)
            player.session.law.restore()
        if getattr(lobby, "solo_copy", False):
            self.party_quests.import_legacy_progress()
            lobby.solo_copy = False
        if saved.get("world"):
            root.clock.hour = float(saved["world"].get("_clock_hour", root.clock.hour))
            root.clock.day = int(
                float(saved["world"].get("_clock_day", root.clock.day))
            )
            root.director.restore()

    @property
    def heading(self):
        cam = fio.camera(self.logic)
        return cam.overhead_heading(0) if cam is not None else math.pi

    @property
    def local_players(self):
        return [
            p
            for p in self.players.values()
            if p.owner == self.lobby.owner and not p.bot
        ]

    @property
    def ui_session(self):
        player = self.players.get(self._ui_owner)
        return player.session if player else self.root

    def _create_player(self, member, primary=False, saved=None):
        import glm

        from engine.player import Player

        from ..runtime import MiniwindSession

        pid, profile = member["player_id"], member["profile"]
        origin = fio.player(self.logic)
        position = list(origin.pos) if origin is not None else [0.0, 0.0, 0.0]
        if primary and origin is not None:
            physics = origin
            session = self.root
        else:
            i = len(self.players)
            physics = Player(
                position[0] + (i % 2) * 48,
                position[2] + (i // 2) * 48,
                0.0,
                physics_enabled=True,
            )
            physics.pos.y = position[1]
            if self.root._blocked_by_wall(
                physics.pos.x, physics.pos.y + 48, physics.pos.z
            ):
                physics.pos = glm.vec3(*position)
            adapter = PlayerLogic(self.logic, physics)
            session = MiniwindSession(adapter, cfg=self._settings)
            adapter.game_session = session
        data = saved.get("character") if saved else member.get("character")
        if data:
            character = Character.from_dict(data)
        else:
            from ..rpg.game_state import GameState

            created = GameState.new_game(
                self.root.store,
                profile["name"],
                profile["race"],
                profile["class"],
                profile.get("birthsign", "none"),
                profile.get("gender", "male"),
                head=profile["head"],
                rng=self.root.rng,
            )
            character = created.character
        character.head = profile["head"]
        character.name = profile["name"]
        character.gender = profile.get("gender", "male")
        character.handed = profile.get("handed", "right")
        session.game = CoopGameState(
            self.party_quests, pid, character, rng=self.root.rng
        )
        session.store = session.game.store
        # The root's store is the world store. Player-local rules explicitly
        # use GameState.store; additional sessions also use that scoped view.
        from ..sim.law import Writs

        session.law = Writs(session.store)
        session.player_id = pid
        session.coop = self
        session.needs_char_creation = False
        session.open_screen = None
        session.dialogue_selected = 0
        session.strip_selected = 0
        session._strip_confirm_pending = False
        session.game.add_roll_listener(session._on_dice_roll)
        session.game.add_xp_listener(session._on_xp)
        session.game.add_drink_listener(session._on_drink)
        context = PlayerContext(
            pid,
            member["owner"],
            dict(profile),
            session,
            physics,
            connected=member.get("connected", True),
            bot=bool(member.get("bot", False)),
        )
        if context.bot:
            context.mind = CompanionMind(
                (self.lobby.state or self.lobby.lobby.snapshot())["campaign_id"],
                pid, (saved or {}).get("companion")
            )
        if (
            saved
            and saved.get("position")
            and not getattr(self.lobby, "travelling", False)
        ):
            physics.pos = glm.vec3(*saved["position"])
            physics.angle = float(saved.get("angle", 0))
            context.returning = bool(saved.get("returning", False)) and context.bot
        self.players[pid] = context
        return context

    def install_world(self):
        from ..entities import NPC
        from .world import WorldBindings

        self._world_bindings = WorldBindings(self)
        self._world_bindings.install()
        if self.authority:
            self._old_sound_observer = self.logic.game_state.sound_observer
            self.logic.game_state.sound_observer = self._record_sound

        existing = fio.things(self.logic)
        existing[:] = [
            t for t in existing if not t.properties.get("multiplayer_player")
        ]
        for context in self.players.values():
            self._prepare_player_session(context)
            actor = NPC(
                pos=[0, 64, 0],
                properties={
                    "id": context.player_id,
                    "name": context.profile["name"],
                    "display_name": context.profile["name"],
                    "faction": "player",
                    "team": "player",
                    "is_player": True,
                    "player_id": context.player_id,
                    "multiplayer_player": True,
                    "bw_persistent": True,
                    "disabled": True,
                    "combatant": True,
                    "aggression": "passive",
                    "head": context.profile["head"],
                    "sprite": heads.head_path(context.profile["head"]),
                    "custom_idle": heads.head_path(context.profile["head"]),
                    "custom_shoot": heads.head_path(context.profile["head"]),
                    "sprite_width": 128,
                    "sprite_height": 128,
                    "health": context.session.game.character.health,
                    "_sim_tier": 0,
                },
            )
            context.actor = actor
            fio.things(self.logic).append(actor)
            self._sync_actor(context)
        self.root.head_registry.set_players(
            {p.player_id: p.profile["head"] for p in self.players.values()}
        )
        self.root._assign_npc_heads()
        fio.rebuild_entity_caches(self.logic)
        # Director callbacks must use the offender's identity, not Player 1.
        original = self.root.director.on_bounty

        def bounty(amount, event, reporter):
            context = self.context_by_key(getattr(event, "actor", ""))
            if context is not None:
                context.session._sim_on_bounty(amount, event, reporter)
            elif original is not None:
                original(amount, event, reporter)

        self.root.director.on_bounty = bounty
        self.root.director.store_for_actor = lambda key: (
            self.context_by_key(key).session.game.store
            if self.context_by_key(key)
            else self.party_quests.store
        )
        if not self.authority:
            from .replication import make_remote

            for context in self.players.values():
                make_remote(context)
        self.checkpoint()
        self.lobby.travelling = False

    def _record_sound(self, request):
        if request.get("position") is not None:
            self._sounds.append(dict(request))
        if self._old_sound_observer is not None:
            self._old_sound_observer(request)

    def context_by_key(self, key):
        key = str(key)
        return self.players.get(key.removeprefix("player:"))

    def avatar(self, player_id):
        context = self.players.get(player_id)
        return context.actor if context is not None else None

    def _sync_actor(self, context):
        actor = context.actor
        if actor is None:
            return
        c = context.session.game.character
        p = actor.properties
        p.update(
            health=c.health,
            max_health=c.max_health,
            dead=c.is_dead,
            hidden=not context.connected,
            inventory=[],
            _facing=context.physics.angle,
            equipped_weapon=equipment.equipped_id(c, "weapon"),
            offhand_weapon=equipment.equipped_id(c, "shield"),
            handed=c.handed,
            sneaking=context.session.game.sneaking,
            alignment=float(getattr(c, "alignment", 0)),
            _attack_anim=context.session._attack_anim_time,
            _offhand_anim=context.session._offhand_anim_time,
        )
        actor.pos = [
            float(context.physics.pos[0]),
            float(context.physics.pos[1]) + 64.0,
            float(context.physics.pos[2]),
        ]
        try:
            from engine.change_journal import touch

            touch(actor)
        except (ImportError, AttributeError):
            pass

    def overhead_weapons(self):
        """Each visible party member's own held items and hand animations."""
        held = []
        for player in self.players.values():
            actor = player.actor
            if (actor is None or not player.connected
                    or player.session.game.character.is_dead
                    or actor.properties.get("hidden")):
                continue
            facing = float(player.physics.angle)
            size = float(actor.properties.get("sprite_width", 128) or 128)
            for entry in player.session.overhead_player_weapon():
                item, handed, attacking = entry[:3]
                if not item:
                    continue
                lag = float(entry[3] or 0.0) if len(entry) > 3 else 0.0
                block = float(entry[4] or 0.0) if len(entry) > 4 else 0.0
                held.append((tuple(actor.pos), facing + lag, item, handed,
                             attacking, size, block))
        return held

    def local_input(self, player_id, frame, actions=()):
        with self.input_lock:
            self.input_queue.append((player_id, frame, tuple(actions)))

    def _keyboard(self, ctx):
        from .. import keybinds

        keyboard = next(
            (p for p in self.local_players if p.profile["device"] == "keyboard"), None
        )
        if keyboard is None:
            return
        down = getattr(ctx, "key_down", lambda _: False)
        names = {
            "inventory",
            "character",
            "journal",
            "quest",
            "spells",
            "map",
            "levelup",
            "attack",
            "cast",
            "next_spell",
            "sneak",
            "heal",
            "interact",
        }
        current = frozenset(ctx.keys or ())
        edges = current - self._last_keys
        self._last_keys = current
        actions = []
        menu = (
            keyboard.session.open_screen is not None
            or keyboard.session.dialogue is not None
        )
        game_menu = getattr(self, "_game_menu_open", False)
        if 0x01000039 in edges:  # Qt.Key_F10: party pause, separate from Esc.
            actions.append(("pause", []))
        from ..host import _NAV_BY_CODE

        if game_menu:
            pass  # Qt owns this computer's game-menu keys; other peers continue.
        elif menu:
            for key in edges:
                for name in _NAV_BY_CODE.get(key, ()):
                    if name in (
                        "up",
                        "down",
                        "left",
                        "right",
                        "return",
                        "enter",
                        "escape",
                        "esc",
                    ):
                        actions.append(("menu_key", [name]))
        else:
            for action in names:
                binding = keybinds.key_binding(action)
                if (
                    binding
                    and down(binding)
                    and not getattr(self, "_key_" + action, False)
                ):
                    actions.append((action, []))
                setattr(self, "_key_" + action, bool(binding and down(binding)))
            for number in "123456789":
                if down(number) and not getattr(self, "_key_slot" + number, False):
                    actions.append(("select_strip_slot", [int(number) - 1]))
                setattr(self, "_key_slot" + number, down(number))
        mx, mz = (
            float(down("d")) - float(down("a")),
            float(down("w")) - float(down("s")),
        )
        aim = self.logic.game_state.get_aim_yaw()
        h = keyboard.physics.angle if aim is None else aim
        x, z = -mx * math.cos(h) + mz * math.sin(h), mx * math.sin(h) + mz * math.cos(h)
        length = max(1.0, math.hypot(x, z))
        x /= length
        z /= length
        held = set(self._mouse_held)
        if down("shift"):
            held.add("sprint")
        if down(keybinds.key_binding("block") or "b"):
            held.add("block")
        if menu or game_menu:
            x = z = 0
            held.clear()
        self.local_input(
            keyboard.player_id, InputFrame(x, z, aim, frozenset(held)), actions
        )

    def mouse_hand(self, mode, down):
        context = next(
            (p for p in self.local_players if p.profile["device"] == "keyboard"), None
        )
        if context is None:
            return
        name = "right_hand" if mode == "secondary" else "left_hand"
        (self._mouse_held.add if down else self._mouse_held.discard)(name)
        held = (
            set(context.frame.held) - {"left_hand", "right_hand"}
        ) | self._mouse_held
        self.local_input(
            context.player_id,
            InputFrame(
                context.frame.move_x,
                context.frame.move_z,
                context.frame.aim,
                frozenset(held),
            ),
        )

    def move_all(self, delta):
        """Called by Fio at the normal movement point, before world interactions."""
        if self.disconnected or self.paused:
            return
        if self.authority and any(p.bot for p in self.players.values()):
            from .bots import PartyBots

            if not hasattr(self, "_bots"):
                self._bots = PartyBots(self)
            self._bots.tick(delta)
        if not self.authority:
            from .replication import interpolate

            interpolate(self)
            # Predict only the locally controlled bodies. Authoritative frames
            # reconcile these positions; remote bodies are interpolated below.
            selected = self.local_players
        else:
            selected = list(self.players.values())
        before = {p.player_id: tuple(p.physics.pos) for p in selected}
        for context in selected:
            if time.monotonic() - context.last_input > self.INPUT_TIMEOUT:
                context.frame = InputFrame()
            if context.session.game.character.is_dead or not context.connected:
                continue
            step = min(0.05, max(0.0, delta))
            self._move_player(context, context.frame, step)
            context.simulated_sequence = context.sequence
            if not self.authority:
                context.prediction.append((context.local_sequence, step, context.frame))
            # Every controlled body participates in environmental triggers.
            # The primary body's normal engine trigger pass follows this.
            if self.authority and context.session is not self.root:
                context.session.logic.trigger_runtime._handle_triggers(False, delta)
                context.session.logic.portal_runtime.update(delta)
            self._sync_actor(context)
        self._camera(delta, before)

    def _move_player(self, context, frame, delta):
        """The same collision-aware step serves live input and reconciliation."""
        import glm

        if frame.aim is not None:
            context.physics.angle = frame.aim
        session = context.session
        menu = session.open_screen is not None or session.dialogue is not None
        move = glm.vec3(0) if menu else glm.vec3(frame.move_x, 0, frame.move_z)
        brushes = self.logic.collision_runtime._collision_brushes_cache
        movers = self.logic.mover_runtime._mover_brush_list
        doors = self.logic.mover_runtime._door_brush_list
        grid = self.logic.session_runtime.spatial_grid
        if context.returning:
            from .world import CompanionCollisionGrid, collision_brush

            # Streaming follows the human party. A returning bot still needs
            # its local collision hulls; never unhide shared render objects.
            if grid is not None:
                grid = CompanionCollisionGrid(grid)
            else:
                brushes = [collision_brush(b) for b in brushes]
            movers = [collision_brush(b) for b in movers]
            doors = [collision_brush(b) for b in doors]
        context.physics.update(
            delta,
            move,
            False,
            False,
            brushes,
            movers,
            doors,
            self.logic.world_runtime.terrain,
            spatial_grid=grid,
            sprint="sprint" in frame.held and session.game.character.stamina > 0,
            movement_angle=0.0,
        )

    def reconcile(self, context, data):
        import glm

        context.physics.pos = glm.vec3(*data["pos"])
        context.physics.velocity = glm.vec3(*data.get("velocity", (0, 0, 0)))
        context.physics.on_ground = bool(data.get("on_ground", False))
        context.physics.angle = float(data["angle"])
        ack = int(data.get("movement_ack", -1))
        while context.prediction and context.prediction[0][0] <= ack:
            context.prediction.popleft()
        if not self.paused and not context.session.game.character.is_dead:
            for _, delta, frame in context.prediction:
                self._move_player(context, frame, delta)
        self._sync_actor(context)

    @staticmethod
    def _footprint_scale(aspect, fov, angle):
        # Radius of the largest ground-plane circle inside all four frustum
        # planes, divided by camera height. This also covers an oblique view.
        tilt = math.radians(90 - max(15, min(90, angle)))
        c, s = math.cos(tilt), math.sin(tilt)
        v = math.tan(math.radians(max(30, min(120, fov))) / 2)
        h = v * max(0.25, min(4, aspect))
        return min(v / (c * (c + s * v)), h / (c * math.sqrt(1 + s * s * h * h)))

    def _camera(self, delta, before=None):

        active = [
            p
            for p in self.players.values()
            if p.connected and not p.session.game.character.is_dead and not p.returning
        ]
        if not active:
            active = list(self.players.values())[:1]
        if not active:
            return
        cam = self.logic.camera
        top = min(2200.0, float(cam.overhead_height_limit or 2200))
        scale = self._footprint_scale(
            cam.frustum_aspect, cam.frustum_fov, cam.overhead_angle
        )
        if self.authority:
            scales = [scale]
            for owner, viewport in self._viewports.items():
                if owner in self.lobby.peers.values():
                    scales.append(self._footprint_scale(*viewport))
            scale = min(scales)
            self._party_radius = max(48, min(self.MAX_SEPARATION, top * scale - 160))
        radius = min(self._party_radius, max(48, top * scale - 160))
        # Stop outward movement at the party boundary. Restoring the previous
        # collision-checked position never drags a body through a wall.
        for _ in range(4):
            x = sum(float(p.physics.pos.x) for p in active) / len(active)
            z = sum(float(p.physics.pos.z) for p in active) / len(active)
            for p in active:
                old = (before or {}).get(p.player_id)
                if (
                    old is not None
                    and math.hypot(p.physics.pos.x - x, p.physics.pos.z - z) > radius
                ):
                    p.physics.pos.x, p.physics.pos.z = old[0], old[2]
                    p.physics.velocity.x = p.physics.velocity.z = 0
                    self._sync_actor(p)
        x = sum(float(p.physics.pos.x) for p in active) / len(active)
        z = sum(float(p.physics.pos.z) for p in active) / len(active)
        y = sum(float(p.physics.pos.y) for p in active) / len(active)
        cam.set_camera_focus((x, y, z), glide=False)
        cam.overhead_orientation = "north"
        span = max(
            (
                math.hypot(float(p.physics.pos.x) - x, float(p.physics.pos.z) - z)
                for p in active
            ),
            default=0,
        )
        height = min(top, max(min(800, top), (span + 160) / scale))
        cam.overhead_height = max(
            height,
            cam.overhead_height
            + (height - cam.overhead_height) * (1 - math.exp(-max(0.0, delta) * 5)),
        )
        cam.overhead_height = min(top, cam.overhead_height)
        self.root._fit_bigworld_reach(cam, height)

    @contextlib.contextmanager
    def _locked(self):
        """Hold the party lock, always after the engine's ``monster_lock``.

        The MonsterAI thread runs under ``monster_lock`` and calls
        :meth:`damage` when a monster hits a party member, so it takes
        ``monster_lock`` then ``self.lock``. The logic thread's :meth:`tick`
        reaches code that takes ``monster_lock`` (the root session grounds
        actors under it). Taking ``self.lock`` first there would let the two
        threads wait on each other for ever: the game freezes on its last
        frame with no error. Both locks are re-entrant, so one order on every
        thread is enough.
        """
        with fio.monster_lock(self.logic) or contextlib.nullcontext():
            with self.lock:
                yield

    def damage(self, player_id, amount, kind="physical", source=None, cause="attack"):
        if not self.authority:
            return 0.0
        context = self.players.get(player_id)
        if context is None or context.session.game.character.is_dead:
            return 0.0
        if getattr(source, "properties", {}).get("multiplayer_player"):
            return 0.0
        with self._locked():
            runtime = fio.player_runtime(context.session.logic)
            runtime.last_damage = (source, cause, kind)
            if source is not None:
                from .bots import PartyBots
                if not hasattr(self, "_bots"):
                    self._bots = PartyBots(self)
                self._bots.note_attack(source)
            result = context.session._mitigate_incoming(amount, kind)
            context.session._sync_engine_health()
            if context.session.game.character.is_dead:
                context.session.open_screen = None
                context.session.end_dialogue()
            self._sync_actor(context)
            return result

    def prepare_ai(self, monsters):
        if not self.authority:
            return
        alive = [
            p
            for p in self.players.values()
            if p.connected and not p.session.game.character.is_dead
        ]
        if not alive:
            return
        for thing in monsters:
            props = thing.properties
            if props.get("multiplayer_player") or props.get("dead"):
                continue
            # A retaliating NPC keeps its specific offender; ordinary hunters
            # choose the nearest living party member, never an invisible P1.
            target = props.get("_aggro_target")
            owned = next(
                (
                    p
                    for p in self.players.values()
                    if p.actor is not None and id(p.actor) == target
                ),
                None,
            )
            if owned is not None and owned in alive:
                continue
            if not self.logic.monster_ai._hunts_player(thing):
                continue
            nearest = min(
                alive,
                key=lambda p: (
                    (p.actor.pos[0] - thing.pos[0]) ** 2
                    + (p.actor.pos[2] - thing.pos[2]) ** 2
                ),
            )
            props["_aggro_target"] = id(nearest.actor)

    def _drain_inputs(self):
        with self.input_lock:
            pending = list(self.input_queue)
            self.input_queue.clear()
        for pid, frame, actions in pending:
            context = self.players.get(pid)
            if context is None or context.owner != self.lobby.owner or context.bot:
                continue
            context.frame = frame
            context.last_input = time.monotonic()
            if self.authority:
                for action, args in actions:
                    try:
                        self.action(context, action, args)
                    except (ValueError, TypeError, KeyError, IndexError) as exc:
                        context.session.notify(str(exc)[:200], 4.0)
            else:
                self.sequence += 1
                context.local_sequence = self.sequence
                self.lobby.network.send(
                    "host",
                    {
                        "type": "input",
                        "player_id": pid,
                        "sequence": self.sequence,
                        "frame": frame.to_dict(),
                        "actions": [[a, list(v)] for a, v in actions],
                        "viewport": [
                            self.logic.camera.frustum_aspect,
                            self.logic.camera.frustum_fov,
                            self.logic.camera.overhead_angle,
                        ],
                    },
                )

    def request(self, player_id, action, args=()):
        context = self.players.get(player_id)
        if context is None:
            return
        if self.authority:
            return self.action(context, action, list(args))
        if context.owner != self.lobby.owner:
            return
        self.sequence += 1
        self.lobby.network.send(
            "host",
            {
                "type": "action",
                "player_id": player_id,
                "sequence": self.sequence,
                "action": action,
                "args": list(args),
            },
        )

    def _network(self):
        for peer, message in self.lobby.network.poll():
            if self.lobby.handle(peer, message):
                if (
                    self.authority
                    and message.get("type") == "hello"
                    and peer in self.lobby.peers
                ):
                    owner = self.lobby.peers[peer]
                    for context in self.players.values():
                        if context.owner == owner:
                            context.sequence = -1
                            context.frame = InputFrame()
                continue
            try:
                kind = message.get("type")
                if self.authority and kind in ("input", "action"):
                    self.lobby._rate_limit(peer, 400)
                    owner = self.lobby.peers.get(peer)
                    context = self.players.get(message.get("player_id"))
                    if context is None or owner is None or context.owner != owner:
                        raise LobbyError(
                            "That character does not belong to this connection."
                        )
                    sequence = message.get("sequence")
                    if not isinstance(sequence, int) or sequence <= context.sequence:
                        continue
                    context.sequence = sequence
                    context.last_input = time.monotonic()
                    if kind == "input":
                        context.frame = InputFrame.from_dict(message.get("frame"))
                        viewport = message.get("viewport")
                        if (
                            isinstance(viewport, list)
                            and len(viewport) == 3
                            and all(
                                isinstance(v, (int, float)) and math.isfinite(v)
                                for v in viewport
                            )
                        ):
                            self._viewports[owner] = (
                                max(0.25, min(4, viewport[0])),
                                max(30, min(120, viewport[1])),
                                max(15, min(90, viewport[2])),
                            )
                        actions = message.get("actions", [])
                        if not isinstance(actions, list) or len(actions) > 16:
                            raise LobbyError("Invalid action list.")
                        for action, args in actions:
                            self.action(context, action, args)
                    else:
                        self.action(
                            context, message.get("action"), message.get("args", [])
                        )
                elif not self.authority and peer == "host" and kind == "world":
                    self.apply_snapshot(message)
                elif not self.authority and peer == "host" and kind == "sounds":
                    sounds = message.get("sounds", [])
                    if not isinstance(sounds, list) or len(sounds) > 128:
                        raise LobbyError("Invalid sound events.")
                    for sound in sounds:
                        if isinstance(sound, dict) and isinstance(
                            sound.get("file"), str
                        ):
                            self.logic.game_state.queue_sound(sound)
                elif not self.authority and peer == "host" and kind == "travel":
                    import hashlib

                    from .compatibility import text_bytes
                    from .model import map_path

                    name = (
                        "maps/"
                        + str(message.get("map", "")).replace("\\", "/").split("/")[-1]
                    )
                    path = map_path(self.lobby.root, name)
                    if hashlib.sha256(text_bytes(path)).hexdigest() != message.get(
                        "map_hash"
                    ):
                        raise LobbyError(
                            "The destination map differs from the host's map."
                        )
                    self.lobby.travelling = True
                    self.lobby.map_name = name
                    self.lobby.state["map"] = name
                    self.logic.interaction_runtime.level_complete_ui = {
                        "active": True,
                        "immediate": True,
                        "target_map": name,
                        "destination_spawn": message.get("destination_spawn", ""),
                    }
            except (
                ValueError,
                TypeError,
                KeyError,
                IndexError,
                AttributeError,
                OverflowError,
            ) as exc:
                self.lobby.network.send(
                    peer, {"type": "error", "message": str(exc)[:200]}
                )
        self.lobby.maintenance()

    def tick(self, ctx):
        with self._locked():
            self._network()
            self.disconnected = bool(getattr(self.lobby, "disconnected", False))
            if self.disconnected:
                for player in self.players.values():
                    player.frame = InputFrame()
            self._keyboard(ctx)
            self._drain_inputs()
            if self._world_bindings is not None:
                self._world_bindings.sync()
            # Character ownership survives socket replacement on reconnect.
            state = self.lobby.state or {}
            for member in state.get("members", []):
                player = self.players.get(member["player_id"])
                if player is None and self.authority and member.get("ready"):
                    player = self._create_player(member)
                    self.install_added_player(player)
                if player is not None:
                    player.connected = member.get("connected", True)
            delta = min(0.1, max(0.0, float(ctx.delta)))
            if self.authority and self.travel is not None:
                for player in self.players.values():
                    if (
                        player.bot
                        and player.connected
                        and not player.session.game.character.is_dead
                    ):
                        self.ready_to_travel(player)
            for player in self.players.values():
                player.session.sprint_held = (
                    player.connected and "sprint" in player.frame.held
                )
            if self.authority and not self.paused:
                self.root.tick(delta)
                for player in self.players.values():
                    self._player_tick(
                        player, delta, primary=player.session is self.root
                    )
                self.party_quests.collect_shared_items()
                self.party_quests.tick()
                self._death_flow(delta)
            else:
                for player in self.players.values():
                    player.session.tick_ui(delta)
            from ..ui import hits

            hits.run_clicks(self.ui_session)
            if self.lobby.errors:
                self.ui_session.notify(self.lobby.errors.pop(0), 6.0)
            if not self.authority:
                candidates = [
                    p
                    for p in self.local_players
                    if p.session.open_screen is not None
                    or p.session.dialogue is not None
                ]
                if candidates:
                    self._ui_owner = candidates[-1].player_id
            self.persist()
            if self.authority and self._sounds:
                sounds = []
                while self._sounds:
                    sounds.append(self._sounds.popleft())
                self.lobby.network.broadcast(
                    {"type": "sounds", "sounds": sounds}, peers=self.lobby.peers
                )
            if (
                self.authority
                and self.lobby.peers
                and time.monotonic() - self._snapshot_at >= self.SNAPSHOT_INTERVAL
            ):
                self._snapshot_at = time.monotonic()
                self.lobby.network.broadcast(
                    self.snapshot(), replace=True, peers=self.lobby.peers
                )

    def _player_tick(self, context, delta, primary=False):
        session = context.session
        if not context.connected:
            context.frame = InputFrame()
            self._sync_actor(context)
            return
        frame = context.frame
        if not session.game.character.is_dead:
            session.logic.interaction_runtime.handle(False)
            session.interact_prompt = fio.interaction_prompt(session.logic) or ""
            if not session.interact_prompt:
                target = session.nearest_talkable(context.physics.pos, 200)
                if target is None:
                    target = session.nearest_container(context.physics.pos, 200)
                if target is None:
                    target = session.nearest_corpse(context.physics.pos, 200)
                if target is not None:
                    session.interact_prompt = "Interact: " + str(
                        target.properties.get("display_name")
                        or target.properties.get("name")
                        or "object"
                    )
            for marker in self.root._things_of_type("marker"):
                props = marker.properties
                if props.get("marker_kind") != "location":
                    continue
                if session._dist2d(context.physics.pos, marker.pos) <= float(
                    props.get("discover_radius", 200)
                ):
                    self.party_quests.record(
                        "visit",
                        [props.get(k) for k in ("id", "name", "place_name")],
                        session._thing_id(marker),
                        context.player_id,
                    )
        if not primary:
            session.game.tick(delta, session._sprint(delta))
            session._update_bow_draw(delta)
            session._update_encumbrance()
            session._announce_skill_raises()
            for name in (
                "_attack_cooldown",
                "_offhand_cooldown",
                "_cast_cooldown",
                "_player_flash",
                "_attack_anim_time",
                "_offhand_anim_time",
            ):
                setattr(session, name, max(0.0, getattr(session, name, 0.0) - delta))
            session._tick_pickups()
            session._tick_spellbooks()
            session._tick_triggers()
            session._tick_locations()
            session._age_lists(delta)
            session._sync_engine_health()
        session.toggle_block("block" in frame.held)
        if not session.game.character.is_dead:
            for name, mode in (("left_hand", "primary"), ("right_hand", "secondary")):
                held = name in frame.held
                was = name in context.previous.held
                charge_hand = (
                    session.charge_in_hand() and session.mouse_hand(mode) == "main"
                )
                if held and not was:
                    if charge_hand:
                        session.bow_draw_input("press")
                    else:
                        session.fire_player_weapon(session.logic, mode)
                elif was and not held and charge_hand:
                    session.bow_draw_input("release")
            if "interact" in frame.held:
                self._revive_near(context, delta)
        if (
            session.dialogue_npc is not None
            and session._dist2d(context.physics.pos, session.dialogue_npc.pos) > 260
        ):
            session.end_dialogue()
        if session.open_screen == "lockpicking":
            session.tick_lockpicking(delta)
        context.previous = frame
        self._sync_actor(context)

    def install_added_player(self, context):
        # A late arrival is put beside the current party at a collision-checked
        # spawn rather than at an unrelated authored PlayerStart.
        self.install_world_player(context)
        self.party_quests.attach(context.player_id, context.session.game)
        self.checkpoint()

    def _prepare_player_session(self, context):
        session = context.session
        if session is self.root:
            return
        for name in (
            "clock",
            "director",
            "memory",
            "living",
            "world_index",
            "rng",
            "nav",
            "roads",
            "_arrow_tags",
            "_arrow_traces",
            "_arrow_trace_lock",
            "magic_fx",
            "gore",
            "archery",
            "npc_magic",
            "burning",
            "tactics",
            "head_registry",
            "windmills",
            "flour_supply",
        ):
            setattr(session, name, getattr(self.root, name))
        session._world_bounds = getattr(self.root, "_world_bounds", None)
        session._rebuild_type_index(fio.things(self.logic))
        session.logic.trigger_runtime.rebuild_trigger_index(
            getattr(self.logic.editor_state, "brushes", [])
        )
        session.logic.trigger_runtime._coop_player_only = True
        session.logic.trigger_runtime.fired_once_triggers = (
            self.logic.trigger_runtime.fired_once_triggers
        )
        session.logic.portal_runtime = copy.copy(self.logic.portal_runtime)
        session.logic.portal_runtime.logic = session.logic
        session.logic.portal_runtime.note_player_teleported()
        self.root.director.bus.subscribe(session._alignment_event)

    def install_world_player(self, context):
        # Shared implementation used after an in-progress lobby addition.
        from ..entities import NPC

        self._prepare_player_session(context)
        context.actor = NPC(
            pos=list(context.physics.pos),
            properties={
                "id": context.player_id,
                "name": context.profile["name"],
                "display_name": context.profile["name"],
                "team": "player",
                "faction": "player",
                "is_player": True,
                "player_id": context.player_id,
                "multiplayer_player": True,
                "bw_persistent": True,
                "disabled": True,
                "combatant": True,
                "aggression": "passive",
                "sprite": heads.head_path(context.profile["head"]),
                "head": context.profile["head"],
                "custom_idle": heads.head_path(context.profile["head"]),
                "custom_shoot": heads.head_path(context.profile["head"]),
                "sprite_height": 128,
                "sprite_width": 128,
                "_sim_tier": 0,
            },
        )
        fio.things(self.logic).append(context.actor)
        self.root.head_registry.set_players(
            {p.player_id: p.profile["head"] for p in self.players.values()}
        )
        self._sync_actor(context)
        fio.rebuild_entity_caches(self.logic)

    def action(self, context, action, args=()):
        if (
            action not in self.ACTIONS
            or not isinstance(args, (list, tuple))
            or len(args) > 8
        ):
            raise LobbyError("Invalid player action.")
        if not self.authority:
            return self.request(context.player_id, action, args)
        session = context.session
        if session.game.character.is_dead and action not in (
            "pause",
            "revive",
            "reload_checkpoint",
            "menu_key",
        ):
            return
        if self.paused and action in (
            "attack",
            "cast",
            "cast_at",
            "heal",
            "sneak",
            "interact",
            "revive",
            "travel_ready",
        ):
            return
        if action == "screen":
            from ..ui.screens import STATISTICS_SCREENS

            self.focus(context)
            name = args[0]
            if name not in (*STATISTICS_SCREENS, None, "quest", "levelup"):
                raise LobbyError("Invalid character screen.")
            session.open_screen = name
        elif action == "character_level_up":
            if not session.game.character.can_level_up:
                raise LobbyError("No level is available.")
            result = session.game.character.level_up(choice=args[0])
            session.notify(f"Welcome to level {result['level']}!", 5.0)
            session.open_screen = (
                "levelup" if session.game.character.can_level_up else None
            )
        elif action == "rpg_action":
            name, values = args
            if name not in (
                "use_item",
                "equip",
                "unequip",
                "select_next_spell",
                "roll_for_quest",
            ):
                raise LobbyError("Invalid character action.")
            getattr(session.game, name)(*values)
        elif action in (
            "inventory",
            "character",
            "journal",
            "quest",
            "spells",
            "map",
            "levelup",
        ):
            self.focus(context)
            session.open_screen = None if session.open_screen == action else action
            if context.owner == self.lobby.owner:
                self._ui_owner = context.player_id
        elif action == "attack":
            session.attack_with_both()
        elif action == "cast":
            session.cast_key()
        elif action == "cancel_spell_aim":
            session.cancel_spell_aim()
        elif action == "cast_at":
            point, target_id = args
            target = (
                next(
                    (
                        t
                        for t in fio.things(self.logic)
                        if str(t.properties.get("id")) == str(target_id)
                    ),
                    None,
                )
                if target_id
                else None
            )
            if point is not None and (
                not isinstance(point, list)
                or len(point) != 3
                or not all(
                    isinstance(v, (int, float)) and math.isfinite(v) for v in point
                )
            ):
                raise LobbyError("Invalid spell target.")
            session.cast_at(point, target)
        elif action == "next_spell":
            session.next_spell()
        elif action == "sneak":
            session.toggle_sneak()
        elif action == "heal":
            session.use_health_potion()
        elif action == "interact":
            self.interact(context)
        elif action in ("strip_prev", "strip_next"):
            session.cycle_strip(-1 if action == "strip_prev" else 1)
        elif action == "pause":
            if context.owner != self.lobby.lobby.host:
                raise LobbyError("Only the host can pause the party.")
            self.paused = not self.paused
            fio.set_world_paused(self.logic, "miniwind.party", self.paused)
        elif action == "menu_key":
            key = str(args[0])
            if key in ("tab_prev", "tab_next"):
                from ..ui.screens import next_statistics_tab

                session.open_screen = next_statistics_tab(
                    session.open_screen, 1 if key == "tab_next" else -1
                )
                return
            if session.dialogue is not None:
                session.dialogue_key(key)
            elif key in ("escape", "esc"):
                session.open_screen = None
            else:
                from ..ui import screens

                screens.handle_key(session, key)
        elif action == "revive":
            self._revive_near(
                context, 0
            )  # Progress comes only from held input and server time.
        elif action == "reload_checkpoint":
            if context.owner == self.lobby.lobby.host:
                self.restore_checkpoint()
        elif action == "travel_ready":
            self.ready_to_travel(context)
        elif action == "choose":
            if session.dialogue is None:
                raise LobbyError("That conversation has ended.")
            self.party_quests.transaction(lambda: session.choose(int(args[0])))
        else:
            # Existing game verbs enforce equipment, quantities, prices, class
            # prerequisites and cooldowns. Never accept arbitrary attributes or
            # an executable callback from the network.
            self._validate_menu_target(context, action, args)
            getattr(session, action)(*args)

    def _validate_menu_target(self, context, action, args=()):
        session = context.session
        if action in ("buy", "sell"):
            target = session.merchant_npc
        elif action == "item_drop":
            if not args or not any(
                isinstance(v, (list, tuple)) and v and v[0] == "container" for v in args
            ):
                return
            target = session.container_thing
        elif action in (
            "take_from_container",
            "store_in_container",
            "take_all_from_container",
        ):
            target = session.container_thing
        elif action in ("train_with_teacher", "learn_from_teacher"):
            target = session.trainer_npc
        else:
            return
        if target is None or session._dist2d(context.physics.pos, target.pos) > 240:
            raise LobbyError("That object is no longer within reach.")

    def interact(self, context):
        session = context.session
        self.focus(context)
        if getattr(session, "_strip_confirm_pending", False):
            session._strip_confirm_pending = False
            session.select_strip_slot(session.strip_selected)
            return
        if session.open_screen is not None:
            session.open_screen = None
            return
        if session.dialogue is not None:
            session.end_dialogue()
            return
        if self.travel is not None:
            self.ready_to_travel(context)
            return
        session.logic.interaction_runtime.handle(True)
        transition = session.logic.interaction_runtime.level_complete_ui
        if transition:
            session.logic.interaction_runtime.level_complete_ui = None
            if transition.get("generate_level"):
                session.notify(
                    "Co-op travel requires an installed destination map.", 5.0
                )
                return
            self.travel = dict(transition, ready=[context.player_id])
            for p in self.players.values():
                p.session.notify("Party travel requested. Press interact to join.", 6.0)
            self.ready_to_travel(context)
            return
        if fio.interaction_prompt(session.logic):
            return
        if self._revive_near(context, 0):
            return
        npc = session.nearest_talkable(context.physics.pos, 200.0)
        if npc is not None:
            if any(
                p.session.dialogue_npc is npc and p.session.dialogue is not None
                for p in self.players.values()
            ):
                session.notify("A party member is speaking with them.")
                return
            session.start_dialogue(npc, context.physics)
        else:
            corpse = session.nearest_corpse(context.physics.pos, 200.0)
            container = session.nearest_container(context.physics.pos, 200.0)
            if corpse is not None and (
                container is None
                or session._dist2d(context.physics.pos, corpse.pos)
                < session._dist2d(context.physics.pos, container.pos)
            ):
                session.loot_corpse(corpse)
            elif container is not None:
                session.open_container(container)
        if context.owner == self.lobby.owner:
            self._ui_owner = context.player_id

    def ready_to_travel(self, context):
        if self.travel is None:
            return
        if context.player_id not in self.travel["ready"]:
            self.travel["ready"].append(context.player_id)
        live = {
            p.player_id
            for p in self.players.values()
            if p.connected and not p.session.game.character.is_dead
        }
        if live.issubset(self.travel["ready"]):
            request = dict(self.travel)
            request.pop("ready", None)
            name = (
                "maps/"
                + str(request.get("target_map", "")).replace("\\", "/").split("/")[-1]
            )
            import hashlib

            from .compatibility import text_bytes
            from .model import map_path

            map_hash = hashlib.sha256(
                text_bytes(map_path(self.lobby.root, name))
            ).hexdigest()
            request["immediate"] = True
            self.logic.interaction_runtime.level_complete_ui = request
            self.lobby.travelling = True
            self.lobby.network.broadcast(
                {
                    "type": "travel",
                    "map": request.get("target_map", ""),
                    "destination_spawn": request.get("destination_spawn", ""),
                    "map_hash": map_hash,
                },
                peers=self.lobby.peers,
            )
            self.lobby.map_name = self.lobby.lobby.map_name = name
            self.lobby.lobby.map_hash = map_hash
            self.lobby.state = self.lobby.lobby.snapshot()
            self.travel = None

    def _revive_near(self, context, delta):
        for victim in self.players.values():
            if victim is context or not victim.session.game.character.is_dead:
                continue
            if context.session._dist2d(context.physics.pos, victim.physics.pos) > 130:
                continue
            key = context.player_id, victim.player_id
            now = time.monotonic()
            last, total = self._reviving.get(key, (now, 0.0))
            total = (total if now - last < 0.4 else 0.0) + delta
            self._reviving[key] = (now, total)
            context.session.interact_prompt = "Hold interact to revive your companion"
            if total >= self.REVIVE_SECONDS:
                victim.session.game.character.health = max(
                    1.0, victim.session.game.character.max_health * 0.3
                )
                victim.session._sync_engine_health()
                self._sync_actor(victim)
                self._reviving.pop(key, None)
            return True
        return False

    def _death_flow(self, delta):
        if self.respawn_at_village:
            for bot in self.players.values():
                if (not bot.bot or not bot.connected
                        or not bot.session.game.character.is_dead):
                    self._bot_deaths.pop(bot.player_id, None)
                    continue
                elapsed = self._bot_deaths.get(bot.player_id, 0.0) + delta
                self._bot_deaths[bot.player_id] = elapsed
                if elapsed >= self.BOT_RESPAWN_SECONDS:
                    self._respawn_bot(bot)
        connected = [p for p in self.players.values() if p.connected]
        can_respawn = self.respawn_at_village and any(p.bot for p in connected)
        if (connected and not can_respawn
                and all(p.session.game.character.is_dead for p in connected)):
            if self._wipe_at is None:
                self._wipe_at = time.monotonic()
                for p in connected:
                    p.session.notify(
                        "The party has fallen. Returning to the last checkpoint…", 5.0
                    )
            elif time.monotonic() - self._wipe_at > 3:
                self.restore_checkpoint()
        else:
            self._wipe_at = None

    def _respawn_bot(self, bot):
        import glm

        session, physics = bot.session, bot.physics
        character = session.game.character
        character.effects.clear()
        character.health = character.max_health
        character.stamina = character.max_stamina
        character.magicka = character.max_magicka
        # Keep the authored start even when the party has moved or resumed a save.
        physics.pos = glm.vec3(*self._village_spawn)
        physics.velocity = glm.vec3(0)
        physics.on_ground = False
        bot.frame = bot.previous = InputFrame()
        bot.prediction.clear()
        bot.bot_target = None
        bot.returning = True
        bot.task = "Returning from village"
        session._cancel_bow_draw()
        session.toggle_block(False)
        session.open_screen = None
        session.end_dialogue()
        session._sync_engine_health()
        session.logic.portal_runtime.note_player_teleported()
        if session.nav is not None and bot.actor is not None:
            session.nav.forget(id(bot.actor))
        self.root._road_plans.pop(id(bot.actor), None)
        self._bot_deaths.pop(bot.player_id, None)
        self._reviving = {
            key: value for key, value in self._reviving.items()
            if bot.player_id not in key
        }
        self._sync_actor(bot)
        self.ui_session.notify(bot.profile["name"] + " respawned at the village.")

    def campaign(self):
        return {
            "version": 1,
            "campaign_id": self.lobby.state["campaign_id"],
            "respawn_at_village": self.respawn_at_village,
            "world": {
                **copy.deepcopy(self.party_quests.store.all()),
                "_clock_hour": str(self.root.clock.hour),
                "_clock_day": str(self.root.clock.day),
            },
            "members": copy.deepcopy(self.lobby.state["members"]),
            "players": {
                pid: {
                    "character": p.session.game.character.to_dict(),
                    "position": list(p.physics.pos),
                    "angle": p.physics.angle,
                    "returning": p.returning,
                    "companion": (
                        (p.mind or CompanionMind(self.lobby.state["campaign_id"], pid)).to_dict()
                        if p.bot else None
                    ),
                }
                for pid, p in self.players.items()
            },
        }

    def simulation_focus(self):
        import glm

        live = [p for p in self.players.values() if p.connected and not p.returning]
        if not live:
            return None
        return sum((p.physics.pos for p in live), glm.vec3(0)) / len(live)

    def focus(self, context):
        for other in self.players.values():
            if other is context or other.owner != context.owner:
                continue
            other.session.open_screen = None
            other.session.end_dialogue()
        if context.owner == self.lobby.owner:
            self._ui_owner = context.player_id

    def portal_arrived(self, traveller):
        if not self.authority:
            return
        import glm

        origin = traveller.pos
        for i, context in enumerate(self.players.values()):
            if context.physics is traveller:
                continue
            x, z = float(origin.x) + (i % 2) * 48, float(origin.z) + (i // 2) * 48
            if self.root._blocked_by_wall(x, float(origin.y) + 48, z):
                x, z = float(origin.x), float(origin.z)
            context.physics.pos = glm.vec3(x, origin.y, z)
            context.physics.velocity = glm.vec3(0)
            context.physics.angle = traveller.angle
            context.session.logic.portal_runtime.note_player_teleported()
            self._sync_actor(context)

    def persist(self):
        if not self.authority:
            return
        if time.monotonic() - self._persist_at < 1:
            return
        self._persist_at = time.monotonic()
        self.root.persist()
        for player in self.players.values():
            if player.session is not self.root:
                player.session.law.persist()
        self.lobby.campaign_state = self.campaign()

    def checkpoint(self):
        if self.authority:
            from engine import savegame

            self._checkpoint = savegame.build_snapshot(self.logic)

    def restore_checkpoint(self):
        if self._checkpoint is None:
            return
        from engine import savegame

        savegame.restore_snapshot(self.logic, self._checkpoint)
        self._wipe_at = None

    def restore_campaign(self, saved):
        if (
            saved.get("version") != 1
            or saved.get("campaign_id") != self.lobby.state["campaign_id"]
        ):
            raise ValueError("The save belongs to a different co-op campaign.")
        clear = getattr(self.party_quests.store, "clear", None)
        if clear is not None:
            clear()
        for key, value in saved["world"].items():
            self.party_quests.store.set(key, value)
        import glm

        for pid, data in saved["players"].items():
            p = self.players[pid]
            p.session.game.character = Character.from_dict(data["character"])
            p.physics.pos = glm.vec3(*data["position"])
            p.physics.velocity = glm.vec3(0)
            p.returning = p.bot and bool(data.get("returning", False))
            p.mind = (CompanionMind(saved["campaign_id"], pid, data.get("companion"))
                      if p.bot else None)
            p.frame = p.previous = InputFrame()
            p.bot_target = None
            p.prediction.clear()
            p.actor = next(
                (
                    t
                    for t in fio.things(self.logic)
                    if t.properties.get("player_id") == pid
                ),
                p.actor,
            )
            p.session.open_screen = None
            p.session.end_dialogue()
            self._sync_actor(p)
            p.session.law.restore()
        self.root.director.restore()
        self.root.clock.hour = float(
            saved["world"].get("_clock_hour", self.root.clock.hour)
        )
        self.root.clock.day = int(
            float(saved["world"].get("_clock_day", self.root.clock.day))
        )
        self._wipe_at = None
        self._bot_deaths.clear()
        # References and reaction deadlines belong to the old live world.
        if hasattr(self, "_bots"):
            from .bots import PartyBots
            self._bots = PartyBots(self)

    def snapshot(self):
        from .replication import capture

        return capture(self)

    def apply_snapshot(self, message):
        from .replication import apply

        return apply(self, message)

    def leave(self):
        if self._device_reader is not None:
            self._device_reader.close()
            self._device_reader = None
        if self.authority:
            self.logic.game_state.sound_observer = self._old_sound_observer
        self._persist_at = 0
        self.persist()
        if self.authority:
            from engine import savegame

            self.root.persist(force=True)
            path = (
                self.lobby.root
                / "saves"
                / ("coop_" + self.lobby.state["campaign_id"] + "_latest.fiosave")
            )
            data = savegame.build_snapshot(
                self.logic, map_name=self.map_name.split("/")[-1]
            )
            savegame.write(str(path), data)
        # Avatars are campaign characters, never permanently authored map NPCs.
        things = fio.things(self.logic)
        things[:] = [
            t
            for t in things
            if not getattr(t, "properties", {}).get("multiplayer_player")
        ]
        if self._world_bindings is not None:
            self._world_bindings.close()
        from ..ui import hits

        hits.clear()
        if not getattr(self.lobby, "travelling", False):
            from .lobby import finish

            finish()
