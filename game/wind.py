"""
Wind: which way it blows across the Vale, and how hard.

One wind for the whole world, wandering slowly: its direction drifts a few
degrees a minute and turns now and then, its strength rises and falls over
the hours between a still morning and a gusty afternoon. Fire in the grass
runs before it (:mod:`game.grass_fire`) and its smoke drifts down it; the
rain leans in it (:mod:`game.ui.rain`), the clouds ride it (:mod:`game.sky`)
and the grass sways in it (:func:`grass_sway`, the renderer's ``grass_wind``).

A storm (:attr:`game.weather.Weather.storm`, fed in by :meth:`Wind.update`)
blows a gale on top: much stronger, in gusts that come and go over seconds
and veer the wind a little as they pass.

It is plain state advanced by game time -- no Qt, no GL -- and keeps nothing
between sessions: each day's wind is new.
"""

from __future__ import annotations

import math
import random

#: Radians the direction may drift per game hour, at most.
DRIFT_PER_HOUR = 0.6
#: Strength never falls below this (a breath of air) nor above 1 (a gale).
CALM = 0.15
#: How fast strength follows its slowly wandering target (per game hour).
EASE_PER_HOUR = 0.8
#: A full storm's gale: added to the strength, plus up to GUST_FORCE more in
#: a gust. Gusts are timed in real seconds -- a new one about every
#: 1 / GUST_PER_SECOND s, rising and falling at GUST_EASE a second -- and
#: veer the heading by up to GUST_VEER radians.
STORM_FORCE = 1.0
GUST_FORCE = 0.7
GUST_PER_SECOND = 0.6
GUST_EASE = 2.5
GUST_VEER = 0.35
#: The grass shader's wind strength (engine grass.vert ``windStrength``):
#: SWAY_CALM in still air plus SWAY_PER_FORCE per unit of :meth:`Wind.force`
#: -- a fresh breeze sways it about as the engine's default 0.65, a storm
#: past 1, where the shader's gale terms take over.
SWAY_CALM = 0.35
SWAY_PER_FORCE = 0.45


class Wind:
    """The world's wind: :meth:`vector` is ``(x, z)`` scaled by strength."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.angle = self.rng.uniform(0.0, 2.0 * math.pi)   # the way it blows TO
        self.strength = self.rng.uniform(0.3, 0.7)
        self._target = self.strength
        self._turn = 0.0
        #: How stormy it is (0..1), and the gust now and the one coming.
        self.storm = 0.0
        self.gust = 0.0
        self._gust_target = 0.0
        self.veer = 0.0
        self._veer_target = 0.0

    def update(self, hours: float, seconds: float = 0.0, storm: float = None) -> None:
        """Advance the wind by *hours* of game time (*seconds* of real
        time, for the gusts), with the weather *storm*-y (0..1; None leaves
        it as it was)."""
        if storm is not None:
            self.storm = max(0.0, min(1.0, float(storm)))
        self._gusts(max(0.0, min(1.0, float(seconds))))
        hours = max(0.0, min(1.0, float(hours)))
        if hours <= 0.0:
            return
        rng = self.rng
        # The heading wanders: a slow random turn that itself changes.
        self._turn += rng.uniform(-1.0, 1.0) * hours * 2.0
        self._turn = max(-1.0, min(1.0, self._turn))
        self.angle = (self.angle + self._turn * DRIFT_PER_HOUR * hours) % (2.0 * math.pi)
        # Strength eases toward a target that is picked afresh now and then.
        if rng.random() < hours * 0.5:
            self._target = rng.uniform(CALM, 1.0)
        self.strength += (self._target - self.strength) * min(1.0, EASE_PER_HOUR * hours)
        self.strength = max(CALM, min(1.0, self.strength))

    def _gusts(self, seconds: float) -> None:
        """A storm's gusts: a new one picked now and then, each rising and
        falling toward it. Out of a storm they die away (and draw no
        numbers, so calm weather plays out as it always did)."""
        if seconds <= 0.0:
            return
        if self.storm > 0.0:
            rng = self.rng
            if rng.random() < seconds * GUST_PER_SECOND:
                self._gust_target = rng.random()
                self._veer_target = rng.uniform(-1.0, 1.0)
        else:
            self._gust_target = self._veer_target = 0.0
        k = min(1.0, GUST_EASE * seconds)
        self.gust += (self._gust_target - self.gust) * k
        self.veer += (self._veer_target - self.veer) * k

    def force(self) -> float:
        """How hard it blows now: the strength (0..1), and a storm's gale
        and gust on top (up to 1 + STORM_FORCE + GUST_FORCE)."""
        return self.strength + self.storm * (STORM_FORCE + GUST_FORCE * self.gust)

    def direction(self):
        """The unit ``(x, z)`` the wind blows toward (a gust veers it)."""
        a = self.angle + self.storm * GUST_VEER * self.veer
        return math.cos(a), math.sin(a)

    def vector(self):
        """``(x, z)``: the direction scaled by :meth:`force` (0..1, more in
        a storm)."""
        dx, dz = self.direction()
        f = self.force()
        return dx * f, dz * f


def grass_sway(wind):
    """``(dir x, dir z, strength)`` for the renderer's ``grass_wind``: the
    way *wind* blows and how hard the grass shader sways in it -- gently
    in a breeze, violently in a storm. None (no wind) is the engine's
    default breeze."""
    if wind is None:
        return None
    dx, dz = wind.direction()
    return dx, dz, SWAY_CALM + SWAY_PER_FORCE * wind.force()


#: The storm's howl: the sound pack's wind ambience, a seamless loop, heard
#: everywhere while it storms, louder with the gale and each gust.
HOWL_SOUND = "Ambient_Wind01.wav"
HOWL_ID = "weather:storm_wind"
HOWL_START = 0.05           # storm level the howl starts at...
HOWL_STOP = 0.03            # ...and dies away below (no flicker between)
HOWL_QUIET, HOWL_LOUD = 0.25, 0.9
HOWL_EVERY = 0.5            # seconds between volume updates while it howls


class StormHowl:
    """When to start, follow and stop the storm's wind loop.

    :meth:`update` returns the sound requests to queue (often none): one
    looping ``play`` as the storm rises, a ``keep_playing`` refresh with the
    new volume every :data:`HOWL_EVERY` seconds (it never restarts the loop,
    and brings it back if the mixer dropped it), and a ``stop`` as it ends.
    """

    def __init__(self):
        self.playing = False
        self._clock = 0.0

    def volume(self, storm, gust) -> float:
        s = max(0.0, min(1.0, float(storm)))
        g = max(0.0, min(1.0, float(gust)))
        return round(s * (HOWL_QUIET + (HOWL_LOUD - HOWL_QUIET) * (0.4 + 0.6 * g)), 3)

    def _play(self, storm, gust):
        return {"action": "play", "file": HOWL_SOUND, "entity_id": HOWL_ID,
                "looping": True, "keep_playing": True, "global": True,
                "volume": self.volume(storm, gust)}

    def update(self, seconds, storm, gust):
        if not self.playing:
            if storm < HOWL_START:
                return []
            self.playing, self._clock = True, 0.0
            return [self._play(storm, gust)]
        if storm < HOWL_STOP:
            return self.stop()
        self._clock += max(0.0, float(seconds))
        if self._clock < HOWL_EVERY:
            return []
        self._clock = 0.0
        return [self._play(storm, gust)]

    def stop(self):
        if not self.playing:
            return []
        self.playing = False
        return [{"action": "stop", "file": HOWL_SOUND, "entity_id": HOWL_ID}]
