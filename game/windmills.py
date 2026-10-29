"""Windmill sails, driven by an explicit production flag.

The mill and its rotor are ordinary Props. ``mill_rotor_for`` on the rotor
names the mill's stable entity id; ``mill_producing`` on the mill is the seam
for the future production system. No goods or production rules live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import glm

from engine.change_journal import touch
from . import fio

PRODUCING = "mill_producing"
ROTOR_FOR = "mill_rotor_for"
HUB = (0.0, 550.0, 170.0)
RUN_SPEED = 45.0                 # degrees per real second (7.5 rpm)
SPIN_UP_SECONDS = 3.0
SPIN_DOWN_SECONDS = 3.0


def set_producing(mill, producing: bool) -> None:
    """Future production code sets this when work starts or stops."""
    mill.properties[PRODUCING] = bool(producing)


@dataclass
class RotorMotion:
    """Continuous angle and speed, including interrupted starts and stops."""

    angle: float = 0.0
    speed: float = 0.0

    def advance(self, delta: float, producing: bool) -> None:
        if not math.isfinite(delta) or delta <= 0.0:
            return
        target = RUN_SPEED if producing else 0.0
        duration = SPIN_UP_SECONDS if producing else SPIN_DOWN_SECONDS
        acceleration = math.copysign(RUN_SPEED / duration, target - self.speed)
        time_to_target = abs(target - self.speed) / abs(acceleration)
        ramp = min(delta, time_to_target)
        # Integrate the ramp and any remaining steady motion separately. This
        # gives the same motion for a long tick as for many small ticks.
        distance = self.speed * ramp + 0.5 * acceleration * ramp * ramp
        self.speed = target if delta >= time_to_target else self.speed + acceleration * ramp
        distance += self.speed * (delta - ramp)
        self.angle = (self.angle + distance) % 360.0


@dataclass
class _Mill:
    body: object
    rotor: object
    motion: RotorMotion = field(default_factory=RotorMotion)
    _rest_pos: list = field(init=False)
    _rest_rotation: list = field(init=False)
    _rest_scale: object = field(init=False)

    def __post_init__(self):
        self._rest_pos = list(self.rotor.pos)
        self._rest_rotation = list(self.rotor.properties.get("rotation", (0, 0, 0)))
        scale = self.rotor.properties.get("scale", (1, 1, 1))
        self._rest_scale = scale if isinstance(scale, (int, float)) else list(scale)

    def restore(self) -> None:
        self.rotor.pos = self._rest_pos
        self.rotor.properties["rotation"] = self._rest_rotation
        self.rotor.properties["scale"] = self._rest_scale
        touch(self.rotor)

    def place(self) -> None:
        """Follow the tower's transform, rotating only around the local hub."""
        props = self.body.properties
        rotation = list(props.get("rotation", (0.0, 0.0, 0.0)))
        scale = props.get("scale", (1.0, 1.0, 1.0))
        if isinstance(scale, (int, float)):
            scale = (scale, scale, scale)
        # Fio's model rotation order is Y, X, Z.
        basis = glm.rotate(glm.mat4(1.0), math.radians(rotation[1]), glm.vec3(0, 1, 0))
        basis = glm.rotate(basis, math.radians(rotation[0]), glm.vec3(1, 0, 0))
        basis = glm.rotate(basis, math.radians(rotation[2]), glm.vec3(0, 0, 1))
        offset = basis * glm.vec4(*(HUB[i] * scale[i] for i in range(3)), 0.0)
        pos = [float(self.body.pos[i] + offset[i]) for i in range(3)]
        if list(self.rotor.pos) != pos:
            self.rotor.pos = pos
        rotation[2] += self.motion.angle
        changes = {"rotation": rotation, "scale": list(scale)}
        changed = False
        for key, value in changes.items():
            if self.rotor.properties.get(key) != value:
                self.rotor.properties[key] = value
                changed = True
        if changed:
            # Property dict writes alone do not reach the render projection.
            touch(self.rotor)


class Windmills:
    """Per-session rotor state; each authored mill operates independently."""

    def __init__(self, logic):
        self.logic = logic
        self.mills: list[_Mill] = []

    def install(self) -> None:
        self.clear()
        things = fio.things(self.logic)
        by_id = {t.properties.get("id"): t for t in things}
        self.mills = []
        for rotor in things:
            target = rotor.properties.get(ROTOR_FOR)
            if not target:
                continue
            body = by_id.get(target)
            if body is None or body is rotor:
                continue
            angle = (rotor.properties.get("rotation", (0, 0, 0))[2]
                     - body.properties.get("rotation", (0, 0, 0))[2])
            mill = _Mill(body, rotor, RotorMotion(angle=angle % 360.0))
            mill.place()
            self.mills.append(mill)

    def update(self, delta: float) -> None:
        for mill in self.mills:
            props = mill.body.properties
            producing = bool(props.get(PRODUCING, True)) and not props.get("disabled", False)
            mill.motion.advance(delta, producing)
            mill.place()

    def clear(self) -> None:
        for mill in self.mills:
            mill.restore()
        self.mills.clear()
