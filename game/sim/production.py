"""
Production — objects that make other objects.

A cow is not a milk quest. A cow is an entity with three authored fields::

    produces            = "milk"     # an item id from the ordinary item DB
    produce_every_hours = 8.0
    produce_into        = "world"    # or "self" (into its own inventory)

Every ``produce_every_hours`` of game time it yields one stack. Because the
yield is an ordinary item and the producer's ``owner`` is copied onto it, the
bucket of milk that appears beside the cow is *owned by the farmer* — which
means it can be carried, traded, given, dropped, and stolen, and stealing it is
a crime with witnesses, a bounty and a farmer who remembers, none of which was
written for milk.

The same three fields make a hen that lays eggs, a well that fills buckets, a
mine cart that accumulates ore, or an alchemist's still — with no new code.

State is kept on the producer's own property dict (``_produce_progress``), so it
serialises with the entity for free.
"""

from __future__ import annotations

from typing import Dict, List, Optional

PROGRESS = "_produce_progress"

#: Where the yield goes.
INTO_WORLD = "world"   # spawns a takeable item beside the producer
INTO_SELF = "self"     # accumulates in the producer's own inventory

DEFAULT_INTERVAL = 8.0
#: A producer stops once this many un-collected yields are outstanding, so an
#: unvisited farm does not carpet the map in buckets.
DEFAULT_MAX_PENDING = 3


class Yield:
    """One produced stack, ready for the caller to place in the world."""

    __slots__ = ("item_id", "quantity", "owner", "owner_name", "owner_faction")

    def __init__(self, item_id: str, quantity: int = 1, owner: str = "",
                 owner_name: str = "", owner_faction: str = ""):
        self.item_id = str(item_id)
        self.quantity = max(1, int(quantity))
        self.owner = str(owner or "")
        self.owner_name = str(owner_name or "")
        self.owner_faction = str(owner_faction or "")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Yield {self.quantity}x{self.item_id} owner={self.owner_name!r}>"


def is_producer(props: Optional[Dict]) -> bool:
    return bool(isinstance(props, dict) and str(props.get("produces", "") or "").strip())


def interval_of(props: Dict) -> float:
    try:
        v = float(props.get("produce_every_hours", DEFAULT_INTERVAL))
    except (TypeError, ValueError):
        v = DEFAULT_INTERVAL
    return max(0.05, v)


def max_pending(props: Dict) -> int:
    try:
        return max(1, int(props.get("produce_max", DEFAULT_MAX_PENDING)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PENDING


def pending(props: Dict) -> int:
    """How many yields are outstanding beside this producer right now."""
    try:
        return max(0, int(props.get("_produce_pending", 0)))
    except (TypeError, ValueError):
        return 0


def note_collected(props: Dict, count: int = 1) -> None:
    """Tell a producer one of its outstanding yields was taken, so it resumes."""
    props["_produce_pending"] = max(0, pending(props) - max(1, int(count)))


def advance(props: Dict, hours: float) -> List[Yield]:
    """Advance a producer by *hours* of game time; return what it yielded.

    A dead producer yields nothing — a slaughtered cow stops giving milk, which
    is exactly the sort of consequence the player should be able to cause and
    the designer should never have to write."""
    if not is_producer(props) or props.get("dead"):
        return []
    hours = float(hours)
    if hours <= 0:
        return []
    if pending(props) >= max_pending(props):
        return []

    try:
        progress = float(props.get(PROGRESS, 0.0))
    except (TypeError, ValueError):
        progress = 0.0
    progress += hours
    every = interval_of(props)
    out: List[Yield] = []
    room = max_pending(props) - pending(props)
    while progress >= every and len(out) < room:
        progress -= every
        out.append(_make_yield(props))
    # Never bank more than one interval of unspent progress: an unvisited farm
    # should not fire a dozen yields the instant the player walks in.
    props[PROGRESS] = round(min(progress, every), 4)
    if out:
        props["_produce_pending"] = pending(props) + len(out)
    return out


def _make_yield(props: Dict) -> Yield:
    from . import ownership
    try:
        qty = max(1, int(props.get("produce_quantity", 1)))
    except (TypeError, ValueError):
        qty = 1
    # The yield inherits the producer's owner: milk from the farmer's cow is the
    # farmer's milk. An unowned wild animal produces unowned goods.
    return Yield(str(props.get("produces", "")).strip(), qty,
                 owner=ownership.owner_of(props),
                 owner_name=ownership.owner_name_of(props),
                 owner_faction=ownership.owner_faction_of(props))


def time_to_next(props: Dict) -> float:
    """Hours until the next yield — shown in the editor's object inspector."""
    if not is_producer(props):
        return 0.0
    try:
        progress = float(props.get(PROGRESS, 0.0))
    except (TypeError, ValueError):
        progress = 0.0
    return max(0.0, interval_of(props) - progress)


def describe(props: Dict) -> str:
    """A one-line production summary for the object inspector."""
    if not is_producer(props):
        return "produces nothing"
    item = str(props.get("produces", ""))
    every = interval_of(props)
    where = "into the world" if str(props.get("produce_into", INTO_WORLD)) == INTO_WORLD \
        else "into its own inventory"
    return (f"produces {item} every {every:g}h {where} "
            f"({pending(props)}/{max_pending(props)} waiting, "
            f"next in {time_to_next(props):.1f}h)")
