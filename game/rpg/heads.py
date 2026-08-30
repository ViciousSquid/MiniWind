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

**Guard heads** (``guard01``…``guard04``) are a separate, NPC-only pool under
the same directory. They are never offered at player character creation and
are never picked by :func:`random_head`; they only become available in the
editor's Appearance tab for an NPC whose ``name`` contains "guard" (see
:mod:`game.editor_ui`), and an authored guard head is preserved for such NPCs
by :meth:`game.runtime.GameRuntime._assign_npc_heads`.
"""

from __future__ import annotations

import os
import random as _random
from typing import Iterable, Optional

#: Heads are numbered head00 … head19 (20 in total).
HEAD_FIRST = 0
HEAD_LAST = 19
HEAD_COUNT = HEAD_LAST - HEAD_FIRST + 1
HEAD_DIR = "assets/sprites/heads"
HEAD_IDS = [f"head{n:02d}" for n in range(HEAD_FIRST, HEAD_LAST + 1)]

#: Special guard heads — assets/sprites/heads/guard01.png … guard04.png.
#: A separate pool from HEAD_IDS: NPC-only, opt-in (never random, never the
#: player's), offered only for NPCs whose name contains "guard".
GUARD_HEAD_IDS = [f"guard{n:02d}" for n in (1, 2, 3, 4)]

#: Overlay blended over a head sprite when its owner is dead.
DEAD_OVERLAY = f"{HEAD_DIR}/dead.png"


def _repo_root() -> str:
    """Best-effort absolute path to the project root (two levels up from
    this file: game/rpg/heads.py -> game/rpg -> game -> root)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def dead_overlay_path() -> str:
    """Repo-relative path to the shared 'dead' overlay drawn over a head."""
    return DEAD_OVERLAY


def is_head(head_id) -> bool:
    return str(head_id) in HEAD_IDS


def is_guard_head(head_id) -> bool:
    return str(head_id) in GUARD_HEAD_IDS


def is_any_head(head_id) -> bool:
    """True for a regular head id, a special guard head id, or any other
    id whose PNG actually exists under assets/sprites/heads/ (e.g. a head
    picked via the editor's Browse… button)."""
    hid = str(head_id or "")
    if not hid:
        return False
    if hid in HEAD_IDS or hid in GUARD_HEAD_IDS:
        return True
    return os.path.isfile(os.path.join(_repo_root(), HEAD_DIR, f"{hid}.png"))


def normalise(head_id) -> str:
    """Return a valid regular head id (falls back to the first head).
    Guard heads are a separate pool — see :func:`guard_head_path`."""
    hid = str(head_id or "").strip()
    return hid if hid in HEAD_IDS else HEAD_IDS[0]


def head_path(head_id) -> str:
    """Repo-relative sprite path for a regular head id."""
    return f"{HEAD_DIR}/{normalise(head_id)}.png"


def guard_head_path(head_id) -> str:
    """Repo-relative sprite path for a guard head id (falls back to guard01)."""
    hid = str(head_id or "").strip()
    hid = hid if hid in GUARD_HEAD_IDS else GUARD_HEAD_IDS[0]
    return f"{HEAD_DIR}/{hid}.png"


def any_head_path(head_id) -> str:
    """Repo-relative sprite path for a regular head, a guard head, or any
    other id whose PNG exists under assets/sprites/heads/ (browsed head)."""
    hid = str(head_id or "")
    if hid in GUARD_HEAD_IDS:
        return guard_head_path(hid)
    if hid in HEAD_IDS:
        return head_path(hid)
    if hid and os.path.isfile(os.path.join(_repo_root(), HEAD_DIR, f"{hid}.png")):
        return f"{HEAD_DIR}/{hid}.png"
    return head_path(hid)


def index_of(head_id) -> int:
    try:
        return HEAD_IDS.index(normalise(head_id))
    except ValueError:
        return 0


def head_at(index: int) -> str:
    return HEAD_IDS[int(index) % HEAD_COUNT]


def random_head(rng: Optional[_random.Random] = None,
                exclude: Iterable[str] = ()) -> str:
    """A random regular head id, avoiding any in *exclude* (e.g. the player's
    head). Never returns a guard head — those are opt-in only."""
    ban = {str(e) for e in exclude}
    pool = [h for h in HEAD_IDS if h not in ban] or list(HEAD_IDS)
    return (rng or _random).choice(pool)
