"""
MiniWind cutscene runtime.

Cutscenes are authored as ordinary map entities.  Their sequence is data: a
list of camera shots, actor staging, optional dialogue, and transient
message/message2/message3 lines.  No Lua or scene-specific Python is involved.
"""

from __future__ import annotations

import json
import math


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


def _angle_to(from_pos, to_pos):
    fx, fy, fz = from_pos
    tx, ty, tz = to_pos
    dx, dy, dz = tx - fx, ty - fy, tz - fz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-6:
        return 0.0, 0.0
    return math.atan2(dx, dz), math.asin(max(-1.0, min(1.0, dy / dist)))


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _camera_from_logic(logic):
    player = getattr(logic, "player", None)
    if player is not None:
        pos = _vec3(getattr(player, "pos", (0, 0, 0)))
        return {
            "pos": pos,
            "yaw": float(getattr(player, "angle", 0.0)),
            "pitch": float(getattr(player, "pitch", 0.0)),
            "fov": 90.0,
        }
    return {"pos": [0.0, 0.0, 0.0], "yaw": 0.0, "pitch": 0.0, "fov": 90.0}


def normalise_sequence(raw):
    """Return a validated, versioned sequence dictionary."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"version": 1, "actors": [], "shots": []}
    if not isinstance(raw, dict):
        return {"version": 1, "actors": [], "shots": []}

    actors = raw.get("actors", [])
    shots = raw.get("shots", [])
    if not isinstance(actors, list):
        actors = []
    if not isinstance(shots, list):
        shots = []

    clean_actors = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        aid = str(actor.get("id", "")).strip()
        if not aid:
            continue
        clean_actors.append({
            "id": aid,
            "name": str(actor.get("name", "") or ""),
            "pos": _vec3(actor.get("pos")),
            "yaw": float(actor.get("yaw", actor.get("angle", 0.0)) or 0.0),
        })

    clean_shots = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        cam = shot.get("camera", {})
        if not isinstance(cam, dict):
            cam = {}
        dialogue = shot.get("dialogue", {})
        if not isinstance(dialogue, dict):
            dialogue = {}
        messages = shot.get("messages", {})
        if not isinstance(messages, dict):
            messages = {}
        camera = {
            "pos": _vec3(cam.get("pos")),
            "yaw": float(cam.get("yaw", 0.0) or 0.0),
            "pitch": float(cam.get("pitch", 0.0) or 0.0),
            "fov": float(cam.get("fov", 90.0) or 90.0),
        }
        clean_shots.append({
            "duration": max(0.05, float(shot.get("duration", 2.0) or 2.0)),
            "camera": camera,
            "look_at": str(shot.get("look_at", "") or ""),
            "dialogue": {
                "speaker_id": str(dialogue.get("speaker_id", "") or ""),
                "text": str(dialogue.get("text", "") or ""),
                "duration": max(0.0, float(dialogue.get("duration", 0.0) or 0.0)),
            },
            "messages": {
                key: str(messages.get(key, "") or "") for key in _MESSAGE_KEYS
            },
        })

    return {
        "version": int(raw.get("version", 1) or 1),
        "actors": clean_actors,
        "shots": clean_shots,
    }


class CutsceneManager:
    """Runs one authored MiniWind cutscene at a time."""

    def __init__(self, session):
        self.session = session
        self.scene = None
        self.sequence = {"version": 1, "actors": [], "shots": []}
        self.shot_index = -1
        self.elapsed = 0.0
        self.dialogue = None
        self.message_lines = {}
        self._from_camera = None
        self._actor_restore = []
        self._restore_enabled = True
        self._played = set()

    @property
    def active(self):
        return self.scene is not None

    @property
    def current_shot(self):
        if not self.active:
            return None
        shots = self.sequence.get("shots", [])
        if 0 <= self.shot_index < len(shots):
            return shots[self.shot_index]
        return None

    @property
    def current_title(self):
        shot = self.current_shot
        if not shot:
            return "Cutscene"
        dialog = shot.get("dialogue", {})
        speaker = self._find_actor(dialog.get("speaker_id"))
        if speaker is not None:
            return str(speaker.properties.get("display_name")
                       or speaker.properties.get("name")
                       or "Conversation")
        return "Cutscene"

    def _find_actor(self, actor_id):
        if not actor_id:
            return None
        for thing in self.session.logic.things:
            props = getattr(thing, "properties", {})
            if str(props.get("id", "")) == str(actor_id):
                return thing
        return None

    def _find_scene(self, scene_id):
        if not scene_id:
            return None
        for thing in self.session.logic.things:
            props = getattr(thing, "properties", {})
            if str(props.get("id", "")) == str(scene_id):
                return thing
        return None

    def _stage_actors(self):
        self._actor_restore = []
        for authored in self.sequence.get("actors", []):
            actor = self._find_actor(authored.get("id"))
            if actor is None:
                continue
            old_pos = _vec3(getattr(actor, "pos", (0, 0, 0)))
            old_yaw = getattr(actor, "angle", None)
            old_triggered = actor.properties.get("triggered", None)
            self._actor_restore.append((actor, old_pos, old_yaw, old_triggered))
            try:
                import glm
                actor.pos = glm.vec3(*_vec3(authored.get("pos")))
            except Exception:
                actor.pos = list(_vec3(authored.get("pos")))
            if old_yaw is not None:
                try:
                    actor.angle = float(authored.get("yaw", old_yaw))
                except (TypeError, ValueError):
                    pass
            # Park staged actors so the normal MonsterAI thread cannot walk
            # them away from the authored blocking while the cutscene runs.
            actor.properties["triggered"] = True
            actor.properties["_cutscene_staged"] = True

    def _restore_actors(self):
        for actor, pos, yaw, triggered in self._actor_restore:
            if self._restore_enabled:
                try:
                    import glm
                    actor.pos = glm.vec3(*pos)
                except Exception:
                    actor.pos = list(pos)
                if yaw is not None:
                    actor.angle = yaw
            if triggered is None:
                actor.properties.pop("triggered", None)
            else:
                actor.properties["triggered"] = triggered
            actor.properties.pop("_cutscene_staged", None)
        self._actor_restore = []

    def _camera_dict(self, shot):
        cam = dict(shot.get("camera", {}) or {})
        return {
            "pos": _vec3(cam.get("pos")),
            "yaw": float(cam.get("yaw", 0.0) or 0.0),
            "pitch": float(cam.get("pitch", 0.0) or 0.0),
            "fov": float(cam.get("fov", 90.0) or 90.0),
        }

    def _apply_camera(self, camera):
        logic = self.session.logic
        state = getattr(logic, "cinematic_state", None)
        if not isinstance(state, dict):
            state = {}
        state.update({
            "active": False,
            "paused": False,
            "cutscene": True,
            "cam_pos": list(camera["pos"]),
            "cam_angle": float(camera["yaw"]),
            "cam_pitch": float(camera["pitch"]),
            "fov": float(camera.get("fov", 90.0)),
        })
        logic.cinematic_state = state

    def _look_at_camera(self, camera, actor_id):
        actor = self._find_actor(actor_id)
        if actor is None:
            return camera
        pos = _vec3(getattr(actor, "pos", (0, 0, 0)))
        yaw, pitch = _angle_to(camera["pos"], pos)
        out = dict(camera)
        out["yaw"] = yaw
        out["pitch"] = pitch
        return out

    def _shot_camera(self, shot):
        camera = self._camera_dict(shot)
        return self._look_at_camera(camera, shot.get("look_at", ""))

    def _queue_engine_message(self, key, text):
        if not text:
            return
        logic = self.session.logic
        gs = getattr(logic, "game_state", None)
        queue = getattr(gs, "queue_console_command", None)
        if queue is None:
            return
        import json as _json
        try:
            queue(f"{key} {_json.dumps(text, ensure_ascii=False)}")
        except Exception:
            pass

    def _set_shot_ui(self, shot):
        self.dialogue = None
        dialog = shot.get("dialogue", {}) or {}
        text = str(dialog.get("text", "") or "").strip()
        speaker = str(dialog.get("speaker_id", "") or "")
        if text:
            speaker_obj = self._find_actor(speaker)
            self.dialogue = {
                "speaker_id": speaker,
                "speaker": (
                    str(speaker_obj.properties.get("display_name")
                        or speaker_obj.properties.get("name")
                        or "Unknown")
                    if speaker_obj is not None else "Narrator"
                ),
                "text": text,
            }

        self.message_lines = {
            key: str((shot.get("messages", {}) or {}).get(key, "") or "")
            for key in _MESSAGE_KEYS
        }
        for key in _MESSAGE_KEYS:
            self._queue_engine_message(key, self.message_lines[key])

    def _set_camera_to_shot(self, shot, from_camera=None):
        target = self._shot_camera(shot)
        self._from_camera = dict(from_camera or target)
        self._apply_camera(target)

    def start(self, scene=None):
        """Start *scene*. Returns False for invalid/already-running scenes."""
        if self.active:
            return False
        if scene is None:
            return False
        props = getattr(scene, "properties", {})
        scene_id = str(props.get("id", "") or "")
        if scene_id and scene_id in self._played and props.get("once", True):
            return False

        sequence = normalise_sequence(props.get("sequence", ""))
        if not sequence.get("shots"):
            return False

        self.scene = scene
        self.sequence = sequence
        self.shot_index = 0
        self.elapsed = 0.0
        self._restore_enabled = bool(props.get("restore_actors", True))
        self._stage_actors()

        self._set_shot_ui(self.sequence["shots"][0])
        current = _camera_from_logic(self.session.logic)
        self._from_camera = current
        self._set_camera_to_shot(self.sequence["shots"][0], current)

        if scene_id:
            self._played.add(scene_id)

        io = getattr(self.session.logic, "io_manager", None)
        if io is not None:
            io.fire_output(scene, "OnStarted")
        return True

    def start_by_id(self, scene_id):
        return self.start(self._find_scene(scene_id))

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
        if self.active:
            return False
        for scene in self.session._things_of_type("miniwindcutscene"):
            if str(scene.properties.get("trigger_mode", "")) == "play_start":
                if self.start(scene):
                    return True
        return False

    def tick(self, delta):
        if not self.active:
            return
        shot = self.current_shot
        if shot is None:
            self.stop()
            return

        self.elapsed += max(0.0, float(delta))
        duration = max(float(shot.get("duration", 2.0) or 2.0), 0.05)
        dialog = shot.get("dialogue", {}) or {}
        dialog_duration = float(dialog.get("duration", 0.0) or 0.0)
        duration = max(duration, dialog_duration)

        target = self._shot_camera(shot)
        progress = min(1.0, self.elapsed / duration)
        camera = {
            "pos": [_lerp(a, b, progress)
                    for a, b in zip(self._from_camera["pos"], target["pos"])],
            "yaw": _lerp(self._from_camera["yaw"], target["yaw"], progress),
            "pitch": _lerp(self._from_camera["pitch"], target["pitch"], progress),
            "fov": _lerp(self._from_camera["fov"], target["fov"], progress),
        }
        if shot.get("look_at"):
            camera = self._look_at_camera(camera, shot.get("look_at"))
        self._apply_camera(camera)

        if self.elapsed >= duration:
            next_index = self.shot_index + 1
            if next_index >= len(self.sequence.get("shots", [])):
                self.stop()
                return
            self.shot_index = next_index
            self.elapsed = 0.0
            self._set_shot_ui(self.sequence["shots"][next_index])
            self._set_camera_to_shot(self.sequence["shots"][next_index], camera)

    def stop(self):
        if not self.active:
            return
        scene = self.scene
        scene_id = str(getattr(scene, "properties", {}).get("id", "") or "")
        self._restore_actors()
        self.scene = None
        self.shot_index = -1
        self.elapsed = 0.0
        self.dialogue = None
        self.message_lines = {}
        self._from_camera = None
        self.session.logic.cinematic_state = None
        io = getattr(self.session.logic, "io_manager", None)
        if io is not None:
            io.fire_output(scene, "OnFinished")

    def toggle(self, scene):
        if self.active:
            self.stop()
            return True
        return self.start(scene)
