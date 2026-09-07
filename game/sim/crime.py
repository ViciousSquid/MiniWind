"""
Crime and consequence — a bounty is what *other people do about it*.

The important inversion here: committing a crime does not, by itself, do
anything. A crime becomes a bounty only when somebody who knows about it tells
the law. That single rule is what makes all of the following fall out of the
simulation without a line of scenario code:

* murder the only witness and there is no bounty — until the body is found
* rob a house at night while the street sleeps and walk away clean
* rob it at noon and the baker who saw you has to *survive the walk* to a guard
* a guard who witnesses it himself needs no messenger
* a rumour that reaches a guard days later still lands the bounty

Reporting is deduplicated per event in the shared KV store, so ten witnesses to
one murder produce one bounty, not ten — while ten separate murders produce ten.
"""

from __future__ import annotations

from typing import Dict, Optional

from . import ownership
from .events import kind_spec

#: Bounty each crime kind carries. Theft is scaled by the value taken (see
#: :func:`bounty_for`); the rest are flat, in the tradition of the genre.
CRIME_BOUNTY: Dict[str, int] = {
    "attack": 40,
    "death": 1000,
    "theft": 25,
    "trespass": 5,
}

#: How much a crime costs the offender in the victim's own eyes. These map onto
#: the existing per-NPC disposition memory events so there is exactly one
#: opinion model in the game.
CRIME_MEMORY = {
    "attack": "assaulted",
    "theft": "robbed",
    "death": "kin_slain",
}

#: Factions whose members will act on a crime themselves rather than needing to
#: find someone who will. Data, not a role check, so a settlement can author its
#: own militia, temple guard or thieves' court. The player is deliberately not
#: here: the player is who the law is *for*.
LAW_FACTIONS = {"guards"}

#: Below this certainty a witness is not sure enough to swear to it.
REPORT_CERTAINTY = 0.3


def is_crime(subject) -> bool:
    """Whether *subject* is an offence — an event, a stored fact, or a bare kind.

    A per-occurrence ``crime`` flag always wins over the kind's default tags, so
    a lawful killing carried through the same pipeline never becomes a bounty
    (see :attr:`game.sim.events.WorldEvent.is_crime`)."""
    if isinstance(subject, dict):
        override = subject.get("crime")
        kind = subject.get("kind", "")
    else:
        override = getattr(subject, "data", {}).get("crime") \
            if hasattr(subject, "data") else None
        kind = getattr(subject, "kind", subject)
    if override is not None:
        return bool(override)
    return "crime" in kind_spec(str(kind))["tags"]


def is_lawful(props: Optional[Dict]) -> bool:
    """Whether this actor can act on a crime report directly (a guard).

    Recognised by faction membership or by the ``lawful`` property, so an
    authored bailiff or a modded temple warden works without touching code."""
    if not isinstance(props, dict):
        return False
    if props.get("lawful"):
        return True
    fac = str(props.get("faction") or props.get("team") or "").lower()
    if fac in LAW_FACTIONS:
        return True
    return str(props.get("npc_role", "")).lower().startswith("guard")


def bounty_for(event) -> int:
    """The bounty this event would carry if reported.

    A theft's bounty scales with what was taken, so pocketing a bucket of milk
    is not a hanging offence and emptying a strongbox is."""
    kind = str(getattr(event, "kind", ""))
    base = int(CRIME_BOUNTY.get(kind, 0))
    if base <= 0:
        return 0
    if kind == "theft":
        data = getattr(event, "data", None) or {}
        value = ownership.theft_value(data)
        return max(base, base + int(value))
    return base


def _reported_key(event_id: int) -> str:
    return f"crime.{int(event_id)}.reported"


def already_reported(store, event_id: int) -> bool:
    if store is None or not event_id:
        return False
    return str(store.get(_reported_key(event_id), "false")).lower() in (
        "1", "true", "yes")


def mark_reported(store, event_id: int, reporter: str = "") -> None:
    if store is None or not event_id:
        return
    store.set(_reported_key(event_id), "1")
    if reporter:
        store.set(f"crime.{int(event_id)}.reporter", str(reporter))


def can_report(fact: Dict, witness_props: Optional[Dict],
               witness_key: str = "") -> bool:
    """Whether this witness is willing and able to lay the charge themselves.

    They must be lawful, sure enough of what they know, and not the offender —
    nobody turns themselves in, which is why a corrupt guard who commits the
    crime himself walks away from it."""
    if not isinstance(fact, dict):
        return False
    if witness_key and fact.get("actor") == witness_key:
        return False
    if float(fact.get("certainty", 0.0)) < REPORT_CERTAINTY:
        return False
    if fact.get("reported"):
        return False
    if not is_crime(fact):
        return False
    return is_lawful(witness_props)


def report(store, fact: Dict, witness_key: str = "",
           witness_props: Optional[Dict] = None) -> int:
    """Lay a charge for the crime in *fact*; returns the bounty to apply.

    Returns 0 when the witness cannot report, or when this crime has already
    been reported by somebody else — one crime, one bounty."""
    if not can_report(fact, witness_props, witness_key):
        return 0
    event_id = int(fact.get("e", 0) or 0)
    if already_reported(store, event_id):
        return 0
    from .events import WorldEvent
    # The fact carries the value that was recorded on the original event, so a
    # charge laid days later still fits the crime.
    stub = WorldEvent(fact.get("kind", ""),
                      data={"value": int(fact.get("value", 0) or 0)})
    amount = bounty_for(stub)
    if amount <= 0:
        return 0
    mark_reported(store, event_id, witness_key)
    return amount


def memory_event(kind: str) -> str:
    """The :mod:`game.rpg.disposition` memory event a crime kind maps onto."""
    return CRIME_MEMORY.get(str(kind), "")


def unsolved(store, bus, limit: int = 20):
    """Crimes in the event history that nobody has reported yet.

    The editor's history view flags these — a designer can see at a glance that
    the town has three unreported thefts walking around inside people's heads."""
    out = []
    for ev in bus.recent(limit=200, tag="crime"):
        if not already_reported(store, ev.id):
            out.append(ev)
        if len(out) >= max(1, int(limit)):
            break
    return out
