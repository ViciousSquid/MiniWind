"""MiniWind cutscene director: standalone JSON timeline + deterministic playback."""

from __future__ import annotations

import json
import math
import uuid

from . import cutscene_files

_EVENT_TYPES = {"fight", "blood", "dialogue", "message"}
_MESSAGE_KEYS = ("message", "message2", "message3")

def _vec3(value, default=(0.0, 0.0, 0.0)):
    try:
        if hasattr(value, "x"):
            return [float(value.x), float(value.y), float(value.z)]
        values = list(value)
        if len(values) >= 3:
            return [float(values[0]), float(values[1]), float(values[2])]
    except (TypeError, ValueError):
        pass
    return list(default)

def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)

def _smooth(t):
    t = max(0.0, min(1.0, float(t)))
    return t * t * (3.0 - 2.0 * t)

def _angle_to(from_pos, to_pos):
    fx, fy, fz = from_pos
    tx, ty, tz = to_pos
    dx, dy, dz = tx - fx, ty - fy, tz - fz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-6:
        return 0.0, 0.0
    return math.atan2(dx, dz), math.asin(max(-1.0, min(1.0, dy / dist)))

def _sorted_keyframes(value):
    if not isinstance(value, list):
        return []
    out = []
    for row in value:
        if not isinstance(row, dict):
            continue
        try:
            row = dict(row)
            row["time"] = max(0.0, float(row.get("time", 0.0)))
        except (TypeError, ValueError):
            continue
        out.append(row)
    out.sort(key=lambda row: row["time"])
    return out

def normalise_cutscene(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"version": 2, "actors": [], "camera": [], "actor_tracks": {}, "events": [], "settings": {}}
    if not isinstance(raw, dict):
        raw = {}

    settings = raw.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    actors = raw.get("actors", [])
    if not isinstance(actors, list):
        actors = []
    actor_rows = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        aid = str(actor.get("id", "")).strip()
        if not aid:
            continue

        row = {
            "id": aid,
            "name": str(actor.get("name", "") or ""),
        }

        # A wizard-created actor is embedded as a portable definition.  Older
        # cutscenes simply point at an actor already present in the map, so the
        # legacy form remains untouched.
        definition = actor.get("definition")
        if isinstance(definition, dict):
            props = definition.get("properties", {})
            if not isinstance(props, dict):
                props = {}
            dtype = str(definition.get("type") or props.get("type") or "npc").lower()
            row["spawn"] = bool(actor.get("spawn", True))
            row["definition"] = {
                "type": dtype,
                "pos": _vec3(definition.get("pos")),
                "properties": dict(props),
            }
        elif actor.get("spawn"):
            row["spawn"] = True

        actor_rows.append(row)

    tracks = raw.get("actor_tracks", {})
    if not isinstance(tracks, dict):
        tracks = {}
    clean_tracks = {str(aid): _sorted_keyframes(frames) for aid, frames in tracks.items()}

    camera = _sorted_keyframes(raw.get("camera", []))
    events = []
    for index, event in enumerate(raw.get("events", []) if isinstance(raw.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type", "")).strip().lower()
        if kind not in _EVENT_TYPES:
            continue
        try:
            start = max(0.0, float(event.get("time", 0.0)))
        except (TypeError, ValueError):
            start = 0.0
        row = dict(event)
        row["type"] = kind
        row["time"] = start
        if kind == "fight":
            row["attackers"] = [str(x) for x in row.get("attackers", []) if x]
            row["defenders"] = [str(x) for x in row.get("defenders", []) if x]
            try:
                row["duration"] = max(0.05, float(row.get("duration", 5.0)))
            except (TypeError, ValueError):
                row["duration"] = 5.0
            style = str(row.get("style", "normal") or "normal").lower()
            row["style"] = style if style in ("normal", "melee", "bow", "magic") else "normal"
        elif kind == "blood":
            row["position"] = _vec3(row.get("position"))
            try:
                row["width"] = max(8.0, float(row.get("width", 72.0)))
                row["height"] = max(8.0, float(row.get("height", 48.0)))
            except (TypeError, ValueError):
                row["width"], row["height"] = 72.0, 48.0
        elif kind == "dialogue":
            row["speaker_id"] = str(row.get("speaker_id", "") or "")
            row["text"] = str(row.get("text", "") or "")
            try:
                row["duration"] = max(0.05, float(row.get("duration", 3.0)))
            except (TypeError, ValueError):
                row["duration"] = 3.0
        elif kind == "message":
            line = str(row.get("line", "message") or "message").lower()
            row["line"] = line if line in _MESSAGE_KEYS else "message"
            row["text"] = str(row.get("text", "") or "")
        row["_index"] = index
        events.append(row)

    events.sort(key=lambda row: (row["time"], row["_index"]))
    return {
        "version": int(raw.get("version", 2) or 2),
        "id": str(raw.get("id", "") or ""),
        "name": str(raw.get("name", "Cutscene") or "Cutscene"),
        "actors": actor_rows,
        "camera": camera,
        "actor_tracks": clean_tracks,
        "events": events,
        "settings": {
            "restore_actors": bool(settings.get("restore_actors", True)),
            "stop_on_escape": bool(settings.get("stop_on_escape", True)),
        },
    }

class CutsceneManager:
    """Play one external JSON cutscene at a time."""

    def __init__(self, session):
        self.session = session
        self.scene = None
        self.cutscene = None
        self.shot_index = -1
        self.elapsed = 0.0
        self.dialogue = None
        self.message_lines = {}
        self._actor_restore = []
        self._restore_enabled = True
        self._fired_events = set()
        self._fight_cooldowns = {}
        self._fight_original_styles = {}
        self._spawned_blood = []
        # Actors authored by the wizard are runtime-only and must disappear
        # when the cutscene ends or is cancelled.
        self._spawned_actors = []
        self._played = set()
        self._play_start_checked = False
        self._cleanup_offer = None

    @property
    def active(self):
        return self.scene is not None

    @property
    def current_shot(self):
        return None

    @property
    def current_title(self):
        return str((self.cutscene or {}).get("name", "Cutscene"))

    def _find_actor(self, actor_id):
        if not actor_id:
            return None
        for thing in getattr(self.session.logic, "things", ()):
            props = getattr(thing, "properties", {})
            if str(props.get("id", "")) == str(actor_id):
                return thing
        return None

    def _actor_name(self, actor_id):
        actor = self._find_actor(actor_id)
        if actor is None:
            return "Narrator"
        props = actor.properties
        return str(props.get("display_name") or props.get("name") or "Actor")

    def _actor_pose(self, actor):
        return _vec3(getattr(actor, "pos", (0, 0, 0))), float(getattr(actor, "angle", 0.0))

    @staticmethod
    def _assign_pos(actor, pos):
        try:
            import glm
            actor.pos = glm.vec3(*pos)
        except Exception:
            actor.pos = list(pos)

    def _instantiate_spawned_actor(self, row):
        """Build a wizard-authored temporary actor from its embedded definition."""
        definition = row.get("definition")
        if not isinstance(definition, dict):
            return None

        try:
            from .entities import NPC, Creature
            actor_type = str(
                definition.get("type")
                or definition.get("properties", {}).get("type")
                or "npc"
            ).replace("_", "").lower()
            cls = Creature if actor_type == "creature" else NPC
            props = dict(definition.get("properties") or {})
            props["id"] = str(row.get("id") or props.get("id") or uuid.uuid4())
            props["type"] = "creature" if cls is Creature else "npc"
            props.pop("_io_connections", None)
            actor = cls(
                pos=_vec3(definition.get("pos")),
                properties=props,
            )
            try:
                actor.angle = float(definition.get("yaw", getattr(actor, "angle", 0.0)))
            except (TypeError, ValueError):
                pass
            actor.properties["_cutscene_temporary"] = True
            actor.properties["triggered"] = True
            return actor
        except Exception:
            return None

    def _stage_actors(self):
        self._actor_restore = []
        self._spawned_actors = []
        things = getattr(self.session.logic, "things", None)
        if things is None:
            return

        for row in (self.cutscene or {}).get("actors", []):
            actor = None
            spawned = bool(row.get("spawn") and isinstance(row.get("definition"), dict))
            if spawned:
                actor = self._instantiate_spawned_actor(row)
                if actor is not None:
                    things.append(actor)
                    self._spawned_actors.append(actor)
            if actor is None:
                actor = self._find_actor(row.get("id"))
            if actor is None:
                continue

            props = actor.properties
            pos, yaw = self._actor_pose(actor)
            self._actor_restore.append({
                "actor": actor, "pos": pos, "yaw": yaw,
                "health": props.get("health"), "dead": props.get("dead"),
                "triggered": props.get("triggered"), "awake": props.get("awake"),
                "target_name": props.get("target_name"),
                "aggro": props.get("_aggro_target"),
                "is_shooting": props.get("is_shooting"),
                "spawned": actor in self._spawned_actors,
            })
            props["triggered"] = True
            props["awake"] = False
            props["_cutscene_staged"] = True

    def _restore_actors(self):
        for row in self._actor_restore:
            actor = row["actor"]
            props = actor.properties
            if self._restore_enabled:
                self._assign_pos(actor, row["pos"])
                actor.angle = row["yaw"]
                for key in ("health", "dead"):
                    old = row[key]
                    if old is None:
                        props.pop(key, None)
                    else:
                        props[key] = old
            # Runtime AI control flags are always restored. With restore_actors
            # disabled the battle outcome/positions survive, but the NPCs must
            # still return to their normal simulation state instead of remaining
            # parked forever by the cutscene director.
            for key, saved_key in (
                ("triggered", "triggered"), ("awake", "awake"),
                ("target_name", "target_name"), ("_aggro_target", "aggro"),
                ("is_shooting", "is_shooting"),
            ):
                old = row[saved_key]
                if old is None:
                    props.pop(key, None)
                else:
                    props[key] = old
            props.pop("_cutscene_staged", None)
        self._actor_restore = []

    def _actor_track_pose(self, actor_id, elapsed):
        frames = (self.cutscene or {}).get("actor_tracks", {}).get(str(actor_id), [])
        if not frames:
            return None
        if elapsed <= frames[0]["time"]:
            frame = frames[0]
            return _vec3(frame.get("pos")), float(frame.get("yaw", 0.0) or 0.0)
        if elapsed >= frames[-1]["time"]:
            frame = frames[-1]
            return _vec3(frame.get("pos")), float(frame.get("yaw", 0.0) or 0.0)
        for left, right in zip(frames, frames[1:]):
            if left["time"] <= elapsed <= right["time"]:
                span = max(1e-6, right["time"] - left["time"])
                t = _smooth((elapsed - left["time"]) / span)
                lp, rp = _vec3(left.get("pos")), _vec3(right.get("pos"))
                return ([ _lerp(lp[i], rp[i], t) for i in range(3) ],
                        _lerp(left.get("yaw", 0.0), right.get("yaw", 0.0), t))
        return None

    def _camera_pose(self, elapsed):
        frames = (self.cutscene or {}).get("camera", [])
        if not frames:
            return None
        if len(frames) == 1:
            frame = frames[0]
            return self._camera_frame(frame, elapsed)
        if elapsed <= frames[0]["time"]:
            return self._camera_frame(frames[0], elapsed)
        for left, right in zip(frames, frames[1:]):
            if left["time"] <= elapsed <= right["time"]:
                span = max(1e-6, right["time"] - left["time"])
                t = _smooth((elapsed - left["time"]) / span)
                lp, rp = _vec3(left.get("pos")), _vec3(right.get("pos"))
                pos = [_lerp(lp[i], rp[i], t) for i in range(3)]
                yaw = _lerp(left.get("yaw", 0.0), right.get("yaw", 0.0), t)
                pitch = _lerp(left.get("pitch", 0.0), right.get("pitch", 0.0), t)
                fov = _lerp(left.get("fov", 90.0), right.get("fov", 90.0), t)
                return self._look_camera(pos, yaw, pitch, fov, right.get("look_at") or left.get("look_at"))
        return self._camera_frame(frames[-1], elapsed)

    def _camera_frame(self, frame, elapsed):
        pos = _vec3(frame.get("pos"))
        return self._look_camera(pos, float(frame.get("yaw", 0.0)),
                                 float(frame.get("pitch", 0.0)),
                                 float(frame.get("fov", 90.0)),
                                 frame.get("look_at"))

    def _look_camera(self, pos, yaw, pitch, fov, look_at):
        if isinstance(look_at, dict) and look_at.get("actor"):
            actor = self._find_actor(look_at.get("actor"))
            target = _vec3(getattr(actor, "pos", pos)) if actor is not None else pos
            yaw, pitch = _angle_to(pos, target)
        elif isinstance(look_at, (list, tuple)) and len(look_at) >= 3:
            yaw, pitch = _angle_to(pos, _vec3(look_at))
        return {"pos": pos, "yaw": yaw, "pitch": pitch, "fov": fov}

    def _apply_camera(self):
        pose = self._camera_pose(self.elapsed)
        if pose is None:
            return
        self.session.logic.cinematic_state = {
            "active": False, "paused": False, "cutscene": True,
            "cam_pos": pose["pos"], "cam_angle": pose["yaw"],
            "cam_pitch": pose["pitch"], "fov": pose["fov"],
        }

    def _event_is_active(self, event):
        start = float(event.get("time", 0.0))
        if event["type"] in ("fight", "dialogue"):
            return start <= self.elapsed < start + float(event.get("duration", 0.0))
        return False

    def _fight_pairs(self, event):
        attackers = [self._find_actor(aid) for aid in event.get("attackers", [])]
        defenders = [self._find_actor(aid) for aid in event.get("defenders", [])]
        attackers = [a for a in attackers if a is not None and not a.properties.get("dead", False)]
        defenders = [d for d in defenders if d is not None and not d.properties.get("dead", False)]
        return attackers, defenders

    @staticmethod
    def _dist(a, b):
        return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))

    def _advance_fight(self, event, delta):
        logic = self.session.logic
        monster_ai = getattr(logic, "monster_ai", None)
        attackers, defenders = self._fight_pairs(event)
        if not attackers or not defenders:
            return
        now = self.elapsed
        for side, enemies in ((attackers, defenders), (defenders, attackers)):
            for actor in side:
                if actor.properties.get("dead", False):
                    continue
                target = min(enemies, key=lambda x: self._dist(actor.pos, x.pos))
                target_pos = _vec3(target.pos)
                here = _vec3(actor.pos)
                dx = target_pos[0] - here[0]
                dy = target_pos[1] - here[1]
                dz = target_pos[2] - here[2]
                distance = math.sqrt(dx * dx + dy * dy + dz * dz)
                style = str(actor.properties.get("attack_style", "melee")).lower()
                forced_style = str(event.get("style", "normal") or "normal").lower()
                if forced_style != "normal":
                    if id(actor) not in self._fight_original_styles:
                        self._fight_original_styles[id(actor)] = (
                            actor, actor.properties.get("attack_style"))
                    actor.properties["attack_style"] = forced_style
                    style = forced_style
                attack_range = 640.0 if style in ("bow", "magic") else 100.0
                if distance > attack_range * 0.85:
                    length = max(1e-6, distance)
                    speed = max(20.0, float(actor.properties.get("move_speed", 90.0)))
                    step = min(distance - attack_range * 0.7, speed * max(0.0, float(delta)))
                    if step > 0:
                        self._assign_pos(actor, [here[0] + dx / length * step,
                                                here[1] + dy / length * step,
                                                here[2] + dz / length * step])
                    continue
                key = id(actor)
                if now < self._fight_cooldowns.get(key, -1.0):
                    continue
                self._fight_cooldowns[key] = now + (0.7 if style != "melee" else 0.9)
                if monster_ai is not None and hasattr(monster_ai, "_monster_attack"):
                    try:
                        import glm
                        src = glm.vec3(*_vec3(actor.pos))
                        dst = glm.vec3(*_vec3(target.pos))
                        monster_ai._monster_attack(
                            actor, actor.properties.get("monster_type", "human"),
                            dst, target, distance * distance,
                            glm.vec3(src.x, src.y + 64.0, src.z),
                            glm.vec3(dst.x, dst.y + 64.0, dst.z))
                    except Exception:
                        self._fallback_damage(actor, target)
                else:
                    self._fallback_damage(actor, target)
                actor.properties["is_shooting"] = True
                actor.properties["_cutscene_shooting_until"] = now + 0.22

    def _fallback_damage(self, attacker, target):
        damage = max(1, int(attacker.properties.get("damage", 10)))
        health = int(target.properties.get("health", 100)) - damage
        target.properties["health"] = health
        if health <= 0:
            target.properties["dead"] = True
            target.properties["health"] = 0

    def _spawn_blood(self, event):
        try:
            from engine.prop_entity import Prop
            from .rpg import gib
            import random
            paths = gib.stain_paths(magical=False)
            if not paths:
                return
            variant = event.get("variant", "random")
            if str(variant).lower() == "random":
                sprite = random.choice(paths)
            else:
                try:
                    sprite = paths[max(0, min(len(paths) - 1, int(variant)))]
                except (TypeError, ValueError):
                    sprite = paths[0]
            props = {
                "type": "prop", "id": str(uuid.uuid4()),
                "name": "cutscene_blood", "display_name": "Blood",
                "render_mode": "billboard", "sprite_path": sprite,
                "sprite_size": [float(event.get("width", 72.0)), float(event.get("height", 48.0))],
                "collision_shape": "none", "hidden_in_game": False,
            }
            blood = Prop(pos=_vec3(event.get("position")), properties=props)
            self.session.logic.things.append(blood)
            self._spawned_blood.append((blood, bool(event.get("persist", True))))
        except Exception:
            return

    def _fire_events(self):
        for index, event in enumerate((self.cutscene or {}).get("events", [])):
            if event.get("_index", index) in self._fired_events:
                continue
            if float(event.get("time", 0.0)) > self.elapsed + 1e-8:
                continue
            self._fired_events.add(event.get("_index", index))
            kind = event["type"]
            if kind == "blood":
                self._spawn_blood(event)
            elif kind == "message":
                line = event.get("line", "message")
                text = str(event.get("text", ""))
                self.message_lines[line] = text
                self._queue_engine_message(line, text)
            elif kind == "dialogue":
                self.dialogue = {
                    "speaker_id": str(event.get("speaker_id", "") or ""),
                    "speaker": self._actor_name(event.get("speaker_id")),
                    "text": str(event.get("text", "") or ""),
                }
        active_dialogue = None
        for event in (self.cutscene or {}).get("events", []):
            if event["type"] == "dialogue" and self._event_is_active(event):
                active_dialogue = event
        if active_dialogue is None:
            self.dialogue = None
        for key in _MESSAGE_KEYS:
            current = None
            for event in reversed((self.cutscene or {}).get("events", [])):
                if event["type"] == "message" and event.get("line") == key and float(event.get("time", 0.0)) <= self.elapsed:
                    current = str(event.get("text", ""))
                    break
            if current is None:
                self.message_lines.pop(key, None)
            else:
                self.message_lines[key] = current

    def _queue_engine_message(self, key, text):
        logic = self.session.logic
        gs = getattr(logic, "game_state", None)
        queue = getattr(gs, "queue_console_command", None)
        if queue is None or not text:
            return
        try:
            queue(f"{key} {json.dumps(text, ensure_ascii=False)}")
        except Exception:
            pass

    def _clear_shooting_flags(self):
        for row in self._actor_restore:
            actor = row["actor"]
            until = float(actor.properties.get("_cutscene_shooting_until", 0.0) or 0.0)
            if until <= self.elapsed:
                actor.properties.pop("_cutscene_shooting_until", None)
                actor.properties["is_shooting"] = False

    def start(self, scene=None):
        if self.active or scene is None:
            return False
        if getattr(self.session, "dialogue", None) is not None or getattr(self.session, "open_screen", None) is not None:
            return False
        props = getattr(scene, "properties", {})
        filename = str(props.get("cutscene_file", "") or "").strip()
        if not filename:
            return False
        raw = cutscene_files.load_cutscene(filename)
        self.cutscene = normalise_cutscene(raw)
        if not (self.cutscene.get("camera") or self.cutscene.get("actor_tracks") or self.cutscene.get("events")):
            self.cutscene = None
            return False
        scene_id = str(props.get("id", "") or self.cutscene.get("id", "") or filename)
        if scene_id in self._played and props.get("once", True):
            return False
        self.scene = scene
        self.elapsed = 0.0
        self._fired_events = set()
        self._fight_cooldowns = {}
        self._spawned_blood = []
        self._spawned_actors = []
        self._restore_enabled = bool(self.cutscene.get("settings", {}).get("restore_actors", props.get("restore_actors", True)))
        self._stage_actors()
        self._apply_camera()
        self._fire_events()
        if scene_id:
            self._played.add(scene_id)
        io = getattr(self.session.logic, "io_manager", None)
        if io is not None:
            io.fire_output(scene, "OnStarted")
        return True

    def start_by_id(self, scene_id):
        for scene in self.session._things_of_type("miniwindcutscene"):
            if str(scene.properties.get("id", "")) == str(scene_id):
                return self.start(scene)
        return False

    def trigger_proximity(self):
        if self.active:
            return False
        player_pos = self.session._player_pos()
        if player_pos is None:
            return False
        for scene in self.session._things_of_type("miniwindcutscene"):
            props = scene.properties
            if str(props.get("trigger_mode", "proximity")) != "proximity":
                continue
            scene_id = str(props.get("id", "") or "")
            if scene_id in self._played and props.get("once", True):
                continue
            radius = max(1.0, float(props.get("trigger_radius", 160.0) or 160.0))
            if self.session._dist2d(player_pos, scene.pos) <= radius:
                return self.start(scene)
        return False

    def trigger_at_play_start(self):
        if self.active or self._play_start_checked:
            return False
        self._play_start_checked = True
        for scene in self.session._things_of_type("miniwindcutscene"):
            if str(scene.properties.get("trigger_mode", "")) == "play_start":
                if self.start(scene):
                    return True
        return False

    def tick(self, delta):
        if not self.active:
            return
        self.elapsed += max(0.0, float(delta))
        active_fight_ids = set()
        for event in (self.cutscene or {}).get("events", []):
            if event["type"] == "fight" and self._event_is_active(event):
                active_fight_ids.update(event.get("attackers", []))
                active_fight_ids.update(event.get("defenders", []))
        for row in self._actor_restore:
            row["actor"].properties.pop("_cutscene_in_fight", None)
        for actor_id in active_fight_ids:
            actor = self._find_actor(actor_id)
            if actor is not None:
                actor.properties["_cutscene_in_fight"] = True
        for row in self._actor_restore:
            actor = row["actor"]
            pose = self._actor_track_pose(actor.properties.get("id"), self.elapsed)
            if pose is not None and not actor.properties.get("_cutscene_in_fight", False):
                self._assign_pos(actor, pose[0])
                actor.angle = pose[1]
        self._fire_events()
        for event in (self.cutscene or {}).get("events", []):
            if event["type"] == "fight" and self._event_is_active(event):
                self._advance_fight(event, delta)
        self._clear_shooting_flags()
        self._apply_camera()
        duration_candidates = [float(f.get("time", 0.0)) for f in self.cutscene.get("camera", [])]
        duration_candidates += [float(f.get("time", 0.0)) for frames in self.cutscene.get("actor_tracks", {}).values() for f in frames]
        for event in self.cutscene.get("events", []):
            duration_candidates.append(float(event.get("time", 0.0)) + (float(event.get("duration", 0.0)) if event["type"] in ("fight", "dialogue") else 0.0))
        total = max(duration_candidates or [0.0])
        if self.elapsed >= total and not any(self._event_is_active(e) for e in self.cutscene.get("events", [])):
            self.stop(reason="finished")

    def consume_cleanup_offer(self):
        offer = self._cleanup_offer
        self._cleanup_offer = None
        return list(offer or [])

    def cleanup_scene(self, objects):
        things = getattr(self.session.logic, "things", None)
        if things is None:
            return 0
        removed = 0
        for obj in list(objects or []):
            try:
                things.remove(obj)
                removed += 1
            except ValueError:
                pass
        return removed

    def stop(self, reason="cancelled"):
        if not self.active:
            return
        scene = self.scene
        cleanup_candidates = [row["actor"] for row in self._actor_restore]
        cleanup_candidates.extend(blood for blood, _persist in self._spawned_blood)
        if scene is not None:
            cleanup_candidates.append(scene)
        for row in self._actor_restore:
            row["actor"].properties.pop("_cutscene_in_fight", None)
            row["actor"].properties.pop("_cutscene_shooting_until", None)
        self._restore_actors()
        for blood, persist in self._spawned_blood:
            if not persist:
                try:
                    self.session.logic.things.remove(blood)
                except ValueError:
                    pass
        self.scene = None
        self.cutscene = None
        self.elapsed = 0.0
        self.dialogue = None
        self.message_lines = {}
        for actor, original_style in self._fight_original_styles.values():
            if original_style is None:
                actor.properties.pop("attack_style", None)
            else:
                actor.properties["attack_style"] = original_style
        self._fight_original_styles = {}
        self._fight_cooldowns = {}
        for actor in self._spawned_actors:
            try:
                self.session.logic.things.remove(actor)
            except ValueError:
                pass
        self._spawned_actors = []
        self._spawned_blood = []
        self._cleanup_offer = cleanup_candidates if reason == "finished" else None
        self.session.logic.cinematic_state = None
        io = getattr(self.session.logic, "io_manager", None)
        if io is not None:
            io.fire_output(scene, "OnFinished")