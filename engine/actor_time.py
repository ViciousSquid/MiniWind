"""Actors whose own clock runs faster or slower than the world's.

The logic thread and the monster AI advance the world by fixed ticks, as many
a real second as ``LogicThread.time_scale`` asks for. An actor given a *time
rate* here takes ``rate`` times each tick's delta for itself -- its movement,
its turning, its attack timers and animations -- while the rest of the world
keeps the plain tick. A rate of ``1 / time_scale`` is an actor the slowed
world does not slow: it moves at its normal speed in real time, and so twice
as fast as everyone else under a half-speed world.

Rates are held on the logic thread as ``actor_time_rates`` (``id(entity)`` ->
``(entity, rate)``); the dictionary is empty, and asking costs one truth test,
whenever nobody's clock is altered. The player's tick
(:meth:`engine.logic_player.LogicPlayer.update_primary`) and the monster AI's
(:meth:`engine.monster_ai.MonsterAI.update`) consult it; a game consults
:func:`rate` for the clocks it keeps itself.
"""

from __future__ import annotations

#: The fastest and slowest an actor's clock may run against the world's.
MIN_RATE = 0.05
MAX_RATE = 20.0


def rates(logic) -> dict:
    """The altered clocks on *logic* (``id(entity)`` -> ``(entity, rate)``);
    empty when there are none."""
    table = getattr(logic, "actor_time_rates", None)
    if table is None:
        table = {}
        try:
            logic.actor_time_rates = table
        except Exception:
            pass
    return table


def set_rate(logic, entity, rate) -> None:
    """Run *entity*'s clock at *rate* times the world's (1: as the world)."""
    if entity is None:
        return
    table = rates(logic)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        rate = 1.0
    if abs(rate - 1.0) < 1e-9:
        table.pop(id(entity), None)
        return
    table[id(entity)] = (entity, max(MIN_RATE, min(MAX_RATE, rate)))


def clear(logic, entity=None) -> None:
    """Put *entity*'s clock (or everyone's) back in step with the world."""
    table = getattr(logic, "actor_time_rates", None)
    if not table:
        return
    if entity is None:
        table.clear()
    else:
        table.pop(id(entity), None)


def rate(logic, entity) -> float:
    """How fast *entity*'s clock runs against the world's (1.0 unaltered)."""
    table = getattr(logic, "actor_time_rates", None)
    if not table or entity is None:
        return 1.0
    entry = table.get(id(entity))
    if entry is None or entry[0] is not entity:
        return 1.0
    return entry[1]


def row_deltas(logic, entities, delta, row_delta=None, sit_out=None):
    """Per-row deltas for a batch of *entities* ticked together.

    *row_delta* (one per row, or None for *delta* everywhere) and *sit_out*
    are what the caller already has; they come back unchanged when no clock
    is altered. Otherwise each altered row's delta is multiplied by its rate
    and an all-False *sit_out* is supplied where there was none."""
    table = getattr(logic, "actor_time_rates", None)
    if not table or not entities:
        return row_delta, sit_out
    import numpy as np
    scale = None
    for i, entity in enumerate(entities):
        entry = table.get(id(entity))
        if entry is not None and entry[0] is entity:
            if scale is None:
                scale = np.ones(len(entities), dtype=np.float64)
            scale[i] = entry[1]
    if scale is None:
        return row_delta, sit_out
    base = (np.full(len(entities), float(delta), dtype=np.float64) if row_delta is None
            else np.asarray(row_delta, dtype=np.float64))
    if sit_out is None:
        sit_out = np.zeros(len(entities), dtype=bool)
    return base * scale, sit_out
