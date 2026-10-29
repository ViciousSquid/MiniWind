"""
The director — the glue that makes the pipeline a loop.

    EVENT → PERCEPTION → INTERPRETATION → STATE CHANGE → BEHAVIOUR

:class:`Director` owns the event bus and drives every step of that chain for
whatever actors it is handed. It is the *only* module in :mod:`game.sim` that
knows about more than one system, and it deliberately knows nothing about any
particular scenario: it never asks "was this the blacksmith?", only "who
perceived it, what do they now believe, and what does that make them want?".

It also owns the simulation's long-lived **subsystems** (:mod:`.system`): the
storyteller's pacing and the faction actors are attached here, tick after the
pipeline on world time, and reset, persist and restore with the event history.

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
from .system import SimSystem

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

#: How often (game hours) the *distant* world's reactive simulation runs: its
#: gossip, reports and production, all at once, covering the whole interval.
#: Off screen and out of reach, nobody can tell news travelled in hour-long
#: steps rather than half-hour ones.
COARSE_INTERVAL_HOURS = 1.0

#: Per-actor stamps: the simulation time an actor's production was last
#: advanced, and the day its memory last faded. An actor the simulation did
#: not visit (parked by the world streamer) catches up from these when it is
#: next visited, in one step.
SIM_AT_KEY = "_sim_at"
SIM_DAY_KEY = "_sim_day"


#: Below this many actors a plain nested loop beats NumPy's per-call overhead;
#: at or above it, proximity searches are batched (see :func:`_near_pairs`).
VECTOR_MIN = 48


def slug(text) -> str:
    """Lowercase, alnum-only identity slug (matches runtime/disposition)."""
    return "".join(ch.lower() if ch.isalnum() else "_"
                   for ch in str(text)).strip("_")


def _disposition():
    """game.rpg.disposition, resolved once (None where the rpg core is absent).

    Identity is asked for every actor several times per tick; an import
    statement in the call cost a trip through the import machinery each time."""
    global _DISPOSITION
    if _DISPOSITION is None:
        try:
            from ..rpg import disposition
        except Exception:
            disposition = False
        _DISPOSITION = disposition
    return _DISPOSITION or None


_DISPOSITION = None


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
    disposition = _disposition()
    if disposition is not None:
        try:
            return disposition.mem_key(props)
        except Exception:
            pass
    for field in ("id", "name", "display_name", "npc_role"):
        v = props.get(field)
        if v:
            return slug(v)
    return ""


def peek_actor_key(thing) -> str:
    """:func:`actor_key` for read-only callers: the same key, but the actor's
    properties are never written (no identity cache is stored on them)."""
    if thing is None:
        return ""
    if isinstance(thing, str):
        return slug(thing)
    props = getattr(thing, "properties", None)
    if not isinstance(props, dict):
        return ""
    if props.get("is_player") or props.get("_player"):
        return PLAYER_KEY
    disposition = _disposition()
    if disposition is not None:
        try:
            return disposition.peek_mem_key(props)
        except Exception:
            pass
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


def _xz(things):
    """An ``(n, 2)`` array of planar positions; a missing one is NaN, so it
    never compares as near (as :func:`perception.dist2d` makes it infinite)."""
    import numpy as np          # lazily: the package imports without NumPy
    out = np.full((len(things), 2), np.nan)
    for i, thing in enumerate(things):
        p = getattr(thing, "pos", None)
        if p is not None:
            out[i, 0] = p[0]
            out[i, 1] = p[2]
    return out


def _pad(radius: float) -> float:
    # Batched tests over-include by a hair; callers confirm with dist2d, so a
    # pair on the boundary is decided exactly as the scalar loop decides it.
    return (radius * 1.0001 + 1e-6) ** 2


def _near_pairs(points, radius: float, block: int = 64):
    """``(i, j)`` with ``i < j`` that may be within *radius*, in nested-loop
    order (by ``i``, then ``j``), computed a block of rows at a time so a
    caller that stops early never pays for the rest of the square."""
    import numpy as np
    n = len(points)
    r2 = _pad(radius)
    x, z = points[:, 0], points[:, 1]
    cols = np.arange(n)
    for start in range(0, n - 1, block):
        stop = min(n, start + block)
        dx = x[start:stop, None] - x[None, :]
        dz = z[start:stop, None] - z[None, :]
        hit = (dx * dx + dz * dz <= r2) & (cols[None, :] > np.arange(start, stop)[:, None])
        rows, js = np.nonzero(hit)
        yield from zip((rows + start).tolist(), js.tolist())


def _within(points, pos, radius: float):
    """Indices of *points* that may be within *radius* of *pos*, ascending."""
    import numpy as np
    if pos is None:
        return []
    dx = points[:, 0] - float(pos[0])
    dz = points[:, 1] - float(pos[2])
    return np.nonzero(dx * dx + dz * dz <= _pad(radius))[0].tolist()


def _unreported_crimes(facts):
    """The crimes in *facts* this holder has not yet reported, in order."""
    return [f for f in facts if crime.is_crime(f) and not f.get("reported")]


class _DirtyActors(set):
    """Dirty flags with a revision that survives a decision consuming a flag."""

    def __init__(self, keys=()):
        super().__init__(keys)
        self.revision = 0

    def add(self, key):
        super().add(key)
        self.revision += 1

    def clear(self):
        super().clear()
        self.revision += 1

    def update(self, *others):
        for other in others:
            for key in other:
                self.add(key)

    def __ior__(self, other):
        self.update(other)
        return self


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
                 on_message: Optional[Callable[[str], None]] = None,
                 on_witness=None, sight_test=None, region_for=None,
                 on_gossip=None):
        self.store = store
        self.clock = clock
        self.rng = rng
        self.bus = bus if bus is not None else EventBus()
        self.on_bounty = on_bounty
        self.on_message = on_message
        self.on_witness = on_witness
        self.sight_test = sight_test
        self.region_for = region_for
        #: ``on_gossip(speaker, listener, fact)``: somebody just told somebody
        #: something they did not know (the game voices it).
        self.on_gossip = on_gossip
        #: ``rumour_decay(fact) -> float | None``: how much certainty a fact
        #: loses each time it is retold (None: the usual amount).
        self.rumour_decay = None
        # Pure on-demand projection supplied by the living world. Sampling
        # uses evaluate(), while ordinary decisions may cache their results.
        self.mood_context = None
        self.mood_context_key = None
        self.fact_reader = None
        self.ctx = appraisal.Context(hostile=hostile, disposition=disposition,
                                     store=store)
        #: actor key -> ranked intents (recomputed when their knowledge changes)
        self._intents: Dict[str, List[Intent]] = {}
        self._dirty = _DirtyActors()
        self._intent_context = {}
        self._gossip_clock = 0.0
        self._coarse_clock = 0.0
        self._coarse_from = 0.0      # sim_time of the last coarse pass
        #: Game hours this simulation has run (the clock production reads).
        self.sim_time = 0.0
        self._prev_time = 0.0
        # Baseline the day at construction so the first day boundary that
        # actually passes is the first one that ages anybody's memory.
        self._last_day: Optional[int] = (
            int(getattr(clock, "day", 0) or 0) if clock is not None else None)
        #: Yields produced this tick, drained by the session which places them
        #: in the world (the director has no way to spawn an entity itself).
        self.pending_yields: List = []
        #: name -> attached subsystem, in attachment (tick / restore) order.
        self._systems: Dict[str, SimSystem] = {}

    # ------------------------------------------------------------ subsystems
    def attach(self, system: SimSystem) -> SimSystem:
        """Own *system*'s lifecycle from now on; returns it for the caller's handle."""
        if not system.name or system.name in self._systems:
            raise ValueError(f"subsystem needs a unique name, got {system.name!r}")
        self._systems[system.name] = system
        return system

    def system(self, name: str) -> Optional[SimSystem]:
        return self._systems.get(name)

    @property
    def systems(self) -> List[SimSystem]:
        return list(self._systems.values())

    def reset(self) -> None:
        """A new world: no history, no decided intents, every subsystem at its start."""
        self.bus.clear()
        self.invalidate()
        for system in self.systems:
            system.reset()

    # ------------------------------------------------------------------ time
    def _now(self):
        day = int(getattr(self.clock, "day", 0) or 0)
        hour = float(getattr(self.clock, "hour", 12.0) or 12.0)
        return day, hour

    def world_hours(self) -> float:
        """Absolute world time in game hours: what subsystems are ticked at."""
        if self.clock is None:
            return self.sim_time
        return (float(getattr(self.clock, "day", 0) or 0) * 24.0
                + float(getattr(self.clock, "hour", 0.0) or 0.0))

    # ----------------------------------------------------------- emit events
    def emit(self, kind: str, actor=None, target=None, pos=None,
             observers: Sequence = (), at=None, **data) -> WorldEvent:
        """Record something that happened and run it through the whole chain.

        *actor* and *target* may be entities or bare identity strings. *pos*
        defaults to the actor's position, then the target's. Everything else
        (an item id, a value, a damage number) rides along in ``data`` for the
        systems that care."""
        day, hour = self._now()
        if at is not None:
            day, hour = int(float(at) // 24), float(at) % 24
        akey = actor_key(actor)
        tkey = actor_key(target)
        if pos is None:
            pos = _pos(actor) or _pos(target) or (0.0, 0.0, 0.0)
        if self.region_for is not None and "law_region" not in data:
            data["law_region"] = self.region_for(pos)
        aprops = _props(actor)
        if aprops.get("_faction_cause"):
            data.setdefault("cause", dict(aprops["_faction_cause"]))
            data.setdefault("home", aprops["_faction_cause"]["home"])
            data.setdefault("journey", aprops.get("_journey", ""))
        if aprops and "actor_faction" not in data:
            data["actor_faction"] = str(aprops.get("faction")
                                        or aprops.get("team") or "")
        tprops = _props(target)
        if tprops and "target_faction" not in data:
            data["target_faction"] = str(tprops.get("faction") or tprops.get("team") or "")
        if aprops and "actor_alignment" not in data:
            from ..rpg import alignment
            data["actor_alignment"] = alignment.of_npc(dict(aprops))
        event = WorldEvent(
            kind, actor=akey, actor_name=actor_name(actor, akey or "someone"),
            target=tkey, target_name=actor_name(target, tkey or ""),
            pos=pos, day=day, hour=hour, data=data)
        self.bus.emit(event)
        percepts = self.dispatch(event, observers, actor_thing=actor, target_thing=target)
        if (event.is_crime and event.actor == PLAYER_KEY and percepts
                and self.on_witness is not None):
            self.on_witness(event, any(pc.mode == "sight" for pc in percepts))
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
                                        actor_thing=actor_thing, sight_test=self.sight_test)
        learned = 0
        for pc in percepts:
            key = actor_key(pc.observer)
            if not key or key == event.actor:
                continue
            fact = knowledge.fact_from_event(
                event, pc.clarity, knowledge.source_for(pc.mode))
            # A scream tells you where trouble is, not the culprit's name.
            fact["identified"] = pc.mode == "sight" and pc.clarity >= 0.3
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
                pc.observer.properties["asleep"] = False
                pc.observer.properties["sched_state"] = "AWAKENED"
                event.note(f"{actor_name(pc.observer)} was woken by the noise")

        # The victim always knows, witnesses or not — unless the event was
        # their death, which is the one thing nobody gets to remember.
        if (target_thing is not None and event.target
                and event.data.get("victim_knows", True)
                and event.target != event.actor
                and not _props(target_thing).get("dead")):
            victim_percept = next((pc for pc in percepts if pc.observer is target_thing), None)
            fact = knowledge.fact_from_event(event, 1.0, knowledge.SOURCE_WITNESSED)
            # A living victim knows who struck them, even if the event's
            # sight/sound witness classification was obscured (e.g. at night).
            # Other crimes retain the usual eyewitness-identification rule.
            fact["identified"] = ("violence" in event.tags or bool(
                victim_percept and victim_percept.mode == "sight"))
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
        if fact.get("actor") != PLAYER_KEY or not fact.get("identified", True):
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
    @property
    def knowledge_revision(self):
        return self._dirty.revision

    def evaluate(self, thing) -> List[Intent]:
        """Read-only appraisal at a mention/materialisation/journey touchpoint."""
        props = _props(thing)
        key = peek_actor_key(thing)
        facts = self.fact_reader(key) if self.fact_reader is not None else knowledge.facts(self.store, key)
        mood = self.mood_context(thing, facts) if self.mood_context is not None else None
        # Appraisal reads a detached copy, so nothing it does reaches the actor.
        return appraisal.appraise_all(dict(props), key, facts, self.ctx, mood=mood)

    def intents(self, thing, refresh: bool = False) -> List[Intent]:
        """This actor's ranked intents, recomputed only when their beliefs moved."""
        key = actor_key(thing)
        if not key:
            return []
        context = self.mood_context_key(thing) if self.mood_context_key is not None else None
        if (refresh or key in self._dirty or key not in self._intents
                or self._intent_context.get(key) != context):
            self._intents[key] = self.evaluate(thing)
            self._intent_context[key] = context
            self._dirty.discard(key)
        return self._intents[key]

    def cached_intents(self, key: str) -> Optional[List[Intent]]:
        """The intents already decided for *key*, or None while they are stale.

        Never appraises, so a sampler can read decisions without making one:
        the cache, dirty flags and revision are untouched."""
        if key in self._dirty or key not in self._intents:
            return None
        return list(self._intents[key])

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
            self._intent_context.clear()
            self._dirty.clear()
            return
        key = actor_key(thing)
        if key:
            self._dirty.add(key)

    def knowledge_lines(self, thing, limit: int = 8) -> List[str]:
        return knowledge.summary(self.store, peek_actor_key(thing), limit)

    # ----------------------------------------------------------------- ticks
    def tick(self, actors: Sequence, hours: float, distant: Sequence = ()) -> None:
        """Advance the parts of the simulation that run on their own clock:
        rumour propagation, crime reporting and production.

        By simulation detail (the world streamer's tiers):

        * *actors* -- near the player (NEAR / ACTIVE): every tick, gossip
          every :data:`GOSSIP_INTERVAL_HOURS`;
        * *distant* -- DISTANT: one coarse pass every
          :data:`COARSE_INTERVAL_HOURS` covering the whole interval (their
          gossip among themselves, their reports, their production);
        * anyone in neither -- DORMANT, parked: nothing at all. Production
          and memory catch up from per-actor stamps the next time they are
          in one of the lists.
        """
        hours = max(0.0, float(hours))
        self._prev_time = self.sim_time
        self.sim_time += hours
        actors = [a for a in (actors or ()) if not _props(a).get("dead")]
        distant = [a for a in (distant or ()) if not _props(a).get("dead")]
        self._gossip_clock += hours
        if self._gossip_clock >= GOSSIP_INTERVAL_HOURS:
            self._gossip_clock = 0.0
            self.spread_rumours(actors)
        self.resolve_reports(actors)
        self.tick_production(actors)
        if distant:
            self._coarse_clock += hours
            if self._coarse_clock >= COARSE_INTERVAL_HOURS:
                self._coarse_clock = 0.0
                self.spread_rumours(distant)
                self.resolve_reports(distant)
                self.tick_production(distant, since=self._coarse_from)
                self._coarse_from = self.sim_time
        else:
            self._coarse_clock = 0.0
            self._coarse_from = self.sim_time
        self._roll_day(actors + distant)
        # Subsystems sample the state this pass just produced.
        now = self.world_hours()
        for system in self.systems:
            system.tick(now)

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
        n = len(awake)
        keys = [actor_key(a) for a in awake]
        # Every pair in nested-loop order; a crowd batches the distance test.
        pairs = (_near_pairs(_xz(awake), GOSSIP_RADIUS) if n >= VECTOR_MIN
                 else ((i, j) for i in range(n) for j in range(i + 1, n)))
        for i, j in pairs:
            if exchanges >= GOSSIP_BUDGET:
                break
            skey, lkey = keys[i], keys[j]
            if not skey or not lkey or lkey == skey:
                continue
            speaker, listener = awake[i], awake[j]
            if perception.dist2d(_pos(speaker), _pos(listener)) > GOSSIP_RADIUS:
                continue
            passed = knowledge.gossip(self.store, skey, lkey, self.rng,
                                      decay=self.rumour_decay)
            back = knowledge.gossip(self.store, lkey, skey, self.rng,
                                    decay=self.rumour_decay)
            if passed:
                self._dirty.add(lkey)
                self._on_learned(listener, lkey, passed[0])
            if back:
                self._dirty.add(skey)
                self._on_learned(speaker, skey, back[0])
            if self.on_gossip is not None:
                if passed:
                    self.on_gossip(speaker, listener, passed[0])
                elif back:
                    self.on_gossip(listener, speaker, back[0])
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
        living = [a for a in actors if not _props(a).get("dead")]
        actors = [a for a in living if not perception._is_asleep(_props(a))]
        lawful = [a for a in living if crime.is_lawful(_props(a))]
        charges = 0

        # (1) an ordinary witness passes a crime on to a nearby lawful actor
        okeys = officers = None
        for witness in actors:
            wkey = actor_key(witness)
            if not wkey or crime.is_lawful(_props(witness)):
                continue
            # Read-only: tell() copies a fact before passing it on.
            crimes = knowledge.derived_view(self.store, wkey, _unreported_crimes)
            if not crimes:
                continue
            if okeys is None:
                okeys = [actor_key(officer) for officer in lawful]
                officers = _xz(lawful) if len(lawful) >= VECTOR_MIN else None
            # In list order, so the first officer in reach is still the one told.
            reach = (range(len(lawful)) if officers is None
                     else _within(officers, _pos(witness), TELL_RADIUS))
            for k in reach:
                officer, okey = lawful[k], okeys[k]
                if not okey or okey == wkey:
                    continue
                if perception.dist2d(_pos(witness), _pos(officer)) > TELL_RADIUS:
                    continue
                if self.sight_test is not None and not self.sight_test(witness, _pos(officer)):
                    continue
                # A messenger at arm's length can wake the night watch; they
                # still have to make the journey rather than report remotely.
                if perception._is_asleep(_props(officer)):
                    officer.properties.update(asleep=False, awake=True, sched_state="AWAKENED")
                for f in crimes:
                    if knowledge.tell(self.store, wkey, okey, f):
                        self._dirty.add(okey)
                        ev = self.bus.get(f.get("e", 0))
                        if ev is not None:
                            ev.note(f"{actor_name(witness)} reported it to "
                                    f"{actor_name(officer)}")
                    knowledge.mark_reported(self.store, wkey, f.get("e", 0))
                    self._dirty.add(wkey)
                break

        # (2) a lawful actor who knows about an unreported crime lays the charge
        for officer in lawful:
            if perception._is_asleep(_props(officer)):
                continue
            okey = actor_key(officer)
            if not okey:
                continue
            oprops = _props(officer)
            # Only crimes not yet reported can be charged (report() checks the
            # rest). A snapshot: marking one reported does not change this list.
            for f in knowledge.derived_view(self.store, okey, _unreported_crimes):
                amount = crime.report(self.store, f, okey, oprops)
                if amount <= 0:
                    continue
                knowledge.mark_reported(self.store, okey, f.get("e", 0))
                charges += 1
                ev = self.bus.get(f.get("e", 0))
                if f.get("actor") == PLAYER_KEY and self.on_bounty is not None:
                    # The bounded history may have shed an old crime. Testimony
                    # still carries the scene's jurisdiction and charge value.
                    reported_event = ev or WorldEvent(
                        f.get("kind", ""), actor=f.get("actor", ""),
                        pos=f.get("pos"), day=f.get("day", 0), hour=f.get("hour", 0),
                        data={"law_region": f.get("law_region", ""),
                              "crime": f.get("crime", True)})
                    reported_event.id = int(f.get("e", 0))
                    try:
                        self.on_bounty(amount, reported_event, okey)
                    except Exception:
                        pass
                if ev is not None:
                    ev.note(f"{actor_name(officer)} laid a charge "
                            f"({amount} gold bounty)")
                self._dirty.add(okey)
        return charges

    def tick_production(self, actors: Sequence, hours: Optional[float] = None,
                        since: Optional[float] = None) -> List:
        """Advance every producing object; queue what they made.

        Each producer advances by the simulation time since it was last
        advanced (its :data:`SIM_AT_KEY` stamp), so one visited every tick
        moves by the tick, a distant one by the coarse interval, and one the
        streamer parked for hours catches up in one step on its return
        (production itself never banks more than a batch). One never seen
        before counts from *since* (default: the previous tick; the coarse
        pass passes its own last run). *hours*, when given, advances everyone
        by exactly that instead.

        The director cannot create entities, so yields are queued for the
        session (which knows how to place an item in the scene) to drain."""
        made = []
        now = self.sim_time
        fresh = self._prev_time if since is None else float(since)
        for thing in actors:
            props = _props(thing)
            if not production.is_producer(props):
                continue
            if hours is None:
                try:
                    stamp = float(props.get(SIM_AT_KEY, fresh))
                except (TypeError, ValueError):
                    stamp = fresh
                if stamp > now:              # a stamp from an earlier session
                    stamp = fresh
                step = now - stamp
            else:
                step = hours
            props[SIM_AT_KEY] = now
            for y in production.advance(props, step):
                made.append((thing, y))
        if made:
            self.pending_yields.extend(made)
        return made

    def drain_yields(self) -> List:
        """Take the queued production output (the session places it in the world)."""
        out, self.pending_yields = self.pending_yields, []
        return out

    def _roll_day(self, actors: Sequence) -> None:
        """At each day boundary, let everyone's knowledge fade a little.

        By each actor's own :data:`SIM_DAY_KEY` stamp: one the simulation did
        not visit at the last boundary (parked) fades by every day it missed
        at the next boundary it is visited on."""
        day, _hour = self._now()
        if self._last_day is None:
            self._last_day = day
            return
        if day == self._last_day:
            return
        last = self._last_day
        self._last_day = day
        for thing in actors:
            key = actor_key(thing)
            if not key:
                continue
            props = _props(thing)
            try:
                since = int(props.get(SIM_DAY_KEY, last))
            except (TypeError, ValueError):
                since = last
            elapsed = day - since if since < day else (1 if since == last else 0)
            props[SIM_DAY_KEY] = day
            if elapsed > 0:
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
        for system in self.systems:
            system.persist()

    def restore(self) -> int:
        """The history first, then each subsystem; returns the events loaded."""
        loaded = 0
        if self.store is not None:
            loaded = self.bus.load_json(self.store.get(self.HISTORY_KEY, ""))
        for system in self.systems:
            system.restore()
        return loaded

    # ------------------------------------------------------------ inspection
    def report_lines(self, limit: int = 25) -> List[str]:
        """The World Event / History view's text form (newest first)."""
        out = []
        for ev in self.bus.recent(limit=limit):
            out.append(f"[{ev.timestamp()}] {ev.describe()}")
            for c in ev.consequences:
                out.append(f"      ↳ {c}")
        return out
