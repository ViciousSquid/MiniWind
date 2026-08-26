"""
Gibbing rules — when a lethal hit is violent enough to blow a monster/NPC apart.

A *gib* is a death from a very large hit: instead of a clean corpse the body
shows the universal gore sprite (``assets/sprites/monsters/<type>/dead.png``,
which exists for both the ``human`` and ``flying`` monster types). This module
holds only the pure decision — "was this overkill?" — and the flag it sets, so
every damage path (player gunfire, monster infighting, MiniWind melee/spells)
shares one consistent rule and the renderer just reacts to the ``gibbed`` flag.

Deliberately dependency-free (no Qt/GL, no game imports) so both the engine and
the engine-agnostic RPG core can import it, and it stays headless-testable.
"""

from __future__ import annotations

#: A killing blow gibs when its damage is at least this multiple of the
#: victim's maximum health — i.e. a genuinely oversized hit, not a normal kill.
GIB_DAMAGE_FRACTION = 1.5
#: ...and is at least this many points, so a big hit is always needed even for
#: very low-health enemies (a stray point of chip damage never gibs).
GIB_MIN_DAMAGE = 40


def max_health(props) -> int:
    """Best-effort maximum health for a monster/NPC from its properties.

    Prefers an explicit ``max_health`` (recorded when the entity is created),
    falling back to current ``health``. Always at least 1 so the fraction test
    can't divide the world by zero."""
    for key in ("max_health", "health"):
        try:
            v = int(props.get(key) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v
    return 1


def should_gib(props, damage, new_health) -> bool:
    """True when a lethal hit was violent enough to gib the victim.

    Requires the hit to be fatal (``new_health <= 0``) AND to have dealt both an
    absolute minimum and at least :data:`GIB_DAMAGE_FRACTION`× the victim's max
    health in one blow."""
    try:
        dmg = float(damage)
        nh = float(new_health)
    except (TypeError, ValueError):
        return False
    if nh > 0:
        return False
    return dmg >= GIB_MIN_DAMAGE and dmg >= GIB_DAMAGE_FRACTION * max_health(props)


def mark_gibbed(props, damage, new_health) -> bool:
    """Flag *props* as gibbed if the killing hit qualifies. Returns whether it did.

    Sets ``gibbed = True`` on overkill so the sprite resolver switches the corpse
    to the universal gore sprite. Never clears the flag (a body stays gibbed)."""
    if isinstance(props, dict) and should_gib(props, damage, new_health):
        props["gibbed"] = True
        return True
    return False
