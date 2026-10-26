"""
Walking and running for NPCs and creatures, paid for in stamina as the
player's sprint is.

An actor walks at Fio's fighter pace. When it wants to run -- closing on an
enemy, fleeing a fright -- it runs at :data:`RUN_SCALE` times that while its
stamina lasts, spending :data:`RUN_COST` a second. Run dry and it is *winded*:
it walks until :data:`RECOVER_AT` of its stamina is back. Walking or standing
refills :data:`REGEN` a second.

Stamina is settled lazily, when an actor's pace is asked for (:func:`pace`),
never on a tick of its own; a pause between asks counts as rest, so an actor
that stopped running never keeps paying for it. The pool is the authored
``max_stamina``, else :data:`STAMINA_BASE` plus :data:`STAMINA_PER_LEVEL` a
level.

The chosen pace is left in ``_speed_scale``, which Fio's combat AI multiplies
its step by (:mod:`engine.monster_ai`); the schedule mover reads the return
value of :func:`pace`.
"""

from __future__ import annotations

#: A run, as a multiple of walking pace (90 -> 189 units a second: well under
#: the player's 300, so a runner can still be run down).
RUN_SCALE = 2.1
#: Stamina a second: spent running, regained otherwise.
RUN_COST = 14.0
REGEN = 6.0
#: Winded at empty; running again once this share is back.
RECOVER_AT = 0.35
#: The pool when the map authors none.
STAMINA_BASE = 60.0
STAMINA_PER_LEVEL = 8.0
#: The most of one gap between asks that can have been spent running.
RUN_GAP = 0.25


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def max_stamina(props) -> float:
    authored = props.get("max_stamina")
    if authored is not None:
        return max(1.0, _float(authored, STAMINA_BASE))
    level = max(1, int(_float(props.get("creature_level", 1), 1)))
    return STAMINA_BASE + STAMINA_PER_LEVEL * level


def stamina(props, now) -> float:
    """*props*' actor's stamina at *now*, settled since it was last asked."""
    top = max_stamina(props)
    if "_stamina" not in props:
        current = top
    else:
        elapsed = max(0.0, now - _float(props.get("_stamina_at"), now))
        ran = min(elapsed, RUN_GAP) if props.get("_running") else 0.0
        current = _float(props.get("_stamina"), top) - RUN_COST * ran + REGEN * (elapsed - ran)
    current = min(top, max(0.0, current))
    props["_stamina"] = current
    props["_stamina_at"] = now
    if current <= 0.0:
        props["_winded"] = True
    elif props.get("_winded") and current >= top * RECOVER_AT:
        props.pop("_winded", None)
    return current


def pace(props, now, want_run: bool) -> float:
    """The pace (1 = a walk) *props*' actor moves at now, wanting to run or
    not; recorded in ``_speed_scale`` for Fio's combat AI."""
    current = stamina(props, now)
    running = bool(want_run) and current > 0.0 and not props.get("_winded")
    props["_running"] = running
    scale = RUN_SCALE if running else 1.0
    props["_speed_scale"] = scale
    return scale


def walk(props) -> None:
    """Back to a walk, nothing asked (an actor out of the player's sight)."""
    props.pop("_speed_scale", None)
    props.pop("_running", None)
