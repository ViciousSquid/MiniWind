"""An actor's heading: one value, one writer.

The heading is ``properties['angle']``, in degrees, in PlayerStart's
convention: 0 looks along +Z, 90 along +X, so forward is
``(sin a, 0, cos a)`` and the heading toward ``(dx, _, dz)`` is
``atan2(dx, dz)``. The editor authors it (a placed actor's facing) and play
turns it; the editor puts the authored value back when play stops.

This module is the only code that writes a heading, and every write tells the
change journal with the cheap :data:`~engine.change_journal.FACING` flag, so a
table re-reads that one value (a head sprite's spin) without resolving the
row. Code that needs a heading reads :func:`heading` (radians).

Turns are eased when the caller passes the frame's *delta*: the actor swings
toward its new heading at :data:`TURN_RATE` rather than snapping. A game sets
the rate it wants; ``None`` snaps, as Fio's stock monsters do.
"""

from __future__ import annotations

import math

#: Radians per second an actor swings toward a new heading when the caller
#: passes a delta. ``None`` turns it outright.
TURN_RATE = None

#: Changes smaller than this (degrees) are round-off in repeated float32
#: movement vectors, not a turn: no write, no journal record.
_EPSILON_DEG = 1e-4

_TWO_PI = math.pi * 2.0


def wrap(angle: float) -> float:
    """*angle* (radians) folded into (-pi, pi]."""
    return (float(angle) + math.pi) % _TWO_PI - math.pi


def heading(thing) -> float:
    """*thing*'s heading in radians (forward ``(sin a, 0, cos a)``)."""
    try:
        return math.radians(float(thing.properties.get('angle', 0.0) or 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def set_heading(thing, radians: float) -> float:
    """Point *thing* along *radians*; returns the heading it now has."""
    radians = float(radians)
    if not math.isfinite(radians):
        return heading(thing)
    props = thing.properties
    angle = math.degrees(radians) % 360.0
    try:
        previous = float(props.get('angle', 0.0) or 0.0)
    except (TypeError, ValueError):
        previous = None
    if previous is None or abs((angle - previous + 180.0) % 360.0 - 180.0) > _EPSILON_DEG:
        from .change_journal import FACING, touch
        props['angle'] = angle
        touch(thing, FACING)
    return math.radians(angle)


def turn_toward(thing, dx: float, dz: float, delta=None, rate=None) -> float:
    """Turn *thing* toward the world direction ``(dx, _, dz)``.

    With a *delta* and a turn rate (*rate*, else :data:`TURN_RATE`) the turn is
    eased; otherwise it is made outright. A near-zero direction is ignored, so
    an actor at rest keeps looking the way it was. Returns the heading
    (radians) the actor now has.
    """
    dx = float(dx)
    dz = float(dz)
    if not (math.isfinite(dx) and math.isfinite(dz)) or dx * dx + dz * dz <= 1e-9:
        return heading(thing)
    target = math.atan2(dx, dz)
    rate = TURN_RATE if rate is None else rate
    if delta is None or not rate or rate <= 0.0:
        return set_heading(thing, target)
    current = heading(thing)
    diff = wrap(target - current)
    step = float(rate) * float(delta)
    if abs(diff) > step:
        target = current + math.copysign(step, diff)
    return set_heading(thing, target)


def face_direction(thing, direction, delta=None) -> float:
    """:func:`turn_toward` for a 3-vector movement or attack direction."""
    return turn_toward(thing, direction[0], direction[2], delta)


# ---------------------------------------------------------------------------
# View cones: what an actor facing a way can see, and its blind spot.
# ---------------------------------------------------------------------------
#: An actor whose properties carry ``view_cone`` (degrees, the whole cone)
#: sees only within that many degrees of its heading: the rest is its blind
#: spot. None of Fio's stock monsters has one (they see all round).
VIEW_CONE_KEY = 'view_cone'
#: Closer than this (world units) an actor knows you are there whatever way
#: it faces: it hears you breathe, feels the floor give.
VIEW_CONE_NEAR = 64.0


def angle_off(heading_radians: float, dx: float, dz: float) -> float:
    """How far (radians, 0..pi) the direction ``(dx, dz)`` is from a
    heading."""
    if dx == 0.0 and dz == 0.0:
        return 0.0
    return abs(wrap(math.atan2(dx, dz) - float(heading_radians)))


def view_cone(thing):
    """*thing*'s view cone in degrees, or None when it sees all round."""
    try:
        cone = float((getattr(thing, 'properties', None) or {}).get(VIEW_CONE_KEY) or 0.0)
    except (TypeError, ValueError):
        return None
    return cone if 0.0 < cone < 360.0 else None


def in_view_cone(thing, x: float, z: float, near: float = VIEW_CONE_NEAR) -> bool:
    """Whether the point ``(x, z)`` is where *thing* can see it: inside its
    view cone, or too close to miss. Always True for one without a cone."""
    cone = view_cone(thing)
    if cone is None:
        return True
    dx, dz = float(x) - float(thing.pos[0]), float(z) - float(thing.pos[2])
    if dx * dx + dz * dz <= near * near:
        return True
    return angle_off(heading(thing), dx, dz) <= math.radians(cone) * 0.5


def in_blind_spot(heading_radians: float, cone_degrees, dx: float, dz: float) -> bool:
    """Whether the direction ``(dx, dz)`` lies in the blind spot of a cone of
    *cone_degrees* along a heading (False for no cone)."""
    if cone_degrees is None or not 0.0 < float(cone_degrees) < 360.0:
        return False
    return angle_off(heading_radians, dx, dz) > math.radians(float(cone_degrees)) * 0.5
