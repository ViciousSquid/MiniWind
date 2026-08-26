"""
Extremely simple Radiant-AI-style schedules (§4).

An NPC's schedule is a small, explicit list of time-ordered entries:

    [
        {"hour": 6,  "state": "IDLE",          "location": "home"},
        {"hour": 8,  "state": "GOING_TO_WORK", "location": "work"},
        {"hour": 9,  "state": "WORKING",       "location": "work"},
        {"hour": 17, "state": "GOING_HOME",    "location": "home"},
        {"hour": 22, "state": "SLEEPING",      "location": "home"},
    ]

Given the current game hour, :func:`evaluate` returns the entry in effect — the
last one whose ``hour`` has passed, wrapping around midnight. That is the whole
"planner": no per-frame autonomous decision-making, just a table lookup on the
low-frequency decision tick. Combat is layered on top as an override in
``runtime.py`` (schedule → enemy detected → combat → back to schedule), so the
schedule itself never has to know about it.

The ``location`` is a *key* ("home" / "work" / "market"), resolved to a world
position by the NPC's own ``home`` / ``work_location`` properties (or a named
entity) at movement time — so schedules stay portable data.

Pure Python — safe everywhere.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Schedule states (§4). COMBAT is never authored in a schedule; it is applied by
# the runtime as a temporary override and removed when combat ends.
SLEEPING = "SLEEPING"
GOING_TO_WORK = "GOING_TO_WORK"
WORKING = "WORKING"
GOING_HOME = "GOING_HOME"
IDLE = "IDLE"
COMBAT = "COMBAT"
#: Runtime-only overrides (never authored in a schedule): FLEE is applied to a
#: non-combatant NPC when a hostile is near; WANDER is a brief local stroll an
#: idle NPC takes on its own; PATROL is a guard walking its authored circuit of
#: patrol markers while on duty. All three are removed when the reason passes and
#: the underlying schedule resumes.
FLEE = "FLEE"
ALERT = "ALERT"
RALLY = "RALLY"
WANDER = "WANDER"
PATROL = "PATROL"

#: Ready-made schedules keyed by ``npc_role`` (§4), loaded from editable content
#: (``game/data/schedules.json`` + mods). A map can also author a bespoke
#: ``schedule`` property; these are just sensible defaults so a freshly-placed
#: NPC already "lives". The schedule *planner* (:func:`evaluate`) is code; the
#: schedules themselves are data.
def _load_schedules() -> Dict[str, List[Dict]]:
    from game import data
    return dict(data.load("schedules") or {})


ROLE_SCHEDULES: Dict[str, List[Dict]] = _load_schedules()


def schedule_for(role: str) -> List[Dict]:
    """Return a *copy* of the default schedule for an ``npc_role`` (may be [])."""
    return [dict(e) for e in ROLE_SCHEDULES.get(str(role or "").strip().lower(), [])]


def evaluate(schedule: List[Dict], game_hour: float) -> Optional[Dict]:
    """Return the schedule entry in effect at *game_hour*, or None if empty.

    The active entry is the one with the greatest ``hour`` that is <= the
    current hour; before the first entry of the day it wraps to the *last*
    entry (i.e. the overnight activity carries over past midnight).
    """
    if not schedule:
        return None
    entries = sorted(schedule, key=lambda e: float(e.get("hour", 0)))
    active = entries[-1]  # wrap: overnight entry until the first morning entry
    for entry in entries:
        if float(entry.get("hour", 0)) <= game_hour:
            active = entry
        else:
            break
    return active
