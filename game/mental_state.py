"""
A read-only *mental-state snapshot* of a monster/NPC, for the in-game debug
inspector (the click-to-inspect console command and its floating popup).

This module is deliberately pure Python and engine-free: it reads an entity's
public ``properties`` dict (plus, optionally, the engine's per-monster AI state
and the live MiniWind session) and returns a plain, display-ready structure. The
Qt popup in :mod:`engine.floating_windows` renders it; keeping the derivation
here means it can be unit-tested headlessly and reused anywhere.

The snapshot is a dict::

    {
      "title":    "Guard  (guards)",
      "subtitle": "guard · defensive · alive",
      "sections": [ (heading, [(label, value), ...]), ... ],
      "tasks":    [ (priority:int, label:str, active:bool), ... ],  # highest first
    }

``tasks`` is the "internal task list with priorities": a synthesised, ranked
view of what the actor is trying to do right now — combat/threat reactions
outrank the daily schedule, which outranks idle wandering. The single active
task is flagged so the UI can highlight it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Priority bands for the synthesised task list (higher = more urgent).
PRI_COMBAT = 100
PRI_FLEE = 90
PRI_RALLY = 80
PRI_ALERT = 70
PRI_INVESTIGATE = 60
PRI_SCHEDULE = 40
PRI_WANDER = 20
PRI_IDLE = 10

# Human blurbs for the schedule/runtime states an NPC can be in.
_STATE_BLURB = {
    "IDLE": "Idle at home",
    "GOING_TO_WORK": "Heading to work",
    "WORKING": "Working",
    "GOING_HOME": "Heading home",
    "SLEEPING": "Sleeping",
    "COMBAT": "In combat",
    "FLEE": "Fleeing to safety",
    "ALERT": "On alert",
    "RALLY": "Rallying against a threat",
    "WANDER": "Wandering",
    "PATROL": "Patrolling",
}


def _get(props: Dict[str, Any], *keys, default=None):
    """First present value among *keys* in a properties dict."""
    for k in keys:
        if k in props and props[k] not in (None, ""):
            return props[k]
    return default


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def snapshot(thing, monster_state: Optional[dict] = None,
             session: Optional[object] = None) -> Dict[str, Any]:
    """Build a display-ready mental-state snapshot for *thing*.

    ``monster_state`` is the engine's ``MonsterAI.monster_states[id]`` dict for
    this actor (optional). ``session`` is the live ``MiniwindSession`` (optional)
    — when given, its confidence model enriches a civilian's threat read. Every
    lookup is defensive so a half-initialised or non-MiniWind entity still
    produces a sensible snapshot.
    """
    props = getattr(thing, "properties", None)
    if not isinstance(props, dict):
        props = {}
    monster_state = monster_state or {}

    role = str(_get(props, "npc_role", "creature_role", default="?"))
    name = str(_get(props, "display_name", "name", default=role.title()))
    faction = str(_get(props, "faction", "team", default="?"))
    aggression = str(_get(props, "aggression", default="passive"))
    dead = bool(props.get("dead", False))
    life = "dead" if dead else "alive"

    title = f"{name}  ({faction})"
    subtitle = f"{role} · {aggression} · {life}"

    # ---- Identity ----------------------------------------------------
    identity = [
        ("Name", name),
        ("Role", role),
        ("Faction", faction),
        ("Aggression", aggression),
        ("Combatant", _fmt(bool(props.get("combatant", aggression in ("defensive", "hostile"))))),
    ]

    # ---- Vitals / combat --------------------------------------------
    vitals = [
        ("Health", _fmt(_get(props, "health", default="?"))),
        ("Courage", _fmt(_get(props, "courage", default="?"))),
        ("Attack style", _fmt(_get(props, "attack_style", default="?"))),
        ("Sight range", _fmt(_get(props, "sight_range", "sight", default="?"))),
    ]

    # ---- Live AI flags ----------------------------------------------
    target = _get(props, "target_name", "_aggro_target", default=None)
    in_sight = bool(monster_state.get("in_sight", props.get("_in_sight", False)))
    investigating = monster_state.get("investigating_sound")
    ai = [
        ("Awake", _fmt(bool(props.get("awake", not props.get("triggered", False))))),
        ("Parked (triggered)", _fmt(bool(props.get("triggered", False)))),
        ("Player in sight", _fmt(in_sight)),
        ("Current target", _fmt(target) if target else "—"),
    ]

    sched_state = str(_get(props, "sched_state", default="")).upper()
    if sched_state:
        ai.insert(0, ("State", f"{sched_state} — {_STATE_BLURB.get(sched_state, sched_state)}"))

    # Optional confidence read from the live MiniWind session.
    confidence = None
    if session is not None and not dead:
        try:
            from . import runtime as _rt
            sight = getattr(_rt, "FLEE_SIGHT", 480.0)
        except Exception:
            sight = 480.0
        try:
            threat = session._nearest_hostile(thing, sight)
        except Exception:
            threat = None
        if threat is not None:
            try:
                confidence = session._civilian_confidence(thing, threat)
            except Exception:
                confidence = None
            if confidence is not None:
                ai.append(("Confidence vs threat", _fmt(confidence)))

    # ---- Task list (prioritised) ------------------------------------
    tasks = _build_tasks(props, sched_state, target, investigating, confidence)

    sections: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("Identity", identity),
        ("Vitals & Combat", vitals),
        ("AI State", ai),
    ]

    # ---- Anchors (home/work) for social NPCs ------------------------
    home = props.get("home")
    work = props.get("work_location")
    if home or work:
        anchors = []
        if home is not None:
            anchors.append(("Home", _fmt(home)))
        if work:
            anchors.append(("Workplace", _fmt(work)))
        sections.append(("Anchors", anchors))

    return {
        "title": title,
        "subtitle": subtitle,
        "sections": sections,
        "tasks": tasks,
    }


def _build_tasks(props, sched_state, target, investigating, confidence):
    """Synthesise a ranked task list from the actor's current situation.

    Returns ``[(priority, label, active), …]`` sorted highest-priority first.
    Exactly the top applicable reaction is marked ``active``; the rest are the
    lower-priority intents that would take over if the situation changed.
    """
    aggression = str(props.get("aggression", "passive"))
    combatant = bool(props.get("combatant", aggression in ("defensive", "hostile")))
    dead = bool(props.get("dead", False))
    tasks: List[Tuple[int, str, bool]] = []

    if dead:
        return [(0, "Dead — no active tasks", True)]

    # Combat / threat reactions (mutually exclusive top of the stack).
    if target and combatant:
        tasks.append((PRI_COMBAT, f"Attack {target}", False))
    if props.get("_flee") or sched_state == "FLEE":
        tasks.append((PRI_FLEE, "Flee to safety", False))
    if props.get("_rally") or sched_state == "RALLY":
        tasks.append((PRI_RALLY, "Rally with nearby friendlies", False))
    if sched_state == "ALERT":
        tasks.append((PRI_ALERT, "Hold and stay alert", False))
    if investigating:
        tasks.append((PRI_INVESTIGATE, "Investigate a noise", False))

    # Daily schedule (the standing job when nothing urgent is happening).
    if sched_state and sched_state not in ("FLEE", "RALLY", "ALERT"):
        loc = props.get("work_location") or "home"
        blurb = _STATE_BLURB.get(sched_state, sched_state.title())
        if sched_state in ("GOING_TO_WORK", "WORKING"):
            blurb = f"{blurb} ({loc})"
        tasks.append((PRI_SCHEDULE, f"Schedule: {blurb}", False))

    # Fallback intents.
    if props.get("autonomy", False) and props.get("wander_radius", 0):
        tasks.append((PRI_WANDER, "Wander locally when idle", False))
    if not tasks:
        tasks.append((PRI_IDLE, "Idle", False))

    tasks.sort(key=lambda t: t[0], reverse=True)
    # Flag the single highest-priority task as the active one.
    top_pri = tasks[0][0]
    tasks = [(p, label, p == top_pri) for (p, label, _a) in tasks]
    return tasks
