"""
The director — the glue that makes the pipeline a loop.

    EVENT → PERCEPTION → INTERPRETATION → STATE CHANGE → BEHAVIOUR

:class:`Director` owns the event bus and drives every step of that chain for
whatever actors it is handed. It is the *only* module in :mod:`game.sim` that
knows about more than one system, and it deliberately knows nothing about any
particular scenario: it never asks "was this the blacksmith?", only "who
perceived it, what do they now believe, and what does that make them want?".

It also keeps the **explanation trail** — the ranked intents and the plain
sentence behind each one — which is what the editor's Live Simulation
Inspector reads when a designer asks why an NPC is doing what it is doing.

Everything here is engine-free: actors are any object with ``.properties`` and
``.pos``, so the whole director is exercised headlessly in the tests.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from . import appraisal, crime, knowledge, ownership, perception, production
from .appraisal import Intent
from .events import EventBus, WorldEvent

#: The player's stable identity key. The player is an actor like any other as
#: far as this package is concerned — which is why NPCs can witness, remember
#: and gossip about the player without a single player-specific branch.
PLAYER_KEY = "player"

#: How near two actors must be to exchange gossip, and how often (game hours)
#: a gossip pass runs. Deliberately unhurried: news travelling at the speed of
#: people walking past each other is what makes outrunning it possible.
GOSSIP_RADIUS = 220.0
GOSSIP_INTERVAL_HOURS = 0.5

#: How near a witness must get to a lawful actor to lay a charge.
TELL_RADIUS = 260.0

#: Cap on how many gossip exchanges happen in one pass, so a crowded square
#: cannot spike the frame budget.
GOSSIP_BUDGET = 6


def slug(text) -> str:
    """Lowercase, alnum-only identity slug (matches runtime/disposition)."""
    return "".join(ch.lower() if ch.isalnum() else "_"
                   for ch in str(text)).strip("_")


def actor_key(thing) -> str:
    """A stable identity key for any actor.

    Delegates to :func:`game.rpg.disposition.mem_key` — the identity MiniWind
    already files per-NPC player memory under — so an NPC's knowledge, their
    opinion of the player and their editor inspector row are one identity, not
    three. The local slug is only the fallback for a context where the rpg core
    is not importable."""
    if thing is None:
        return ""
    if isinstance(thing, str):
        return slug(thing)
    props = getattr(thing, "properties", None)
    if not isinstance(props, dict):
        return ""
    if props.get("is_player") or props.get("_player"):
        return PLAYER_KEY
    try:
        from ..rpg.disposition import mem_key
        return mem_key(props)
    except Exception:
        for field in ("id", "name", "display_name", "npc_role"):
            v = props.get(field)
            if v:
                return slug(v)
    return ""


def actor_name(thing, default: str = "someone") -> str:
    props = getattr(thing, "properties", None)
    if isinstance(props, dict):
        for field in ("display_name", "name", "npc_role"):
            v = props.get(field)
            if v:
                return str(v)
    return default


def _props(thing) -> Dict:
    p = getattr(thing, "properties", None)
    return p if isinstance(p, dict) else {}


def _pos(thing):
    p = getattr(thing, "pos", None)
    return list(p) if p is not None else None


class Director:
    """Runs the reactive pipeline over a set of actors.

    ``hostile`` and ``disposition`` are injected so the director never imports
    the faction matrix or the opinion model directly — the session supplies the
    game's real ones, and a test supplies two lambdas.
    """

    def __init__(self, store=None, clock=None, rng=None, bus: Optional[EventBus] = None,
                 hostile: Optional[Callable[[str, str], bool]] = None,
                 disposition: Optional[Callable[[Dict, str], int]] = None,
                 on_bounty: Optional[Callable[[int, WorldEvent, str], None]] = None,
                 on_message: Optional[Callable[[str], None]] = None):
        self.store = store
        self.clock = clock
        self.rng = rng
        self.bus = bus if bus is not None else EventBus()
        self.on_bounty = on_bounty
        self.on_message = on_message
        self.ctx = appraisal.Context(hostile=hostile, disposition=disposition,
                                     store=store)
        #: actor key -> ranked intents (recomputed when their knowledge changes)
        self._intents: Dict[str, List[Intent]] = {}
        self._dirty: set = set()
        self._gossip_clock = 0.0
        # Baseline the day at construction so the first day boundary that
        # actually passes is the first one that ages anybody's memory.
        self._last_day: Optional[int] = (
            int(getattr(clock, "day", 0) or 0) if clock is not None else None)
        #: Yields produced this tick, drained by the session which places them
        #: in the world (the director has no way to spawn an entity itself).
        self.pending_yields: List = []

    # ------------------------------------------------------------------ time
    def _now(self):
        day = int(getattr(self.clock, "day", 0) or 0)
        hour = float(getattr(self.clock, "hour", 12.0) or 12.0)
        return day, hour

    # ----------------------------------------------------------- emit events
    def emit(self, kind: str, actor=None, target=None, pos=None,
             observers: Sequence = (), **data) -> WorldEvent:
        """Record something that happened and run it through the whole chain.

        *actor* and *target* may be entities or bare identity strings. *pos*
        defaults to the actor's position, then the target's. Everything else
        (an item id, a value, a damage number) rides along in ``data`` for the
        systems that care."""
        day, hour = self._now()
        akey = actor_key(actor)
        tkey = actor_key(target)
        if pos is None:
            pos = _pos(actor) or _pos(target) or (0.0, 0.0, 0.0)
        aprops = _props(actor)
        if aprops and "actor_faction" not in data:
            data["actor_faction"] = str(aprops.get("faction")
                                        or aprops.get("team") or "")
        event = WorldEvent(
            kind, actor=akey, actor_name=actor_name(actor, akey or "someone"),
            target=tkey, target_name=actor_name(target, tkey or ""),
            pos=pos, day=day, hour=hour, data=data)
        self.bus.emit(event)
        self.dispatch(event, observers, actor_thing=actor, target_thing=target)
        return event

    # ------------------------------------------------- perception → knowledge
    def dispatch(self, event: WorldEvent, observers: Iterable,
                 actor_thing=None, target_thing=None) -> List:
        """Work out who perceived *event* and write what each of them now knows.

        The victim of an event always learns it with full certainty — you know
        when you have been robbed even if you never saw who did it, and that
        asymmetry is what lets a theft be discovered later."""
        _day, hour = self._now()
        percepts = perception.witnesses(event, observers or (), hour=hour,
                                        actor_thing=actor_thing)
        learned = 0
        for pc in percepts:
            key = actor_key(pc.observer)
            if not key or key == event.actor:
                continue
            fact = knowledge.fact_from_event(
                event, pc.clarity, knowledge.source_for(pc.mode))
            if event.kind == "theft":
                fact["value"] = int(event.data.get("value", 0) or 0)
            if knowledge.learn(self.store, key, fact):
                learned += 1
                self._dirty.add(key)
                self._on_learned(pc.observer, key, fact)
            if pc.woke:
                # A loud enough noise gets a sleeper out of bed — no scripted
                # "wake the town" step, just hearing at reduced range.
                pc.observer.properties["_woken_by"] = event.id
                pc.observer.properties["awake"] = True
                event.note(f"{actor_name(pc.observer)} was woken by the noise")

        # The victim always knows, witnesses or not — unless the event was
        # their death, which is the one thing nobody gets to remember.
        if (target_thing is not None and event.target
                and event.target != event.actor
                and not _props(target_thing).get("dead")):
            fact = knowledge.fact_from_event(event, 1.0, knowledge.SOURCE_WITNESSED)
            if event.kind == "theft":
                fact["value"] = int(event.data.get("value", 0) or 0)
            if knowledge.learn(self.store, event.target, fact):
                self._dirty.add(event.target)
                self._on_learned(target_thing, event.target, fact)

        if percepts:
            names = ", ".join(sorted({actor_name(p.observer) for p in percepts})[:4])
            event.note(f"witnessed by {names}")
        elif event.is_crime:
            event.note("nobody saw it")
        return percepts

    def _on_learned(self, observer, key: str, fact: Dict) -> None:
        """The **state change** step: folding new knowledge into durable state.

        Right now that means one thing — learning that somebody wronged you or
        yours moves your opinion of them. It is done here rather than at the
        moment of the crime precisely so that opinion only changes for people
        who actually find out."""
        if fact.get("actor") != PLAYER_KEY:
            return
        mem = crime.memory_event(fact.get("kind", ""))
        if not mem:
            return
        props = _props(observer)
        victim = str(fact.get("target", ""))
        tie = appraisal.relationship_to(props, victim, fact.get("target_name", ""))
        if victim == key:
            pass                                    # done to them directly
        elif mem == "kin_slain" and tie in appraisal.WARM_TIES:
            pass                                    # done to their kin
        elif fact.get("kind") == "theft" and victim != key:
            return                                  # someone else's loss
        elif mem == "kin_slain":
            return                                  # a stranger's death
        try:
            from ..rpg import disposition as disp
            # A half-remembered rumour moves an opinion less than testimony.
            base = disp.EVENTS.get(mem, (0, False))[0]
            scaled = int(round(base * max(0.3, float(fact.get("certainty", 1.0)))))
            disp.remember(self.store, props, mem, amount=scaled)
        except Exception:
            pass

    # -------------------------------------------------- interpretation → why
    def intents(self, thing, refresh: bool = False) -> List[Intent]:
        """This actor's ranked intents, recomputed only when their beliefs moved."""
        key = actor_key(thing)
        if not key:
            return []
        if refresh or key in self._dirty or key not in self._intents:
            facts = knowledge.facts(self.store, key)
            self._intents[key] = appraisal.appraise_all(
                _props(thing), key, facts, self.ctx)
            self._dirty.discard(key)
        return self._intents[key]

    def top_intent(self, thing) -> Optional[Intent]:
        got = self.intents(thing)
        return got[0] if got else None

    def why(self, thing) -> str:
        """The plain-English reason this actor is doing what it is doing."""
        return appraisal.explain(self.intents(thing))

    def invalidate(self, thing=None) -> None:
        """Force an actor's (or everyone's) intents to be reconsidered."""
        if thing is None:
            self._intents.clear()
            self._dirty.clear()
            return
        key = actor_key(thing)
        if key:
            self._dirty.add(key)

    def knowledge_lines(self, thing, limit: int = 8) -> List[str]:
        return knowledge.summary(self.store, actor_key(thing), limit)

    # ----------------------------------------------------------------- ticks
    def tick(self, actors: Sequence, hours: float) -> None:
        """Advance the parts of the simulation that run on their own clock:
        rumour propagation, crime reporting and production."""
        actors = [a for a in (actors or ()) if not _props(a).get("dead")]
        self._gossip_clock += max(0.0, float(hours))
        if self._gossip_clock >= GOSSIP_INTERVAL_HOURS:
            self._gossip_clock = 0.0
            self.spread_rumours(actors)
        self.resolve_reports(actors)
        self.tick_production(actors, hours)
        self._roll_day(actors)

    def spread_rumours(self, actors: Sequence) -> int:
        """One pass of people telling each other what they know.

        Pairs are whoever happens to be standing near each other and awake — no
        conversation scheduling, no dialogue authoring. The town's information
        network *is* its foot traffic."""
        if self.store is None:
            return 0
        awake = [a for a in actors
                 if str(_props(a).get("sched_state", "")).upper() != "SLEEPING"]
        exchanges = 0
        for i, speaker in enumerate(awake):
            if exchanges >= GOSSIP_BUDGET:
                break
            skey = actor_key(speaker)
            if not skey:
                continue
            for listener in awake[i + 1:]:
                if exchanges >= GOSSIP_BUDGET:
                    break
                lkey = actor_key(listener)
                if not lkey or lkey == skey:
                    continue
                if perception.dist2d(_pos(speaker), _pos(listener)) > GOSSIP_RADIUS:
                    continue
                passed = knowledge.gossip(self.store, skey, lkey, self.rng)
                back = knowledge.gossip(self.store, lkey, skey, self.rng)
                if passed:
                    self._dirty.add(lkey)
                    self._on_learned(listener, lkey, passed[0])
                if back:
                    self._dirty.add(skey)
                    self._on_learned(speaker, skey, back[0])
                if passed or back:
                    exchanges += 1
                    ev = self.bus.get((passed or back)[0].get("e", 0))
                    if ev is not None:
                        ev.note(f"{actor_name(speaker)} and {actor_name(listener)} "
                                f"spoke of it")
        return exchanges

    def resolve_reports(self, actors: Sequence) -> int:
        """Turn witness testimony into bounty — but only once it reaches the law.

        Two paths, both general: a lawful actor who knows about a crime charges
        it directly, and an ordinary witness standing near a lawful actor tells
        them, which makes it the guard's knowledge and therefore the guard's
        charge. A witness killed on the way to the guard reports nothing."""
        if self.store is None:
            return 0
        lawful = [a for a in actors if crime.is_lawful(_props(a))]
        charges = 0

        # (1) an ordinary witness passes a crime on to a nearby lawful actor
        for witness in actors:
            wkey = actor_key(witness)
            if not wkey or crime.is_lawful(_props(witness)):
                continue
            crimes = [f for f in knowledge.facts(self.store, wkey)
                      if crime.is_crime(f) and not f.get("reported")]
            if not crimes:
                continue
            for officer in lawful:
                okey = actor_key(officer)
                if not okey or okey == wkey:
                    continue
                if perception.dist2d(_pos(witness), _pos(officer)) > TELL_RADIUS:
                    continue
                for f in crimes:
                    if knowledge.tell(self.store, wkey, okey, f):
                        self._dirty.add(okey)
                        ev = self.bus.get(f.get("e", 0))
                        if ev is not None:
                            ev.note(f"{actor_name(witness)} reported it to "
                                    f"{actor_name(officer)}")
                    knowledge.mark_reported(self.store, wkey, f.get("e", 0))
                break

        # (2) a lawful actor who knows about an unreported crime lays the charge
        for officer in lawful:
            okey = actor_key(officer)
            if not okey:
                continue
            oprops = _props(officer)
            for f in list(knowledge.facts(self.store, okey)):
                amount = crime.report(self.store, f, okey, oprops)
                if amount <= 0:
                    continue
                knowledge.mark_reported(self.store, okey, f.get("e", 0))
                charges += 1
                ev = self.bus.get(f.get("e", 0))
                if f.get("actor") == PLAYER_KEY and self.on_bounty is not None:
                    try:
                        self.on_bounty(amount, ev, okey)
                    except Exception:
                        pass
                if ev is not None:
                    ev.note(f"{actor_name(officer)} laid a charge "
                            f"({amount} gold bounty)")
                self._dirty.add(okey)
        return charges

    def tick_production(self, actors: Sequence, hours: float) -> List:
        """Advance every producing object; queue what they made.

        The director cannot create entities, so yields are queued for the
        session (which knows how to place an item in the scene) to drain."""
        made = []
        for thing in actors:
            props = _props(thing)
            if not production.is_producer(props):
                continue
            for y in production.advance(props, hours):
                made.append((thing, y))
        if made:
            self.pending_yields.extend(made)
        return made

    def drain_yields(self) -> List:
        """Take the queued production output (the session places it in the world)."""
        out, self.pending_yields = self.pending_yields, []
        return out

    def _roll_day(self, actors: Sequence) -> None:
        """At each day boundary, let everyone's knowledge fade a little."""
        day, _hour = self._now()
        if self._last_day is None:
            self._last_day = day
            return
        if day == self._last_day:
            return
        elapsed = max(1, day - self._last_day)
        self._last_day = day
        for thing in actors:
            key = actor_key(thing)
            if key:
                knowledge.decay(self.store, key, elapsed)
                self._dirty.add(key)

    # --------------------------------------------------------- theft helper
    def take(self, thing_props: Dict, taker, target_thing=None,
             observers: Sequence = (), item_id: str = "", item_name: str = "",
             value: int = 0, pos=None) -> Optional[WorldEvent]:
        """Record somebody taking an object — as a theft if it was owned.

        One call covers the world item, the container stack, the shop shelf and
        the bucket of milk beside the cow, because the only question asked is
        "did this belong to somebody else?"."""
        tkey = actor_key(taker)
        tprops = _props(taker)
        faction = str(tprops.get("faction") or tprops.get("team") or "")
        owned = ownership.is_theft(thing_props, tkey, faction)
        kind = "theft" if owned else "pickup"
        data = {"item": item_id, "item_name": item_name or item_id,
                "value": int(value or ownership.theft_value(thing_props))}
        target = target_thing
        if owned and target is None:
            target = ownership.owner_of(thing_props)
        return self.emit(kind, actor=taker, target=target, pos=pos,
                         observers=observers, **data)

    # ---------------------------------------------------------- persistence
    HISTORY_KEY = "sim.history"

    def persist(self) -> None:
        if self.store is not None:
            self.store.set(self.HISTORY_KEY, self.bus.to_json())

    def restore(self) -> int:
        if self.store is None:
            return 0
        return self.bus.load_json(self.store.get(self.HISTORY_KEY, ""))

    # ------------------------------------------------------------ inspection
    def report_lines(self, limit: int = 25) -> List[str]:
        """The World Event / History view's text form (newest first)."""
        out = []
        for ev in self.bus.recent(limit=limit):
            out.append(f"[{ev.timestamp()}] {ev.describe()}")
            for c in ev.consequences:
                out.append(f"      ↳ {c}")
        return out
