"""
Unlocking a container outright -- the console's ``unlock`` and the Knock spell.

Both open a lock the same way, through :func:`unlock`: a locked container (or
one jammed by a sheared pick) is unlocked at once, any lockpicking on it is
put away and "Unlocked!" goes in the roll log (the list on the left of the
play window); one that is not locked is left as it is.

* **Console ``unlock``** (:func:`begin_pick`): the world pauses and the
  container under the mouse is highlighted; a click unlocks it. Esc or a
  right-click cancels.
* **Knock** (``MiniwindSession.do_cast``): readied, the cursor becomes a hand
  and a click picks the container; it must be within :data:`KNOCK_REACH` of
  the caster, and the spell works :data:`KNOCK_PER_DAY` times a day.
"""

from __future__ import annotations

import math

#: How near the caster a container must be for Knock (world units).
KNOCK_REACH = 64.0
#: How many times a day Knock can be worked.
KNOCK_PER_DAY = 2
#: How near the click a container must be to be the one picked (world units).
PICK_RADIUS = 72.0

#: Said in the roll log (the list on the left of the play window).
UNLOCKED = "Unlocked!"
#: Floating words over the caster (like a fizzle).
ONCE_MORE = "Can only be used once more"
NOT_AGAIN = "Can't be used again today"
TOO_FAR = "Too far away"


def is_locked(thing) -> bool:
    p = getattr(thing, "properties", None) or {}
    return bool(p.get("locked") or p.get("lock_jammed"))


def unlock(session, thing) -> bool:
    """Unlock *thing* at once if it is locked (or jammed); True when it was.
    One already open is left alone."""
    p = getattr(thing, "properties", None)
    if not isinstance(p, dict) or str(p.get("type", "")) != "container" or not is_locked(thing):
        return False
    p["locked"] = False
    p["lock_jammed"] = False
    p.pop("lockpick_state", None)
    if getattr(session, "lockpick_thing", None) is thing:
        session.close_lockpicking(save_progress=False)
    log = getattr(session, "log_line", None)
    if log is not None:
        log(UNLOCKED, True, prominent=True)
    try:
        from engine.change_journal import touch
        touch(thing)
    except Exception:
        pass
    return True


def containers(session):
    """The containers a pick can land on (not hidden)."""
    things = getattr(session, "_things_of_type", None)
    found = things("container") if things is not None else ()
    return [t for t in found if not (t.properties or {}).get("hidden")]


def nearest_to(session, point, radius: float = PICK_RADIUS):
    """The container nearest world *point* on the ground, within *radius*."""
    if point is None:
        return None
    best, best_d = None, radius
    for thing in containers(session):
        d = math.hypot(float(thing.pos[0]) - float(point[0]),
                       float(thing.pos[2]) - float(point[2]))
        if d <= best_d:
            best, best_d = thing, d
    return best


def container_at(session, view, x, y):
    """The container under pixel (*x*, *y*) of *view*: the first one the ray
    through it passes close to, nearest the camera; None when none."""
    try:
        import glm
        w, h = max(1, view.width()), max(1, view.height())
        inverse = glm.inverse(view.projection_matrix * view.view_matrix)
        nx, ny = 2.0 * x / w - 1.0, 1.0 - 2.0 * y / h
        near = inverse * glm.vec4(nx, ny, -1.0, 1.0)
        far = inverse * glm.vec4(nx, ny, 1.0, 1.0)
        near, far = glm.vec3(near) / near.w, glm.vec3(far) / far.w
    except Exception:
        return None
    o = (float(near.x), float(near.y), float(near.z))
    d = (float(far.x - near.x), float(far.y - near.y), float(far.z - near.z))
    length = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) or 1.0
    d = (d[0] / length, d[1] / length, d[2] / length)
    best, best_t = None, math.inf
    for thing in containers(session):
        p = thing.properties
        size = max(float(p.get("sprite_width", 64) or 64), float(p.get("sprite_height", 64) or 64))
        radius = max(40.0, size * 0.5)
        c = (float(thing.pos[0]), float(thing.pos[1]), float(thing.pos[2]))
        oc = (o[0] - c[0], o[1] - c[1], o[2] - c[2])
        b = oc[0] * d[0] + oc[1] * d[1] + oc[2] * d[2]
        disc = b * b - (oc[0] ** 2 + oc[1] ** 2 + oc[2] ** 2 - radius * radius)
        if disc < 0.0:
            continue
        t = -b - math.sqrt(disc)
        if 0.0 <= t < best_t:
            best, best_t = thing, t
    return best


def begin_pick(window, session=None) -> bool:
    """The console's ``unlock``: pause, highlight the container under the
    mouse, and unlock the one clicked (if it is locked)."""
    if session is None:
        from game import runtime
        session = runtime._current_session
    view = getattr(window, "view_3d", None)
    begin = getattr(window, "begin_actor_pick", None)
    if session is None or view is None or begin is None:
        return False

    def find(x, y):
        return container_at(session, view, x, y)

    def picked(thing):
        import game.ui.hits as hits
        hits.queue(lambda s, t=thing: unlock(s, t))

    try:
        return bool(begin(picked, find=find, verb="Unlock"))
    except TypeError:                     # an editor without the finder
        return False
