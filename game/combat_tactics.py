"""
How ranged fighters move in a fight: casters and archers keep their distance,
but can always be run down.

Fio's combat AI walks every fighter straight at its target. That suits a
swordsman; a mage or an archer who strolls into sword reach throws away the
one advantage it has. This module is the game's half of Fio's steer hook
(``MonsterAI._steer_hook``, installed by :class:`game.runtime.MiniwindSession`):
for each fighter about to step, it says where that step should go.

A fighter whose loadout fights at range with a spell or a bow
(:mod:`game.combat_loadout`) keeps to a band of distance, :data:`KEEP_BAND`:

* **too far** -- it advances, routed round walls as every chaser is
  (:mod:`game.navigation`);
* **in the band** -- it stands and fights, now and then edging a step to the
  side so it is not a fixed mark (:data:`SIDESTEP_EVERY`);
* **too close** -- it backs away, in a burst of at most
  :data:`RETREAT_BURST` seconds, then must stand for at least
  :data:`RETREAT_REST` (it casts or draws in that pause).

It can always be caught. It backs away at a walk (90 units a second), while
the player runs at 300 and a fighter closing in runs at about 190 for as long
as its stamina lasts (:mod:`game.npc_stamina`); and because every burst is
followed by a rest, a caster gives up ground even to a walking swordsman. Within
:data:`COMMIT_RANGE` it stops backing off and fights with whatever blade it
has; so it does after :data:`MAX_RETREATS` bursts in :data:`RETREAT_WINDOW`
seconds, or when a burst makes no ground (a wall at its back). Committed, it
stands its ground for :data:`COMMIT_SECONDS`. While backing away it does not
attack: one does not shoot well walking backwards.

Big World tiers bound the cost. Only fighters at ``NEAR`` or ``ACTIVE`` fidelity
use tactics; anything farther out (which the player cannot watch) chases
straight on, as before. Nothing here runs per tick for an actor that is not
stepping toward a target, and its loadout is re-read at most every
:data:`LOADOUT_SECONDS`.
"""

from __future__ import annotations

import math

from . import combat_loadout, npc_stamina

#: Distances (min, max) each ranged style tries to fight from.
KEEP_BAND = {combat_loadout.MAGIC: (300.0, 620.0), combat_loadout.BOW: (380.0, 820.0)}
#: Inside this the fighter stops backing off and uses its blade.
COMMIT_RANGE = 140.0
#: A retreat lasts at most this long, and is followed by at least this much
#: standing (casting, drawing) before the next.
RETREAT_BURST = 1.1
RETREAT_REST = 1.6
#: How far ahead a backing-off fighter aims (it re-aims every tick).
RETREAT_STEP = 160.0
#: This many retreats in this many seconds and it stands and fights.
MAX_RETREATS = 3
RETREAT_WINDOW = 12.0
#: How long a fighter that has committed to melee keeps to it.
COMMIT_SECONDS = 5.0
#: A burst that gained less than this share of the ground it should have
#: (a wall behind it) leaves it cornered: it commits.
STUCK_SHARE = 0.3
#: Walking pace of Fio's fighters, for the ground a burst should gain.
FIGHTER_SPEED = 90.0
#: A fighter in its band edges sideways for SIDESTEP_SECONDS every
#: SIDESTEP_EVERY seconds, alternating sides.
SIDESTEP_EVERY = 3.2
SIDESTEP_SECONDS = 0.7
#: Standing in the band with no shot for this long (no line of sight) and it
#: advances to find one.
NO_SHOT_ADVANCE = 3.0
#: How long a fighter's loadout answer is reused.
LOADOUT_SECONDS = 0.5
#: A fighter closing on its foe runs (stamina allowing) when farther than
#: this; a ranged one runs back toward its band when this far beyond it.
RUN_FROM = 220.0
RUN_MARGIN = 250.0

HOLD = "hold"
RETREAT = "retreat"
ADVANCE = "advance"
SIDESTEP = "sidestep"
COMMIT = "commit"


def ranged_style(props) -> str:
    """The ranged style *props*' fighter would use (magic or bow), or ''."""
    style = combat_loadout.choose_style(combat_loadout.build_loadout(props), False)
    return style if style in KEEP_BAND else ""


class _State:
    __slots__ = ("mode", "since", "until", "retreats", "start", "style", "style_at",
                 "side", "last_shot")

    def __init__(self, now):
        self.mode = ADVANCE
        self.since = now
        self.until = 0.0
        self.retreats = []
        self.start = None
        self.style = ""
        self.style_at = -1e9
        self.side = 1.0
        self.last_shot = now


class CombatTactics:
    """Per-session tactics (see the module doc)."""

    def __init__(self, clock, nav=None, tier_of=None, busy=None):
        #: ``clock() -> seconds`` of unpaused play.
        self._clock = clock
        self._nav = nav
        self._tier_of = tier_of
        #: ``busy(thing) -> bool``: mid-draw on a bow, so it stands still.
        self._busy = busy
        self._states = {}

    # -- engine hooks ---------------------------------------------------------
    def steer_many(self, things, starts, targets):
        """Fio's steer hook: a waypoint (or None) per stepping fighter."""
        out = [None] * len(things)
        routed = []
        for i, (thing, start, target) in enumerate(zip(things, starts, targets)):
            if thing is None:
                continue
            wp = self.waypoint(thing, start, target)
            if wp is None:
                routed.append(i)
            else:
                out[i] = wp
        if routed and self._nav is not None:
            sub = self._nav.steer_many([things[i] for i in routed],
                                       [starts[i] for i in routed],
                                       [targets[i] for i in routed])
            for i, wp in zip(routed, sub or ()):
                out[i] = wp
        return out

    def note_shot(self, thing) -> None:
        """A shot fell due for *thing* (the shot hook calls this)."""
        state = self._states.get(id(thing))
        if state is not None:
            state.last_shot = self._clock()

    def retreating(self, thing) -> bool:
        """Whether *thing* is backing away this moment (and so holds its fire)."""
        state = self._states.get(id(thing))
        return state is not None and state.mode == RETREAT

    def forget(self, thing) -> None:
        self._states.pop(id(thing), None)

    def clear(self) -> None:
        self._states.clear()

    # -- the decision ---------------------------------------------------------
    def waypoint(self, thing, start, target):
        """Where *thing* at *start* should head with its foe at *target*:
        ``(x, y, z)``, its own position to stand, or None to chase as usual."""
        props = getattr(thing, "properties", None)
        if not isinstance(props, dict) or props.get("_flee") or props.get("dead"):
            return None
        if self._tier_of is not None:
            from engine.spatial import TIER_ACTIVE
            if self._tier_of(thing) > TIER_ACTIVE:
                self._states.pop(id(thing), None)
                npc_stamina.walk(props)
                return None
        now = self._clock()
        key = id(thing)
        state = self._states.get(key)
        if state is None:
            state = self._states[key] = _State(now)
        if now - state.style_at > LOADOUT_SECONDS:
            state.style = ranged_style(props)
            state.style_at = now
        dist = math.hypot(float(start[0]) - float(target[0]),
                          float(start[2]) - float(target[2]))
        if not state.style:
            state.mode = ADVANCE
            npc_stamina.pace(props, now, dist > RUN_FROM)
            return None
        mode = self._decide(state, props, start, target, now)
        # Run to close in or to get back in range; back away and edge
        # sideways at a walk.
        far = KEEP_BAND[state.style][1]
        npc_stamina.pace(props, now, (mode == ADVANCE and dist > far + RUN_MARGIN)
                         or (mode == COMMIT and dist > RUN_FROM))
        sx, sy, sz = float(start[0]), float(start[1]), float(start[2])
        if mode != COMMIT and self._busy is not None and self._busy(thing):
            return (sx, sy, sz)                     # an archer draws standing
        if mode in (HOLD, COMMIT):
            # A commit to melee closes in: the shot hook stabs once it is near.
            return None if mode == COMMIT else (sx, sy, sz)
        if mode == ADVANCE:
            return None
        dx, dz = sx - float(target[0]), sz - float(target[2])
        dist = math.hypot(dx, dz) or 1.0
        ax, az = dx / dist, dz / dist                       # away from the foe
        if mode == SIDESTEP:
            return (sx - az * state.side * RETREAT_STEP, sy, sz + ax * state.side * RETREAT_STEP)
        # Back away, angled a little to its side so it does not back into
        # the same wall twice.
        lx, lz = -az * state.side * 0.35, ax * state.side * 0.35
        return (sx + (ax + lx) * RETREAT_STEP, sy, sz + (az + lz) * RETREAT_STEP)

    def _decide(self, state, props, start, target, now) -> str:
        dist = math.hypot(float(start[0]) - float(target[0]),
                          float(start[2]) - float(target[2]))
        near, far = KEEP_BAND[state.style]

        if state.mode == COMMIT:
            if now < state.until:
                return COMMIT
            state.retreats.clear()
        if dist <= COMMIT_RANGE:
            return self._commit(state, now)
        if state.mode == RETREAT:
            elapsed = now - state.since
            moved = math.hypot(float(start[0]) - state.start[0],
                               float(start[2]) - state.start[1])
            if elapsed >= 0.4 and moved < STUCK_SHARE * FIGHTER_SPEED * elapsed:
                return self._commit(state, now)          # a wall at its back
            if elapsed < RETREAT_BURST and dist < near:
                return RETREAT
            return self._set(state, HOLD, now)
        if dist < near:
            if state.mode == HOLD and now - state.since < RETREAT_REST:
                return HOLD                               # still casting / drawing
            state.retreats = [t for t in state.retreats if now - t < RETREAT_WINDOW]
            if len(state.retreats) >= MAX_RETREATS:
                return self._commit(state, now)
            state.retreats.append(now)
            state.start = (float(start[0]), float(start[2]))
            state.side = -state.side
            return self._set(state, RETREAT, now)
        if dist > far or now - state.last_shot > NO_SHOT_ADVANCE:
            if state.mode != ADVANCE:
                self._set(state, ADVANCE, now)
            return ADVANCE
        # In the band: stand, with a sidestep now and then.
        if state.mode == SIDESTEP:
            if now - state.since < SIDESTEP_SECONDS:
                return SIDESTEP
            return self._set(state, HOLD, now)
        if state.mode != HOLD:
            self._set(state, HOLD, now)
            state.last_shot = max(state.last_shot, now - 1.0)
            return HOLD
        if now - state.since > SIDESTEP_EVERY:
            state.side = -state.side
            return self._set(state, SIDESTEP, now)
        return HOLD

    @staticmethod
    def _set(state, mode, now) -> str:
        state.mode = mode
        state.since = now
        return mode

    @staticmethod
    def _commit(state, now) -> str:
        state.mode = COMMIT
        state.since = now
        state.until = now + COMMIT_SECONDS
        return COMMIT
