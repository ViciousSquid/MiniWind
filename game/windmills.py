"""Windmill stock and sails: wheat in the inventory keeps the rotor turning.

The mill and its rotor are ordinary Props. ``mill_rotor_for`` on the rotor
names the mill's stable entity id. The tower owns the ordinary, persistent
item inventory that farmers deliver to and the player can open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import glm

from engine.change_journal import touch
from . import fio
from .rpg import inventory, items

MILL = "windmill"
ROTOR_FOR = "mill_rotor_for"
WHEAT = "wheat"
FLOUR = "flour"
WHEAT_PER_FLOUR = 10
MILL_BATCH_HOURS = 0.25
HUB = (0.0, 550.0, 170.0)
DELIVERY_OFFSET = (0.0, 0.0, 210.0)   # outside the door and foundation
RUN_SPEED = 45.0                 # degrees per real second (7.5 rpm)
SPIN_UP_SECONDS = 3.0
SPIN_DOWN_SECONDS = 3.0


def item_stock(owner, item_id: str) -> int:
    """Count positive quantities across all stacks of an ordinary inventory."""
    stocks = getattr(owner, "properties", owner).get("inventory")
    if not isinstance(stocks, list):
        return 0
    quantity = 0
    for stack in stocks:
        if not isinstance(stack, dict) or stack.get("id") != item_id:
            continue
        try:
            quantity += max(0, int(stack.get("qty", 0)))
        except (TypeError, ValueError):
            continue
    return quantity


def wheat_stock(owner) -> int:
    return item_stock(owner, WHEAT)


def take_stock(owner, item_id: str, quantity: int) -> int:
    """Remove a quantity across stacks, including inventories split by the UI."""
    remaining = max(0, int(quantity))
    stocks = inventory.get_inventory(owner)
    for stack in list(stocks):
        if not isinstance(stack, dict) or stack.get("id") != item_id:
            continue
        try:
            have = max(0, int(stack.get("qty", 0)))
        except (TypeError, ValueError):
            continue
        moved = min(remaining, have)
        if moved:
            stack["qty"] = have - moved
            remaining -= moved
            if not stack["qty"]:
                stocks.remove(stack)
        if not remaining:
            break
    return max(0, int(quantity)) - remaining


def mill_flour(mill, hours: float) -> int:
    """Consume ten wheat per flour, using game time and persistent progress."""
    if not math.isfinite(hours) or hours <= 0 or not is_producing(mill):
        return 0
    batches = wheat_stock(mill) // WHEAT_PER_FLOUR
    props = mill.properties
    if not batches:
        props["mill_progress"] = 0.0
        return 0
    try:
        every = max(0.01, float(props.get("mill_batch_hours", MILL_BATCH_HOURS)))
        progress = max(0.0, float(props.get("mill_progress", 0.0)))
    except (TypeError, ValueError):
        every, progress = MILL_BATCH_HOURS, 0.0
    if not math.isfinite(every) or not math.isfinite(progress):
        every, progress = MILL_BATCH_HOURS, 0.0
    progress += hours
    made = min(batches, int((progress + 1e-9) / every))
    if made:
        take_stock(mill, WHEAT, made * WHEAT_PER_FLOUR)
        inventory.add_item(inventory.get_inventory(mill), items.make(FLOUR, made))
    props["mill_progress"] = (max(0.0, progress - made * every)
                              if wheat_stock(mill) >= WHEAT_PER_FLOUR else 0.0)
    return made


def is_producing(mill) -> bool:
    props = mill.properties
    return (not props.get("_bw_parked_disabled", props.get("disabled"))
            and not props.get("dead") and wheat_stock(mill) > 0)


def _basis(props):
    rotation = props.get("rotation", (0.0, 0.0, 0.0))
    basis = glm.rotate(glm.mat4(1.0), math.radians(rotation[1]), glm.vec3(0, 1, 0))
    basis = glm.rotate(basis, math.radians(rotation[0]), glm.vec3(1, 0, 0))
    return glm.rotate(basis, math.radians(rotation[2]), glm.vec3(0, 0, 1))


def delivery_point(mill) -> list:
    """The drop-off point in front of the placed tower's door."""
    scale = mill.properties.get("scale", (1, 1, 1))
    if isinstance(scale, (int, float)):
        scale = (scale, scale, scale)
    offset = _basis(mill.properties) * glm.vec4(
        *(DELIVERY_OFFSET[i] * scale[i] for i in range(3)), 0.0)
    return [float(mill.pos[i] + offset[i]) for i in range(3)]


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
        offset = _basis(props) * glm.vec4(*(HUB[i] * scale[i] for i in range(3)), 0.0)
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
        self._bodies: dict[str, object] = {}

    def bodies(self) -> tuple:
        return tuple(self._bodies.values())

    def find(self, entity_id):
        body = self._bodies.get(entity_id)
        if body is None or body.properties.get("dead") or body.properties.get(
                "_bw_parked_disabled", body.properties.get("disabled")):
            return None
        return body

    def nearest(self, pos):
        available = [body for key in self._bodies if (body := self.find(key)) is not None]
        return min(available, key=lambda b: math.hypot(b.pos[0] - pos[0], b.pos[2] - pos[2]),
                   default=None)

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
            body.properties[MILL] = True
            inventory.get_inventory(body)
            self._bodies[body.properties["id"]] = body
            angle = (rotor.properties.get("rotation", (0, 0, 0))[2]
                     - body.properties.get("rotation", (0, 0, 0))[2])
            mill = _Mill(body, rotor, RotorMotion(angle=angle % 360.0))
            mill.place()
            self.mills.append(mill)

    def update(self, delta: float) -> None:
        for mill in self.mills:
            mill.motion.advance(delta, is_producing(mill.body))
            mill.place()

    def produce(self, hours: float) -> None:
        for body in self._bodies.values():
            mill_flour(body, hours)

    def produce_until(self, world_hour: float, *, initial_hours: float = 0.0) -> None:
        """Include waiting/sleeping clock jumps and time spent in another map."""
        for body in self._bodies.values():
            try:
                last = float(body.properties.get("mill_updated_at", world_hour - initial_hours))
            except (TypeError, ValueError):
                last = world_hour
            body.properties["mill_updated_at"] = world_hour
            mill_flour(body, max(0.0, world_hour - last))

    def clear(self) -> None:
        for mill in self.mills:
            mill.restore()
        self.mills.clear()
        self._bodies.clear()
