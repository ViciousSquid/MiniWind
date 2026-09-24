"""
How a MiniWind actor looks, expressed in the terms Fio's renderer already reads.

Fio 2.5.5 draws every Monster from a dense projection
(:mod:`engine.entity_table`): once per frame the logic thread refreshes each
monster's :meth:`Monster.get_render_snapshot`, and the entity table re-resolves
a monster's sprite *only* when the inputs Fio watches change -- ``dead``,
``is_shooting``, ``monster_type``, ``variant`` and the three ``custom_*``
sprite paths. The instanced sprite pass then draws it from columns; no
per-actor draw code runs.

So a MiniWind look that is just "a different picture" does not need renderer
code at all. It needs the *right value in a field Fio already watches*:

* a slain **head actor** keeps its identity -- its head with the shared
  ``heads/dead.png`` painted over it. That composite is written once per head
  (``assets/sprites/heads/dead_cache/``, git-ignored) and published as the
  actor's ``custom_dead``;
* a **gibbed** body is its splatter sprite, also published as ``custom_dead``;
* anything else leaves ``custom_dead`` empty, and Fio falls back to the
  monster type's own ``dead.png``.

``custom_dead`` is therefore *derived* state here, never authored: MiniWind's
editor offers no death-sprite field, and :func:`refresh_death_look` recomputes
it whenever the head or the gib state changes. Because the value is a field
Fio watches, the change reaches the 3D billboard (warm sprite re-resolve), the
2D map icon (:meth:`Monster.get_sprite_path`) and packaging with no further
wiring.

The per-frame parts of the look -- heading, hit flash, fade -- are not
pictures; see :func:`render_state` for how they cross into the same pipeline.
"""

from __future__ import annotations

import math
import os
from typing import Optional

HEADS_DIR = "assets/sprites/heads"
DEAD_OVERLAY = f"{HEADS_DIR}/dead.png"
DEAD_CACHE_DIR = f"{HEADS_DIR}/dead_cache"

#: Actor ``type`` values that can wear a head.
_ACTOR_TYPES = ("npc", "creature", "monster")

#: idle head path -> composite path. Only hits are cached (art may appear later).
_dead_head_cache: dict = {}


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def is_head_sprite(rel_path) -> bool:
    """True when *rel_path* is one of the character head sprites (``headNN``)."""
    rp = str(rel_path or "").replace("\\", "/")
    base = os.path.basename(rp)
    return ("/heads/" in rp or rp.startswith("heads/")) and base.startswith("head")


def is_head_actor(props) -> bool:
    """Whether an actor wears a head: the actors that turn to face their heading.

    An actor may say so outright with ``is_head`` (the reaper wears
    ``heads/reaper.png``, which is not a numbered head); otherwise an NPC,
    creature or monster whose idle sprite is a ``headNN`` does.
    """
    if not isinstance(props, dict):
        return False
    if "is_head" in props:
        return bool(props["is_head"])
    if str(props.get("type", "")).lower() not in _ACTOR_TYPES:
        return False
    return is_head_sprite(props.get("custom_idle", ""))


def dead_head_composite(idle_rel, root: Optional[str] = None) -> Optional[str]:
    """Repo-relative path to *idle_rel* (a head) with ``heads/dead.png`` over it.

    Written once to :data:`DEAD_CACHE_DIR` and reused. ``None`` when *idle_rel*
    is not a head or the head/overlay art is missing, so the caller falls back
    to the ordinary corpse sprite. The composite is a plain PNG, so the 3D
    billboard and the 2D map icon both pick it up through Fio's normal sprite
    path.
    """
    if not is_head_sprite(idle_rel):
        return None
    root = root or _repo_root()
    cached = _dead_head_cache.get(idle_rel)
    if cached and os.path.isfile(os.path.join(root, cached)):
        return cached
    result = None
    try:
        head_abs = os.path.join(root, idle_rel)
        overlay_abs = os.path.join(root, DEAD_OVERLAY)
        if os.path.isfile(head_abs) and os.path.isfile(overlay_abs):
            name = os.path.splitext(os.path.basename(idle_rel))[0] + "__dead.png"
            out_rel = f"{DEAD_CACHE_DIR}/{name}"
            out_abs = os.path.join(root, out_rel)
            if not os.path.isfile(out_abs):
                from PIL import Image
                base = Image.open(head_abs).convert("RGBA")
                over = Image.open(overlay_abs).convert("RGBA")
                if over.size != base.size:
                    over = over.resize(base.size, Image.LANCZOS)
                base.alpha_composite(over)
                os.makedirs(os.path.dirname(out_abs), exist_ok=True)
                base.save(out_abs)
            result = out_rel
    except Exception:
        result = None
    if result:
        _dead_head_cache[idle_rel] = result
    return result


def death_look(props, root: Optional[str] = None) -> str:
    """The sprite a dead actor should show, or ``""`` for Fio's type default."""
    if not isinstance(props, dict):
        return ""
    if props.get("gibbed") and props.get("gib_sprite"):
        return str(props["gib_sprite"])
    idle = str(props.get("custom_idle", "") or "")
    if is_head_sprite(idle):
        return dead_head_composite(idle, root) or ""
    return ""


def refresh_death_look(props, root: Optional[str] = None) -> bool:
    """Publish :func:`death_look` as Fio's ``custom_dead``. Returns whether it changed."""
    if not isinstance(props, dict):
        return False
    look = death_look(props, root)
    before = props.get("custom_dead", "")
    if look:
        props["custom_dead"] = look
    else:
        props.pop("custom_dead", None)
    return (before or "") != look


#: Transient per-session actor keys MiniWind writes during play. Cleared when a
#: session starts or stops so a revived body is not still a splatter and an
#: actor starts the next fight from its authored kit.
TRANSIENT_KEYS = ("_active_weapon", "_bleed_last_hp", "_hit_flash", "_opacity")


def reset_transient(things) -> None:
    """Reset MiniWind's per-session actor state after Fio's own monster reset.

    Fio clears ``dead`` when a session starts; a body that is no longer dead
    cannot still be gibbed, so the gib record goes too and the death look is
    re-derived from the head.
    """
    for thing in things or ():
        props = getattr(thing, "properties", None)
        if not isinstance(props, dict):
            continue
        if str(props.get("type", "")).lower() not in _ACTOR_TYPES:
            continue
        for key in TRANSIENT_KEYS:
            props.pop(key, None)
        if not props.get("dead"):
            for key in ("gibbed", "gib_sprite", "gib_magical"):
                props.pop(key, None)
        refresh_death_look(props)


# ---------------------------------------------------------------------------
# Per-frame look -- what crosses into the renderer through the snapshot
# ---------------------------------------------------------------------------

#: How long (s) the red hit flash lasts; the tint fades out over this time.
HIT_FLASH_TINT = (1.0, 0.15, 0.1)
HIT_FLASH_MAX = 0.75

#: The head art's "front" is the image bottom; a half turn makes it point
#: along the actor's heading.
HEAD_FACING_OFFSET = math.pi


def render_state(props) -> dict:
    """The generic per-frame render fields a MiniWind actor publishes.

    These are the keys Fio's entity projection reads from a monster's render
    snapshot (see :meth:`engine.entity_table.EntityTable.refresh_actor_look`):

    * ``heading`` -- world yaw (radians) the sprite should face, or absent for
      an upright billboard. Only head actors turn;
    * ``tint`` -- ``(r, g, b, strength)`` mixed over the sprite (hit flash);
    * ``opacity`` -- whole-sprite alpha (the reaper's fade).
    """
    out = {}
    if is_head_actor(props):
        facing = props.get("_facing")
        if facing is None:
            facing = props.get("angle", 0.0)
        try:
            out["heading"] = float(facing or 0.0) + HEAD_FACING_OFFSET
        except (TypeError, ValueError):
            out["heading"] = HEAD_FACING_OFFSET
    try:
        flash = float(props.get("_hit_flash", 0.0) or 0.0)
    except (TypeError, ValueError):
        flash = 0.0
    if flash > 0.0:
        out["tint"] = HIT_FLASH_TINT + (min(HIT_FLASH_MAX, flash * 4.0),)
    if "_opacity" in props:
        try:
            out["opacity"] = max(0.0, min(1.0, float(props["_opacity"] or 0.0)))
        except (TypeError, ValueError):
            pass
    return out
