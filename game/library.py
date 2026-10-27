"""
Books in the world: which book turns up where, and who deals in them.

Every book item names the places it is found in with ``"found"`` in
``game/data/items.json``:

* ``town`` -- in homes and cottages, and in townsfolk's pockets;
* ``shop`` -- on the shelves of the merchants who deal in books;
* ``shrine`` -- at shrines, chapels and holy ruins;
* ``wild`` -- in caves, ruins, camps and the nests of things under the hills;
* ``bandit`` -- in brigand camps and on brigands;
* ``cult`` -- among the Ashen Circle.

The world tool (game/tools/furnish_world.py) lays books out by these, the
merchants stock them by these (game/ui/screens.py), and the loot tables
(game/rpg/loot.py) draw on them.

**Notes** are the short things: a shopping list, a poem, a page torn from
the Millbrook Crier, a list of names nobody should be on. They are book items
too (``"note": true``) -- read, carried, sold like any book -- but no shop
keeps them. Wherever the world gets a book, it is a note half the time
(:data:`NOTE_SHARE`).

Not every merchant deals in books. A smith, an armourer, a brewer, a hunter,
a cook or a farmer has no shelf for them: they will not sell you one, and
will not buy one from you (``"I'm not interested in that"``). Anyone else
who trades does both. An authored ``buys_books`` on the merchant decides it
outright.

Pure Python, no Qt; every pick is seeded, so the same world always gets the
same books.
"""

from __future__ import annotations

import random
import zlib
from typing import Dict, Iterable, List, Optional

TOWN = "town"
SHOP = "shop"
SHRINE = "shrine"
WILD = "wild"
BANDIT = "bandit"
CULT = "cult"
PLACES = (TOWN, SHOP, SHRINE, WILD, BANDIT, CULT)

#: Roles that keep no shelf for books.
NO_BOOK_ROLES = frozenset({"blacksmith", "armourer", "farmer"})
#: Words in a merchant's name or title that mark a trade with no use for books.
NO_BOOK_TRADES = ("smith", "armourer", "brewer", "hunter", "chef", "cook",
                  "farmer", "butcher", "fisher")
#: How many titles a bookish merchant keeps on the shelf.
SHOP_TITLES = 5

#: The share of the writing lying about the world that is a note, not a book.
NOTE_SHARE = 0.5

#: What a merchant says to a book they have no use for.
NOT_INTERESTED = "I'm not interested in that"


def _writing(where: Optional[str], notes: bool) -> List[str]:
    from .rpg import items
    out = []
    for d in items.items_by_category(items.BOOK):
        found = d.get("found") or ()
        if bool(d.get("note")) == notes and (where is None or where in found):
            out.append(d.id)
    return sorted(out)


def books(where: Optional[str] = None) -> List[str]:
    """Every book (not note) item id, or those found in *where*, in a
    stable order."""
    return _writing(where, notes=False)


def notes(where: Optional[str] = None) -> List[str]:
    """Every note item id, or those found in *where*, in a stable order."""
    return _writing(where, notes=True)


def is_book(item_id) -> bool:
    from .rpg import items
    d = items.get(item_id)
    return d is not None and d.category == items.BOOK


def seeded(*parts) -> random.Random:
    """A random stream fixed by *parts* (names, ids): the same every run."""
    key = "|".join(str(p) for p in parts)
    return random.Random(zlib.crc32(key.encode("utf-8")))


def pick(rng: random.Random, where: str, exclude: Iterable[str] = ()) -> Optional[str]:
    """Something to read found in *where* -- a note :data:`NOTE_SHARE` of
    the time, else a book -- not one of *exclude*; None if there is none."""
    skip = set(exclude)
    shelves = [books(where), notes(where)]
    if rng.random() < NOTE_SHARE:
        shelves.reverse()
    for shelf in shelves:
        pool = [b for b in shelf if b not in skip]
        if pool:
            return rng.choice(pool)
    return None


def _merchant_words(props: Dict) -> str:
    return " ".join(str(props.get(k) or "") for k in ("display_name", "name")).lower()


def deals_in_books(props: Optional[Dict]) -> bool:
    """Whether the merchant with *props* sells and buys books (see the module
    docstring)."""
    if not isinstance(props, dict):
        return True
    authored = props.get("buys_books")
    if isinstance(authored, bool):
        return authored
    if str(props.get("npc_role") or "").strip().lower() in NO_BOOK_ROLES:
        return False
    words = _merchant_words(props)
    return not any(t in words for t in NO_BOOK_TRADES)


def shop_books(props: Optional[Dict], count: int = SHOP_TITLES) -> List[str]:
    """The titles a bookish merchant keeps: a few of the shop books, a
    different few for each merchant. None for a merchant who does not deal
    in books."""
    if not deals_in_books(props):
        return []
    props = props or {}
    pool = books(SHOP)
    rng = seeded("shop", props.get("id") or props.get("name") or "")
    rng.shuffle(pool)
    return sorted(pool[:max(0, int(count))])


def will_buy(props: Optional[Dict], item_id) -> bool:
    """Whether the merchant with *props* will buy *item_id* from the player."""
    return not is_book(item_id) or deals_in_books(props)
