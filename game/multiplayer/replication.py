"""Value-only authoritative frames and client UI command adapters."""

from __future__ import annotations

from collections.abc import Mapping
import math
import time

from .. import fio
from ..rpg.character import Character

FIELDS = frozenset(
    (
        "id",
        "type",
        "name",
        "display_name",
        "npc_role",
        "monster_type",
        "team",
        "faction",
        "health",
        "max_health",
        "dead",
        "hidden",
        "disabled",
        "head",
        "sprite",
        "sprite_file",
        "sprite_width",
        "sprite_height",
        "sprite_scale",
        "opacity",
        "custom_idle",
        "custom_shoot",
        "custom_dead",
        "equipped_weapon",
        "offhand_weapon",
        "handed",
        "is_shooting",
        "_facing",
        "_attack_anim",
        "_offhand_anim",
        "_active_weapon",
        "_bow_charge",
        "_ward_until",
        "_ward_strength",
        "_shield_blocking",
        "_shield_pose",
        "item_id",
        "quantity",
        "locked",
        "lock_jammed",
        "lock_difficulty",
        "lockpick_state",
        "multiplayer_player",
        "player_id",
        "is_player",
        "marker_kind",
        "place_name",
        "intensity",
        "radius",
        "color",
        "state",
        "orientation",
        "angle",
        "_sim_tier",
    )
)


def clean(value):
    """Drop runtime object references/callables; never serialise Python objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Mapping):
        # A dict, or the engine's row view of a door's or mover's state.
        return {str(k): clean(v) for k, v in value.items()
                if not callable(v) and not str(k).startswith("_")}
    return None


def identity(thing):
    return str(thing.properties.get("id") or thing.properties.get("name") or "")


def capture(coop):
    from engine.savegame import _capture_moving_brushes

    coop.sequence += 1
    entities = []
    for thing in fio.things(coop.logic):
        props = getattr(thing, "properties", {})
        sid = identity(thing)
        if not sid:
            continue
        entities.append(
            {
                "id": sid,
                "pos": [float(v) for v in thing.pos],
                "props": clean({k: v for k, v in props.items() if k in FIELDS}),
            }
        )
    players = {}
    for pid, p in coop.players.items():
        s = p.session
        targets = {}
        for field in (
            "dialogue_npc",
            "merchant_npc",
            "container_thing",
            "trainer_npc",
            "lockpick_thing",
        ):
            target = getattr(s, field, None)
            if target is not None:
                targets[field] = {
                    "id": identity(target),
                    "props": clean(target.properties),
                }
        players[pid] = {
            "owner": p.owner,
            "profile": p.profile,
            "connected": p.connected,
            "bot": p.bot,
            "task": p.task,
            "returning": p.returning,
            "character": clean(s.game.character.to_dict()),
            "pos": [float(v) for v in p.physics.pos],
            "angle": float(p.physics.angle),
            "ack": p.sequence,
            "movement_ack": p.simulated_sequence,
            "velocity": [float(v) for v in p.physics.velocity],
            "on_ground": p.physics.on_ground,
            "screen": s.open_screen,
            "dialogue": clean(s.current_view()),
            "targets": targets,
            "selected": s.dialogue_selected,
            "notifications": clean(s.notifications),
            "prompt": s.interact_prompt,
            "floaters": clean(s.floaters),
            "bow_charge": s.bow_charge,
            "spell_aiming": s.spell_aiming,
            "strip_selected": s.strip_selected,
            "blocking": s._blocking,
            "attack_anim": s._attack_anim_time,
            "offhand_anim": s._offhand_anim_time,
            "cast_cooldown": s._cast_cooldown,
            "log": clean(s.game.log[-20:]),
            "roll_log": clean(s.roll_log),
            "dice_animation": clean(s.dice_animation) if not p.bot else None,
        }
    values = coop.party_quests.store.all()
    world = {
        k: v
        for k, v in values.items()
        if k.startswith(("quest.", "party.", "visited.", "players."))
    }
    movers = {str(k): clean(v) for k, v in coop.logic.mover_runtime.door_states.items()}
    fx = coop.root.magic_fx.frame()
    projectiles = coop.logic.combat_runtime.projectile_positions
    return {
        "type": "world",
        "sequence": coop.sequence,
        "map": coop.map_name,
        "players": players,
        "entities": entities,
        "world": clean(world),
        "clock": {"hour": coop.root.clock.hour, "day": coop.root.clock.day},
        "paused": coop.paused,
        "party_radius": coop._party_radius,
        "travel": clean(coop.travel),
        "doors": movers,
        "moving_brushes": _capture_moving_brushes(coop.logic),
        "arrows": clean(coop.root.arrows_in_flight),
        "arrow_paths": clean(coop.root.arrow_paths),
        "magic": [fx[0].tolist(), clean(fx[1]), clean(fx[2])],
        "projectiles": projectiles.tolist(),
    }


class RemoteDialogue:
    def __init__(self, view):
        self._view = view

    def view(self):
        return self._view


def apply(coop, message):
    if message.get("map") != coop.map_name:
        return
    sequence = message.get("sequence")
    if not isinstance(sequence, int) or sequence <= coop._received_sequence:
        return
    players = message.get("players")
    entities = message.get("entities")
    if (
        not isinstance(players, dict)
        or not 1 <= len(players) <= 4
        or not isinstance(entities, list)
    ):
        raise ValueError("Invalid authoritative world frame.")
    if len(entities) > 50000:
        raise ValueError("Too many entities in world frame.")
    coop._applying = True
    try:
        import glm

        from editor.things import Thing
        from engine.savegame import _restore_moving_brushes

        from ..entities import NPC, Creature

        _restore_moving_brushes(coop.logic, message.get("moving_brushes"))
        coop.paused = bool(message.get("paused"))

        things = fio.things(coop.logic)
        here = {identity(t): t for t in things if identity(t)}
        present = set()
        rebuilt = False
        for data in entities:
            sid = str(data["id"])
            present.add(sid)
            thing = here.get(sid)
            if thing is None:
                kind = str(data["props"].get("type", "")).lower()
                from editor.things import ENTITY_TYPES
                from plugins.manager import get_manager

                builtins = {
                    str(k).replace("_", "").lower(): v for k, v in ENTITY_TYPES.items()
                }
                cls = (
                    get_manager().entity_class_for_type(kind)
                    or builtins.get(kind.replace("_", ""))
                    or (
                        NPC
                        if kind == "npc"
                        else Creature
                        if kind in ("creature", "monster")
                        else Thing
                    )
                )
                thing = cls(pos=data["pos"], properties=data["props"])
                things.append(thing)
                here[sid] = thing
                rebuilt = True
            if not hasattr(coop, "_render_targets"):
                coop._render_targets = {}
            coop._render_targets[sid] = (
                thing,
                list(thing.pos),
                list(data["pos"]),
                time.monotonic(),
            )
            thing.properties.update(data["props"])
            # Replicas never decide or produce independent actions.
            from engine.change_journal import touch

            touch(thing)
        removed = [t for t in things if identity(t) and identity(t) not in present]
        if removed:
            things[:] = [t for t in things if t not in removed]
            rebuilt = True
        if hasattr(coop, "_render_targets"):
            coop._render_targets = {
                k: v for k, v in coop._render_targets.items() if k in present
            }
        if rebuilt:
            fio.rebuild_entity_caches(coop.logic)
        for pid, data in players.items():
            context = coop.players.get(pid)
            if context is None:
                context = coop._create_player(
                    {
                        "player_id": pid,
                        "owner": data["owner"],
                        "profile": data["profile"],
                        "bot": data.get("bot", False),
                    },
                    saved={"character": data["character"]},
                )
                make_remote(context)
            s = context.session
            context.connected = bool(data["connected"])
            context.bot = bool(data.get("bot", False))
            context.task = str(data.get("task", ""))
            context.returning = bool(data.get("returning", False)) and context.bot
            context.actor = here.get(pid)
            s.game.character = Character.from_dict(data["character"])
            s.open_screen = data.get("screen")
            view = data.get("dialogue")
            s.dialogue = RemoteDialogue(view) if view else None
            s.dialogue_selected = int(data.get("selected", 0))
            s.notifications = list(data.get("notifications", []))
            s.interact_prompt = str(data.get("prompt", ""))
            s.floaters = list(data.get("floaters", []))
            s.bow_charge = data.get("bow_charge")
            s.spell_aiming = bool(data.get("spell_aiming"))
            s.strip_selected = int(data.get("strip_selected", 0))
            s._blocking = bool(data.get("blocking"))
            s._attack_anim_time = float(data.get("attack_anim", 0.0))
            s._offhand_anim_time = float(data.get("offhand_anim", 0.0))
            s._cast_cooldown = float(data.get("cast_cooldown", 0.0))
            s.game.log = list(data.get("log", []))
            s.roll_log = list(data.get("roll_log", []))
            s.dice_animation = data.get("dice_animation") if not context.bot else None
            for field in (
                "dialogue_npc",
                "merchant_npc",
                "container_thing",
                "trainer_npc",
                "lockpick_thing",
            ):
                detail = data.get("targets", {}).get(field)
                target = here.get(detail["id"]) if detail else None
                if target is not None:
                    target.properties.update(detail["props"])
                setattr(s, field, target)
            if context.owner == coop.lobby.owner:
                coop.reconcile(context, data)
            else:
                context.physics.pos = glm.vec3(*data["pos"])
                context.physics.angle = float(data["angle"])
        values = message.get("world", {})
        for key in coop.party_quests.store.all():
            if (
                key.startswith(("quest.", "party.", "visited.", "players."))
                and key not in values
            ):
                coop.party_quests.store.set(key, "")
        for key, value in values.items():
            coop.party_quests.store.set(key, value)
        clock = message.get("clock", {})
        coop.root.clock.hour = float(clock.get("hour", coop.root.clock.hour))
        coop.root.clock.day = int(clock.get("day", coop.root.clock.day))
        coop.paused = bool(message.get("paused"))
        coop._party_radius = float(message.get("party_radius", coop.MAX_SEPARATION))
        coop.travel = message.get("travel")
        coop.root.arrows_in_flight = tuple(message.get("arrows", []))
        coop.root.arrow_paths = tuple(message.get("arrow_paths", []))
        import numpy as np

        fx = message.get("magic", [[], [], []])
        coop.remote_fx = (
            np.asarray(fx[0], dtype=np.float32).reshape(-1, 12),
            fx[1],
            fx[2],
        )
        coop.logic.combat_runtime.projectile_positions = np.asarray(
            message.get("projectiles", []), dtype=np.float32
        ).reshape(-1, 3)
        for key, value in message.get("doors", {}).items():
            coop.logic.mover_runtime.door_states[int(key)] = value
        coop._received_sequence = sequence
    finally:
        coop._applying = False


def interpolate(coop):
    from engine.change_journal import touch

    now = time.monotonic()
    for thing, start, end, received in getattr(coop, "_render_targets", {}).values():
        if thing.properties.get("multiplayer_player") and any(
            p.actor is thing and p.owner == coop.lobby.owner
            for p in coop.players.values()
        ):
            continue
        alpha = min(1.0, max(0.0, (now - received) / coop.SNAPSHOT_INTERVAL))
        thing.pos = [a + (b - a) * alpha for a, b in zip(start, end)]
        touch(thing)


def make_remote(context):
    from ..runtime import MiniwindSession

    class RemoteSession(MiniwindSession):
        def __getattribute__(self, name):
            if name in (
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
                "cast_at",
                "cancel_spell_aim",
            ):
                coop = object.__getattribute__(self, "coop")
                if not getattr(coop, "_applying", False):
                    pid = object.__getattribute__(self, "player_id")

                    def send(*args, **kwargs):
                        if name == "cast_at":
                            point, target = (args + (None,))[:2]
                            return coop.request(
                                pid,
                                name,
                                [
                                    point,
                                    identity(target) if target is not None else None,
                                ],
                            )
                        if kwargs:
                            import inspect

                            bound = inspect.signature(
                                getattr(MiniwindSession, name)
                            ).bind(self, *args, **kwargs)
                            bound.apply_defaults()
                            args = bound.args[1:]
                        return coop.request(pid, name, args)

                    return send
            return super().__getattribute__(name)

        def __setattr__(self, name, value):
            if name == "open_screen" and "coop" in vars(self):
                coop = object.__getattribute__(self, "coop")
                if not getattr(coop, "_applying", False):
                    coop.request(self.player_id, "screen", [value])
            super().__setattr__(name, value)

    context.session.__class__ = RemoteSession
    from .quests import CoopGameState

    class RemoteGameState(CoopGameState):
        def __getattribute__(self, name):
            if name in (
                "use_item",
                "equip",
                "unequip",
                "select_next_spell",
                "roll_for_quest",
            ):
                session = context.session
                if not getattr(session.coop, "_applying", False):
                    return lambda *args: session.coop.request(
                        session.player_id, "rpg_action", [name, list(args)]
                    )
            return super().__getattribute__(name)

    context.session.game.__class__ = RemoteGameState
