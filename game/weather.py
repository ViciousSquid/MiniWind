"""
Weather: clear skies, cloud, rain, snow and storms over the Vale, and what
they do.

One weather for the world, changing by itself over the game's hours: a spell
of clear sky, cloud gathering, rain, now and then a storm, clearing again.
How hard it rains eases in and out rather than switching; the ground gets
wet in the rain and dries afterwards, faster under a clear sky.

What it does to fire (:mod:`game.grass_fire`, :mod:`game.burning`):

* rain makes burning grass burn out faster and spread slower -- heavy rain
  stops a fire spreading at all and soon puts it out;
* wet ground barely catches (its fuel is scaled by :meth:`Weather.dryness`);
* someone burning, and a Flare's fire on the ground, go out sooner.

What a storm does besides (:attr:`Weather.storm` eases in and out with it):
the wind blows a gale in gusts (:mod:`game.wind`), the grass and the fields
thrash in it, lightning strikes now and then (:mod:`game.lightning`), and no
one travels -- fast travel is refused, and the parties on the roads stay put
until it passes (:meth:`Weather.storming`).

Snow (:data:`SNOW`) comes only when it is cold -- from the end of autumn,
through winter, to the year's end (:func:`game.calendar.coldness`, handed to
:meth:`Weather.update`): in the cold the sky follows :data:`NEXT_COLD`, where
snow takes rain's place, and a storm is a **blizzard** -- snow, not rain, a
gale all the same, and lightning rarely. Falling snow settles
(:attr:`Weather.snow`, 0..1), lies through the cold, and thaws -- fast once
the cold is gone, faster in rain -- its meltwater wetting the ground. Snow
lying on the ground barely burns (:meth:`Weather.dryness`). From the console
``weather snow`` makes it snow in any season (it thaws soon in summer).

The look is drawn by :mod:`game.ui.rain` over the scene, and the settled
snow on the terrain (the renderer's ``snow_cover``). It is plain state
advanced by game time -- no Qt, no GL -- so it is tested headless.
"""

from __future__ import annotations

import random

CLEAR, OVERCAST, RAIN, STORM, SNOW = "clear", "overcast", "rain", "storm", "snow"
KINDS = (CLEAR, OVERCAST, RAIN, STORM, SNOW)
#: Other words for them (the console's ``weather sunny``).
ALIASES = {"sunny": CLEAR, "sun": CLEAR, "fair": CLEAR, "cloudy": OVERCAST, "cloud": OVERCAST,
           "rainy": RAIN, "raining": RAIN, "thunder": STORM, "stormy": STORM,
           "snowy": SNOW, "snowing": SNOW, "snowfall": SNOW}
#: How hard it rains in each, 0..1, and how long a spell of each lasts
#: (game hours, min..max). A blizzard (a storm in the cold) rains not at all.
RAIN_OF = {CLEAR: 0.0, OVERCAST: 0.0, RAIN: 0.55, STORM: 1.0, SNOW: 0.0}
SPELL_HOURS = {CLEAR: (6.0, 20.0), OVERCAST: (2.0, 6.0), RAIN: (1.0, 5.0), STORM: (0.5, 2.0),
               SNOW: (2.0, 7.0)}
#: How hard it snows (0..1): steady snow, and a blizzard (a storm in the cold).
SNOWFALL_OF = {SNOW: 0.6}
BLIZZARD_SNOWFALL = 1.0
#: How cold it must be (game/calendar.py ``coldness``) for the cold sky:
#: snow for rain, blizzards for storms.
COLD = 0.5
#: What follows what, and how likely: in the warm months ...
NEXT = {CLEAR: ((OVERCAST, 1.0),),
        OVERCAST: ((RAIN, 0.55), (CLEAR, 0.35), (STORM, 0.10)),
        RAIN: ((OVERCAST, 0.6), (STORM, 0.15), (CLEAR, 0.25)),
        STORM: ((RAIN, 0.7), (OVERCAST, 0.3)),
        SNOW: ((OVERCAST, 0.6), (RAIN, 0.2), (CLEAR, 0.2))}
#: ... and in the cold, where snow takes rain's place.
NEXT_COLD = {CLEAR: ((OVERCAST, 1.0),),
             OVERCAST: ((SNOW, 0.55), (CLEAR, 0.35), (STORM, 0.10)),
             SNOW: ((OVERCAST, 0.6), (STORM, 0.12), (CLEAR, 0.28)),
             STORM: ((SNOW, 0.7), (OVERCAST, 0.3)),
             RAIN: ((SNOW, 0.6), (OVERCAST, 0.4))}
#: Settled snow (0..1): how fast it builds while snow falls (per game hour at
#: full snowfall), and how fast it thaws (per game hour): slowly in the cold,
#: fast once it is gone, faster in rain. Meltwater wets the ground.
SETTLE_PER_HOUR = 0.6
THAW_COLD_PER_HOUR = 0.01
THAW_WARM_PER_HOUR = 0.35
THAW_RAIN_PER_HOUR = 0.6
MELT_WETS = 0.8
#: Lightning in a blizzard, as a share of a storm's.
BLIZZARD_LIGHTNING = 0.3
#: How fast the rain eases toward what the sky is doing (per game hour).
EASE_PER_HOUR = 3.0
#: Wetness: how fast rain soaks the ground, and how fast it dries (per game
#: hour; clear sky dries twice as fast as cloud).
SOAK_PER_HOUR = 1.5
DRY_PER_HOUR = 0.12
#: How dark the sky is over each (a wash over the scene, 0..1).
GLOOM_OF = {CLEAR: 0.0, OVERCAST: 0.18, RAIN: 0.3, STORM: 0.45, SNOW: 0.22}
#: How stormy the air is in each (0..1): the gale, the lightning.
STORM_OF = {CLEAR: 0.0, OVERCAST: 0.0, RAIN: 0.0, STORM: 1.0, SNOW: 0.0}
#: What a player is told when a storm forbids travel.
NO_TRAVEL_TEXT = "No one travels in this storm."


class Weather:
    def __init__(self, rng=None, kind=CLEAR):
        self.rng = rng or random.Random()
        self.kind = kind
        self.left = self._spell(kind)
        self.rain = RAIN_OF[kind]
        self.gloom = GLOOM_OF[kind]
        self.storm = STORM_OF[kind]
        self.wet = 0.0
        #: How cold it is (0..1, game/calendar.py ``coldness``), as last told.
        self.cold = 0.0
        #: How hard snow falls this instant (0..1), and how much lies (0..1).
        self.snowfall = 0.0
        self.snow = 0.0
        #: A spell forced from the console: (kind, hours) or None.
        self.forced = False

    def _spell(self, kind) -> float:
        lo, hi = SPELL_HOURS[kind]
        return self.rng.uniform(lo, hi)

    def set(self, kind, hours=None, at_once=False) -> bool:
        """Turn the sky to *kind* (or one of its :data:`ALIASES`) for *hours*
        (or a spell of the usual length). It fades in as weather does;
        *at_once* skips that (tests and tools only)."""
        kind = ALIASES.get(str(kind).lower(), str(kind).lower())
        if kind not in KINDS:
            return False
        self.kind = kind
        self.left = float(hours) if hours else self._spell(kind)
        self.forced = True
        if at_once:
            self.rain, self.gloom = self._rain_target(), GLOOM_OF[kind]
            self.storm = STORM_OF[kind]
            self.snowfall = self._snowfall_target()
        return True

    # -- what the sky is aiming for --------------------------------------------
    def is_cold(self) -> bool:
        return self.cold >= COLD

    def blizzard(self) -> bool:
        """A storm in the cold: snow on the gale instead of rain."""
        return self.kind == STORM and self.is_cold()

    def _rain_target(self) -> float:
        return 0.0 if self.blizzard() else RAIN_OF[self.kind]

    def _snowfall_target(self) -> float:
        return BLIZZARD_SNOWFALL if self.blizzard() else SNOWFALL_OF.get(self.kind, 0.0)

    def update(self, hours: float, cold=None) -> None:
        """Advance the weather by *hours* of game time; *cold* is how cold
        it is now (0..1, :func:`game.calendar.coldness`; None keeps the
        last)."""
        if cold is not None:
            self.cold = max(0.0, min(1.0, float(cold)))
        hours = max(0.0, min(2.0, float(hours)))
        if hours <= 0.0:
            return
        self.left -= hours
        if self.left <= 0.0:
            self.kind = self._roll((NEXT_COLD if self.is_cold() else NEXT)[self.kind])
            self.left = self._spell(self.kind)
            self.forced = False
        k = min(1.0, EASE_PER_HOUR * hours)
        self.rain += (self._rain_target() - self.rain) * k
        self.snowfall += (self._snowfall_target() - self.snowfall) * k
        self.gloom += (GLOOM_OF[self.kind] - self.gloom) * k
        self.storm += (STORM_OF[self.kind] - self.storm) * k
        if self.rain > 0.05:
            self.wet = min(1.0, self.wet + SOAK_PER_HOUR * self.rain * hours)
        else:
            dry = DRY_PER_HOUR * (2.0 if self.kind == CLEAR else 1.0)
            self.wet = max(0.0, self.wet - dry * hours)
        # Snow settles while it falls, and thaws: slowly in the cold, fast
        # once it is gone, faster in rain; its meltwater wets the ground.
        if self.snowfall > 0.05:
            self.snow = min(1.0, self.snow + SETTLE_PER_HOUR * self.snowfall * hours)
        thaw = (THAW_COLD_PER_HOUR * self.cold + THAW_WARM_PER_HOUR * (1.0 - self.cold)
                + THAW_RAIN_PER_HOUR * self.rain) * hours
        if self.snowfall > 0.05:
            thaw *= 0.2                       # it barely thaws while it snows
        melted = min(self.snow, thaw)
        if melted > 0.0:
            self.snow -= melted
            self.wet = min(1.0, self.wet + MELT_WETS * melted)

    def _roll(self, options):
        r = self.rng.random() * sum(w for _k, w in options)
        for kind, w in options:
            r -= w
            if r <= 0.0:
                return kind
        return options[-1][0]

    # -- what it does ------------------------------------------------------------
    def raining(self) -> bool:
        return self.rain > 0.08

    def snowing(self) -> bool:
        return self.snowfall > 0.08

    def lightning(self) -> float:
        """How hard lightning strikes (0..1): a storm's level, a third of it
        in a blizzard."""
        return self.storm * (BLIZZARD_LIGHTNING if self.blizzard() else 1.0)

    def storming(self) -> bool:
        """Whether it storms: from the moment the sky turns to a storm until
        it turns to something else (no one travels in it)."""
        return self.kind == STORM

    def dryness(self) -> float:
        """How readily grass burns (0 soaked or under snow .. 1 dry)."""
        return max(0.05, (1.0 - 0.9 * self.wet) * (1.0 - 0.95 * self.snow))

    def douse(self) -> float:
        """How hard the rain (or half as hard, falling snow) fights fire
        this instant (0..1)."""
        return max(0.0, min(1.0, max(self.rain, 0.5 * self.snowfall)))

    def snapshot(self) -> dict:
        return {"kind": self.kind, "left": round(self.left, 3), "rain": round(self.rain, 3),
                "gloom": round(self.gloom, 3), "storm": round(self.storm, 3),
                "wet": round(self.wet, 3), "snowfall": round(self.snowfall, 3),
                "snow": round(self.snow, 3), "cold": round(self.cold, 3)}

    def restore(self, data) -> None:
        if not isinstance(data, dict) or data.get("kind") not in KINDS:
            return
        self.kind = data["kind"]
        # A save from before storms had their own level: as stormy as its sky.
        self.storm = STORM_OF[self.kind]
        # A save from before snow: none falling, none lying.
        self.snowfall = self.snow = 0.0
        for key in ("left", "rain", "gloom", "storm", "wet", "snowfall", "snow", "cold"):
            try:
                setattr(self, key, float(data.get(key, getattr(self, key))))
            except (TypeError, ValueError):
                pass
