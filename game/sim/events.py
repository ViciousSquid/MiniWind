"""
The world event bus — the single spine every reactive system hangs off.

A :class:`WorldEvent` is a small, serialisable record of *something that
happened in the world*: who did it, to whom, where, when, how loud it was and
what it means. It is deliberately generic — the bus has no idea what a "theft"
or a "murder" is beyond a row in :data:`EVENT_KINDS`, and no system downstream
branches on a scenario. Add a row and every system (perception, knowledge,
rumour, appraisal, the editor's history view) handles the new kind for free.

The bus keeps a bounded history so the editor's **World Event / History** view
can show what happened and, through each event's ``consequences`` list, what it
caused. It is JSON round-trippable so a playthrough's history survives
save/load in the ordinary MiniWind KV store.

Pure Python; no Qt, no engine imports.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Callable, Dict, Iterable, List, Optional, Tuple

#: Default cap on retained history. Old events fall off the front; their
#: consequences have already been folded into durable state (knowledge,
#: disposition, bounty), so the history is a *log*, not the source of truth.
HISTORY_CAP = 400

# ---------------------------------------------------------------------------
# The event vocabulary
# ---------------------------------------------------------------------------
# Each row is: tags, loudness (world units an unsighted actor can still hear
# it from), severity (0-1, how much it matters to a bystander) and a short
# phrase template used by the history view and NPC gossip lines.
#
# ``tags`` are what the rest of the simulation actually reasons about, so a new
# event kind only has to declare what *sort* of thing it is:
#
#   violence   somebody was hurt          → threat appraisal, courage/fear
#   grave      somebody died              → mourning, kin grief, strong memory
#   crime      an offence against the law → witnesses, reporting, bounty
#   property   concerns owned goods       → ownership/theft reasoning
#   social     a friendly interaction     → disposition warmth
#   notable    worth gossiping about      → rumour propagation picks these
#
_KIND_FIELDS = ("tags", "loudness", "severity", "phrase")

EVENT_KINDS: Dict[str, Dict] = {
    "attack": dict(
        tags=("violence", "crime", "notable"), loudness=700.0, severity=0.7,
        phrase="{actor} attacked {target}"),
    "death": dict(
        tags=("violence", "grave", "crime", "notable"), loudness=850.0, severity=1.0,
        phrase="{target} was killed by {actor}"),
    "theft": dict(
        tags=("crime", "property", "notable"), loudness=90.0, severity=0.5,
        phrase="{actor} stole {item} from {target}"),
    "trespass": dict(
        tags=("crime", "property"), loudness=60.0, severity=0.2,
        phrase="{actor} trespassed in {target}'s property"),
    "arrest": dict(
        tags=("notable",), loudness=500.0, severity=0.4,
        phrase="{actor} arrested {target}"),
    "trade": dict(
        tags=("social",), loudness=120.0, severity=0.1,
        phrase="{actor} traded with {target}"),
    "gift": dict(
        tags=("social", "notable"), loudness=120.0, severity=0.3,
        phrase="{actor} gave {target} {item}"),
    "heal": dict(
        tags=("social", "notable"), loudness=200.0, severity=0.4,
        phrase="{actor} healed {target}"),
    "talk": dict(
        tags=("social",), loudness=110.0, severity=0.05,
        phrase="{actor} spoke with {target}"),
    "produce": dict(
        tags=(), loudness=60.0, severity=0.05,
        phrase="{actor} produced {item}"),
    "pickup": dict(
        tags=("property",), loudness=60.0, severity=0.05,
        phrase="{actor} picked up {item}"),
    "give": dict(
        tags=("social", "property"), loudness=110.0, severity=0.2,
        phrase="{actor} handed {target} {item}"),
    "rumour": dict(
        tags=("social",), loudness=110.0, severity=0.05,
        phrase="{actor} told {target} about {item}"),
}

#: A kind the caller never declared still works — it just carries no tags and
#: is quiet and unimportant, which is the safest possible default.
_UNKNOWN_KIND = dict(tags=(), loudness=150.0, severity=0.1,
                     phrase="{actor} did something ({kind})")


def kind_spec(kind: str) -> Dict:
    """The :data:`EVENT_KINDS` row for *kind*, or a quiet, untagged default."""
    return EVENT_KINDS.get(str(kind), _UNKNOWN_KIND)


def register_kind(kind: str, tags: Iterable[str] = (), loudness: float = 150.0,
                  severity: float = 0.1, phrase: str = "") -> None:
    """Add (or replace) an event kind at runtime.

    This is the whole extension point: a mod or a new system declares what
    *sort* of thing its event is, and perception, rumour, appraisal, crime and
    the editor history all handle it without another line of code."""
    EVENT_KINDS[str(kind)] = dict(
        tags=tuple(tags), loudness=float(loudness), severity=float(severity),
        phrase=str(phrase or "{actor} did something ({kind})"))


class WorldEvent:
    """One thing that happened, as plain data.

    ``actor``/``target`` are stable identity *keys* (see
    :func:`game.sim.director.actor_key`); the ``*_name`` fields are the display
    names, kept alongside so the history stays readable after the entity is
    gone. ``data`` is a free-form dict — an item id, a damage number, a value —
    that individual systems read but the bus never interprets.
    """

    __slots__ = ("id", "kind", "actor", "actor_name", "target", "target_name",
                 "pos", "day", "hour", "data", "consequences")

    def __init__(self, kind: str, actor: str = "", actor_name: str = "",
                 target: str = "", target_name: str = "",
                 pos: Optional[Iterable[float]] = None, day: int = 0,
                 hour: float = 0.0, data: Optional[Dict] = None,
                 event_id: int = 0):
        self.id = int(event_id)
        self.kind = str(kind)
        self.actor = str(actor or "")
        self.actor_name = str(actor_name or actor or "")
        self.target = str(target or "")
        self.target_name = str(target_name or target or "")
        self.pos = [float(c) for c in (pos or (0.0, 0.0, 0.0))]
        self.day = int(day)
        self.hour = float(hour)
        self.data = dict(data or {})
        #: Human-readable lines describing what this event *caused*, appended by
        #: whichever system reacted. This is what makes the editor's history
        #: view a causal chain rather than a flat log.
        self.consequences: List[str] = []

    # -- derived properties -------------------------------------------------
    @property
    def tags(self) -> Tuple[str, ...]:
        return tuple(kind_spec(self.kind)["tags"])

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    @property
    def is_crime(self) -> bool:
        """Whether *this* occurrence is an offence.

        Kind-level tagging is the default, but the emitter may override it with
        ``crime=False`` (or ``True``) in ``data`` — because whether a killing is
        murder depends on who was killed, not on the fact that killing happened.
        A guard cutting down a bandit and a player cutting down a farmer are the
        same event kind and different crimes, and that judgement belongs to
        whoever has the faction context, not to the bus."""
        override = self.data.get("crime")
        if override is not None:
            return bool(override)
        return "crime" in self.tags

    @property
    def loudness(self) -> float:
        """How far away an actor with no line of sight can still hear it."""
        return float(self.data.get("loudness", kind_spec(self.kind)["loudness"]))

    @property
    def severity(self) -> float:
        """0-1 weight of how much a bystander should care."""
        return float(self.data.get("severity", kind_spec(self.kind)["severity"]))

    def describe(self) -> str:
        """A one-line, display-ready phrase for the history view."""
        spec = kind_spec(self.kind)
        fields = {
            "actor": self.actor_name or "someone",
            "target": self.target_name or "someone",
            "item": self.data.get("item_name") or self.data.get("item") or "something",
            "kind": self.kind,
        }
        try:
            return spec["phrase"].format(**fields)
        except (KeyError, IndexError, ValueError):
            return f"{fields['actor']} — {self.kind}"

    def note(self, line: str) -> None:
        """Record a consequence of this event (what it made the world do)."""
        line = str(line).strip()
        if line and line not in self.consequences:
            self.consequences.append(line)

    def timestamp(self) -> str:
        h = int(self.hour) % 24
        m = int((self.hour - int(self.hour)) * 60)
        return f"Day {self.day} {h:02d}:{m:02d}"

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> Dict:
        return {
            "id": self.id, "kind": self.kind,
            "actor": self.actor, "actor_name": self.actor_name,
            "target": self.target, "target_name": self.target_name,
            "pos": list(self.pos), "day": self.day, "hour": self.hour,
            "data": dict(self.data), "consequences": list(self.consequences),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "WorldEvent":
        ev = cls(kind=d.get("kind", ""), actor=d.get("actor", ""),
                 actor_name=d.get("actor_name", ""), target=d.get("target", ""),
                 target_name=d.get("target_name", ""), pos=d.get("pos"),
                 day=d.get("day", 0), hour=d.get("hour", 0.0),
                 data=d.get("data"), event_id=d.get("id", 0))
        ev.consequences = [str(x) for x in (d.get("consequences") or [])]
        return ev

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<WorldEvent #{self.id} {self.kind} {self.actor_name!r}→{self.target_name!r}>"


class EventBus:
    """A bounded, subscribable log of :class:`WorldEvent`.

    Subscribers are called synchronously in registration order and are fully
    guarded: a listener that raises can never stop the world from turning."""

    def __init__(self, cap: int = HISTORY_CAP):
        self._history: deque = deque(maxlen=int(cap))
        self._subs: List[Callable[[WorldEvent], None]] = []
        self._next_id = 1

    # -- publish ------------------------------------------------------------
    def emit(self, event: WorldEvent) -> WorldEvent:
        """Stamp *event* with an id, log it and notify every subscriber."""
        if not event.id:
            event.id = self._next_id
            self._next_id += 1
        else:
            self._next_id = max(self._next_id, event.id + 1)
        self._history.append(event)
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:
                # A misbehaving reactor must not break the simulation.
                pass
        return event

    def make(self, kind: str, **kwargs) -> WorldEvent:
        """Build and emit an event in one call."""
        return self.emit(WorldEvent(kind, **kwargs))

    def subscribe(self, fn: Callable[[WorldEvent], None]) -> Callable:
        """Register a listener; returns it so it can be used as a decorator."""
        if callable(fn) and fn not in self._subs:
            self._subs.append(fn)
        return fn

    def unsubscribe(self, fn) -> None:
        if fn in self._subs:
            self._subs.remove(fn)

    # -- read ---------------------------------------------------------------
    @property
    def history(self) -> List[WorldEvent]:
        return list(self._history)

    def recent(self, limit: int = 30, kind: str = "", tag: str = "",
               actor: str = "") -> List[WorldEvent]:
        """The most recent events (newest first), optionally filtered."""
        out = []
        for ev in reversed(self._history):
            if kind and ev.kind != kind:
                continue
            if tag and not ev.has_tag(tag):
                continue
            if actor and actor not in (ev.actor, ev.target):
                continue
            out.append(ev)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get(self, event_id: int) -> Optional[WorldEvent]:
        for ev in reversed(self._history):
            if ev.id == int(event_id):
                return ev
        return None

    def clear(self) -> None:
        self._history.clear()
        self._next_id = 1

    # -- persistence --------------------------------------------------------
    def to_json(self, limit: int = 120) -> str:
        """Serialise the tail of the history (the part worth carrying in a save)."""
        events = list(self._history)[-max(0, int(limit)):]
        return json.dumps({"next": self._next_id,
                           "events": [e.to_dict() for e in events]})

    def load_json(self, raw: str) -> int:
        """Restore a serialised history. Returns how many events were loaded."""
        if not raw:
            return 0
        try:
            blob = json.loads(raw)
        except (TypeError, ValueError):
            return 0
        if not isinstance(blob, dict):
            return 0
        self._history.clear()
        for d in blob.get("events") or []:
            if isinstance(d, dict):
                self._history.append(WorldEvent.from_dict(d))
        self._next_id = max(int(blob.get("next", 1) or 1),
                            max((e.id for e in self._history), default=0) + 1)
        return len(self._history)
