"""
Character **heads** — the portrait/billboard sprites under
``assets/sprites/heads/head00.png`` … ``head19.png``.

A head is the player's whole visual identity (no gender, no animation frames):
the player picks one at character creation, it becomes the player's overhead
sprite, and it is recorded so no NPC ever spawns with the *same* head. The id is
also the key a future audio layer will use to pick voice files.

``assets/sprites/heads/dead.png`` is a shared overlay drawn on top of a head
when its owner dies (see the renderers), so a corpse keeps its identity instead
of switching to a generic role sprite.
"""

from __future__ import annotations

import random as _random
from typing import Iterable, Optional

#: Heads are numbered head00 … head19 (20 in total).
HEAD_FIRST = 0
HEAD_LAST = 19
HEAD_COUNT = HEAD_LAST - HEAD_FIRST + 1
HEAD_DIR = "assets/sprites/heads"
HEAD_IDS = [f"head{n:02d}" for n in range(HEAD_FIRST, HEAD_LAST + 1)]

#: Overlay blended over a head sprite when its owner is dead.
DEAD_OVERLAY = f"{HEAD_DIR}/dead.png"


def dead_overlay_path() -> str:
    """Repo-relative path to the shared 'dead' overlay drawn over a head."""
    return DEAD_OVERLAY


def is_head(head_id) -> bool:
    return str(head_id) in HEAD_IDS


def normalise(head_id) -> str:
    """Return a valid head id (falls back to the first head)."""
    hid = str(head_id or "").strip()
    return hid if hid in HEAD_IDS else HEAD_IDS[0]


def head_path(head_id) -> str:
    """Repo-relative sprite path for a head id."""
    return f"{HEAD_DIR}/{normalise(head_id)}.png"


def index_of(head_id) -> int:
    try:
        return HEAD_IDS.index(normalise(head_id))
    except ValueError:
        return 0


def head_at(index: int) -> str:
    return HEAD_IDS[int(index) % HEAD_COUNT]


def random_head(rng: Optional[_random.Random] = None,
                exclude: Iterable[str] = ()) -> str:
    """A random head id, avoiding any in *exclude* (e.g. the player's head)."""
    ban = {str(e) for e in exclude}
    pool = [h for h in HEAD_IDS if h not in ban] or list(HEAD_IDS)
    return (rng or _random).choice(pool)
