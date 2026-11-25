"""
Stepping round what is in the way: a walker that runs into something strafes.

A walker heading straight for its goal used to press into whatever stood in
its way -- a crate, a barrel, a pillar, the corner of a wall -- and creep along
its face on whichever axis happened to be free. Now, when a step is stopped
almost head-on, the walker sidesteps: it moves perpendicular to its heading,
still facing where it is going, until the lane ahead of it is open, and then
walks on. Only when neither side has an open lane within reach does it fall
back on a route round the obstacle (:mod:`game.navigation`).

* **When it strafes.** A step is *blocked* when the collision test stops it
  along its heading and the axis it could slide along carries less than
  :data:`STRAFE_SLIDE_FRACTION` of the step toward the goal (a glancing
  contact with a long wall still slides along it). The combat chase, which
  Fio's MonsterAI steps itself, is judged by progress instead: a chaser that
  made less than that share of the ground it should have over
  :data:`CHASE_WINDOW` seconds, with something solid just ahead, is blocked.
* **Which side.** Both perpendiculars are probed outward in
  :data:`STRAFE_SPACING` steps up to :data:`STRAFE_REACH` past the body's
  margin; at each spot the lane ahead is tested. The side with the nearer
  open lane wins; a tie goes to the side the walker's final destination lies
  on, else to the side it strafed last (so it does not dither), else right.
* **Commitment.** Once begun, a strafe keeps its side for at least
  :data:`STRAFE_MIN_SECONDS`, and ends when the walker has stepped far enough
  and the lane ahead is open. A sidestep into something solid, or a strafe
  that runs too long, ends it, and the walker falls back on a route; it does
  not probe again for :data:`STRAFE_REST_SECONDS`.
* **Facing.** A strafe never turns anyone: the walker keeps looking at its
  goal (the caller turns it there, through :mod:`engine.monster_facing`).

Cost: nothing while the way is clear. Probing runs once when a step is first
stopped (a few dozen collision lookups at most); a strafe under way costs one
lookup a tick, and a couple more when it checks the lane ahead.

State lives on the walker's ``properties``: :data:`STATE` while a strafe is
under way, :data:`SIDE` (the side last taken), :data:`REST` (seconds before
it may probe again) and, for chasers, :data:`WATCH` (the progress window).
"""

from __future__ import annotations

import math

#: A strafe moves at this share of the walker's pace.
STRAFE_PACE = 0.8
#: A strafe keeps its side at least this long (no dithering left and right).
STRAFE_MIN_SECONDS = 0.35
#: Beyond the time the sidestep should take, a strafe may run this much longer
#: before it is given up as stuck.
STRAFE_MAX_SECONDS = 1.5
#: Sidestep spots are probed this far apart...
STRAFE_SPACING = 40.0
#: ...out to this far past the body's own margin: obstacles up to about twice
#: this wide are stepped round; anything wider is a wall, and gets a route.
STRAFE_REACH = 160.0
#: Extra sideways distance taken beyond the first open lane.
STRAFE_CLEARANCE = 8.0
#: After a probe found no way round (or a strafe failed), this long before
#: another probe.
STRAFE_REST_SECONDS = 1.0
#: A blocked step that can still slide along an axis carrying at least this
#: share of the step toward the goal slides, as before, instead of strafing.
STRAFE_SLIDE_FRACTION = 0.4
#: A chaser's progress is judged over windows this long (seconds).
CHASE_WINDOW = 0.3
#: How far out to the side a chaser's strafe waypoint is placed: far enough
#: that its step is sideways, wherever along the side line it lands.
CHASE_AIM = 400.0
#: A chaser's strafe whose last update is older than this is stale (it
#: stopped chasing in between) and is dropped.
CHASE_STALE = 0.5

STATE = "_strafe"
SIDE = "_strafe_side"
REST = "_strafe_rest"
WATCH = "_strafe_watch"


def side_vector(fx: float, fz: float, side: int):
    """The unit sideways direction off the unit heading ``(fx, fz)``.

    Side +1 is the heading turned a quarter clockwise seen from above (the
    heading convention's +90 degrees: +Z turns to +X); side -1 the other way.
    """
    return fz * side, -fx * side


def lane_open(blocked, x, y, z, fx, fz, margin, reach=0.0) -> bool:
    """Whether a body at ``(x, z)`` can walk on along ``(fx, fz)`` past what
    stopped it: body-sized probes ahead, one *margin* apart, covering
    ``2 * margin + reach`` (so a face slanting away from a sidestep of
    *reach* is still seen)."""
    margin = max(float(margin), 8.0)
    span = 2.0 * margin + max(0.0, float(reach))
    ahead = 0.5 * margin
    while ahead - margin < span:
        if blocked(x + fx * ahead, y, z + fz * ahead):
            return False
        ahead += margin
    return True


def probe(blocked, x, y, z, fx, fz, margin, prefer=0):
    """``(side, distance)`` of the nearest sidestep off heading ``(fx, fz)``
    from which the lane ahead is open, or None when neither side has one
    within reach (shut in, or the obstacle is a long wall).

    *blocked(x, y, z)* is the body-sized collision test. *prefer* (+1/-1)
    wins a tie; 0 means right."""
    reach = float(margin) + STRAFE_REACH
    first = 1 if prefer >= 0 else -1
    best = None
    for side in (first, -first):
        sx, sz = side_vector(fx, fz, side)
        d = STRAFE_SPACING
        while d <= reach and (best is None or d < best[1]):
            px, pz = x + sx * d, z + sz * d
            if blocked(px, y, pz):
                break                          # this side is shut from here on
            if lane_open(blocked, px, y, pz, fx, fz, margin, d):
                best = (side, d)
                break
            d += STRAFE_SPACING
    return best


def prefer_side(props, fx, fz, gx=None, gz=None) -> int:
    """The side a tie goes to: the one the final destination ``(gx, gz)``
    (relative to the walker) lies on, if it is clearly off the heading; else
    the side last strafed; else right (+1)."""
    if gx is not None and gz is not None:
        g = math.hypot(gx, gz)
        across = gx * fz - gz * fx                # dot with side_vector(+1)
        if g > 1e-6 and abs(across) > 0.1 * g:
            return 1 if across > 0 else -1
    side = props.get(SIDE)
    return -1 if side == -1 else 1


def begin(props, side, distance, fx, fz, **extra) -> dict:
    """Start a strafe to *side* of heading ``(fx, fz)``, at least *distance*
    sideways. The sideways line is fixed now: as the walker steps off its
    line the way to its goal swings, and a side line that swung with it would
    lean into the very obstacle it is stepping round."""
    sx, sz = side_vector(fx, fz, side)
    state = {"side": int(side), "need": float(distance) + STRAFE_CLEARANCE,
             "done": 0.0, "t": 0.0, "sx": sx, "sz": sz}
    state.update(extra)
    props[STATE] = state
    props[SIDE] = int(side)
    return state


def strafing(props) -> bool:
    return props.get(STATE) is not None


def rest(props, seconds=STRAFE_REST_SECONDS) -> None:
    """End any strafe and hold off probing for *seconds*."""
    props.pop(STATE, None)
    props[REST] = float(seconds)


def resting(props, delta) -> bool:
    """Count *delta* off the rest after a failed strafe; whether it still
    holds. Call once a tick."""
    left = props.get(REST)
    if not left:
        return False
    left = float(left) - float(delta)
    if left <= 0.0:
        props.pop(REST, None)
        return False
    props[REST] = left
    return True


def _over_time(state, speed) -> bool:
    budget = STRAFE_MAX_SECONDS
    if speed > 1e-6:
        budget += state["need"] / speed
    return state["t"] > budget


def advance(props, blocked, x, y, z, fx, fz, step, delta, margin):
    """One tick of a walker's strafe under way, heading ``(fx, fz)``.

    Returns the spot ``(x, z)`` it sidesteps to; True when the strafe is done
    and the walker should walk on this tick; False when it failed (a sidestep
    into something solid, or it ran too long) -- the strafe is over, a rest
    has begun, and the caller falls back on a route.
    """
    state = props.get(STATE)
    if state is None:
        return True
    state["t"] += float(delta)
    speed = float(step) / float(delta) if delta > 0 else 0.0
    if state["done"] >= state["need"] and state["t"] >= STRAFE_MIN_SECONDS:
        if lane_open(blocked, x, y, z, fx, fz, margin):
            props.pop(STATE, None)
            return True
        state["need"] += STRAFE_SPACING        # still in the way: a little further
    if _over_time(state, speed):
        rest(props)
        return False
    sx, sz = state["sx"], state["sz"]
    nx, nz = x + sx * step, z + sz * step
    if blocked(nx, y, nz):
        rest(props)
        return False
    state["done"] += float(step)
    return nx, nz


def chase(props, start, target, blocked, margin, now, speed):
    """A strafe waypoint for a chaser Fio's MonsterAI steps itself, or None to
    leave it heading for *target*.

    Called each time the chaser is about to step toward *target* from
    *start* (both ``(x, y, z)``). *blocked* is the collision test at the
    engine's own body margin *margin*; *now* the clock (seconds); *speed* the
    chaser's pace (units a second). The engine keeps the chaser facing its
    target, so the strafe does not turn it.
    """
    x, y, z = float(start[0]), float(start[1]), float(start[2])
    dx, dz = float(target[0]) - x, float(target[2]) - z
    dist = math.hypot(dx, dz)
    if dist < 1e-3:
        return None
    fx, fz = dx / dist, dz / dist
    state = props.get(STATE)
    if state is not None:
        last = state.get("clock")
        if last is None or now < last or now - last > CHASE_STALE or "sx" not in state:
            props.pop(STATE, None)               # a walk's strafe, or a stale one
        else:
            ox, oz = state["at"]
            sx, sz = state["sx"], state["sz"]
            state["done"] += max(0.0, (x - ox) * sx + (z - oz) * sz)
            state["t"] += now - last
            state["clock"], state["at"] = now, (x, z)
            if state["done"] >= state["need"] and state["t"] >= STRAFE_MIN_SECONDS:
                if lane_open(blocked, x, y, z, fx, fz, margin):
                    props.pop(STATE, None)
                    props.pop(WATCH, None)
                    return None
                state["need"] += STRAFE_SPACING
            if _over_time(state, speed) or blocked(x + sx * 0.25 * margin, y,
                                                   z + sz * 0.25 * margin):
                props.pop(STATE, None)
                props[WATCH] = {"t": now, "x": x, "z": z, "rest": now + STRAFE_REST_SECONDS}
                return None
            return (x + sx * CHASE_AIM, y, z + sz * CHASE_AIM)
    watch = props.get(WATCH)
    if (watch is None or now < watch["t"] or now - watch["t"] > 2.0 * CHASE_WINDOW):
        props[WATCH] = {"t": now, "x": x, "z": z,
                        "rest": watch["rest"] if watch is not None else None}
        return None
    elapsed = now - watch["t"]
    if elapsed < CHASE_WINDOW:
        return None
    gained = (x - watch["x"]) * fx + (z - watch["z"]) * fz
    watch["t"], watch["x"], watch["z"] = now, x, z
    resting = watch["rest"] is not None and now < watch["rest"]
    if gained >= STRAFE_SLIDE_FRACTION * speed * elapsed or resting:
        return None
    ahead = 0.25 * margin
    if not blocked(x + fx * ahead, y, z + fz * ahead):
        return None                              # slowed, but nothing in the way
    choice = probe(blocked, x, y, z, fx, fz, margin, prefer_side(props, fx, fz))
    if choice is None:
        watch["rest"] = now + STRAFE_REST_SECONDS
        return None
    state = begin(props, *choice, fx, fz, clock=now, at=(x, z))
    sx, sz = state["sx"], state["sz"]
    return (x + sx * CHASE_AIM, y, z + sz * CHASE_AIM)
