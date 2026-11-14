"""
Lightning: a storm's strikes, by chance, and the thunder after them.

While it storms (:attr:`game.weather.Weather.storm`, which eases in and out)
lightning strikes now and then somewhere round the player -- most of it far
off, now and then close enough to see. Each strike lights the sky (a flash,
brighter the nearer it is), and one in view is drawn as a jagged bolt
(:mod:`game.ui.rain`). Its thunder follows after a delay that grows with
the distance (sound is slow; here slower than in life, so the gap is felt).
A strike close by in dry grass may set it alight; but the storm's rain soon
soaks the ground and fights any fire, so that is a storm's first minutes.

Plain state advanced by real seconds -- no Qt, no GL -- and every chance is
drawn from its own rng, so a seeded one plays out the same every time. The
strikes are kept as a tuple replaced whole: the overlay reads it from the
GUI thread while the logic thread advances it.
"""

from __future__ import annotations

import math
import random
from collections import namedtuple

#: Strikes a second in a full storm (one every ten seconds or so).
STRIKES_PER_SECOND = 0.1
#: Where they fall: this far from the player at least, and at most.
NEAR = 250.0
FAR = 9000.0
#: A strike nearer than this is in view and drawn as a bolt; this share of
#: strikes fall that near (the storm is overhead), the rest anywhere farther.
SEEN = 1400.0
SEEN_SHARE = 0.3
#: A strike's look: how long its bolt shows, and how long a strike is kept.
BOLT_SECONDS = 0.32
KEEP_SECONDS = 30.0
#: How fast thunder travels (world units a second): slower than sound truly
#: is, so a strike a few hundred units off rumbles a moment later and one far
#: off several seconds after.
THUNDER_SPEED = 1500.0
#: The sound, and how loud: a near strike's crack to a far one's mutter.
#: There is no thunder recording in the sound pack; the explosion's low boom,
#: played quiet, stands in for it.
THUNDER_SOUND = "explode.mp3"
THUNDER_LOUD = 0.75
THUNDER_QUIET = 0.12
#: A strike within this distance on dry ground sets the grass alight with
#: this chance (times how dry the ground is).
IGNITE_RANGE = 900.0
IGNITE_CHANCE = 0.35

#: One strike: when (seconds on :attr:`Lightning.clock`), where (world x,
#: ground y, z), how far from the player, when its thunder is heard, a seed for its bolt's
#: shape, and whether it set the grass alight.
Strike = namedtuple("Strike", "at x y z distance thunder_at seed ignites")


class Lightning:
    def __init__(self, rng=None, ground=None):
        self.rng = rng or random.Random()
        #: ``ground(x, z) -> y``: where a strike meets the ground.
        self.ground = ground
        #: Seconds this storm-watcher has run (the strikes' clock).
        self.clock = 0.0
        #: Recent strikes, oldest first (a tuple, replaced whole).
        self.strikes = ()
        self._heard = set()

    def update(self, seconds, storm, origin=None, dryness=0.0):
        """Advance *seconds* with the weather *storm*-y (0..1) round
        *origin* ``(x, z)`` on ground *dryness* (0 soaked .. 1 dry).
        Returns the new strikes (usually none)."""
        seconds = max(0.0, min(1.0, float(seconds)))
        self.clock += seconds
        storm = max(0.0, min(1.0, float(storm)))
        new = []
        if storm > 0.0 and origin is not None and seconds > 0.0:
            rng = self.rng
            if rng.random() < 1.0 - math.exp(-STRIKES_PER_SECOND * storm * seconds):
                new.append(self._strike(origin, dryness))
        if new or (self.strikes and self.clock - self.strikes[0].at > KEEP_SECONDS):
            kept = tuple(s for s in self.strikes if self.clock - s.at <= KEEP_SECONDS)
            self.strikes = kept + tuple(new)
            self._heard &= {s.seed for s in self.strikes}
        return new

    def _strike(self, origin, dryness):
        rng = self.rng
        # Some in sight, the rest spread over the area out to FAR.
        if rng.random() < SEEN_SHARE:
            r = rng.uniform(NEAR, SEEN)
        else:
            r = math.sqrt(rng.uniform(SEEN * SEEN, FAR * FAR))
        a = rng.uniform(0.0, 2.0 * math.pi)
        seed = rng.randrange(1 << 30)
        ignites = r < IGNITE_RANGE and rng.random() < IGNITE_CHANCE * max(0.0, min(1.0, dryness))
        x, z = origin[0] + math.cos(a) * r, origin[1] + math.sin(a) * r
        y = float(self.ground(x, z)) if self.ground is not None else 0.0
        return Strike(self.clock, x, y, z, r, self.clock + r / THUNDER_SPEED, seed, ignites)

    def thunder_due(self):
        """``[(strike, volume)]`` whose thunder reaches the player now, each
        once."""
        out = []
        for s in self.strikes:
            if s.seed not in self._heard and s.thunder_at <= self.clock:
                self._heard.add(s.seed)
                near = 1.0 - min(1.0, s.distance / FAR)
                out.append((s, THUNDER_QUIET + (THUNDER_LOUD - THUNDER_QUIET) * near * near))
        return out

    def flash(self, now=None) -> float:
        """How bright the sky is lit this instant (0..1): each strike's double
        flicker, dimmer the farther off it fell."""
        now = self.clock if now is None else now
        best = 0.0
        for s in self.strikes:
            f = flicker(now - s.at)
            if f > 0.0:
                best = max(best, f * (1.0 - 0.6 * min(1.0, s.distance / FAR)))
        return best

    def bolts(self, now=None):
        """``[(strike, age)]`` near enough to see, while their bolt shows."""
        now = self.clock if now is None else now
        return [(s, now - s.at) for s in self.strikes
                if s.distance <= SEEN and 0.0 <= now - s.at < BOLT_SECONDS]


def flicker(t) -> float:
    """A strike's light *t* seconds after it: a sharp flash, a dark beat,
    then a weaker second flicker; nothing after."""
    if 0.0 <= t < 0.08:
        return 1.0 - t / 0.08
    if 0.16 <= t < 0.30:
        return 0.6 * (1.0 - (t - 0.16) / 0.14)
    return 0.0
