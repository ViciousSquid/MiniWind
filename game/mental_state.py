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
#: The reactive simulation's errands: acting on knowledge rather than sight.
#: They outrank the daily schedule (a person with a reason does not go to work)
#: but yield to anything physically happening in front of the actor.
PRI_CONFRONT = 55
PRI_REPORT = 50
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
    "REPORT": "Going to tell the watch",
    "CONFRONT": "Going to confront someone",
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


#: A need at or over this level shows in the actor's mood.
MOOD_NEED_LEVEL = 0.7


def mood(props, target=None, confidence=None) -> Tuple[str, str]:
    """``(mood, why)``: how an actor feels, read from what it is doing.

    Frightened while fleeing (or out-matched by a threat), angry while it
    has a target, otherwise hungry or tired when a need is high, and calm
    when nothing presses on it.
    """
    if props.get("dead"):
        return "dead", ""
    state = str(_get(props, "sched_state", default="")).upper()
    if props.get("_flee") or state == "FLEE":
        return "frightened", "fleeing to safety"
    if confidence is not None and isinstance(confidence, (int, float)) and confidence < 0.5:
        return "uneasy", "a threat is near"
    if target or state in ("ATTACK", "CHASE", "ALERT"):
        return "angry", f"after {target}" if target else "on alert"
    hunger = float(_get(props, "need_hunger", default=0.0) or 0.0)
    fatigue = float(_get(props, "need_fatigue", default=0.0) or 0.0)
    if hunger >= MOOD_NEED_LEVEL and hunger >= fatigue:
        return "hungry", f"hunger {hunger:.2f}"
    if fatigue >= MOOD_NEED_LEVEL:
        return "tired", f"fatigue {fatigue:.2f}"
    return "calm", ""


def snapshot(thing, monster_state: Optional[dict] = None,
             session: Optional[object] = None,
             target_name: Optional[str] = None) -> Dict[str, Any]:
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
        ("Handedness", str(_get(props, "handed", default="right"))),
    ]

    # ---- Vitals / combat --------------------------------------------
    vitals = [
        ("Health", _fmt(_get(props, "health", default="?"))),
        ("Courage", _fmt(_get(props, "courage", default="?"))),
        ("Attack style", _fmt(_get(props, "attack_style", default="?"))),
        ("Sight range", _fmt(_get(props, "sight_range", "sight", default="?"))),
    ]

    # ---- Live AI flags ----------------------------------------------
    target = target_name or _get(props, "target_name", default=None)
    if not target and props.get("_aggro_target") is not None:
        target = "another actor"  # the UI can pass its resolved name
    if (not target and aggression == "hostile" and props.get("awake")
            and not props.get("triggered")):
        target = "player"
    in_sight = bool(monster_state.get("in_sight", props.get("_in_sight", False)))
    investigating = monster_state.get("investigating_sound")
    sched_state = str(_get(props, "sched_state", default="")).upper()
    if dead:
        reaction = "dead"
    elif props.get("_flee") or sched_state == "FLEE":
        reaction = "FLIGHT"
    elif (sched_state in ("COMBAT", "ATTACK", "CHASE")
          or (aggression == "hostile" and not props.get("triggered", False))):
        reaction = "FIGHT"
    elif sched_state == "RALLY":
        reaction = "RALLY"
    elif sched_state == "ALERT":
        reaction = "ALERT"
    else:
        reaction = "none"

    ai = [
        ("Fight or flight", reaction),
        ("Aggro", str(target) if reaction == "FIGHT" and target else "none"),
        ("Awake", _fmt(bool(props.get("awake", not props.get("triggered", False))))),
        ("Parked (triggered)", _fmt(bool(props.get("triggered", False)))),
        ("Player in sight", _fmt(in_sight)),
        ("Current target", _fmt(target) if target else "—"),
    ]

    if sched_state:
        ai.insert(0, ("State", f"{sched_state} — {_STATE_BLURB.get(sched_state, sched_state)}"))
    need_reason = props.get("_need_reason")
    if need_reason:
        ai.append(("Need driving them", str(need_reason)))

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

    equipped = props.get("_active_weapon") or props.get("equipped_weapon")
    if equipped:
        ai.append(("Weapon in hand", str(equipped)))
    if props.get("_pursuit_range") and reaction == "FIGHT":
        ai.append(("Pursuit limit", f"{float(props['_pursuit_range']):.0f} units"))

    # ---- Mood -------------------------------------------------------------
    feeling, feeling_why = mood(props, target, confidence)
    ai.insert(0, ("Mood", f"{feeling} — {feeling_why}" if feeling_why else feeling))
    thought = props.get("_sim_reason")
    if not thought and session is not None:
        try:
            intent = session.director.top_intent(thing)
            if intent is not None:
                thought = f"Considering {intent.label}: {intent.reason}"
        except (AttributeError, TypeError):
            pass
    if thought:
        ai.append(("Thought", str(thought)))

    # ---- Task list (prioritised) ------------------------------------
    tasks = _build_tasks(props, sched_state, target, investigating, confidence)

    # ---- Needs (persistent drives biasing the schedule) --------------------
    if "need_fatigue" in props or "need_hunger" in props:
        vitals.append(("Fatigue", _fmt(_get(props, "need_fatigue", default=0.0))))
        vitals.append(("Hunger", _fmt(_get(props, "need_hunger", default=0.0))))

    sections: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("Identity", identity),
        ("Vitals & Combat", vitals),
        ("AI State", ai),
    ]
    if "need_fatigue" in props or "need_hunger" in props:
        sections.append(("Needs", [
            ("Hunger", _fmt(_get(props, "need_hunger", default=0.0))),
            ("Fatigue", _fmt(_get(props, "need_fatigue", default=0.0)))]))

    # ---- Why (the reactive simulation's own explanation) --------------------
    # The single most useful line in the inspector: what this actor knows that
    # is driving it, in the words the decision itself produced. Written onto the
    # entity by MiniwindSession._apply_sim_intent, so it can never drift out of
    # step with the behaviour it explains.
    reason = props.get("_sim_reason")
    if reason:
        why = [("Wants to", str(props.get("_sim_intent", "?")).title()),
               ("Because", str(reason))]
        if props.get("_sim_target"):
            why.append(("About", str(props["_sim_target"])))
        sections.insert(0, ("Why", why))
        ai.insert(0, ("Driving intent",
                      f"{props.get('_sim_intent', '?')} — {reason}"))

    # ---- Knowledge (what this actor believes, and how sure) ----------------
    if session is not None:
        sections.extend(_knowledge_sections(thing, session))

    # ---- Player standing (this NPC's remembered feelings toward the player) --
    if session is not None and not dead:
        try:
            from .rpg import disposition as _disp
            char = getattr(getattr(session, "game", None), "character", None)
            store = getattr(session, "store", None)
            if char is not None and store is not None:
                s = _disp.summary(char, props, store)
                standing = [
                    ("Disposition", f"{s['disposition']} ({s['tier']})"),
                    ("Wronged by player", _fmt(s["wronged"])),
                    ("Befriended player", _fmt(s["befriended"])),
                ]
                if s["log"]:
                    standing.append(("Remembers", "; ".join(s["log"][-3:])))
                sections.append(("Player Standing", standing))
        except Exception:
            pass

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


def _knowledge_sections(thing, session):
    """The 'what does this person know?' and 'what do they intend?' sections.

    Reads the live director rather than the properties, so a designer can watch
    a rumour arrive and the reaction change in the same panel."""
    out = []
    director = getattr(session, "director", None)
    if director is None:
        return out
    try:
        lines = director.knowledge_lines(thing, limit=8)
        if lines:
            out.append(("Knowledge",
                        [(f"{i + 1}.", line) for i, line in enumerate(lines)]))
    except Exception:
        pass
    try:
        intents = director.intents(thing)
        if intents:
            out.append(("Intents (ranked)",
                        [(f"{i.priority}", f"{i.label} — {i.reason}")
                         for i in intents[:6]]))
    except Exception:
        pass
    return out


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
    if target and (combatant or (aggression == "hostile" and not props.get("triggered", False))):
        tasks.append((PRI_COMBAT, f"Attack {target}", False))
    if props.get("_flee") or sched_state == "FLEE":
        tasks.append((PRI_FLEE, "Flee to safety", False))
    if props.get("_rally") or sched_state == "RALLY":
        tasks.append((PRI_RALLY, "Rally with nearby friendlies", False))
    if sched_state == "ALERT":
        tasks.append((PRI_ALERT, "Hold and stay alert", False))
    # Simulation-driven errands: acting on something known rather than seen.
    if sched_state == "REPORT":
        tasks.append((PRI_REPORT, "Report what they know to the watch", False))
    if sched_state == "CONFRONT":
        tasks.append((PRI_CONFRONT,
                      f"Confront {props.get('_sim_target', 'someone')}", False))
    if investigating:
        tasks.append((PRI_INVESTIGATE, "Investigate a noise", False))

    # Daily schedule (the standing job when nothing urgent is happening).
    if sched_state and sched_state not in ("FLEE", "RALLY", "ALERT",
                                           "REPORT", "CONFRONT"):
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


# ---------------------------------------------------------------------------
# Thoughts: what an actor is thinking, in its own words, for the overhead HUD
# ---------------------------------------------------------------------------
#: First-person lines per situation. One is picked per actor and situation
#: (stable, not random) so an NPC does not change its mind about how to put it.
_THOUGHTS = {
    "flee": ("Too dangerous — I'm getting out of here!", "Run! Run!",
             "I'm no fighter. I need to hide."),
    "rally": ("There are enough of us — we can take them!",
              "Together! Drive them off!"),
    "alert": ("Something's wrong... I'll keep my distance.",
              "Easy now. Watch them closely."),
    "subdue": ("Enough brawling — break it up!",),
    "combat": ("{target} — you'll regret this!", "Have at you, {target}!",
               "{target}! To arms!"),
    "hunt": ("Fresh meat...", "There — prey!", "Easy pickings."),
    "pursue": ("You won't escape the law!", "After them!"),
    "search": ("Where did they go?", "They can't have gone far..."),
    "arrest": ("Stop right there, criminal!",),
    "escort": ("Come quietly now.",),
    "follow": ("Right behind you.", "Lead on."),
    "exhausted": ("So tired... I need to lie down.", "Can barely keep my eyes open."),
    "hungry": ("My stomach's growling — time to eat.", "Can't work on an empty belly."),
    "GOING_TO_WORK": ("Time to get to work.", "Another day, another coin."),
    "WORKING": ("Back to it.", "Busy, busy."),
    "GOING_HOME": ("That's enough for today.", "Home for the night."),
    "SLEEPING": ("Zzz...",),
    "PATROL": ("All quiet. Keep walking.", "Eyes open, stay sharp."),
}

#: Situations urgent enough to think aloud the moment an actor is first seen,
#: rather than waiting for its state to change.
URGENT_THOUGHTS = frozenset(("flee", "rally", "alert", "subdue", "combat", "hunt",
                             "pursue", "search", "arrest", "intent"))


def _pick(options, *salt) -> str:
    import zlib
    return options[zlib.crc32("|".join(str(s) for s in salt).encode()) % len(options)]


def _plain_reason(reason: str) -> str:
    """A simulation reason as a thought: its working - "(courage 0.42)" - is
    for the inspector, not the thought bubble."""
    reason = str(reason).strip()
    if reason.endswith(")") and " (" in reason:
        reason = reason[:reason.rindex(" (")]
    return reason


def thought(props, target_name: Optional[str] = None) -> Tuple[str, str]:
    """``(situation, text)``: what an actor is thinking right now.

    *situation* is a stable key that changes only when the actor's reason for
    what it is doing changes — the HUD shows a fresh thought on each change.
    *text* is the first-person line to show ("Somebody must tell the watch
    what Rufus did."), empty when there is nothing worth saying (idling,
    wandering). Pure: reads only the actor's properties.
    """
    if not isinstance(props, dict) or props.get("dead"):
        return "", ""
    name = str(_get(props, "display_name", "name", default=""))
    state = str(_get(props, "sched_state", default="")).upper()
    target = target_name or "you"
    aggression = str(props.get("aggression", "passive"))

    def line(key, **fmt):
        return key, _pick(_THOUGHTS[key], name, key).format(**fmt)

    if props.get("_flee") or state == "FLEE":
        reason = props.get("_sim_reason") if props.get("_sim_intent") == "FLEE" else ""
        if reason:
            return "flee:" + str(reason), _plain_reason(reason) + "."
        return line("flee")
    if props.get("_subduing"):
        return line("subdue")
    if state == "RALLY":
        return line("rally")
    if state == "ALERT":
        return line("alert")
    if state in ("PURSUE", "ARREST_APPROACH"):
        return line("arrest" if state == "ARREST_APPROACH" else "pursue")
    if state == "SEARCH":
        return line("search")
    if state == "ESCORT":
        return line("escort")
    # Something the actor knows is driving it: say it in the decision's words.
    intent = str(props.get("_sim_intent") or "")
    reason = props.get("_sim_reason")
    acting_on_it = state in ("REPORT", "CONFRONT", "INVESTIGATE", "COMBAT")
    if reason and (intent == "MOURN" or (acting_on_it and intent not in ("IGNORE", "WARM"))):
        return "intent:" + intent + ":" + str(reason), _plain_reason(reason) + "."
    if state == "COMBAT" and props.get("_aggro_target") is not None:
        return "combat:" + str(props.get("_aggro_target")), line(
            "combat", target=target)[1]
    if (aggression == "hostile" and props.get("awake")
            and not props.get("triggered")):
        return line("hunt")
    if state == "FOLLOW":
        return line("follow")
    need = props.get("_need_reason")
    if need in ("exhausted", "hungry"):
        return line(need)
    if state in _THOUGHTS:
        return line(state)
    return state.lower(), ""


# ---------------------------------------------------------------------------
# "What's on your mind?": an actor explaining itself to the player
# ---------------------------------------------------------------------------
#: What somebody busy with nothing in particular says they are about.
_ROUTINE_MIND = {
    "WORKING": "Just working. Somebody has to.",
    "GOING_TO_WORK": "Off to work, same as every day.",
    "GOING_HOME": "Heading home. It's been a long day.",
    "IDLE": "Not much. Taking it easy for a moment.",
    "WANDER": "Just stretching my legs.",
    "PATROL": "Keeping the peace, as ever.",
    "SLEEPING": "I was asleep, if you must know.",
}

#: How a known fact is brought up, by how the actor came to know it.
_KNOWN_FROM = {
    "witnessed": "I saw it with my own eyes: {what}.",
    "heard": "I heard it happen: {what}.",
    "told": "People are saying {what}.",
}


def speak_mind(props, facts=(), intents=(), player_key: str = "player") -> str:
    """What an actor says when the player asks what is on its mind: what it
    is doing and why, what is pressing on it, and the most notable thing it
    knows -- the same reasons that drive its behaviour, in its own words.

    *facts* are its knowledge (:func:`game.sim.knowledge.facts`), *intents*
    its ranked intents; both optional. Pure.
    """
    if not isinstance(props, dict):
        return "..."
    parts = []
    key, now = thought(props)
    state = str(_get(props, "sched_state", default="")).upper()
    if not now or key == state:
        # Plain routine: the overhead thought is a word or two ("Busy,
        # busy."); asked to their face, people say a little more.
        now = _ROUTINE_MIND.get(state, now or "Nothing much.")
    parts.append(now)
    said = {now}

    hunger = float(_get(props, "need_hunger", default=0.0) or 0.0)
    fatigue = float(_get(props, "need_fatigue", default=0.0) or 0.0)
    if hunger >= MOOD_NEED_LEVEL and props.get("_need_reason") != "hungry":
        parts.append("I could eat a horse, mind.")
    if fatigue >= MOOD_NEED_LEVEL and props.get("_need_reason") != "exhausted":
        parts.append("And I'm dead on my feet.")

    for intent in intents or ():
        reason = _plain_reason(getattr(intent, "reason", "")) + "."
        if getattr(intent, "reaction", "") != "IGNORE" and reason not in said and reason != ".":
            parts.append(reason)
            said.add(reason)
            break

    from .sim import events, knowledge
    notable = [f for f in facts or () if knowledge.shareable(f)]
    if notable:
        top = max(notable, key=lambda f: float(f.get("certainty", 0.0))
                  * float(events.kind_spec(f.get("kind", ""))["severity"]))
        if top.get("actor") == player_key:
            top = dict(top, actor_name="you")
        what = knowledge.phrase(top)
        line = _KNOWN_FROM.get(str(top.get("source")), _KNOWN_FROM["told"]).format(what=what)
        if float(top.get("certainty", 0.0)) < 0.5:
            line = line[:-1] + " — though I can't swear to it."
        parts.append(line)
    return " ".join(parts)
