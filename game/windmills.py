"""Windmill stock, flour production and continuously turning sails.

The mill and its rotor are ordinary Props. ``mill_rotor_for`` on the rotor
names the mill's stable entity id. The tower owns the ordinary, persistent
item inventory that farmers deliver to and the player can open.

A mill can be *held*: ``mill_held_by`` names whoever holds it (the Old Mill's
bandit chief). While anyone of that name lives, the mill is idle -- no one
delivers to it or buys from it, and its sails stand still -- and once they are
dead (however they died) it is an ordinary working mill again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import glm

from engine.change_journal import touch
from engine.prop_entity import Prop
from . import fio
from .rpg import inventory, items

MILL = "windmill"
ROTOR_FOR = "mill_rotor_for"
ROTOR_AXIS = "mill_rotor_axis"
ROTOR_ANCHOR = "mill_rotor_anchor"
_ROTATION_AXES = {"x": 0, "y": 1, "z": 2}
HELD_BY = "mill_held_by"
IDLE = "mill_idle"              # set while the mill's holder lives
HOLD_CHECK_SECONDS = 2.0
WHEAT = "wheat"
FLOUR = "flour"
STARTING_FLOUR = 25
STARTING_STOCK_SEEDED = "mill_starting_stock_seeded"
WHEAT_PER_FLOUR = 10
MILL_BATCH_HOURS = 0.25
HUB = (0.0, 550.0, 170.0)  # authored rotor prop anchor; visual hub is +150 local Y
DELIVERY_OFFSET = (0.0, 0.0, 210.0)   # outside the door and foundation
RUN_SPEED = 45.0                 # degrees per real second (7.5 rpm)
SPIN_UP_SECONDS = 3.0
SPIN_DOWN_SECONDS = 3.0

# The original Red Grove windmill body is already authored in the world map,
# but predates the linked-rotor format. Give that stable entity its side-mounted
# rotor at the authored hub position without rewriting the large world file.
_RED_GROVE_BODY_ID = "933ae405-bd82-48e5-b8fc-16a035dc5392"
_RED_GROVE_ROTOR_ID = "6ad420d5-0c99-4d42-8d16-6fcb9b523dce"
_RED_GROVE_ROTOR_HUB = (-2028.658, 515.618, 7454.152)
_RED_GROVE_ROTOR_ANCHOR = (-35.342, 339.618, 17.848)
_RED_GROVE_ROTOR_MODEL = "assets/models/chesterton_windmill_rotor.obj"


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


def is_operational(mill) -> bool:
    """Whether the mill itself is able to run, regardless of its wheat stock."""
    props = mill.properties
    return (not props.get("_bw_parked_disabled", props.get("disabled"))
            and not props.get("dead") and not props.get(IDLE))


def is_producing(mill) -> bool:
    """Whether an operational mill has wheat available for flour production."""
    return is_operational(mill) and wheat_stock(mill) > 0


def _basis(props):
    rotation = props.get("rotation", (0.0, 0.0, 0.0))
    basis = glm.rotate(glm.mat4(1.0), math.radians(rotation[1]), glm.vec3(0, 1, 0))
    basis = glm.rotate(basis, math.radians(rotation[0]), glm.vec3(1, 0, 0))
    return glm.rotate(basis, math.radians(rotation[2]), glm.vec3(0, 0, 1))


def _rotor_axis_index(rotor) -> int:
    """Return the authored local Euler axis used by this rotor (default +Y)."""
    axis = str(rotor.properties.get(ROTOR_AXIS, "y")).lower()
    return _ROTATION_AXES.get(axis, 1)


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
        # Most mills retain the overhead rotor's historical anchor. A body
        # may author a different local hub position for a side-mounted rotor.
        anchor = props.get(ROTOR_ANCHOR, HUB)
        if not isinstance(anchor, (list, tuple)) or len(anchor) != 3:
            anchor = HUB
        try:
            anchor = tuple(float(value) for value in anchor)
            if not all(math.isfinite(value) for value in anchor):
                anchor = HUB
        except (TypeError, ValueError):
            anchor = HUB
        # Fio's model rotation order is Y, X, Z; the offset follows the body.
        offset = _basis(props) * glm.vec4(*(anchor[i] * scale[i] for i in range(3)), 0.0)
        pos = [float(self.body.pos[i] + offset[i]) for i in range(3)]
        if list(self.rotor.pos) != pos:
            self.rotor.pos = pos
        rotation[_rotor_axis_index(self.rotor)] += self.motion.angle
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
        self._hold_clock = 0.0

    def bodies(self) -> tuple:
        return tuple(self._bodies.values())

    def find(self, entity_id):
        body = self._bodies.get(entity_id)
        if body is None or body.properties.get("dead") or body.properties.get(IDLE) or (
                body.properties.get("_bw_parked_disabled", body.properties.get("disabled"))):
            return None
        return body

    def nearest(self, pos):
        available = [body for key in self._bodies if (body := self.find(key)) is not None]
        return min(available, key=lambda b: math.hypot(b.pos[0] - pos[0], b.pos[2] - pos[2]),
                   default=None)

    def _ensure_red_grove_rotor(self, things) -> None:
        """Attach the existing vertical sail model to the legacy Red Grove body.

        The rotor hub coordinates are authored in world space. Keeping the
        corresponding local anchor on the body makes the rotor follow later
        translations, rotations and scale edits through the normal mill path.
        """
        body = next((thing for thing in things
                     if getattr(thing, "properties", {}).get("id") == _RED_GROVE_BODY_ID),
                    None)
        if body is None:
            return

        body_props = body.properties
        body_props.setdefault(ROTOR_ANCHOR, list(_RED_GROVE_ROTOR_ANCHOR))
        if any(getattr(thing, "properties", {}).get(ROTOR_FOR) == _RED_GROVE_BODY_ID
               for thing in things):
            return

        scale = body_props.get("scale", (1.0, 1.0, 1.0))
        if isinstance(scale, (int, float)):
            scale = [scale, scale, scale]
        else:
            scale = list(scale)
        rotor = Prop(
            pos=list(_RED_GROVE_ROTOR_HUB),
            properties={
                "type": "prop",
                "name": "windmill_body_sails",
                "id": _RED_GROVE_ROTOR_ID,
                "render_mode": "model",
                "model_path": _RED_GROVE_ROTOR_MODEL,
                ROTOR_FOR: _RED_GROVE_BODY_ID,
                ROTOR_AXIS: "z",
                "rotation": list(body_props.get("rotation", (0.0, 0.0, 0.0))),
                "scale": scale,
                "carry_enabled": False,
                "collect_enabled": False,
                "physics_enabled": False,
                "no_collision": True,
                "gravity": False,
                "io_enabled": True,
            },
        )
        things.append(rotor)

    def install(self) -> None:
        self.clear()
        things = fio.things(self.logic)
        self._ensure_red_grove_rotor(things)
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
            axis = _rotor_axis_index(rotor)
            angle = (rotor.properties.get("rotation", (0, 0, 0))[axis]
                     - body.properties.get("rotation", (0, 0, 0))[axis])
            mill = _Mill(body, rotor, RotorMotion(angle=angle % 360.0))
            mill.place()
            self.mills.append(mill)
        self.check_holders(things)
        # And again on the first update: actors placed at play start may
        # not all be in the world yet.
        self._hold_clock = HOLD_CHECK_SECONDS

    def seed_starting_stock(self) -> int:
        """Give every mill its opening flour stock once for a new game.

        The marker is an ordinary saved property beside the inventory. This
        method is called from character creation, not session installation,
        so loading a save never replenishes flour that has been used.
        """
        seeded = 0
        for body in self._bodies.values():
            props = body.properties
            if props.get(STARTING_STOCK_SEEDED):
                continue
            missing = max(0, STARTING_FLOUR - item_stock(body, FLOUR))
            if missing:
                flour = items.make(FLOUR, missing)
                if flour is None:
                    raise RuntimeError(f"Starting mill item is not registered: {FLOUR}")
                inventory.add_item(inventory.get_inventory(body), flour)
            props[STARTING_STOCK_SEEDED] = True
            seeded += 1
        return seeded

    def check_holders(self, things=None) -> None:
        """Idle each held mill while anyone of its holder's name lives."""
        held = [b for b in self._bodies.values() if b.properties.get(HELD_BY)]
        if not held:
            return
        if things is None:
            things = fio.things(self.logic)
        living = set()
        for t in things:
            p = getattr(t, "properties", None) or {}
            if p.get("dead") or not p.get("name"):
                continue
            try:
                if float(p.get("health", 1.0)) <= 0.0:
                    continue
            except (TypeError, ValueError):
                pass
            living.add(str(p.get("name")))
            if p.get("display_name"):
                living.add(str(p.get("display_name")))
        for body in held:
            idle = str(body.properties[HELD_BY]) in living
            if bool(body.properties.get(IDLE)) != idle:
                body.properties[IDLE] = idle

    def update(self, delta: float) -> None:
        self._hold_clock += max(0.0, float(delta))
        if self._hold_clock >= HOLD_CHECK_SECONDS:
            self._hold_clock = 0.0
            self.check_holders()
        for mill in self.mills:
            mill.motion.advance(delta, is_operational(mill.body))
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
