"""
Actor heading — one convention, shared by everything that turns an actor.

An actor's heading lives in the transient ``_facing`` property, in radians, in
the engine's forward convention: forward is ``(sin a, 0, cos a)``, so a heading
is ``atan2(dx, dz)`` — the same derivation the player's angle uses. The leading
underscore keeps it out of saved maps.

Everything that reads a heading reads ``_facing``: the 3D head billboard
(:meth:`engine.renderer_core.Renderer.draw_sprites`), the overhead ground sprite,
the actor's equipped-weapon overlay, and the 2D map. So everything that *moves*
an actor has to write it here, or that actor slides around the world without
ever turning. Two systems move actors — the core combat AI
(:mod:`engine.monster_ai`) and the RPG's schedule/needs runtime
(:mod:`game.runtime`) — and this module is the single place both go through.

Headings are eased rather than snapped: given a *delta*, an actor swings toward
its new heading at :data:`ACTOR_TURN_RATE` instead of flipping between frames,
which is the difference between a character turning to walk somewhere and one
that teleports its head around.
"""

from __future__ import annotations

import math

#: Property key holding an actor's heading, in radians.
FACING_KEY = '_facing'

#: How fast (radians/second) an actor swings around to a new heading. About a
#: half-turn every quarter second — quick enough to look responsive in a fight,
#: slow enough to read as a turn rather than a snap.
ACTOR_TURN_RATE = 8.0

_TWO_PI = math.pi * 2.0


def heading_from(dx: float, dz: float) -> float:
    """The heading (radians) that looks along the world direction ``(dx, _, dz)``."""
    return math.atan2(dx, dz)


def wrap_angle(angle: float) -> float:
    """*angle* folded into (-pi, pi]."""
    return (float(angle) + math.pi) % _TWO_PI - math.pi


def face_heading(properties, dx: float, dz: float, delta=None,
                 turn_rate: float = ACTOR_TURN_RATE):
    """Turn the actor owning *properties* toward the direction ``(dx, _, dz)``.

    Writes the eased result to ``properties['_facing']`` and returns it. With no
    *delta* (or no previous heading to ease from) the heading is set outright.
    A near-zero direction is ignored so a stationary actor holds the way it was
    already looking instead of snapping to north.
    """
    dx = float(dx)
    dz = float(dz)
    if dx * dx + dz * dz <= 1e-9:
        return properties.get(FACING_KEY)

    target = wrap_angle(heading_from(dx, dz))
    current = properties.get(FACING_KEY)
    if current is None or delta is None or turn_rate <= 0.0:
        properties[FACING_KEY] = target
        return target

    diff = wrap_angle(target - float(current))
    max_step = float(turn_rate) * float(delta)
    if abs(diff) <= max_step:
        new = target
    else:
        new = wrap_angle(float(current) + math.copysign(max_step, diff))
    properties[FACING_KEY] = new
    return new


def get_heading(properties) -> float:
    """An actor's current heading, falling back to a design-time ``angle``."""
    value = properties.get(FACING_KEY)
    if value is None:
        value = properties.get('angle', 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
