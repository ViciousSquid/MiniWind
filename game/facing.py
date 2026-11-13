"""
Actor heading, MiniWind's way: every actor is a head that turns.

An actor has one heading, its ``angle`` (degrees, 0 = +Z, 90 = +X), owned by
:mod:`engine.monster_facing`: that module is the only writer, and every turn
tells the change journal (the cheap FACING record), so the head billboard turns
without the actor's row being resolved again. Everything that reads a heading
reads :func:`heading` (radians, forward ``(sin a, 0, cos a)``): the head
billboard, the overhead weapon, a shield's facing, the hand glows, the 2D map.

MiniWind's actors swing round rather than snap: :func:`install` sets the
engine's turn rate to :data:`ACTOR_TURN_RATE`, so a turn given the frame's
*delta* is eased -- the combat AI's turns as well as the game's.
"""

from __future__ import annotations

import math

from engine import monster_facing

#: How fast (radians/second) an actor swings around to a new heading. About a
#: half-turn every quarter second -- quick enough to look responsive in a
#: fight, slow enough to read as a turn rather than a snap.
ACTOR_TURN_RATE = 8.0

heading = monster_facing.heading
set_heading = monster_facing.set_heading
wrap_angle = monster_facing.wrap


def install() -> None:
    """Make every eased turn, the engine's included, use MiniWind's rate."""
    monster_facing.TURN_RATE = ACTOR_TURN_RATE


def heading_from(dx: float, dz: float) -> float:
    """The heading (radians) that looks along the world direction ``(dx, _, dz)``."""
    return math.atan2(dx, dz)


def face_heading(actor, dx: float, dz: float, delta=None,
                 turn_rate: float = ACTOR_TURN_RATE) -> float:
    """Turn *actor* toward ``(dx, _, dz)``, eased by *delta* if given; returns
    its heading (radians). A near-zero direction keeps the current heading."""
    return monster_facing.turn_toward(actor, dx, dz, delta, turn_rate)
