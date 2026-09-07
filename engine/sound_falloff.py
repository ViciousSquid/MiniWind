"""
How loud a speaker is from where the listener is standing.

A Speaker entity carries a ``radius`` — the range over which it can be heard —
but nothing used it: every sound played at its authored volume no matter where
the player was, so a fountain across the village was as loud as one underfoot.

The rule here is a plain linear fade: full volume at the speaker, silent at the
edge of its radius, straight line in between. Not physically correct (real sound
falls off with the inverse square), but that is the point — a linear fade is
predictable to author against, because the radius drawn in the editor is exactly
where the sound stops.

Kept as a pure function, free of pygame and of the engine, so the mixing code
stays a thin wrapper and the rule itself can be checked without an audio device.
"""

from __future__ import annotations

import math

#: Below this the channel is silent; there is no point spending a mixer slot on
#: something nobody can hear.
SILENCE_EPSILON = 0.002


def distance_volume(base_volume, distance, radius, is_global=False):
    """The volume a speaker should play at, given how far away the listener is.

    *base_volume* is the speaker's authored volume (0..1), *distance* the world
    distance from listener to speaker, *radius* its audible range. A *is_global*
    speaker — or one with no meaningful radius — ignores distance entirely and
    plays everywhere at its authored volume, which is what a music bed or a
    narration cue wants.

    Returns 0.0 at and beyond the radius, so a speaker out of range costs
    nothing to leave running.
    """
    try:
        base = float(base_volume)
    except (TypeError, ValueError):
        base = 1.0
    base = max(0.0, min(1.0, base))
    if is_global:
        return base

    try:
        radius = float(radius)
        distance = float(distance)
    except (TypeError, ValueError):
        return base
    if radius <= 0.0:
        # No range authored: treat it as unbounded rather than inaudible, which
        # is the reading that keeps an under-configured speaker working.
        return base
    if distance <= 0.0:
        return base
    if distance >= radius:
        return 0.0
    return base * (1.0 - distance / radius)


def distance_between(a, b):
    """World distance between two ``[x, y, z]`` positions, 0.0 if either is missing."""
    if not a or not b:
        return 0.0
    try:
        return math.dist((float(a[0]), float(a[1]), float(a[2])),
                         (float(b[0]), float(b[1]), float(b[2])))
    except (TypeError, ValueError, IndexError):
        return 0.0


def volume_for(listener_pos, speaker):
    """Volume for one live speaker record: ``{pos, volume, radius, global}``."""
    return distance_volume(speaker.get("volume", 1.0),
                           distance_between(listener_pos, speaker.get("pos")),
                           speaker.get("radius", 0.0),
                           bool(speaker.get("global", False)))
