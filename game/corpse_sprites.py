"""
A corpse: its own head, gone grey, with the cross on it -- and then the cross
fades.

When an NPC, a creature or the player dies, its head (or its role art) keeps
its shape but turns greyscale and a little see-through (:data:`DEAD_OPACITY`),
and the cross -- ``assets/sprites/heads/dead.png``,
128 x 128, the heads folder's own, never Fio's
``assets/sprites/monsters/.../dead.png`` -- is laid over it in its own
colours, fitted to the head: a small head (a chicken at 50 px, a crab at 64)
gets a small cross. After :data:`CROSS_HOLD` seconds the cross fades out over
:data:`CROSS_FADE`, leaving the grey head. Real time, so Slow Time does not
stretch it.

The engine draws an NPC's or a creature's corpse from one image
(``custom_dead``), so each look has a short series of them -- the grey head
with the cross at full strength, fainter at each of :data:`FADE_STEPS` steps,
then the grey head alone -- made when needed and kept in
``assets/sprites/heads/dead_cache/`` (not in the repository; remade when the
head or the cross changes). :class:`CorpseFader` steps each corpse through
them. Only in Play: the editor's maps never carry a ``custom_dead``. The
player's corpse is drawn by the overhead renderer from the same grey head and
the cross at a fading opacity (``MiniwindSession.overhead_player_corpse``).

Where the cache cannot be written (a read-only install), a corpse keeps its
plain head rather than ever showing Fio's monster corpse.

A body blown apart (``gibbed``) leaves no corpse at all, so it gets no cross:
the engine draws nothing for it (``engine/entity_table.py``) and the gore is
all that is left.
"""

from __future__ import annotations

import os

#: The cross, from the heads folder (128 x 128).
CROSS = "assets/sprites/heads/dead.png"
#: Where each look's corpse image is kept (ignored by git).
CACHE_DIR = "assets/sprites/heads/dead_cache"
#: Seconds the cross stays at full strength after a death, then the seconds
#: it takes to fade out.
CROSS_HOLD = 3.0
CROSS_FADE = 1.0
#: Steps the cross fades through on an NPC's or a creature's corpse.
FADE_STEPS = 6
#: How opaque a dead head is (the cross is drawn at its own strength).
DEAD_OPACITY = 0.9
#: True while a play session runs: actors built then get their corpse image
#: as they get their look (game/entities.py). False in the editor, so its
#: maps never carry one.
ACTIVE = False


def _root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _repo_path(path: str) -> str:
    """A sprite path as the actors carry it, made repo-relative ("assets/...")."""
    p = str(path or "").replace("\\", "/").lstrip("/")
    if not p.startswith("assets/"):
        p = "assets/" + p
    return p


def _cache_name(rel: str, step: int) -> str:
    """A cache file name for the look at *rel* at fade *step*
    (``sprites/heads/chicken.png``, 0 -> ``heads__chicken__0.png``)."""
    inner = rel[len("assets/"):]
    if inner.startswith("sprites/"):
        inner = inner[len("sprites/"):]
    stem, _ext = os.path.splitext(inner)
    # The opacity is in the name, so a change to it makes fresh images.
    return f"{stem.replace('/', '__')}__o{int(round(DEAD_OPACITY * 100))}__{int(step)}.png"


def cross_alpha(age: float) -> float:
    """How strong the cross is *age* seconds after the death (1 to 0)."""
    if age <= CROSS_HOLD:
        return 1.0
    if CROSS_FADE <= 0.0:
        return 0.0
    return max(0.0, 1.0 - (age - CROSS_HOLD) / CROSS_FADE)


def step_at(age: float) -> int:
    """The fade step for *age* seconds after the death (0 .. FADE_STEPS)."""
    return int(round((1.0 - cross_alpha(age)) * FADE_STEPS))


def _grey(image):
    """*image* in greyscale at DEAD_OPACITY, keeping its shape."""
    alpha = image.getchannel("A").point(lambda v: int(round(v * DEAD_OPACITY)))
    grey = image.convert("L").convert("RGBA")
    grey.putalpha(alpha)
    return grey


def corpse_sprite(sprite_path: str, step: int = 0):
    """The corpse image for an actor drawn as *sprite_path*, at fade *step*:
    the image gone grey with the cross on it at ``1 - step / FADE_STEPS``
    strength (none at FADE_STEPS), made if need be. Repo-relative, ready for
    ``custom_dead``; or None when there is nothing to make it from."""
    if not sprite_path:
        return None
    step = max(0, min(FADE_STEPS, int(step)))
    rel = _repo_path(sprite_path)
    root = _root()
    src = os.path.join(root, rel)
    cross = os.path.join(root, CROSS)
    if rel.startswith(CACHE_DIR + "/") or not os.path.isfile(src) or not os.path.isfile(cross):
        return None
    out_rel = f"{CACHE_DIR}/{_cache_name(rel, step)}"
    out = os.path.join(root, out_rel)
    try:
        newest = max(os.path.getmtime(src), os.path.getmtime(cross))
        if os.path.isfile(out) and os.path.getmtime(out) >= newest:
            return out_rel
        from PIL import Image
        with Image.open(src) as head_image, Image.open(cross) as cross_image:
            corpse = _grey(head_image.convert("RGBA"))     # the head, grey, 90%
            strength = 1.0 - step / FADE_STEPS
            if strength > 0.0:
                mark_image = cross_image.convert("RGBA").resize(corpse.size, Image.LANCZOS)
                if strength < 1.0:
                    a = mark_image.getchannel("A").point(lambda v: int(round(v * strength)))
                    mark_image.putalpha(a)
                corpse.alpha_composite(mark_image)        # the cross, in its own colours
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".tmp"
        corpse.save(tmp, "PNG")
        os.replace(tmp, out)
        return out_rel
    except (OSError, ValueError):
        return None


def mark(props) -> bool:
    """Give an actor its corpse image (``custom_dead``) from the look it wears
    now: the grey head with the full cross -- or, for a body already dead (a
    loaded corpse), the grey head alone, its cross long faded. Its plain look
    when the image cannot be made, never Fio's monster corpse. True when
    ``custom_dead`` changed."""
    if not isinstance(props, dict):
        return False
    look = props.get("custom_idle") or ""
    if not look:
        return False
    step = FADE_STEPS if props.get("dead") else 0
    want = corpse_sprite(look, step) or _repo_path(look)
    if props.get("custom_dead") == want:
        return False
    props["custom_dead"] = want
    if step == FADE_STEPS:
        props["_cross_faded"] = True
    return True


class CorpseFader:
    """Steps each new corpse's cross out: full for CROSS_HOLD seconds, then
    fading through the FADE_STEPS images over CROSS_FADE. Once a game tick."""

    def __init__(self, clock=None):
        import time
        self._clock = clock or time.monotonic
        #: id(actor) -> (actor, the moment it was first seen dead)
        self._dying = {}

    def update(self, corpses, touch=None) -> int:
        """*corpses*: the dead actors now. Returns how many changed image;
        *touch(actor)* is told of each, so the renderer redraws it."""
        now = self._clock()
        seen = set()
        changed = 0
        for actor in corpses:
            p = getattr(actor, "properties", None)
            if not isinstance(p, dict) or p.get("gibbed") or p.get("_cross_faded"):
                continue
            look = p.get("custom_idle") or ""
            if not look:
                continue
            key = id(actor)
            seen.add(key)
            started = self._dying.setdefault(key, (actor, now))[1]
            step = step_at(now - started)
            want = corpse_sprite(look, step)
            if want and p.get("custom_dead") != want:
                p["custom_dead"] = want
                changed += 1
                if touch is not None:
                    touch(actor)
            if step >= FADE_STEPS:
                p["_cross_faded"] = True
                self._dying.pop(key, None)
        for key in [k for k in self._dying if k not in seen]:
            self._dying.pop(key, None)          # revived, removed, or blown apart
        return changed
