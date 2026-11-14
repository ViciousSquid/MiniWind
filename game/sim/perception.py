"""
Perception — *who could possibly have noticed that?*

The single most important thing this module buys is that **an act is not a
fact**. Stabbing a farmer in a crowded square and stabbing him alone in a barn
at midnight are the same event; they differ only in who perceived it. Every
downstream consequence — a guard's response, a bounty, a grieving sister, a
rumour that reaches the next village — hangs off this one question, so it is
answered by one general rule rather than per-scenario checks.

The rule:

* **Sight** needs an awake, living observer inside its own ``sight_range``.
  The range is scaled by the actor's stealth (a sneaking player is harder to
  catch) and by darkness for observers without a light.
* **Sound** needs only that the event's ``loudness`` reaches the observer —
  a sleeper hears at reduced range and may wake for something loud enough.
* **Clarity** falls off with distance and is capped by the mode: you are
  never as sure of what you heard as of what you saw.

The observer's own action always registers at full clarity, but an actor is
never counted as a *witness* to their own deed — that distinction is what lets
"nobody saw me" mean something.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

#: Clarity ceiling per perception mode. Heard events are inherently uncertain,
#: which is what makes them behave like rumours rather than testimony.
SIGHT_CLARITY = 1.0
SOUND_CLARITY = 0.55

#: A sleeping actor hears at this fraction of the event's loudness radius, and
#: sees nothing at all.
SLEEP_HEARING = 0.45
#: A sound at least this loud relative to the sleeper's threshold wakes them.
WAKE_CLARITY = 0.35

#: Fallback sight range when an actor declares none.
DEFAULT_SIGHT = 1024.0

#: Night multiplier on sight for an observer carrying no light source.
NIGHT_SIGHT_FACTOR = 0.45
#: Hours (inclusive-exclusive) that count as night for the purpose above.
NIGHT_START, NIGHT_END = 20.0, 6.0


class Percept:
    """One observer's perception of one event."""

    __slots__ = ("observer", "mode", "clarity", "distance", "woke")

    def __init__(self, observer, mode: str, clarity: float, distance: float,
                 woke: bool = False):
        self.observer = observer
        self.mode = mode              # "sight" | "sound"
        self.clarity = float(clarity)  # 0-1 confidence in what was perceived
        self.distance = float(distance)
        self.woke = bool(woke)        # a sleeper startled awake by the noise

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Percept {self.mode} clarity={self.clarity:.2f} d={self.distance:.0f}>"


def _props(thing) -> Dict:
    p = getattr(thing, "properties", None)
    return p if isinstance(p, dict) else {}


def _pos(thing):
    p = getattr(thing, "pos", None)
    if p is None:
        return None
    try:
        return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]
    except (TypeError, ValueError, IndexError):
        return None


def dist2d(a, b) -> float:
    """Planar distance — MiniWind is top-down, so height never blocks a look."""
    if a is None or b is None:
        return float("inf")
    return math.hypot(float(a[0]) - float(b[0]), float(a[2]) - float(b[2]))


def is_night(hour: float) -> bool:
    h = float(hour) % 24.0
    return h >= NIGHT_START or h < NIGHT_END


def sight_range(observer_props: Dict, hour: float = 12.0) -> float:
    """How far this observer can see right now.

    Authored ``sight_range``, dimmed at night unless the actor carries a lit
    torch. Blind (``sight_range`` 0) actors see nothing and rely on hearing —
    which is exactly how you'd author a blind beggar who still gossips."""
    try:
        base = float(observer_props.get("sight_range", DEFAULT_SIGHT))
    except (TypeError, ValueError):
        base = DEFAULT_SIGHT
    if base <= 0:
        return 0.0
    if is_night(hour) and not (observer_props.get("torch_always")
                               or observer_props.get("torch")
                               or observer_props.get("_torch_lit")):
        base *= NIGHT_SIGHT_FACTOR
    return max(0.0, base)


#: ``stealth`` a sneaking player gains per point of Sneak: 0.5 at Sneak 100.
#: With :func:`stealth_factor` that is sight x 0.5 x (1 - 0.003 x Sneak).
SNEAK_STEALTH_PER_POINT = 0.005


def sneak_stealth(sneak_skill, sneaking: bool = True) -> float:
    """The ``stealth`` (0-0.5) the Sneak skill gives an actor who is
    sneaking; nothing when they are not."""
    if not sneaking:
        return 0.0
    try:
        skill = max(0.0, min(100.0, float(sneak_skill)))
    except (TypeError, ValueError):
        skill = 0.0
    return skill * SNEAK_STEALTH_PER_POINT


#: ``sleight`` per point of Light Fingers: 0.5 at 100. A theft is seen at
#: sight x (1 - 0.003 x Light Fingers), on top of any sneaking.
LIGHT_FINGERS_SLEIGHT_PER_POINT = 0.005
#: The events sleight of hand hides: what a deft hand does.
SLEIGHT_EVENTS = ("theft",)


def sleight(light_fingers) -> float:
    """The ``sleight`` (0-0.5) the Light Fingers skill gives."""
    try:
        skill = max(0.0, min(100.0, float(light_fingers)))
    except (TypeError, ValueError):
        skill = 0.0
    return skill * LIGHT_FINGERS_SLEIGHT_PER_POINT


def _unit(props: Dict, key: str) -> float:
    try:
        return max(0.0, min(1.0, float(props.get(key, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def stealth_factor(actor_props: Optional[Dict], kind: str = "") -> float:
    """Multiplier applied to an observer's sight range against this actor.

    A sneaking actor shrinks everyone's effective sight; ``stealth`` (0-1) on
    the actor's own properties tightens it further. For a theft (*kind*),
    ``sleight`` (0-1) tightens it again: a deft hand is hard to catch. There
    is no separate "detection" subsystem — the same number serves the player,
    an NPC thief and a stalking wolf."""
    p = actor_props or {}
    factor = 0.5 if p.get("sneaking") else 1.0
    factor *= 1.0 - 0.6 * _unit(p, "stealth")
    if kind in SLEIGHT_EVENTS:
        factor *= 1.0 - 0.6 * _unit(p, "sleight")
    return max(0.05, factor)


def notice_chance(distance: float, reach: float) -> float:
    """The chance an observer within *reach* (its sight range against a
    sneaking actor) notices them at *distance*: the clarity it would see
    them with -- near certain up close, 30% at the edge. Rolled on a d20 by
    the game (RULES.md §11)."""
    if reach <= 0.0 or distance > reach:
        return 0.0
    return _falloff(distance, reach)


def can_perceive(observer, event_pos, loudness: float, hour: float = 12.0,
                 actor_props: Optional[Dict] = None, visible: bool = True,
                 kind: str = "") -> Optional[Percept]:
    """Return this observer's :class:`Percept` of an event, or ``None``.

    Sight is tried first (it is clearer); hearing catches what sight misses,
    including for a sleeper — who may be woken by a loud enough noise.
    *kind* is the event's (a theft is harder to see done by a deft hand)."""
    props = _props(observer)
    if props.get("dead"):
        return None
    opos = _pos(observer)
    d = dist2d(opos, event_pos)
    if not math.isfinite(d):
        return None

    asleep = _is_asleep(props)
    if visible and props.get("view_cone"):
        # Nobody sees what is in their blind spot (engine.monster_facing).
        from engine.monster_facing import in_view_cone
        try:
            visible = in_view_cone(observer, float(event_pos[0]), float(event_pos[2]))
        except (TypeError, ValueError, IndexError, AttributeError):
            pass
    if not asleep and visible:
        srange = sight_range(props, hour) * stealth_factor(actor_props, kind)
        if srange > 0.0 and d <= srange:
            clarity = SIGHT_CLARITY * _falloff(d, srange)
            return Percept(observer, "sight", clarity, d)

    hear_range = max(0.0, float(loudness)) * (SLEEP_HEARING if asleep else 1.0)
    if hear_range > 0.0 and d <= hear_range:
        clarity = SOUND_CLARITY * _falloff(d, hear_range)
        return Percept(observer, "sound", clarity, d,
                       woke=asleep and clarity >= WAKE_CLARITY)
    return None


def _falloff(d: float, r: float) -> float:
    """Linear-ish confidence falloff, never dropping below a usable floor.

    Something perceived at the very edge of range is a smudge, not nothing:
    that is what produces a half-remembered fact worth gossiping about."""
    if r <= 0:
        return 0.0
    return max(0.2, 1.0 - 0.7 * (float(d) / float(r)))


def _is_asleep(props: Dict) -> bool:
    state = str(props.get("sched_state", "")).upper()
    return state == "SLEEPING" or bool(props.get("asleep"))


def witnesses(event, observers: Iterable, hour: float = 12.0,
              actor_thing=None, actor_props: Optional[Dict] = None,
              sight_test=None) -> List[Percept]:
    """Every observer that perceived *event*, excluding the actor themselves.

    ``event`` needs only ``pos`` and ``loudness`` — a :class:`WorldEvent`, or
    any duck-typed stand-in — so this is reusable for a noise with no event
    record behind it (a dropped plate, a shout)."""
    pos = getattr(event, "pos", None)
    loud = float(getattr(event, "loudness", 0.0) or 0.0)
    kind = str(getattr(event, "kind", "") or "")
    if actor_props is None:
        actor_props = _props(actor_thing) if actor_thing is not None else None
    out: List[Percept] = []
    for obs in observers or ():
        if obs is actor_thing:
            continue
        p = can_perceive(obs, pos, loud, hour, actor_props, kind=kind)
        if p is not None and p.mode == "sight" and sight_test is not None:
            if not sight_test(obs, pos):
                p = can_perceive(obs, pos, loud, hour, actor_props, visible=False,
                                 kind=kind)
        if p is not None:
            out.append(p)
    out.sort(key=lambda pc: -pc.clarity)
    return out
