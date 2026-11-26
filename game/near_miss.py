"""
An arrow past your head: a whoosh.

When an arrow someone else loosed flies past the player -- close enough to
miss them by inches, but a miss -- and flies on, ``assets/sounds/whoosh.mp3``
plays, centred on the player (an interface sound, heard as if by the ear).

The circumstances, exactly:

* **An arrow** (a projectile loosed with an arrow's ammunition,
  ``stuck_arrows.AMMO_KEY``) -- not a spell, a thrown thing or a bolt of
  magic -- and **not the player's own**.
* **A miss.** An arrow that hits the player is consumed by the engine before
  this looks, so it never whooshes; neither does one that sticks in a barrel
  or a wall, or runs out of range, before it reaches the player.
* **Very close.** Its path this tick passes within :data:`NEAR_MISS_RADIUS`
  of the player -- the hit sphere (``PROJECTILE_PLAYER_RADIUS``, 32) and a
  few inches more.
* **Past, and on.** It was coming toward the player, has gone by its
  nearest point to them and is flying away, still in flight. (An archer
  beside the player loosing away from them is not a near miss.)
* **Once per arrow.**

The path between two ticks is checked as a line, not only where the arrow is
at each tick, so a fast arrow cannot slip between frames unheard. On a tick
with no arrow in flight it costs one count check.
"""

from __future__ import annotations

import contextlib
import math

from . import fio
from .stuck_arrows import AMMO_KEY

#: The sound, from assets/sounds (loose or in a .fiopak).
WHOOSH_SOUND = "whoosh.mp3"
#: The engine's hit sphere round the player (engine/logic_combat.py).
HIT_RADIUS = 32.0
#: Passing nearer than this (world units, from the player's position --
#: their head) is close enough to hear: the hit sphere and a few inches.
NEAR_MISS_RADIUS = HIT_RADIUS + 24.0


def closest_on_segment(a, b, p):
    """``(distance, t)``: how near the segment a→b comes to point p, and
    where along it (0 at a, 1 at b)."""
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ap = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
    length2 = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2]
    t = 0.0 if length2 <= 0.0 else max(0.0, min(1.0, (
        ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / length2))
    c = (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t)
    return math.dist(c, p), t


class NearMiss:
    """Listens for arrows flying past the player's head (module docstring)."""

    def __init__(self, session):
        self.session = session
        #: arrow tag -> its position last tick.
        self._last = {}
        #: Tags of arrows that have already whooshed.
        self._heard = set()
        #: Tags of arrows that have been seen coming toward the player.
        self._coming = set()

    @property
    def logic(self):
        return self.session.logic

    def update(self) -> int:
        """Once a game tick, after the projectiles have moved. Returns how
        many arrows whooshed past this tick."""
        logic = self.logic
        if not fio.projectile_count(logic):
            if self._last:
                self._last.clear()
                self._heard.clear()
                self._coming.clear()
            return 0
        player = fio.player(logic)
        if player is None or getattr(player, "pos", None) is None:
            return 0
        head = (float(player.pos[0]), float(player.pos[1]), float(player.pos[2]))
        from engine.logic_combat import PLAYER_PROJECTILE_OWNER
        store = getattr(getattr(logic, "combat_runtime", None), "_monster_projectiles", None)
        if store is None:
            return 0
        passed = 0
        seen = {}
        with fio.monster_lock(logic) or contextlib.nullcontext():
            for row in range(len(store)):
                tag = int(store.tag[row])
                if not tag or int(store.owner_id[row]) == PLAYER_PROJECTILE_OWNER:
                    continue
                meta = store.metadata.get(tag)
                if not meta or not meta.get(AMMO_KEY):
                    continue                       # not an arrow
                now = (float(store.pos[row, 0]), float(store.pos[row, 1]),
                       float(store.pos[row, 2]))
                vel = (float(store.vel[row, 0]), float(store.vel[row, 1]),
                       float(store.vel[row, 2]))
                seen[tag] = now
                before = self._last.get(tag)
                away = sum(v * (n - h) for v, n, h in zip(vel, now, head)) > 0.0
                if before is not None and tag not in self._coming:
                    # Coming toward the player at some point on the way here.
                    if sum(v * (b - h) for v, b, h in zip(vel, before, head)) < 0.0:
                        self._coming.add(tag)
                if not away:
                    self._coming.add(tag)
                if before is None or tag in self._heard or tag not in self._coming:
                    continue
                distance, t = closest_on_segment(before, now, head)
                if distance <= NEAR_MISS_RADIUS and t < 1.0 and away:
                    self._heard.add(tag)
                    passed += 1
        self._last = seen
        self._heard &= set(seen)
        self._coming &= set(seen)
        if passed:
            play = getattr(self.session, "play_ui_sound", None)
            if play is not None:
                play(WHOOSH_SOUND)
        return passed
