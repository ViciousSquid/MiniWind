"""Camera state and camera math for the LogicThread.

LogicThread owns the simulation loop; this object owns the camera domain:
editor camera state, play camera mode, overhead projection, frustum parameters,
and first-person/overhead transitions.
"""

import math
import time

import glm

from .camera import Camera

# Right-stick pitch may deviate only this far from the configured view.
CAMERA_PITCH_LIMIT = 5.0


class LogicCamera:
    """State and calculations for the editor/play camera."""

    def __init__(self, host):
        # Resolve the player through LogicPlayer at use time. The player runtime
        # owns the live actor reference and may replace it across play sessions.
        self._host = host

        # Frustum parameters are shared with the render projection. They live
        # here so camera math and the values handed to GL cannot drift apart.
        self.frustum_aspect = 16.0 / 9.0
        self.frustum_fov = 90.0

        # Play-mode camera mode: First Person or Overhead.
        self.camera_mode = "First Person"
        self.overhead_height = 800.0
        self.overhead_height_limit = None
        self.overhead_tilt = 0.0
        self.overhead_orientation = "north"
        # Independent orbit: turning the player never turns a north-up camera.
        self.overhead_yaw = 0.0
        self._overhead_pitch = 0.0

        # Avoid normalising the mode string on every render-state build.
        self._camera_mode_raw = None
        self._camera_mode_overhead = False

        # Active First Person <-> Overhead tween, or None.
        self.camera_transition = None

        # Editor camera.
        self.editor_camera = Camera()
        self.editor_camera.pos = glm.vec3(0, 150, 400)

        # Camera focus (set_camera_focus): a world point the overhead camera
        # glides to and holds instead of the player, and glides back from.
        self.reset_camera_focus()

        # Screen shake (shake()): strength as a fraction of the overhead
        # camera's height, when it started and how long it lasts.
        self._shake = (0.0, 0.0, 0.0)

    # ------------------------------------------------------------------
    # Screen shake
    # ------------------------------------------------------------------

    def shake(self, strength: float, seconds: float = 0.3) -> None:
        """Jolt the play camera: *strength* is how far it jumps, as a fraction
        of the overhead camera's height (0.02 is a hard knock), dying away
        over *seconds*. A stronger shake replaces a weaker one in progress."""
        now = time.perf_counter()
        if self.shake_level(now) > float(strength):
            return
        self._shake = (float(strength), now, max(0.05, float(seconds)))

    def shake_level(self, now=None) -> float:
        """How strong the shake is right now (0 when still)."""
        strength, start, seconds = self._shake
        if strength <= 0.0:
            return 0.0
        now = time.perf_counter() if now is None else now
        left = 1.0 - (now - start) / seconds
        return strength * left * left if left > 0.0 else 0.0

    def shake_offset(self, now=None):
        """The world-space jolt to add to the camera this frame (x, z)."""
        now = time.perf_counter() if now is None else now
        level = self.shake_level(now)
        if level <= 0.0:
            return 0.0, 0.0
        amp = level * self.effective_overhead_height()
        return (amp * math.sin(now * 71.0) * math.cos(now * 23.0),
                amp * math.sin(now * 59.0 + 1.3) * math.cos(now * 31.0))

    # ------------------------------------------------------------------
    # Editor/frustum configuration
    # ------------------------------------------------------------------

    def set_editor_camera(self, pos: glm.vec3, yaw: float, pitch: float, fov: float):
        self.editor_camera.pos = glm.vec3(pos)
        self.editor_camera.yaw = yaw
        self.editor_camera.pitch = pitch
        self.editor_camera.fov = fov

    def get_editor_camera(self) -> Camera:
        return self.editor_camera

    def set_frustum_aspect(self, aspect: float):
        self.frustum_aspect = aspect

    def set_frustum_fov(self, fov: float):
        """Set the play view's vertical FOV in degrees."""
        try:
            fov = float(fov)
        except (TypeError, ValueError):
            return
        if 1.0 <= fov <= 179.0:
            self.frustum_fov = fov

    # ------------------------------------------------------------------
    # Camera mode
    # ------------------------------------------------------------------

    def set_camera_mode(self, mode: str):
        """Select the play-mode camera: First Person or Overhead."""
        self.camera_mode = str(mode)

    def is_overhead(self) -> bool:
        """Return whether the active play camera is overhead."""
        cm = self.camera_mode
        if cm != self._camera_mode_raw:
            self._camera_mode_raw = cm
            self._camera_mode_overhead = str(cm).strip().lower() in (
                "overhead", "top-down", "topdown"
            )
        return self._camera_mode_overhead

    @property
    def overhead_angle(self) -> float:
        """Elevation above the ground plane: 90 is straight down."""
        return max(1.0, min(90.0, 90.0 - float(self.overhead_tilt) - self.overhead_pitch))

    @property
    def overhead_pitch(self):
        """Bounded stick adjustment in degrees; the configured tilt stays intact."""
        return self._overhead_pitch

    @overhead_pitch.setter
    def overhead_pitch(self, degrees):
        self._overhead_pitch = max(-CAMERA_PITCH_LIMIT, min(CAMERA_PITCH_LIMIT, float(degrees)))

    def set_overhead_angle(self, degrees) -> float:
        angle = float(degrees)
        if not math.isfinite(angle) or not 1.0 <= angle <= 90.0:
            raise ValueError("overheadangle must be between 1 and 90 degrees")
        self.overhead_tilt = 90.0 - angle
        self.overhead_pitch = 0.0
        return angle

    def effective_overhead_height(self) -> float:
        """Return the camera height after applying an optional ceiling."""
        height = float(self.overhead_height)
        limit = self.overhead_height_limit
        if limit is not None and float(limit) > 0.0:
            height = min(height, float(limit))
        return height

    # ------------------------------------------------------------------
    # Camera focus
    # ------------------------------------------------------------------

    #: Seconds the camera takes to glide to a focus point and back.
    CAMERA_FOCUS_SECONDS = 0.6

    def reset_camera_focus(self):
        """Follow the player again at once (every play session starts so)."""
        self._camera_focus = None
        self._camera_focus_from = None
        self._camera_focus_blend = 0.0
        self._camera_focus_clock = None

    def set_camera_focus(self, point=None, glide=True):
        """Point the overhead camera at *point* ``(x, y, z)``; None returns it.

        The camera glides there over :data:`CAMERA_FOCUS_SECONDS` and holds it
        whatever the player does, until cleared, when it glides back to the
        player (or, with ``glide=False``, snaps straight back). A tool or game
        uses it to show a place without moving anyone (a debug inspector's
        "show me where he works"). First person ignores it; streaming and
        simulation stay centred on the player.
        """
        if point is None:
            self._camera_focus = None
            if not glide:
                self._camera_focus_blend = 0.0
            return
        target = (float(point[0]), float(point[1]), float(point[2]))
        self._camera_focus = target
        self._camera_focus_from = target

    @property
    def camera_focus(self):
        """The point the camera is held on, or None (following the player)."""
        return self._camera_focus

    def focused_camera_centre(self, player_pos):
        """Where the overhead camera centres this frame (see set_camera_focus)."""
        now = time.perf_counter()
        last = self._camera_focus_clock
        self._camera_focus_clock = now
        step = 0.0 if last is None else (now - last) / max(1e-3, self.CAMERA_FOCUS_SECONDS)
        blend = self._camera_focus_blend
        blend = (min(1.0, blend + step) if self._camera_focus is not None
                 else max(0.0, blend - step))
        self._camera_focus_blend = blend
        sx, sz = self.shake_offset(now)
        if blend <= 0.0 or self._camera_focus_from is None:
            if sx or sz:
                return glm.vec3(player_pos.x + sx, player_pos.y, player_pos.z + sz)
            return player_pos
        k = blend * blend * (3.0 - 2.0 * blend)
        fx, fy, fz = self._camera_focus_from
        return glm.vec3(player_pos.x + (fx - player_pos.x) * k + sx,
                        player_pos.y + (fy - player_pos.y) * k,
                        player_pos.z + (fz - player_pos.z) * k + sz)

    # ------------------------------------------------------------------
    # Overhead camera geometry
    # ------------------------------------------------------------------

    def overhead_heading(self, player_angle=0.0):
        """World heading at screen top, shared by movement and navigation HUD."""
        base = (player_angle if str(self.overhead_orientation).strip().lower() == "player"
                else math.pi)
        return base + self.overhead_yaw

    def rotate_overhead(self, dx, dy, player_angle=0.0):
        """Orbit with at most five degrees of pitch from the configured view."""
        # Orbiting must not follow the sprite as it turns to walk.
        if str(self.overhead_orientation).strip().lower() == "player":
            self.overhead_yaw = self.overhead_heading(player_angle) - math.pi
            self.overhead_orientation = "north"
        self.overhead_yaw = (self.overhead_yaw - dx * 0.002) % (2 * math.pi)
        base = max(0.0, min(89.0, float(self.overhead_tilt)))
        self.overhead_pitch = max(-base, min(89.0 - base, self.overhead_pitch + dy * 0.1))

    def _overhead_camera(self, player_pos, angle):
        """Compute (cam_pos, direction, up) for the overhead camera."""
        px = float(player_pos.x)
        py = float(player_pos.y)
        pz = float(player_pos.z)

        heading = self.overhead_heading(angle)
        head_x, head_z = math.sin(heading), math.cos(heading)

        tilt = math.radians(90.0 - self.overhead_angle)
        sin_t, cos_t = math.sin(tilt), math.cos(tilt)
        dir_x = head_x * sin_t
        dir_y = -cos_t
        dir_z = head_z * sin_t
        dlen = math.sqrt(dir_x * dir_x + dir_y * dir_y + dir_z * dir_z) or 1.0
        direction = glm.vec3(dir_x / dlen, dir_y / dlen, dir_z / dlen)

        dist = self.effective_overhead_height() / max(1e-3, cos_t)
        cam_pos = glm.vec3(
            px - direction.x * dist,
            py - direction.y * dist,
            pz - direction.z * dist,
        )
        up = self._safe_up(direction, glm.vec3(head_x, 0.0, head_z))
        return cam_pos, direction, up

    def overhead_ground_footprint(self):
        """Return the ground footprint as (half_x, half_z, reach).

        The footprint is derived from the actual overhead camera and current
        player pose, so streaming/culling consumers see exactly the ground the
        view can reach rather than an independent approximation.
        """
        player = self._host.player_runtime.player
        if not self.is_overhead() or player is None:
            return None

        pos = player.pos
        cam, direction, up = self._overhead_camera(
            pos, getattr(player, "angle", 0.0)
        )
        d = glm.normalize(glm.vec3(direction))
        right = glm.normalize(glm.cross(d, glm.vec3(up)))
        true_up = glm.cross(right, d)

        tan_v = math.tan(math.radians(float(self.frustum_fov)) / 2.0)
        tan_h = tan_v * max(0.1, float(self.frustum_aspect))

        ground = float(pos.y)
        hx = hz = reach = 0.0
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                ray = d + true_up * (sy * tan_v) + right * (sx * tan_h)
                if ray.y >= -1e-3:
                    return None
                t = (ground - cam.y) / ray.y
                dx = cam.x + ray.x * t - pos.x
                dz = cam.z + ray.z * t - pos.z
                hx = max(hx, abs(dx))
                hz = max(hz, abs(dz))
                reach = max(reach, math.hypot(dx, dz))
        return hx, hz, reach

    @staticmethod
    def _safe_up(direction, up):
        """Return a non-degenerate up vector suitable for glm.lookAt."""
        d = glm.vec3(direction)
        if glm.length(d) < 1e-8:
            return glm.vec3(0, 1, 0)
        d = glm.normalize(d)
        u = glm.vec3(up)
        u = glm.normalize(u) if glm.length(u) > 1e-8 else glm.vec3(0, 1, 0)
        if abs(glm.dot(d, u)) > 0.999:
            u = glm.vec3(0, 0, 1) if abs(d.y) > 0.9 else glm.vec3(0, 1, 0)
        return u

    def _camera_for_mode(
        self, overhead, player_pos, player_angle, player_pitch, camera_height
    ):
        """Return (cam_pos, direction, up, fov) for one camera mode."""
        if overhead:
            cam_pos, direction, up = self._overhead_camera(
                player_pos, player_angle
            )
            return cam_pos, direction, up, self.frustum_fov

        cam_pos = player_pos + glm.vec3(0, camera_height, 0)
        direction = glm.vec3(
            math.sin(player_angle) * math.cos(player_pitch),
            math.sin(player_pitch),
            math.cos(player_angle) * math.cos(player_pitch),
        )
        return cam_pos, direction, glm.vec3(0, 1, 0), self.frustum_fov

    # ------------------------------------------------------------------
    # Camera transitions
    # ------------------------------------------------------------------

    def start_camera_transition(self, target_mode=None, duration=1.0):
        """Begin a smooth tween between First Person and Overhead cameras."""
        current_overhead = self.is_overhead()
        if target_mode is None:
            to_overhead = not current_overhead
        else:
            to_overhead = str(target_mode).strip().lower() in (
                "overhead", "top-down", "topdown", "top", "td"
            )
        new_mode = "Overhead" if to_overhead else "First Person"

        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 1.0

        ct = self.camera_transition

        if to_overhead == current_overhead and not ct:
            self.camera_mode = new_mode
            return new_mode

        if duration <= 0.0:
            self.camera_transition = None
            self.camera_mode = new_mode
            return new_mode

        if ct and to_overhead == ct["from_overhead"]:
            progressed = min(ct["elapsed"], ct["duration"])
            remaining_frac = 1.0 - (
                progressed / ct["duration"] if ct["duration"] > 0 else 1.0
            )
            self.camera_transition = {
                "from_overhead": ct["to_overhead"],
                "to_overhead": to_overhead,
                "elapsed": remaining_frac * duration,
                "duration": duration,
            }
            self.camera_mode = new_mode
            return new_mode

        self.camera_transition = {
            "from_overhead": current_overhead,
            "to_overhead": to_overhead,
            "elapsed": 0.0,
            "duration": duration,
        }
        self.camera_mode = new_mode
        return new_mode

    def update_camera_transition(self, delta):
        """Advance the active camera tween and clear it when complete."""
        ct = self.camera_transition
        if not ct:
            return
        ct["elapsed"] += delta
        if ct["elapsed"] >= ct["duration"]:
            self.camera_transition = None
