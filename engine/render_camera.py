"""Presentation-only camera interpolation over immutable simulation samples.

Keep two small poses, never a render-state lease or a copy of the world tables.
Drawing one tick behind lets a 60 Hz simulation move smoothly at the display's
refresh rate without predicting through collisions or changing gameplay.
"""

from dataclasses import dataclass
import math

import glm


@dataclass(frozen=True, slots=True)
class CameraPose:
    eye: glm.vec3
    rotation: glm.quat
    player_pos: glm.vec3
    angle: float
    pitch: float

    @classmethod
    def capture(cls, view, player_pos, angle, pitch):
        world = glm.inverse(view)
        return cls(glm.vec3(world[3]), glm.normalize(glm.quat_cast(world)),
                   glm.vec3(player_pos), float(angle), float(pitch))

    def blend(self, other, alpha):
        eye = glm.mix(self.eye, other.eye, alpha)
        rotation = glm.normalize(glm.slerp(self.rotation, other.rotation, alpha))
        world = glm.mat4_cast(rotation)
        world[3] = glm.vec4(eye, 1.0)
        turn = (other.angle - self.angle + math.pi) % math.tau - math.pi
        return (glm.inverse(world), glm.mix(self.player_pos, other.player_pos, alpha),
                self.angle + turn * alpha,
                self.pitch + (other.pitch - self.pitch) * alpha)

    def continuous_with(self, other):
        # Ordinary movement is a few units per tick. Teleports and camera cuts
        # must appear immediately instead of sweeping through intervening walls.
        return (glm.distance(self.player_pos, other.player_pos) <= 128.0
                and glm.distance(self.eye, other.eye) <= 512.0)


@dataclass(frozen=True, slots=True)
class CameraSample:
    timestamp: float
    primary: CameraPose
    secondary: CameraPose | None

    @classmethod
    def capture(cls, state, timestamp):
        secondary = (CameraPose.capture(state.player2_view_matrix, state.player2_pos,
                                       state.player2_angle, state.player2_pitch)
                     if state.splitscreen_active else None)
        return cls(timestamp, CameraPose.capture(state.camera_view_matrix, state.player_pos,
                                                state.player_angle, state.player_pitch),
                   secondary)


class CameraHistory:
    def __init__(self):
        self._serial = None
        self._context = None
        self._current = None
        self._frames = None

    def capture(self, state, serial, timestamp, context):
        """Publish poses once per simulation step, including on a declined swap.

        A loop iteration with no tick may project the world again. It must keep
        the original pose time; retiming an identical pose restarts the blend
        and creates another periodic hitch.
        """
        if context is None:
            self.__init__()
        elif serial != self._serial or context != self._context:
            current = CameraSample.capture(state, timestamp)
            previous = self._current
            continuous = (
                previous is not None and context == self._context
                and 0.0 < timestamp - previous.timestamp <= 0.1
                and previous.primary.continuous_with(current.primary)
                and ((previous.secondary is None and current.secondary is None)
                     or (previous.secondary is not None and current.secondary is not None
                         and previous.secondary.continuous_with(current.secondary)))
            )
            self._frames = (previous, current) if continuous else None
            self._current = current
            self._serial, self._context = serial, context
        state.camera_frames = self._frames


def interpolate_camera(state, now, delay):
    """Replace only the borrowed snapshot's camera fields, never live state."""
    frames = state.camera_frames
    if frames is None:
        return
    previous, current = frames
    alpha = max(0.0, min(1.0, (now - delay - previous.timestamp)
                         / (current.timestamp - previous.timestamp)))
    (state.camera_view_matrix, state.player_pos,
     state.player_angle, state.player_pitch) = previous.primary.blend(current.primary, alpha)
    if current.secondary is not None:
        (state.player2_view_matrix, state.player2_pos,
         state.player2_angle, state.player2_pitch) = previous.secondary.blend(current.secondary, alpha)
