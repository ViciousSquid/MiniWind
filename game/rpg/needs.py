"""
Needs-driven schedules — a thin utility layer over the Radiant-AI-lite table.

:mod:`game.rpg.schedule` is a pure time-table lookup: given the hour, every NPC
of a role does exactly the same thing, forever. That is cheap and correct, but a
settlement of it is a diorama — each day is identical. This module adds the small
amount of *drive* that turns the timetable into a simulation: two persistent
needs, **fatigue** and **hunger**, that rise and fall with the passing hours and
with what the NPC is actually doing, and a bias that lets a strong enough need
bend the schedule — an exhausted farmer knocks off early to rest, a hungry worker
slips home for a meal.

The needs live as ordinary float properties (``need_fatigue`` / ``need_hunger``,
0-1) so Fio's UUID-matched serializer persists them for free and an NPC's
tiredness survives save/load like any other state. Per-NPC ``need_appetite`` /
``need_stamina`` multipliers (seeded once) keep two farmers from living identical
lives. The bias only fires at high thresholds, so most of the day still follows
the authored schedule — the deviations are the point, not the rule.

Pure Python — the runtime advances and consults it on the low-frequency decision
tick; nothing here runs per frame.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from . import schedule as sched

#: Persistent need properties (0.0 rested/fed … 1.0 exhausted/starving).
FATIGUE = "need_fatigue"
HUNGER = "need_hunger"
#: Per-NPC variation multipliers, seeded once so lives diverge.
APPETITE = "need_appetite"
STAMINA = "need_stamina"

#: Rise / fall rates, per in-game hour.
_FATIGUE_IDLE = 0.045      # simply being awake
_FATIGUE_WORK = 0.075      # a working day tires faster
_FATIGUE_SLEEP = -0.20     # a night's sleep clears it
_HUNGER_RISE = 0.06        # appetite builds through the day
_HUNGER_MEAL = -0.55       # eating at home / while idle
_HUNGER_SLEEP = 0.015      # a slow overnight trickle

#: Thresholds at which a need is strong enough to bend the schedule.
HIGH_FATIGUE = 0.9
HIGH_HUNGER = 0.85

#: States during which fatigue accrues at the working (faster) rate.
_WORK_STATES = {sched.WORKING, sched.GOING_TO_WORK, sched.PATROL}
#: States during which the NPC is taken to be eating (heading home counts —
#: they reach the table and the meal settles their hunger).
_MEAL_STATES = {sched.IDLE, sched.GOING_HOME}


def seed(npc_props: Dict, rng=None) -> None:
    """Give an NPC its one-time appetite/stamina variation (idempotent).

    Called before the first :func:`advance`. With no rng the multipliers default
    to 1.0, so behaviour stays deterministic in tests that don't seed."""
    if APPETITE not in npc_props:
        npc_props[APPETITE] = round(rng.uniform(0.8, 1.2), 3) if rng else 1.0
    if STAMINA not in npc_props:
        npc_props[STAMINA] = round(rng.uniform(0.8, 1.2), 3) if rng else 1.0
    npc_props.setdefault(FATIGUE, 0.0)
    npc_props.setdefault(HUNGER, 0.0)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _get(npc_props: Dict, key: str, default: float) -> float:
    try:
        return float(npc_props.get(key, default))
    except (TypeError, ValueError):
        return default


def advance(npc_props: Dict, hours: float, state: str) -> None:
    """Advance both needs by *hours* spent in schedule *state*.

    Fatigue falls while SLEEPING and climbs otherwise (faster at work); hunger
    falls while eating (IDLE at home), trickles up overnight, and climbs through
    the working day. All values are clamped to 0-1."""
    if hours <= 0.0:
        return
    hours = min(float(hours), 24.0)   # guard a huge gap (e.g. a loaded save)
    appetite = _get(npc_props, APPETITE, 1.0)
    stamina = _get(npc_props, STAMINA, 1.0)

    fatigue = _get(npc_props, FATIGUE, 0.0)
    if state == sched.SLEEPING:
        fatigue += _FATIGUE_SLEEP * hours
    elif state in _WORK_STATES:
        fatigue += _FATIGUE_WORK * hours * stamina
    else:
        fatigue += _FATIGUE_IDLE * hours * stamina
    npc_props[FATIGUE] = _clamp01(fatigue)

    hunger = _get(npc_props, HUNGER, 0.0)
    if state in _MEAL_STATES:
        hunger += _HUNGER_MEAL * hours
    elif state == sched.SLEEPING:
        hunger += _HUNGER_SLEEP * hours
    else:
        hunger += _HUNGER_RISE * hours * appetite
    npc_props[HUNGER] = _clamp01(hunger)


def apply(npc_props: Dict, base_state: str,
          hour: Optional[float] = None) -> Tuple[str, str]:
    """Return ``(state, reason)`` — the schedule state a need may have overridden.

    A high enough need bends the plan: an exhausted NPC breaks off for a nap
    (routed home) and stays asleep until rested, then resumes the schedule; a
    hungry one slips home for a meal, its hunger settling as it reaches the
    table. When no need is pressing, the authored ``base_state`` is returned with
    an empty reason. Already-sleeping NPCs are left to sleep.

    The caller routes any overridden state's destination home, and re-evaluates
    the *authored* base state each tick, so an override lapses on its own the
    moment the need it answered falls back below threshold."""
    if base_state == sched.SLEEPING:
        return base_state, ""
    fatigue = _get(npc_props, FATIGUE, 0.0)
    hunger = _get(npc_props, HUNGER, 0.0)

    if fatigue >= HIGH_FATIGUE:
        # A nap at home; fatigue only recovers while SLEEPING, so this holds
        # until they are rested and then releases back to the schedule.
        return sched.SLEEPING, "exhausted"
    if hunger >= HIGH_HUNGER and base_state in (sched.WORKING, sched.WANDER):
        return sched.GOING_HOME, "hungry"           # a meal break at home
    return base_state, ""
