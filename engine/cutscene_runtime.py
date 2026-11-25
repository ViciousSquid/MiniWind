"""Cutscene playback state machine.

The LogicThread owns the simulation loop; this module owns cinematic playback state,
track sampling, temporary actor lifetime, timed I/O and restoration.
"""

import json
import math
import os
import queue

import numpy as np

from .spatial import clear_live_flag, set_live_flag

try:
    from editor.things import ENTITY_TYPES, Monster as MonsterThing
except ImportError:
    ENTITY_TYPES = {}
    MonsterThing = None

try:
    from editor.debug_console import debug_log
except ImportError:
    def debug_log(category, message):
        print(f"[{category}] {message}")


#: Spoken and thought lines a cutscene can give an actor (``say`` /
#: ``think`` events), and how long one stays up when no duration is authored.
LINE_KINDS = ("say", "think")
LINE_SECONDS = 3.0
#: How often (cutscene seconds) a fighter in a cutscene battle looks again for
#: the nearest living foe, and the cutscene's rules are weighed.
FIGHT_RETARGET_SECONDS = 0.25
#: What a cutscene rule can watch for (``if``) and do about it (``then``).
RULE_CONDITIONS = ("health_below", "dies", "allies_below", "foes_below")
RULE_ACTIONS = ("flee", "cast", "say", "think", "attack", "stand_down")


def _alive(thing):
    props = getattr(thing, "properties", None) or {}
    if props.get("dead"):
        return False
    try:
        return float(props.get("health", 1) or 0) > 0
    except (TypeError, ValueError):
        return True


class CutsceneRuntime:
    """Owns the cutscene state machine while LogicThread remains the orchestrator."""

    def __init__(self, logic):
        self.logic = logic
        self.state = None
        self._message_queue = queue.SimpleQueue()
        #: LogicCamera ids whose "play once" cutscene has played. A game may
        #: fill it from its save (MiniWind does), so a story scene played
        #: before a level change or a load never plays again.
        self.played = set()
        #: A top-down game (MiniWind) sets this: every cutscene camera looks
        #: straight down, screen-up as in play, and a look-at keeps the camera
        #: over its actor instead of turning to face it.
        self.top_down = False
        self._started_this_session = set()
        self._inside = set()
        self._cameras = (None, ())

    # ------------------------------------------------------------------
    # Triggers: what the cutscene editor's Trigger settings ask for.
    # ------------------------------------------------------------------
    def reset_triggers(self):
        """Play is starting: forget what has played (a game puts back what
        its save remembers) and who stood where."""
        self.played.clear()
        self._started_this_session.clear()
        self._inside.clear()
        self._cameras = (None, ())

    def _trigger_cameras(self):
        """Every LogicCamera with a cutscene and a trigger of its own
        (``play_start`` or ``proximity``), cached per scene."""
        state = self.logic.editor_state
        things = state.things
        key = (id(things), len(things), getattr(state, "world_epoch", 0))
        if self._cameras[0] != key:
            cams = tuple(
                t for t in things
                if t.properties.get("type") == "logic_camera"
                and str(t.properties.get("cutscene_file", "") or "").strip()
                and t.properties.get("cutscene_trigger_mode") in ("play_start", "proximity"))
            self._cameras = (key, cams)
        return self._cameras[1]

    def check_triggers(self):
        """Start a cutscene whose trigger has come: Play began, or the player
        walked into its radius (the LogicCamera's place, across the ground).
        A "play once" cutscene plays once; one cutscene at a time."""
        if self.state is not None:
            return
        cams = self._trigger_cameras()
        if not cams:
            return
        player = self.logic.player_runtime.player
        for cam in cams:
            props = cam.properties
            cid = str(props.get("id") or id(cam))
            once = bool(props.get("cutscene_once", True))
            if once and cid in self.played:
                continue
            mode = props.get("cutscene_trigger_mode")
            if mode == "play_start":
                due = cid not in self._started_this_session
            else:
                if player is None:
                    continue
                radius = max(0.0, self._cutscene_number(props.get("cutscene_trigger_radius", 180.0), 180.0))
                dx = float(player.pos[0]) - float(cam.pos[0])
                dz = float(player.pos[2]) - float(cam.pos[2])
                inside = dx * dx + dz * dz <= radius * radius
                due = inside and cid not in self._inside
                if inside:
                    self._inside.add(cid)
                else:
                    self._inside.discard(cid)
            if due and self._start_camera(cam):
                self._started_this_session.add(cid)
                if once:
                    self.played.add(cid)
                self.logic._plugin_emit("cutscene.played", camera=cam, id=cid,
                                        cutscene_file=props.get("cutscene_file"))
                return

    def _start_camera(self, cam):
        """Start *cam* the way its Start input does. True when it is playing."""
        io = self.logic.io_manager
        execute = getattr(io, "_execute_input", None) if io is not None else None
        if execute is None:
            return False
        name = str(cam.properties.get("name", "") or cam.properties.get("id", ""))
        execute(name, "Start", None, "Cutscene", target_id=str(cam.properties.get("id", "") or ""))
        return self.state is not None

    def skip(self):
        """Escape: end the playing cutscene now, if it lets itself be stopped,
        as though it had played out (its OnFinished still fires, so what the
        story does next still happens). True when it stopped."""
        cs = self.state
        if not cs or not cs.get("active"):
            return False
        entity = cs.get("entity")
        allowed = True
        if cs.get("json_cutscene"):
            allowed = bool(cs.get("stop_on_escape", True))
        elif entity is not None:
            allowed = bool(entity.properties.get("cutscene_stop_on_escape", True))
        if not allowed:
            return False
        if cs.get("json_cutscene"):
            self._finish_json_cutscene(cs)
        else:
            self.state = None
            if entity is not None and self.logic.io_manager:
                self.logic.io_manager.fire_output(entity, "OnFinished")
        return True

    def _cutscene_file_path(self, filename):
        """Resolve an authored cutscene path in the project, without allowing
        it outside cutscenes/ (a played package's are :meth:`_package_cutscene`).
        """
        raw = str(filename or "").strip().replace("\\", "/")
        if not raw:
            return None
        roots = [getattr(self.logic, "root_dir",
                         os.path.dirname(os.path.dirname(__file__)))]
        for project_root in roots:
            if not project_root:
                continue
            project_root = os.path.realpath(project_root)
            root = os.path.realpath(os.path.join(project_root, "cutscenes"))
            candidate = os.path.realpath(os.path.join(project_root, raw))
            try:
                inside = os.path.commonpath((root, candidate)) == root
            except ValueError:
                inside = False
            if inside and os.path.isfile(candidate):
                return candidate
        return None

    def _package_cutscene(self, filename):
        """The member of the played package (``logic.package``, read in place)
        that *filename* names inside its ``cutscenes/``, or None. A package's
        cutscenes come before the project's."""
        package = getattr(self.logic, "package", None)
        if package is None:
            return None
        member = package.member(filename)
        if member is None or not member.startswith("cutscenes/"):
            return None
        return member

    def _load_cutscene_file(self, filename):
        member = self._package_cutscene(filename)
        path = None if member is not None else self._cutscene_file_path(filename)
        if member is None and path is None:
            debug_log("Cutscene", f"FAILED: '{filename}' not found or outside cutscenes/")
            return None
        try:
            if member is not None:
                data = self.logic.package.load_json(member)
            else:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            debug_log("Cutscene", f"FAILED: '{filename}' could not be loaded: {exc}")
            return None
        if not isinstance(data, dict) or not isinstance(data.get("camera"), list):
            debug_log("Cutscene", f"FAILED: '{filename}' is invalid (camera keyframes missing)")
            return None
        debug_log("Cutscene", f"LOADED: '{filename}'")
        return data

    @staticmethod
    def _cutscene_number(value, default=0.0):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return float(default)
        if not math.isfinite(value):
            return float(default)
        return value

    @staticmethod
    def _cutscene_vec3(value, default=None):
        if default is None:
            default = [0.0, 0.0, 0.0]
        try:
            if len(value) != 3:
                raise ValueError
            result = [float(value[0]), float(value[1]), float(value[2])]
            if not all(math.isfinite(v) for v in result):
                raise ValueError
            return result
        except (TypeError, ValueError, IndexError):
            return list(default)

    @staticmethod
    def _cutscene_yaw(entity):
        """*entity*'s facing in radians: an actor's ``angle`` property
        (degrees, engine.monster_facing), else an ``angle`` attribute."""
        props = getattr(entity, "properties", {}) or {}
        if "angle" in props:
            try:
                return math.radians(float(props.get("angle") or 0.0))
            except (TypeError, ValueError):
                return 0.0
        return float(getattr(entity, "angle", props.get("yaw", 0.0)))

    @staticmethod
    def _set_cutscene_yaw(entity, yaw):
        """Face *entity* along *yaw* (radians), through the engine's own
        facing (so its billboard turns)."""
        yaw = float(yaw)
        props = getattr(entity, "properties", {}) or {}
        if "angle" in props:
            from .monster_facing import set_heading
            set_heading(entity, yaw)
        elif hasattr(entity, "angle"):
            entity.angle = yaw
        else:
            props["yaw"] = yaw

    @staticmethod
    def _cutscene_lerp_angle(a, b, t):
        delta = ((float(b) - float(a) + math.pi) % (2.0 * math.pi)) - math.pi
        return float(a) + delta * t

    @staticmethod
    def _cutscene_sample(rows, elapsed, initial_pos=None, initial_yaw=0.0):
        """Sample one actor/camera track with linear interpolation."""
        # Only the two bracketing frames matter. Read their times once, without
        # sorting/copying the complete track on every camera and actor tick.
        # A stable sort chose the *last* equal-time left frame and the *first*
        # equal-time right frame; retain those choices, including at endpoints.
        # Keep reading the live rows each call: runtime track edits take effect
        # immediately and cannot leave a persistent ordering cache stale.
        left = right = None
        left_time = right_time = 0.0
        number = CutsceneRuntime._cutscene_number
        for row in rows:
            if not isinstance(row, dict):
                continue
            when = number(row.get("time", 0.0))
            if elapsed <= when:
                if right is None or when < right_time:
                    right, right_time = row, when
            elif left is None or when >= left_time:
                left, left_time = row, when
        if right is None:
            # Also the original result for a NaN elapsed time: every ordered
            # comparison fails, so sampling falls through to the last frame.
            return left
        if left is None:
            if elapsed < right_time and initial_pos is not None:
                return {"pos": list(initial_pos), "yaw": float(initial_yaw), "_before": True}
            return right
        span = right_time - left_time
        t = 1.0 if span <= 1e-9 else max(0.0, min(1.0, (elapsed - left_time) / span))
        lp = CutsceneRuntime._cutscene_vec3(left.get("pos", [0, 0, 0]))
        rp = CutsceneRuntime._cutscene_vec3(right.get("pos", lp), lp)

        # A teleport belongs to the destination keyframe.  Keep the
        # previous shot completely unchanged until its timestamp, then
        # cut to the new location.  This makes large cross-map jumps
        # explicit rather than turning them into a very fast move.
        if right.get("teleport", False):
            if elapsed < right_time:
                return {
                    "pos": list(lp),
                    "yaw": CutsceneRuntime._cutscene_number(left.get("yaw", 0.0)),
                    "pitch": CutsceneRuntime._cutscene_number(left.get("pitch", 0.0)),
                    "fov": CutsceneRuntime._cutscene_number(left.get("fov", 90.0), 90.0),
                    "look_at": left.get("look_at"),
                }
            return {
                "pos": list(rp),
                "yaw": CutsceneRuntime._cutscene_number(right.get("yaw", 0.0)),
                "pitch": CutsceneRuntime._cutscene_number(right.get("pitch", 0.0)),
                "fov": CutsceneRuntime._cutscene_number(right.get("fov", 90.0), 90.0),
                "look_at": right.get("look_at"),
            }

        return {
            "pos": [lp[i] + (rp[i] - lp[i]) * t for i in range(3)],
            "yaw": CutsceneRuntime._cutscene_lerp_angle(
                CutsceneRuntime._cutscene_number(left.get("yaw", 0.0)),
                CutsceneRuntime._cutscene_number(right.get("yaw", 0.0)),
                t,
            ),
            "pitch": (
                CutsceneRuntime._cutscene_number(left.get("pitch", 0.0))
                + (CutsceneRuntime._cutscene_number(right.get("pitch", 0.0))
                   - CutsceneRuntime._cutscene_number(left.get("pitch", 0.0))) * t
            ),
            "fov": (
                CutsceneRuntime._cutscene_number(left.get("fov", 90.0), 90.0)
                + (CutsceneRuntime._cutscene_number(right.get("fov", 90.0), 90.0)
                   - CutsceneRuntime._cutscene_number(left.get("fov", 90.0), 90.0)) * t
            ),
            "look_at": left.get("look_at"),
        }

    #: How close two spawned actors may stand.
    SPAWN_SPACING = 48.0

    def _clear_spawn(self, pos, spawned):
        """*pos*, pushed clear of the actors this cutscene has spawned so far:
        two never appear on top of each other."""
        gap = self.SPAWN_SPACING
        others = [(float(a.pos[0]), float(a.pos[2])) for a in spawned]

        def free(x, z):
            return all((x - ox) ** 2 + (z - oz) ** 2 >= gap * gap for ox, oz in others)
        x, y, z = pos
        if free(x, z):
            return pos
        for ring in range(1, 30):
            steps = 6 * ring
            for k in range(steps):
                a = 2.0 * math.pi * k / steps
                cx, cz = x + math.cos(a) * gap * ring, z + math.sin(a) * gap * ring
                if free(cx, cz):
                    return [cx, y, cz]
        return pos

    def _start_json_cutscene(self, entity, filename, data):
        previous = self.state
        if previous is not None:
            if previous.get("json_cutscene"):
                self._finish_json_cutscene(previous, fire_finished=False)
            else:
                self.state = None
        actors = {}
        actor_initial = {}
        spawned = []
        for row in data.get("actors") or []:
            if not isinstance(row, dict):
                continue
            aid = str(row.get("id", "") or "")
            if not aid:
                continue
            actor = self.logic.world_runtime.find_entity_by_id(aid)
            definition = row.get("definition") if row.get("spawn") else None
            if actor is None and isinstance(definition, dict):
                type_name = str(definition.get("type") or "monster")
                cls = ENTITY_TYPES.get(type_name)
                if cls is None:
                    cls = next((value for key, value in ENTITY_TYPES.items()
                                if str(key).lower() == type_name.lower()), None)
                if cls is None:
                    debug_log("IO", f"LogicCamera: cannot spawn unknown cutscene actor type '{type_name}'")
                    continue
                props = dict(definition.get("properties") or {})
                props["id"] = aid
                props["_cutscene_runtime"] = True
                try:
                    actor = cls(
                        pos=self._clear_spawn(self._cutscene_vec3(definition.get("pos")), spawned),
                        properties=props,
                    )
                    # Authored in degrees, as an actor's angle is.
                    self._set_cutscene_yaw(actor, math.radians(
                        self._cutscene_number(definition.get("yaw", 0.0))))
                    self.logic.editor_state.things.append(actor)
                    spawned.append(actor)
                except Exception as exc:
                    debug_log("IO", f"LogicCamera: failed to spawn cutscene actor '{aid}': {exc}")
                    continue
            if actor is None:
                debug_log("IO", f"LogicCamera: actor '{aid}' is not present; its track will be ignored")
                continue
            actor_initial[aid] = {
                "entity": actor,
                "pos": self._cutscene_vec3(actor.pos),
                "yaw": self._cutscene_yaw(actor),
                "had_disabled": "disabled" in actor.properties,
                "disabled": actor.properties.get("disabled", False),
            }
            actor.properties["_cutscene_runtime"] = True
            set_live_flag(actor, "disabled", True)
            actors[aid] = actor

        if spawned:
            self.logic.world_runtime.build_entity_caches()
            # A game readies its new actors as it does a map's (MiniWind arms
            # an archer with a blade for close quarters, rolls handedness...).
            self.logic._plugin_emit("cutscene.spawned", actors=list(spawned))
        # The scene starts clean: a game drops whatever chatter was up.
        self.logic._plugin_emit("cutscene.started", actors=list(actors.values()))

        # The editor Camera stores yaw/pitch in degrees, while the play-mode
        # camera math below uses radians.  Keep the authored JSON human-readable
        # in degrees and convert the camera track once at runtime.  Converting
        # here (rather than every tick) also keeps interpolation in one unit.
        camera_rows = []
        for source_row in data.get("camera") or []:
            if not isinstance(source_row, dict):
                continue
            row = dict(source_row)
            row["yaw"] = math.radians(
                self._cutscene_number(row.get("yaw", 0.0))
            )
            row["pitch"] = math.radians(
                self._cutscene_number(row.get("pitch", 0.0))
            )
            camera_rows.append(row)
        camera_rows.sort(key=lambda row: self._cutscene_number(row.get("time", 0.0)))
        # An actor track's facing is authored in degrees (an actor's angle);
        # sampled in radians, the short way round, like the camera's.
        actor_tracks = {
            str(aid): sorted(
                [dict(row, yaw=math.radians(self._cutscene_number(row.get("yaw", 0.0))))
                 for row in rows or [] if isinstance(row, dict)],
                key=lambda row: self._cutscene_number(row.get("time", 0.0)),
            )
            for aid, rows in (data.get("actor_tracks") or {}).items()
            if isinstance(rows, list)
        }
        events = [event for event in (data.get("events") or []) if isinstance(event, dict)]
        # Preserve the two cutscene I/O schemas:
        #
        #   New editor authoring: target_id/target_name + input
        #   Legacy cutscenes:     source_id/source_name + output
        #
        # They are not interchangeable.  The former executes an input directly
        # on the target; the latter fires an output from the source and therefore
        # traverses the map's authored I/O connections.
        events.sort(key=lambda event: self._cutscene_number(event.get("time", 0.0)))
        duration = 0.0
        for row in camera_rows:
            duration = max(duration, self._cutscene_number(row.get("time", 0.0)))
        for rows in actor_tracks.values():
            for row in rows:
                duration = max(duration, self._cutscene_number(row.get("time", 0.0)))
        for event in events:
            duration = max(duration, self._cutscene_number(event.get("time", 0.0)))
            if event.get("type") in LINE_KINDS:
                duration = max(
                    duration,
                    self._cutscene_number(event.get("time", 0.0))
                    + self._line_seconds(event),
                )
            if event.get("type") == "fight":
                duration = max(
                    duration,
                    self._cutscene_number(event.get("time", 0.0))
                    + max(0.0, self._cutscene_number(event.get("duration", 0.0))),
                )

        # A single keyframe at t=0 is still a real cutscene state.  Keep it
        # alive for one logical tick so LookAt/message/I/O authoring can observe
        # that state before the runtime finishes an otherwise zero-duration shot.
        if camera_rows and duration <= 0.0:
            duration = 1e-6

        settings = data.get("settings") or {}
        self.state = {
            "active": True,
            "top_down": bool(self.top_down or settings.get("camera") == "top_down"),
            "paused": False,
            "entity": entity,
            "json_cutscene": True,
            "cutscene_file": str(filename),
            "camera_keys": camera_rows,
            "actor_tracks": actor_tracks,
            "actors": actors,
            "actor_initial": actor_initial,
            "spawned_actors": spawned,
            "restore_actors": bool(
                settings.get("restore_actors",
                             entity.properties.get("cutscene_restore_actors", True))
            ),
            "stop_on_escape": bool(
                settings.get("stop_on_escape",
                             entity.properties.get("cutscene_stop_on_escape", True))
            ),
            "elapsed": 0.0,
            "duration": duration,
            "io_events": [event for event in events if event.get("type") == "io"],
            "next_io_event": 0,
            "message_events": [event for event in events if event.get("type") == "message"],
            "next_message_event": 0,
            "fight_events": [
                event for event in events
                if event.get("type") == "fight"
            ],
            "active_fights": {},
            "line_events": [event for event in events if event.get("type") in LINE_KINDS],
            "next_line_event": 0,
            "cast_events": [event for event in events if event.get("type") == "cast"],
            "next_cast_event": 0,
            "rules": [dict(event) for event in events if event.get("type") == "rule"],
            # Actors given over to the game's own orders (fleeing): neither a
            # battle nor their MOVE track has them.
            "detached": {},
            # Actors a battle let go of: their MOVE track carries on from where
            # the fight left them (a key at the moment it ended).
            "fight_retarget_at": 0.0,
        }
        if camera_rows:
            first = camera_rows[0]
            self.state["cam_pos"] = self._cutscene_vec3(first.get("pos"))
            self.state["cam_angle"] = self._cutscene_number(first.get("yaw", 0.0))
            self.state["cam_pitch"] = self._cutscene_number(first.get("pitch", 0.0))
            self.state["fov"] = max(
                1.0,
                min(179.0, self._cutscene_number(first.get("fov", 90.0), 90.0)),
            )

        return True

    def _restore_json_fights(self, cs):
        for fight in (cs.get("active_fights") or {}).values():
            for actor, snapshot, _foes in fight["fighters"]:
                if actor in self.logic.editor_state.things:
                    self._release_fighter(actor, snapshot)
        cs["active_fights"] = {}

    @staticmethod
    def _release_fighter(actor, snapshot):
        """Give a fighter back the flags it had before its battle. The dead
        stay dead: a battle's deaths are the world's."""
        props = actor.properties
        if snapshot.get("had_disabled"):
            set_live_flag(actor, "disabled", snapshot["disabled"])
        else:
            clear_live_flag(actor, "disabled")
        for key, had in (("awake", "had_awake"), ("_aggro_target", "had_aggro"),
                         ("target_name", "had_target_name"),
                         ("triggered", "had_triggered")):
            field = {"_aggro_target": "aggro"}.get(key, key)
            if snapshot.get(had):
                props[key] = snapshot[field]
            else:
                props.pop(key, None)

    def _fight_actor(self, cs, aid):
        return ((cs.get("actors") or {}).get(str(aid))
                or self.logic.world_runtime.find_entity_by_id(str(aid)))

    def fighting_ids(self, cs=None):
        """``id()`` of every actor a cutscene battle has hold of now."""
        cs = cs if cs is not None else self.state
        out = set()
        for fight in ((cs or {}).get("active_fights") or {}).values():
            out.update(id(actor) for actor, _snap, _foes in fight["fighters"])
        return out

    def simulating(self):
        """Whether the world's combat must run through the cutscene now: a
        battle is on, or what one loosed (an arrow, a spell) is still flying."""
        cs = self.state
        if not cs or not cs.get("active") or cs.get("paused"):
            return False
        if cs.get("active_fights") or cs.get("detached"):
            return True
        if not cs.get("fought"):
            return False
        store = getattr(getattr(self.logic, "combat_runtime", None),
                        "_monster_projectiles", None)
        return bool(store is not None and len(store))

    @staticmethod
    def _nearest_living(actor, foes):
        best, best_d = None, None
        ax, az = float(actor.pos[0]), float(actor.pos[2])
        for foe in foes:
            if foe is actor or not _alive(foe):
                continue
            d = (float(foe.pos[0]) - ax) ** 2 + (float(foe.pos[2]) - az) ** 2
            if best is None or d < best_d:
                best, best_d = foe, d
        return best

    def _aim_fighters(self, fight):
        """Each living fighter at the nearest living foe; a fighter whose
        foe has fallen turns to the next. With no foe left it stands down."""
        for actor, _snap, foes in fight["fighters"]:
            if not _alive(actor):
                continue
            props = actor.properties
            current = props.get("_aggro_target")
            if any(id(foe) == current and _alive(foe) for foe in foes):
                continue
            target = self._nearest_living(actor, foes)
            props["_aggro_target"] = id(target) if target is not None else None

    def _begin_fight(self, cs, index, attackers, defenders, mutual=True):
        """Hand *attackers* (and, *mutual*, *defenders*) to the game's combat
        AI, each at its nearest living foe."""
        sides = [(a, defenders) for a in attackers]
        if mutual:
            sides += [(d, attackers) for d in defenders]
        fighters, seen = [], {}
        for actor, foes in sides:
            if MonsterThing is None or not isinstance(actor, MonsterThing):
                continue          # only actors with combat AI fight
            if id(actor) in seen:
                # On both sides: everyone else is its foe.
                entry = fighters[seen[id(actor)]]
                merged = [f for f in entry[2] + foes if f is not actor]
                fighters[seen[id(actor)]] = (entry[0], entry[1], merged)
                continue
            props = actor.properties
            snapshot = {
                "had_disabled": "disabled" in props,
                "disabled": props.get("disabled", False),
                "had_awake": "awake" in props,
                "awake": props.get("awake", False),
                "had_aggro": "_aggro_target" in props,
                "aggro": props.get("_aggro_target"),
                "had_target_name": "target_name" in props,
                "target_name": props.get("target_name"),
                # A parked actor (a scripted ambush, a peaceful townsman)
                # fights in full -- bow drawn, spells cast -- for the battle,
                # and is parked again after.
                "had_triggered": "triggered" in props,
                "triggered": props.get("triggered", False),
            }
            seen[id(actor)] = len(fighters)
            fighters.append((actor, snapshot, [f for f in foes if f is not actor]))
            set_live_flag(actor, "disabled", False)
            props["awake"] = True
            props["triggered"] = False
            props.pop("target_name", None)
            props.pop("_aggro_target", None)
            (cs.get("detached") or {}).pop(id(actor), None)
        fight = {"fighters": fighters}
        self._aim_fighters(fight)
        cs.setdefault("active_fights", {})[index] = fight
        cs["fought"] = True
        self.logic._plugin_emit("cutscene.fight", started=True, index=index,
                                fighters=[f[0] for f in fighters])

    def _end_fight(self, cs, index, active, elapsed):
        """The battle is over: its fighters' flags back; a survivor's MOVE
        track carries on from where the battle left it."""
        actors_of = cs.get("actors") or {}
        for actor, snapshot, _foes in active["fighters"]:
            self._release_fighter(actor, snapshot)
            aid = next((key for key, value in actors_of.items() if value is actor), None)
            if aid is not None and _alive(actor) and aid in (cs.get("actor_tracks") or {}):
                cs["actor_tracks"][aid].append({
                    "time": float(elapsed),
                    "pos": self._cutscene_vec3(actor.pos),
                    "yaw": self._cutscene_yaw(actor),
                })
        cs["active_fights"].pop(index, None)
        cs.setdefault("fights_done", set()).add(index)
        self.logic._plugin_emit("cutscene.fight", started=False, index=index,
                                fighters=[f[0] for f in active["fighters"]])

    def _update_json_fights(self, cs, elapsed):
        """Battles: hand every fighter to the game's own combat AI against the
        other side -- each at its nearest living foe -- for the event's
        duration. ``mutual`` (the default) has the defenders fight back."""
        actors_of = cs.get("actors") or {}
        for index, event in enumerate(cs.get("fight_events") or []):
            start = self._cutscene_number(event.get("time", 0.0))
            duration = max(0.0, self._cutscene_number(event.get("duration", 0.0)))
            end = start + duration
            active = cs.setdefault("active_fights", {}).get(index)

            if start <= elapsed < end and active is None and index not in cs.setdefault("fights_done", set()):
                if "_actors" in event:
                    attackers, defenders = event["_actors"]
                else:
                    attackers = [self._fight_actor(cs, aid) for aid in event.get("attackers", []) or []]
                    defenders = [self._fight_actor(cs, aid) for aid in event.get("defenders", []) or []]
                attackers = [a for a in attackers if a is not None]
                defenders = [d for d in defenders if d is not None]
                if not attackers or not defenders:
                    cs["fights_done"].add(index)
                    continue
                self._begin_fight(cs, index, attackers, defenders, event.get("mutual", True))

            elif active is not None and elapsed >= end:
                self._end_fight(cs, index, active, elapsed)

        if ((cs.get("active_fights") or cs.get("rules"))
                and elapsed >= float(cs.get("fight_retarget_at", 0.0))):
            cs["fight_retarget_at"] = elapsed + FIGHT_RETARGET_SECONDS
            self._weigh_rules(cs, elapsed)
            for fight in cs.get("active_fights", {}).values():
                self._aim_fighters(fight)

    # ------------------------------------------------------------------
    # Rules: "if this actor's health falls below 40%, flee" -- weighed four
    # times a second, each firing once; the game's own AI does the deed.
    # ------------------------------------------------------------------
    @staticmethod
    def _health_pct(thing):
        props = thing.properties
        try:
            health = float(props.get("health", 0) or 0)
            top = float(props.get("max_health") or props.get("_max_health") or health or 1)
        except (TypeError, ValueError):
            return 100.0
        return 100.0 * health / max(1e-6, top)

    def _sides(self, cs, actor):
        """``(allies, foes)`` of *actor* in the battles it is in (itself
        among its allies)."""
        allies, foes = {id(actor): actor}, {}
        for fight in (cs.get("active_fights") or {}).values():
            rows = {id(a): f for a, _s, f in fight["fighters"]}
            if id(actor) not in rows:
                continue
            mine = rows[id(actor)]
            for other, _snap, their_foes in fight["fighters"]:
                if other is actor:
                    continue
                if any(f is actor for f in their_foes):
                    foes[id(other)] = other
                elif not any(f is other for f in mine):
                    allies[id(other)] = other
            for f in mine:
                foes[id(f)] = f
        return list(allies.values()), list(foes.values())

    def _rule_holds(self, cs, rule, actor):
        cond = str(rule.get("if", ""))
        value = self._cutscene_number(rule.get("value", 0.0))
        other = self._fight_actor(cs, rule["of"]) if rule.get("of") else actor
        if other is None:
            return False
        if cond == "health_below":
            return _alive(other) and self._health_pct(other) < value
        if cond == "dies":
            return not _alive(other)
        if cond in ("allies_below", "foes_below"):
            allies, foes = self._sides(cs, actor)
            group = allies if cond == "allies_below" else foes
            return sum(1 for a in group if _alive(a)) < value
        return False

    def _weigh_rules(self, cs, elapsed):
        for rule in cs.get("rules") or []:
            if rule.get("_fired") or elapsed + 1e-9 < self._cutscene_number(rule.get("time", 0.0)):
                continue
            actor = self._fight_actor(cs, rule.get("actor", ""))
            if actor is None or not _alive(actor):
                continue
            if self._rule_holds(cs, rule, actor):
                rule["_fired"] = True
                self._order(cs, actor, rule, elapsed)
                if self.state is not cs:
                    return

    def _order(self, cs, actor, rule, elapsed):
        """Carry out a rule's ``then`` for *actor*."""
        action = str(rule.get("then", ""))
        if action in LINE_KINDS:
            text = str(rule.get("text", "") or "").strip()
            if text:
                self.logic._plugin_emit("cutscene.line", kind=action, actor=actor, text=text,
                                        seconds=self._line_seconds(rule))
        elif action == "stand_down":
            self._leave_fights(cs, actor)
        elif action == "attack":
            targets = [self._fight_actor(cs, t) for t in (rule.get("targets") or [rule.get("target")])
                       if t]
            targets = [t for t in targets if t is not None and t is not actor]
            if targets:
                self.start_fight(cs, [actor], targets, mutual=bool(rule.get("mutual", True)),
                                 until=float(cs.get("duration", elapsed)))
        elif action == "flee":
            # From its nearest living foe -- found before it leaves the fight.
            foes = [f for f in self._sides(cs, actor)[1] if _alive(f)]
            threat = self._nearest_living(actor, foes) if foes else None
            self._leave_fights(cs, actor)
            cs.setdefault("detached", {})[id(actor)] = actor
            self.logic._plugin_emit("cutscene.order", order="flee", actor=actor, threat=threat)
        elif action == "cast":
            self._cast(cs, actor, str(rule.get("spell", "")),
                       self._fight_actor(cs, rule["target"]) if rule.get("target") else None)

    def _leave_fights(self, cs, actor):
        """*actor* out of every battle, its flags given back."""
        for fight in (cs.get("active_fights") or {}).values():
            kept = []
            for row in fight["fighters"]:
                if row[0] is actor:
                    self._release_fighter(actor, row[1])
                else:
                    kept.append(row)
            fight["fighters"] = kept
            for _a, _s, foes in fight["fighters"]:
                foes[:] = [f for f in foes if f is not actor]

    def start_fight(self, cs, attackers, defenders, mutual=True, until=None):
        """A battle begun mid-cutscene (by a rule), as an ATTACK keyframe's."""
        index = f"rule-{len(cs.get('fight_events') or [])}-{len(cs.get('active_fights') or {})}"
        event = {"time": cs["elapsed"], "duration": max(0.0, float(until or cs["duration"]) - cs["elapsed"]),
                 "attackers": [], "defenders": [], "mutual": mutual,
                 "_actors": (list(attackers), list(defenders))}
        cs.setdefault("fight_events", []).append(event)
        self._begin_fight(cs, len(cs["fight_events"]) - 1, list(attackers), list(defenders), mutual)
        return index

    def join_side(self, newcomer, ally):
        """*newcomer* (raised or summoned by *ally*) fights on *ally*'s side
        in every battle *ally* is in -- turning on its old side when it was
        already in the fight (a guard who fell to the bandits rises as the
        necromancer's)."""
        cs = self.state
        if not cs:
            return False
        joined = False
        for fight in (cs.get("active_fights") or {}).values():
            fighters = fight["fighters"]
            row = next((r for r in fighters if r[0] is ally), None)
            if row is None or newcomer is ally:
                continue
            foes = [f for f in row[2] if f is not newcomer]
            index = next((i for i, r in enumerate(fighters) if r[0] is newcomer), None)
            props = newcomer.properties
            if index is None:
                snapshot = {"had_disabled": "disabled" in props, "disabled": props.get("disabled", False),
                            "had_awake": "awake" in props, "awake": props.get("awake", False),
                            "had_aggro": False, "aggro": None, "had_target_name": False,
                            "target_name": None, "had_triggered": "triggered" in props,
                            "triggered": props.get("triggered", False)}
                fighters.append((newcomer, snapshot, foes))
            else:
                fighters[index] = (newcomer, fighters[index][1], foes)
            set_live_flag(newcomer, "disabled", False)
            props["awake"] = True
            props["triggered"] = False
            props.pop("_aggro_target", None)
            # Its new side no longer fights it; whoever fights its master
            # fights it too.
            for other, _s, their in fighters:
                if other is newcomer:
                    continue
                against_ally = any(f is ally for f in their)
                their[:] = [f for f in their if f is not newcomer]
                if against_ally:
                    their.append(newcomer)
            joined = True
            self._aim_fighters(fight)
        return joined

    def _cast(self, cs, actor, spell, target):
        if spell:
            self.logic._plugin_emit("cutscene.cast", actor=actor, spell=spell, target=target)

    def _fire_cast_events(self, cs, elapsed):
        events = cs.get("cast_events") or []
        index = int(cs.get("next_cast_event", 0))
        while index < len(events) and self._cutscene_number(events[index].get("time", 0.0)) <= elapsed + 1e-9:
            event = events[index]
            index += 1
            cs["next_cast_event"] = index
            actor = self._fight_actor(cs, event.get("actor", ""))
            if actor is None or not _alive(actor):
                continue
            target = self._fight_actor(cs, event["target"]) if event.get("target") else None
            self._cast(cs, actor, str(event.get("spell", "")), target)

    def release(self, actor):
        """The game is done with *actor*'s orders (it stopped fleeing)."""
        cs = self.state
        if cs:
            (cs.get("detached") or {}).pop(id(actor), None)

    @classmethod
    def _line_seconds(cls, event):
        return max(0.1, cls._cutscene_number(event.get("duration", LINE_SECONDS), LINE_SECONDS))

    def _fire_line_events(self, cs, elapsed):
        """SAY and THINK: the game shows the line over the actor's head."""
        events = cs.get("line_events") or []
        index = int(cs.get("next_line_event", 0))
        while index < len(events) and self._cutscene_number(events[index].get("time", 0.0)) <= elapsed + 1e-9:
            event = events[index]
            index += 1
            cs["next_line_event"] = index
            text = str(event.get("text", "") or "").strip()
            aid = str(event.get("actor", "") or "")
            actor = self._fight_actor(cs, aid) if aid else None
            if not text or actor is None:
                continue
            if not _alive(actor):
                continue                  # the dead say nothing
            self.logic._plugin_emit("cutscene.line", kind=str(event.get("type")),
                                    actor=actor, text=text,
                                    seconds=self._line_seconds(event))

    def _finish_json_cutscene(self, cs, fire_finished=True):
        self._restore_json_fights(cs)
        for aid, snapshot in (cs.get("actor_initial") or {}).items():
            actor = snapshot.get("entity")
            if actor is None or actor not in self.logic.editor_state.things:
                continue
            if cs.get("restore_actors", True) and _alive(actor):
                # The living go back; the dead lie where they fell.
                actor.pos = list(snapshot.get("pos", actor.pos))
                self._set_cutscene_yaw(
                    actor, snapshot.get("yaw", self._cutscene_yaw(actor))
                )
            if snapshot.get("had_disabled"):
                set_live_flag(actor, "disabled", snapshot["disabled"])
            else:
                clear_live_flag(actor, "disabled")
            actor.properties.pop("_cutscene_runtime", None)
        spawned = list(cs.get("spawned_actors") or [])
        for actor in spawned:
            try:
                self.logic.editor_state.things.remove(actor)
            except ValueError:
                pass
        if spawned:
            self.logic.world_runtime.build_entity_caches()
        entity = cs.get("entity")
        self.state = None
        if fire_finished and entity is not None and self.logic.io_manager:
            self.logic.io_manager.fire_output(entity, "OnFinished")

    def _update_json_cutscene(self, delta):
        cs = self.state
        cs["elapsed"] = float(cs.get("elapsed", 0.0)) + max(0.0, float(delta))
        elapsed = cs["elapsed"]
        camera_keys = cs.get("camera_keys") or []
        if camera_keys:
            frame = self._cutscene_sample(camera_keys, elapsed)
            if frame:
                cs["cam_pos"] = self._cutscene_vec3(frame.get("pos"))
                cs["cam_angle"] = self._cutscene_number(frame.get("yaw", 0.0))
                cs["cam_pitch"] = self._cutscene_number(frame.get("pitch", 0.0))
                cs["fov"] = max(
                    1.0,
                    min(179.0, self._cutscene_number(frame.get("fov", 90.0), 90.0)),
                )
                look_at = frame.get("look_at")
                if isinstance(look_at, dict):
                    target_id = str(look_at.get("actor", "") or "")
                    target = (cs.get("actors") or {}).get(target_id)
                    if target is None:
                        target = self.logic.world_runtime.find_entity_by_id(target_id)
                    if target is not None and cs.get("top_down"):
                        # Top down: over the actor, at the shot's height.
                        target_pos = self._cutscene_vec3(target.pos)
                        cs["cam_pos"] = [target_pos[0], cs["cam_pos"][1], target_pos[2]]
                    elif target is not None:
                        target_pos = self._cutscene_vec3(target.pos)
                        diff = np.asarray(target_pos, dtype=float) - np.asarray(cs["cam_pos"], dtype=float)
                        dist = np.linalg.norm(diff)
                        if dist > 0.01:
                            cs["cam_angle"] = math.atan2(diff[0], diff[2])
                            cs["cam_pitch"] = math.asin(np.clip(diff[1] / dist, -1.0, 1.0))

        self._update_json_fights(cs, elapsed)

        fighting = self.fighting_ids(cs)
        for aid, rows in (cs.get("actor_tracks") or {}).items():
            actor = (cs.get("actors") or {}).get(aid)
            if (actor is None or id(actor) in fighting or not _alive(actor)
                    or id(actor) in (cs.get("detached") or {})):
                continue                  # the battle, the game or death has it now
            snapshot = (cs.get("actor_initial") or {}).get(aid, {})
            frame = self._cutscene_sample(
                rows,
                elapsed,
                initial_pos=snapshot.get("pos"),
                initial_yaw=snapshot.get("yaw", 0.0),
            )
            if frame and not frame.get("_before"):
                actor.pos = self._cutscene_vec3(frame.get("pos"), actor.pos)
                self._set_cutscene_yaw(
                    actor, self._cutscene_number(frame.get("yaw", 0.0))
                )
                physics_world = self.logic.session_runtime.physics_world
                if physics_world is not None:
                    try:
                        physics_world.sync_entity_position(actor, wake=True)
                    except (AttributeError, TypeError, ValueError):
                        pass

        message_events = cs.get("message_events", [])
        message_index = int(cs.get("next_message_event", 0))
        while message_index < len(message_events) and float(message_events[message_index].get("time", 0.0)) <= elapsed + 1e-9:
            event = message_events[message_index]
            message_index += 1
            cs["next_message_event"] = message_index
            text = str(event.get("text", "") or "").strip()[:50]
            if text:
                line = str(event.get("line", "message") or "message").strip().lower()
                if line not in ("message", "message2", "message3"):
                    line = "message"
                self._message_queue.put((line, text))

        self._fire_line_events(cs, elapsed)
        self._fire_cast_events(cs, elapsed)

        if not self._fire_cinematic_io_events():
            return
        if elapsed >= float(cs.get("duration", 0.0)):
            self._finish_json_cutscene(cs)

    def consume_cinematic_messages(self):
        """Return queued cutscene HUD messages for the GUI thread."""
        messages = []
        while True:
            try:
                messages.append(self._message_queue.get_nowait())
            except queue.Empty:
                return messages

    def _fire_cinematic_io_events(self):
        """Fire timed cutscene I/O events, accepting both authored schemas."""
        cs = self.state
        if not cs or not cs.get('active') or not self.logic.io_manager:
            return bool(cs and cs.get('active'))

        events = cs.get('io_events', [])
        index = int(cs.get('next_io_event', 0))
        elapsed = float(cs.get('elapsed', 0.0))
        while index < len(events) and float(events[index].get('time', 0.0)) <= elapsed + 1e-9:
            event = events[index]
            index += 1
            cs['next_io_event'] = index

            # New editor format: address an entity input directly.
            target_id = str(event.get('target_id', '') or '')
            target_name = str(event.get('target_name', '') or '')
            input_name = str(event.get('input', '') or '').strip()
            if target_name or target_id or input_name:
                if not target_name and target_id:
                    target = self.logic.world_runtime.find_entity_by_id(target_id)
                    target_name = str(
                        getattr(target, 'properties', {}).get('name', '') or target_id
                    )
                if target_name and input_name:
                    execute_input = getattr(self.logic.io_manager, '_execute_input', None)
                    if execute_input is None:
                        debug_log(
                            "IO",
                            f"Cutscene I/O target '{target_name}' cannot execute input "
                            f"'{input_name}': IO manager has no input executor.",
                        )
                    else:
                        execute_input(
                            target_name,
                            input_name,
                            event.get('parameter'),
                            "Cutscene",
                            target_id=target_id,
                        )
                else:
                    debug_log(
                        "IO",
                        f"Cutscene I/O target '{target_name or target_id}' has no input to fire.",
                    )
            else:
                # Legacy format: fire a source output so the map's normal
                # connection graph resolves the downstream input.
                source_id = str(event.get('source_id', '') or '')
                source_name = str(event.get('source_name', '') or '')
                output_name = str(event.get('output', '') or '').strip()
                source = None
                if source_id:
                    source = self.logic.world_runtime.find_entity_by_id(source_id)
                if source is None and source_name:
                    source = self.logic.world_runtime.find_entity_by_name(source_name)
                if source is not None and output_name:
                    self.logic.io_manager.fire_output(
                        source,
                        output_name,
                        event.get('parameter'),
                    )
                else:
                    debug_log(
                        "IO",
                        f"Cutscene legacy I/O source '{source_name or source_id}' "
                        f"has no output to fire.",
                    )

            # An input/output may stop, replace or otherwise mutate the cinematic.
            if self.state is not cs:
                return False
        return True

    def _update_cinematic_camera(self, delta: float):
        cs = self.state
        if not cs or not cs.get('active') or cs.get('paused'):
            return

        if cs.get('json_cutscene'):
            self._update_json_cutscene(delta)
            return

        cs['elapsed'] = float(cs.get('elapsed', 0.0)) + max(0.0, float(delta))
        if not self._fire_cinematic_io_events():
            return
        node_name = cs['current_node']
        node = self.logic.world_runtime.find_path_node_by_name(node_name)
        if node is None:
            debug_log("IO", f"CinematicCamera: node '{node_name}' not found — aborting")
            entity = cs.get('entity')
            self.state = None
            if entity and self.logic.io_manager:
                self.logic.io_manager.fire_output(entity, 'OnFinished')
            return

        origin = np.array(cs['origin'], dtype=float)
        target = np.array(node.pos, dtype=float)
        segment_vec = target - origin
        segment_len = np.linalg.norm(segment_vec)

        if segment_len < 1.0:
            cs['lerp_t'] = 1.0
        else:
            cs['lerp_t'] += (cs['speed'] * delta) / segment_len

        t = min(cs['lerp_t'], 1.0)
        current_pos = origin + segment_vec * t

        cs['cam_pos'] = current_pos.tolist()

        # Normal path-facing target.  With "look ahead" enabled this is the
        # next node; otherwise it is the node currently being approached.
        if cs.get('look_ahead'):
            next_name = node.get_next_node_name()
            look_node = self.logic.world_runtime.find_path_node_by_name(next_name) if next_name else node
            path_look_target = np.array(
                look_node.pos if look_node else node.pos,
                dtype=float,
            )
        else:
            path_look_target = target

        look_target = path_look_target

        # An explicit LookAt temporarily overrides the path target.  The live
        # entity is retained so moving targets are tracked automatically.
        focus_target = cs.get('lookat_target')
        if focus_target is not None:
            if isinstance(focus_target, dict):
                focus_pos = focus_target.get('pos')
            else:
                focus_pos = getattr(focus_target, 'pos', None)
            try:
                if focus_pos is not None:
                    look_target = np.asarray(focus_pos, dtype=float)
                else:
                    cs['lookat_target'] = None
                    cs['lookat_return_remaining'] = None
            except (TypeError, ValueError):
                cs['lookat_target'] = None
                cs['lookat_return_remaining'] = None

        # Return from LookAt is timed in the camera's logic clock, so pausing
        # the cinematic camera also pauses the focus timer.
        if cs.get('lookat_target') is not None:
            remaining = cs.get('lookat_return_remaining')
            if remaining is not None:
                remaining -= max(0.0, float(delta))
                if remaining <= 0.0:
                    cs['lookat_target'] = None
                    cs['lookat_return_remaining'] = None
                    look_target = path_look_target
                else:
                    cs['lookat_return_remaining'] = remaining

        diff = look_target - current_pos
        dist = np.linalg.norm(diff)
        if dist > 0.01:
            desired_angle = math.atan2(diff[0], diff[2])
            desired_pitch = math.asin(np.clip(diff[1] / dist, -1.0, 1.0))

            if not cs.get('_look_initialized', False):
                cs['cam_angle'] = desired_angle
                cs['cam_pitch'] = desired_pitch
                cs['_look_initialized'] = True
            else:
                # Exponential smoothing is frame-rate independent and removes
                # the hard bearing jump at each PathNode boundary.
                alpha = 1.0 - math.exp(-8.0 * max(0.0, float(delta)))
                current_angle = cs.get('cam_angle', desired_angle)
                angle_delta = (
                    (desired_angle - current_angle + math.pi)
                    % (2.0 * math.pi)
                ) - math.pi
                cs['cam_angle'] = current_angle + angle_delta * alpha
                current_pitch = cs.get('cam_pitch', desired_pitch)
                cs['cam_pitch'] = (
                    current_pitch + (desired_pitch - current_pitch) * alpha
                )

        if cs['lerp_t'] >= 1.0:
            # PathNodes are real I/O sources for cinematic camera arrival.
            # Fire the node first so it can drive arbitrary I/O, including
            # stopping or replacing this camera.
            if self.logic.io_manager:
                self.logic.io_manager.fire_output(node, 'OnCameraArrived')
                self.logic.io_manager.fire_output(cs['entity'], 'OnReachNode')

            # Arrival outputs may mutate the cinematic state.
            if self.state is not cs:
                return

            next_name = node.get_next_node_name()
            if next_name:
                cs['origin'] = list(node.pos)
                cs['current_node'] = next_name
                cs['lerp_t'] = 0.0
            else:
                entity = cs['entity']
                self.state = None
                if self.logic.io_manager:
                    self.logic.io_manager.fire_output(entity, 'OnFinished')


