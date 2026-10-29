"""
Character **heads** — the portrait/billboard sprites under
``assets/sprites/heads/head00.png`` … ``head186.png``.

A head is the player's whole visual identity (no gender, no animation frames):
the player picks one at character creation, it becomes the player's overhead
sprite, and it is recorded so no NPC ever spawns with the *same* head. The id is
also the key a future audio layer will use to pick voice files.

``assets/sprites/heads/dead.png`` is a shared overlay drawn on top of a head
when its owner dies (see the renderers), so a corpse keeps its identity instead
of switching to a generic role sprite.

**Guard heads** (``guard01``…``guard26``) are a separate, NPC-only pool under
the same directory. They are never offered at player character creation and
are never picked by :func:`random_head`; they only become available in the
editor's Appearance tab for a guard or a town archer (``npc_role`` "guard" or
"guard_archer", see :mod:`game.editor_ui`), and such NPCs always wear one: an
authored guard head is kept, any other is swapped for a random guard head by
:meth:`game.runtime.GameRuntime._assign_npc_heads`.
"""

from __future__ import annotations

import os
import random as _random
from typing import Iterable, Optional

#: Heads are numbered head00 … head186 (187 in total).
HEAD_FIRST = 0
HEAD_LAST = 186
HEAD_COUNT = HEAD_LAST - HEAD_FIRST + 1
HEAD_DIR = "assets/sprites/heads"
HEAD_IDS = [f"head{n:02d}" for n in range(HEAD_FIRST, HEAD_LAST + 1)]

#: Special guard heads — assets/sprites/heads/guard01.png … guard26.png.
#: A separate pool from HEAD_IDS: NPC-only, opt-in (never random, never the
#: player's), offered only for NPCs with the guard role.
GUARD_HEAD_IDS = [f"guard{n:02d}" for n in range(1, 27)]

#: Overlay blended over a head sprite when its owner is dead.
DEAD_OVERLAY = f"{HEAD_DIR}/dead.png"

#: Animal roles. Each wears a head of its own kind (see :func:`animal_head`),
#: never a person's.
ANIMAL_ROLES = frozenset({"wolf", "bear", "boar", "mudcrab", "cow", "sheep", "hen"})

#: Animal roles whose head art goes by another name: a hen wears chicken.png.
ANIMAL_HEAD_ALIASES = {"hen": "chicken"}

#: The head an animal wears until its own head image exists.
PLACEHOLDER_HEAD = "placeholder"

#: The world size (width and height) every head is drawn at, on every actor
#: whatever its role, so all heads look the same size. It is the player's own
#: overhead sprite size (Fio's ``QtGameView.overhead_sprite_size``).
HEAD_SIZE = 128


#: Heads drawn at other than :data:`HEAD_SIZE` by nature, as a fraction of it:
#: a chicken is a small bird, 50 px of the usual 128. Numbered variants share
#: their head's scale (``chicken2`` is a chicken). An actor's own
#: ``head_scale`` wins over this.
CHICKEN_SIZE = 50
HEAD_SCALES = {"chicken": CHICKEN_SIZE / HEAD_SIZE}


def default_scale(head_id) -> float:
    """The scale *head_id* is drawn at when its actor sets none (1.0 for most)."""
    hid = str(head_id or "").strip().lower()
    if hid in HEAD_SCALES:
        return HEAD_SCALES[hid]
    return HEAD_SCALES.get(hid.rstrip("0123456789"), 1.0)


def size_for(props, head_id=None) -> int:
    """The size an actor's head is drawn at: :data:`HEAD_SIZE`, times its
    ``head_scale`` for the few that are meant to be enormous (a dragon), or
    else the head's own :func:`default_scale` (a chicken is a third).

    *head_id* is the head it wears, when that is not yet in *props*."""
    props = props or {}
    authored = props.get("head_scale")
    try:
        scale = float(authored) if authored not in (None, "") else 0.0
    except (TypeError, ValueError):
        scale = 0.0
    if not scale:
        scale = default_scale(props.get("head") if head_id is None else head_id)
    return int(round(HEAD_SIZE * max(0.25, min(scale, 12.0))))


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


#: Roles that wear guard heads: the town guards and the town archers.
GUARD_ROLES = frozenset({"guard", "guard_archer"})


def is_guard(props) -> bool:
    """Guard appearances are reserved for, and always worn by, the guards and
    the town archers (:data:`GUARD_ROLES`)."""
    return str((props or {}).get("npc_role", "")).strip().lower() in GUARD_ROLES


#: Heads whose art may not be in place yet, and what stands in until it is
#: (the dragon wears ``dragon.png``; ``dragon01.png`` is drawn by
#: game/tools/make_dragon_head.py).
FALLBACK_HEADS = {"dragon": "dragon01"}


def _head_file(hid) -> str:
    return os.path.join(_repo_root(), HEAD_DIR, f"{hid}.png")


def _available(hid) -> str:
    """*hid*, or its stand-in when its own PNG is missing ("" if neither)."""
    if hid and os.path.isfile(_head_file(hid)):
        return hid
    alt = FALLBACK_HEADS.get(hid)
    if alt and os.path.isfile(_head_file(alt)):
        return alt
    return ""


def is_any_head(head_id) -> bool:
    """True for a regular head id, a special guard head id, or any other
    id whose PNG actually exists under assets/sprites/heads/ (e.g. a head
    picked via the editor's Browse… button)."""
    hid = str(head_id or "")
    if not hid:
        return False
    if hid in HEAD_IDS or hid in GUARD_HEAD_IDS:
        return True
    return bool(_available(hid))


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
    found = _available(hid)
    if found:
        return f"{HEAD_DIR}/{found}.png"
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


def random_guard_head(rng: Optional[_random.Random] = None) -> str:
    """A random guard head id (guard01…guard26). Used to auto-assign a head to
    an NPC with the guard role that has no head explicitly set in the editor."""
    return (rng or _random).choice(GUARD_HEAD_IDS)


def animal_heads(role) -> list:
    """Every head an animal of *role* may wear, sorted.

    Its own art: ``<role>.png`` and its numbered variants (``<role>2.png``,
    ``<role>01.png``, ...); failing that, the same under the role's
    :data:`ANIMAL_HEAD_ALIASES` name (a hen wears the chickens). Empty until
    any has been drawn."""
    kind = str(role or "").strip().lower()
    if not kind:
        return []
    try:
        names = os.listdir(os.path.join(_repo_root(), HEAD_DIR))
    except OSError:
        names = []
    for name in (kind, ANIMAL_HEAD_ALIASES.get(kind)):
        if not name:
            continue
        found = sorted(
            f[:-4] for f in names
            if f.endswith(".png") and f.startswith(name)
            and (len(f) == len(name) + 4 or f[len(name):-4].isdigit()))
        if found:
            return found
    return []


def animal_head(role, rng: Optional[_random.Random] = None, deck=None) -> str:
    """The head id an animal of *role* wears: one of :func:`animal_heads`,
    or :data:`PLACEHOLDER_HEAD` until any is drawn.

    With a *deck* (a dict kept across one pass over the world) the heads are
    dealt rather than drawn: each role's set is shuffled, dealt out, then
    reshuffled, so a flock wears its variants in even numbers instead of
    however a run of coin flips falls."""
    rng = rng or _random
    kind = str(role or "").strip().lower()
    if deck is None:
        pool = animal_heads(kind)
        return rng.choice(pool) if pool else PLACEHOLDER_HEAD
    entry = deck.get(kind)
    if entry is None:
        entry = deck[kind] = (animal_heads(kind), [])
    pool, hand = entry
    if not pool:
        return PLACEHOLDER_HEAD
    if not hand:
        hand.extend(pool)
        rng.shuffle(hand)
    return hand.pop()


def name_is_guard(name) -> bool:
    """True if an NPC name marks it as a guard (case-insensitive substring),
    matching the editor's Appearance tab rule for offering guard heads."""
    return "guard" in str(name or "").lower()
