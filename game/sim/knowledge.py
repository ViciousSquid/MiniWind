"""
Knowledge — what each actor *believes*, how sure they are, and where it came from.

A witness stores a **Fact**: a compressed copy of an event plus the two fields
that make information behave like information — ``certainty`` (0-1) and
``source`` (``witnessed`` / ``heard`` / ``told``). Because a fact is data and
not a flag, the same store serves testimony, suspicion and gossip:

* A guard who *saw* the murder is certain, and reports it.
* A cook who only *heard* a scream knows something violent happened and can
  describe it badly.
* Anyone they talk to afterwards gets the fact **told**, at a decayed
  certainty — so the news spreads through the settlement at walking pace, can
  be outrun, and dies with the last person who knew it.

Facts live in the same persistent KV store as the disposition memory
(:mod:`game.rpg.disposition`), keyed by the actor's stable identity, so
knowledge survives save/load and can be inspected in the editor.

Pure Python + a string KV store.
"""

from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional, Sequence

#: Most facts kept per actor (oldest, least certain shed first). NPCs are not
#: archives; a town gradually forgets, which keeps old news from dominating.
FACT_CAP = 24

#: Below this certainty a fact is no longer worth repeating or acting on.
FORGET_BELOW = 0.12

#: Certainty lost each time a fact is passed from one mouth to the next.
TELL_DECAY = 0.2
#: Certainty lost per in-game day for facts that were only heard or told.
DAILY_DECAY = 0.06
#: Witnessed facts fade far more slowly — you remember what you saw.
DAILY_DECAY_WITNESSED = 0.015

SOURCE_WITNESSED = "witnessed"
SOURCE_HEARD = "heard"
SOURCE_TOLD = "told"

#: How a fact's source reads in the inspector / dialogue flavour.
SOURCE_PHRASE = {
    SOURCE_WITNESSED: "saw it",
    SOURCE_HEARD: "heard it happen",
    SOURCE_TOLD: "was told",
}


def _base(key: str) -> str:
    return f"npc.{key}.facts"


# ---------------------------------------------------------------------------
# Building facts
# ---------------------------------------------------------------------------
def fact_from_event(event, certainty: float, source: str,
                    told_by: str = "") -> Dict:
    """Compress a :class:`~game.sim.events.WorldEvent` into a stored belief.

    Only the fields an NPC could plausibly retain are kept: what happened, who
    to whom, roughly where and when. A perceiver who was uncertain keeps the
    *same* fields — uncertainty lives in the number, not in missing data, so
    every consumer can treat all facts alike."""
    return {
        "e": int(getattr(event, "id", 0) or 0),
        "kind": str(getattr(event, "kind", "")),
        "actor": str(getattr(event, "actor", "")),
        "actor_name": str(getattr(event, "actor_name", "")),
        "target": str(getattr(event, "target", "")),
        "target_name": str(getattr(event, "target_name", "")),
        "day": int(getattr(event, "day", 0) or 0),
        "hour": round(float(getattr(event, "hour", 0.0) or 0.0), 2),
        "pos": [round(float(c), 1) for c in (getattr(event, "pos", None) or (0, 0, 0))],
        "item": str((getattr(event, "data", None) or {}).get("item", "")),
        # Whether this occurrence was an offence travels with the fact, so a
        # lawful killing stays lawful however far the story is passed on.
        "crime": bool(getattr(event, "is_crime", False)),
        "certainty": max(0.0, min(1.0, float(certainty))),
        "source": str(source),
        "from": str(told_by or ""),
        "reported": False,
    }


def source_for(mode: str) -> str:
    """Map a perception mode onto a knowledge source."""
    return SOURCE_WITNESSED if mode == "sight" else SOURCE_HEARD


# ---------------------------------------------------------------------------
# Reading / writing an actor's facts
# ---------------------------------------------------------------------------
def facts(store, key: str) -> List[Dict]:
    """Every fact this actor currently believes (most recent last)."""
    if store is None or not key:
        return []
    raw = store.get(_base(key), "")
    if raw in (None, "", "false"):
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [f for f in data if isinstance(f, dict)] if isinstance(data, list) else []


def _write(store, key: str, items: Sequence[Dict]) -> None:
    if store is None or not key:
        return
    # Shed the least useful first: low certainty, then oldest.
    items = [f for f in items if float(f.get("certainty", 0)) >= FORGET_BELOW]
    if len(items) > FACT_CAP:
        items = sorted(items, key=lambda f: (float(f.get("certainty", 0)),
                                             int(f.get("day", 0))),
                       reverse=True)[:FACT_CAP]
        items = sorted(items, key=lambda f: (int(f.get("day", 0)),
                                             float(f.get("hour", 0.0))))
    try:
        store.set(_base(key), json.dumps(items))
    except (TypeError, ValueError):
        pass


def learn(store, key: str, fact: Dict) -> bool:
    """Fold *fact* into this actor's knowledge.

    Returns ``True`` when it was genuinely new information — either an event
    they had not heard of, or a more certain account of one they had. Learning
    the same rumour twice from two mouths is not news, which is what stops
    gossip from ringing endlessly around a settlement."""
    if store is None or not key or not isinstance(fact, dict):
        return False
    if float(fact.get("certainty", 0.0)) < FORGET_BELOW:
        return False
    existing = facts(store, key)
    eid = int(fact.get("e", 0) or 0)
    for i, f in enumerate(existing):
        if eid and int(f.get("e", 0) or 0) == eid:
            if float(fact["certainty"]) > float(f.get("certainty", 0.0)) + 1e-6:
                # A better account of something already known: upgrade in place
                # and carry over whether it was already reported to the law.
                merged = dict(fact)
                merged["reported"] = bool(f.get("reported"))
                existing[i] = merged
                _write(store, key, existing)
                return True
            return False
    existing.append(dict(fact))
    _write(store, key, existing)
    return True


def knows(store, key: str, event_id: int) -> Optional[Dict]:
    """This actor's belief about a specific event, if they hold one."""
    for f in facts(store, key):
        if int(f.get("e", 0) or 0) == int(event_id):
            return f
    return None


def knows_about(store, key: str, kind: str = "", actor: str = "",
                target: str = "", min_certainty: float = FORGET_BELOW) -> List[Dict]:
    """Facts matching a coarse query — the generic 'do you know anything about
    X?' used by dialogue, appraisal and the inspector alike."""
    out = []
    for f in facts(store, key):
        if kind and f.get("kind") != kind:
            continue
        if actor and f.get("actor") != actor:
            continue
        if target and f.get("target") != target:
            continue
        if float(f.get("certainty", 0.0)) < min_certainty:
            continue
        out.append(f)
    return out


def mark_reported(store, key: str, event_id: int) -> None:
    """Flag that this actor has already told the law about an event, so the
    same witness cannot generate a second bounty for one crime."""
    items = facts(store, key)
    changed = False
    for f in items:
        if int(f.get("e", 0) or 0) == int(event_id) and not f.get("reported"):
            f["reported"] = True
            changed = True
    if changed:
        _write(store, key, items)


def forget_all(store, key: str) -> None:
    if store is not None and key:
        store.set(_base(key), "[]")


# ---------------------------------------------------------------------------
# Rumour propagation
# ---------------------------------------------------------------------------
def shareable(fact: Dict) -> bool:
    """Whether a fact is worth repeating: certain enough to state, and about
    something a person would actually bring up."""
    from .events import kind_spec
    if float(fact.get("certainty", 0.0)) < FORGET_BELOW + TELL_DECAY:
        return False
    return "notable" in kind_spec(fact.get("kind", ""))["tags"]


def tell(store, speaker_key: str, listener_key: str, fact: Dict,
         decay: float = TELL_DECAY) -> bool:
    """Pass one fact from speaker to listener at a decayed certainty."""
    told = dict(fact)
    told["certainty"] = max(0.0, float(fact.get("certainty", 0.0)) - float(decay))
    told["source"] = SOURCE_TOLD
    told["from"] = str(speaker_key)
    told["reported"] = False   # hearsay has not been reported by *this* mouth
    return learn(store, listener_key, told)


def gossip(store, speaker_key: str, listener_key: str, rng=None,
           limit: int = 1) -> List[Dict]:
    """One conversation: the speaker passes on up to *limit* of their most
    interesting shareable facts. Returns the facts that were genuinely news.

    This is the whole rumour system. Whether two people ever have this
    conversation is the caller's business (proximity, schedule, faction), which
    keeps information spread a property of the world rather than a script."""
    if store is None or not speaker_key or not listener_key:
        return []
    if speaker_key == listener_key:
        return []
    pool = [f for f in facts(store, speaker_key) if shareable(f)]
    if not pool:
        return []
    # Most interesting first: certainty × how much the event kind matters.
    from .events import kind_spec
    pool.sort(key=lambda f: -(float(f.get("certainty", 0.0))
                              * float(kind_spec(f.get("kind", ""))["severity"])))
    if rng is not None and len(pool) > 1:
        # A little noise so the same pair doesn't always trade the same story.
        head = pool[:3]
        rng.shuffle(head)
        pool = head + pool[3:]
    passed = []
    for f in pool[:max(1, int(limit))]:
        if tell(store, speaker_key, listener_key, f):
            passed.append(f)
    return passed


def decay(store, key: str, days: int = 1) -> int:
    """Age this actor's knowledge by *days*; returns how many facts survived.

    Hearsay fades fast, testimony slowly. Called once per in-game day, this is
    what lets a settlement genuinely move on — and what makes lying low until
    the story is forgotten a real strategy rather than an authored option."""
    items = facts(store, key)
    if not items:
        return 0
    n = max(0, int(days))
    for f in items:
        rate = (DAILY_DECAY_WITNESSED if f.get("source") == SOURCE_WITNESSED
                else DAILY_DECAY)
        f["certainty"] = max(0.0, float(f.get("certainty", 0.0)) - rate * n)
    kept = [f for f in items if float(f["certainty"]) >= FORGET_BELOW]
    _write(store, key, kept)
    return len(kept)


def describe(fact: Dict) -> str:
    """A display-ready line for the inspector and gossip dialogue."""
    from .events import WorldEvent
    ev = WorldEvent(fact.get("kind", ""), actor_name=fact.get("actor_name", ""),
                    target_name=fact.get("target_name", ""),
                    data={"item": fact.get("item", "")})
    phrase = ev.describe()
    src = SOURCE_PHRASE.get(fact.get("source", ""), fact.get("source", ""))
    pct = int(round(float(fact.get("certainty", 0.0)) * 100))
    return f"{phrase} — {src}, {pct}% sure (day {fact.get('day', 0)})"


def summary(store, key: str, limit: int = 8) -> List[str]:
    """The inspector's 'what does this person know?' list, most certain first."""
    items = sorted(facts(store, key),
                   key=lambda f: -float(f.get("certainty", 0.0)))
    return [describe(f) for f in items[:max(1, int(limit))]]
