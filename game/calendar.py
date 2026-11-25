"""
The Vale's calendar: years, seasons, leap years, sunrise and sunset, the moon.

One place answers "what day of the year is it?", "is it day?", "how dark is
it?" -- the night overlay (:mod:`game.ui.daylight`), the reflected sky
(:mod:`game.sky`), torches after dark (:attr:`GameClock.is_daytime`), the
wheat (:meth:`game.runtime` ``_update_season``) and the HUD all read it, so
they always agree.

The year
--------
A year is :data:`YEAR_DAYS` (28) game days -- four seasons of seven, spring
first -- about 11 real hours at the default 24 real minutes a day. Every
:data:`LEAP_EVERY`-th year (years 4, 8, 12 ...) is a **leap year**: it has a
29th day, **Leap Day**, after the last day of winter and before the next
spring. Leap Day belongs to no week and no season; the Vale keeps it as the
Leap Festival (:func:`festival`).

The game clock counts days from 1; day 1 is the last day of year 1's summer
(:data:`YEAR_START_DAYS`), close to where the farming year always opened.

Day and night
-------------
Day length follows the year: about 15.8 hours at midsummer and 8.6 at
midwinter, 12.2 at the equinoxes, centred on solar noon (12:24). Everything
that shades the day is keyed to *solar hours* (:func:`solar_hour`): the
clock's hour stretched so that sunrise always reads 06:18 and sunset 18:30
-- the equinox. At an equinox solar hours are clock hours, so the look of the
day there is unchanged; in summer the same dawn simply comes earlier and dusk
later.

Pure Python -- no Qt, no GL -- so it is tested headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Days in an ordinary year: four seasons of :data:`SEASON_DAYS`.
YEAR_DAYS = 28
SEASON_DAYS = 7
SEASONS = ("spring", "summer", "autumn", "winter")
#: Every this-many years is a leap year (year 4, 8, 12, ...).
LEAP_EVERY = 4
#: An ordinary year plus a leap year's extra day, every LEAP_EVERY years.
CYCLE_DAYS = YEAR_DAYS * LEAP_EVERY + 1
#: Whole days of year 1 already gone at the clock's day 0, midnight: a new game
#: (day 1) opens on the last day of summer, the wheat standing tall and gold.
#: Whole, so that every date turns over at the clock's midnight.
YEAR_START_DAYS = 12
#: The same as a fraction of the year.
YEAR_START = YEAR_START_DAYS / YEAR_DAYS

#: Solar noon, and day length: mean (the equinoxes) and how far it swings.
SOLAR_NOON = 12.4
DAY_HOURS_MEAN = 12.2
DAY_HOURS_SWING = 3.6
#: Where in the year the longest day falls (mid-summer).
MIDSUMMER = 0.375
#: Sunrise and sunset at an equinox: the hours solar hours are measured in.
EQUINOX_SUNRISE = SOLAR_NOON - DAY_HOURS_MEAN / 2.0      # 06:18
EQUINOX_SUNSET = SOLAR_NOON + DAY_HOURS_MEAN / 2.0       # 18:30
#: Daytime in solar hours (torches go out, lamps are not needed).
DAYTIME = (6.0, 20.0)
#: The sun's height at noon: midsummer and midwinter (degrees).
NOON_ELEVATION = (62.0, 18.0)

#: Days from one new moon to the next.
LUNAR_DAYS = 8.0
MOON_PHASES = ("new moon", "waxing crescent", "first quarter", "waxing gibbous",
               "full moon", "waning gibbous", "last quarter", "waning crescent")

LEAP_FESTIVAL = "leap"
LEAP_DAY_NAME = "Leap Day"


def is_leap_year(year: int) -> bool:
    return int(year) % LEAP_EVERY == 0


def year_length(year: int) -> int:
    return YEAR_DAYS + (1 if is_leap_year(year) else 0)


def position(clock) -> float:
    """Days since the first morning of year 1's spring (a float)."""
    return YEAR_START_DAYS + float(clock.day) + float(clock.hour) / 24.0


def _locate(days: float):
    """``(year, days into that year)`` for a :func:`position`."""
    cycles, rest = divmod(float(days), CYCLE_DAYS)
    year = 1 + LEAP_EVERY * int(cycles)
    for _ in range(LEAP_EVERY):
        length = year_length(year)
        if rest < length:
            break
        rest -= length
        year += 1
    return year, rest


@dataclass(frozen=True)
class Date:
    year: int
    #: 1-based day of the year; 29 is Leap Day.
    day_of_year: int
    #: "spring" .. "winter"; Leap Day reports "winter" (the year's end).
    season: str
    #: 1..7 within the season (Leap Day: 8).
    day_of_season: int
    leap_year: bool
    leap_day: bool
    #: 0..1 through the year (0 = first day of spring). Leap Day holds at
    #: the very end of winter.
    year_fraction: float

    @property
    def season_name(self) -> str:
        return LEAP_DAY_NAME if self.leap_day else self.season.capitalize()


def date_at(days: float) -> Date:
    year, rest = _locate(days)
    leap_day = rest >= YEAR_DAYS
    index = int(rest)
    season_index = min(len(SEASONS) - 1, index // SEASON_DAYS)
    fraction = (YEAR_DAYS - 1e-6) / YEAR_DAYS if leap_day else rest / YEAR_DAYS
    return Date(year=year, day_of_year=index + 1, season=SEASONS[season_index],
                day_of_season=index - season_index * SEASON_DAYS + 1,
                leap_year=is_leap_year(year), leap_day=leap_day,
                year_fraction=fraction)


def date(clock) -> Date:
    """Today's :class:`Date` on *clock* (a :class:`GameClock`)."""
    return date_at(position(clock))


def year_fraction(clock) -> float:
    return date(clock).year_fraction


def season(clock) -> str:
    return date(clock).season


def season_blend(clock, ease_days: float = 1.5):
    """``(season, next season, t)``: *t* rises 0..1 over the last *ease_days*
    of a season, so colours and odds change gradually, not at one midnight."""
    d = date(clock)
    days = d.year_fraction * YEAR_DAYS
    into = days - SEASONS.index(d.season) * SEASON_DAYS
    nxt = SEASONS[(SEASONS.index(d.season) + 1) % len(SEASONS)]
    t = (into - (SEASON_DAYS - ease_days)) / ease_days
    t = max(0.0, min(1.0, t))
    return d.season, nxt, t * t * (3.0 - 2.0 * t)


# -- the sun -------------------------------------------------------------------
def _summer(fraction: float) -> float:
    """1 at midsummer, -1 at midwinter, 0 at the equinoxes."""
    return math.cos(2.0 * math.pi * (float(fraction) - MIDSUMMER))


def day_hours(fraction: float) -> float:
    return DAY_HOURS_MEAN + DAY_HOURS_SWING * _summer(fraction)


def sun_times(fraction: float):
    """``(sunrise, sunset)`` in clock hours at a point in the year."""
    half = day_hours(fraction) / 2.0
    return SOLAR_NOON - half, SOLAR_NOON + half


def sunrise_sunset(clock):
    """Today's ``(sunrise, sunset)`` (taken at noon, so it holds all day)."""
    noon = position(clock) - float(clock.hour) / 24.0 + 0.5
    return sun_times(date_at(noon).year_fraction)


def solar_hour_at(hour: float, sunrise: float, sunset: float) -> float:
    """*hour* stretched so sunrise reads :data:`EQUINOX_SUNRISE` and sunset
    :data:`EQUINOX_SUNSET` (day and night each stretched evenly)."""
    h = float(hour) % 24.0
    day = sunset - sunrise
    eq_day = EQUINOX_SUNSET - EQUINOX_SUNRISE
    if sunrise <= h < sunset:
        return EQUINOX_SUNRISE + (h - sunrise) * eq_day / day
    night = 24.0 - day
    into = (h - sunset) % 24.0
    return (EQUINOX_SUNSET + into * (24.0 - eq_day) / night) % 24.0


def solar_hour(clock) -> float:
    """The clock's hour in solar hours (see the module notes): what the
    night overlay, the reflected sky and :func:`is_daytime` are keyed to."""
    rise, set_ = sun_times(date(clock).year_fraction)
    return solar_hour_at(clock.hour, rise, set_)


def is_daytime(clock) -> bool:
    return DAYTIME[0] <= solar_hour(clock) < DAYTIME[1]


def sun(clock):
    """``(elevation, azimuth)`` in degrees. Elevation is negative below the
    horizon; azimuth runs east (90) through south (180) to west (270)."""
    f = date(clock).year_fraction
    s = solar_hour(clock)
    hi, lo = NOON_ELEVATION
    noon = (hi + lo) / 2.0 + (hi - lo) / 2.0 * _summer(f)
    day = EQUINOX_SUNSET - EQUINOX_SUNRISE
    if EQUINOX_SUNRISE <= s < EQUINOX_SUNSET:          # sunrise..sunset: 0..pi
        angle = math.pi * (s - EQUINOX_SUNRISE) / day
    else:                                              # the night: pi..2pi
        angle = math.pi + math.pi * ((s - EQUINOX_SUNSET) % 24.0) / (24.0 - day)
    azimuth = (90.0 + 180.0 * angle / math.pi) % 360.0
    return noon * math.sin(angle), azimuth


# -- the moon ------------------------------------------------------------------
def moon_phase(clock) -> float:
    """0 new moon, 0.5 full moon, back to 1."""
    return (position(clock) / LUNAR_DAYS) % 1.0


def moon_name(clock) -> str:
    return MOON_PHASES[int(round(moon_phase(clock) * len(MOON_PHASES))) % len(MOON_PHASES)]


# -- festivals -----------------------------------------------------------------
def festival(clock):
    """The festival kept today, or None: :data:`LEAP_FESTIVAL` on Leap Day."""
    return LEAP_FESTIVAL if date(clock).leap_day else None


def day_name(clock, weekdays):
    """Today's name: a weekday from *weekdays*, or "Leap Day", which belongs
    to no week (the weekdays carry on around it)."""
    if date(clock).leap_day:
        return LEAP_DAY_NAME
    return weekdays[(int(clock.day) - 1) % len(weekdays)]


def _hhmm(hour: float) -> str:
    minutes = int(round(float(hour) * 60.0)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def describe(clock) -> str:
    """One line for tools and the storyteller window: the date, the season,
    sunrise and sunset, the moon -- and Leap Day or a leap year."""
    d = date(clock)
    rise, set_ = sunrise_sunset(clock)
    when = (f"Year {d.year} · {LEAP_DAY_NAME} — the Leap Festival" if d.leap_day else
            f"Year {d.year}{' (leap year)' if d.leap_year else ''} · {d.season.capitalize()}, "
            f"day {d.day_of_season} of {SEASON_DAYS}")
    return (f"{when} · Day {int(clock.day)} {_hhmm(clock.hour)} · sunrise {_hhmm(rise)} · "
            f"sunset {_hhmm(set_)} · {moon_name(clock).replace(' moon', '')} moon")


# -- what the Vale is told at the turn of a day ----------------------------------
def announcements(clock):
    """``[(text, toast)]`` for the start of today: a new year, a new season,
    Leap Day and its eve. *toast* marks the line worth a toast on screen."""
    d = date(clock)
    out = []
    if d.leap_day:
        out.append((f"LEAP DAY! The Vale keeps the Leap Festival, as it does but once in "
                    f"{LEAP_EVERY} years. Lanterns, bonfires and music in every town; no "
                    f"honest soul works today.", True))
        return out
    if d.day_of_year == 1:
        out.append((f"A new year begins: Year {d.year}." + (
            " It is a leap year: Leap Day falls after the last day of winter."
            if d.leap_year else ""), True))
    if d.day_of_season == 1:
        out.append((f"{d.season.capitalize()} has come to the Vale.", d.day_of_year != 1))
    if d.leap_year and d.day_of_year == YEAR_DAYS:
        out.append(("Tomorrow is Leap Day. The towns are hanging lanterns for the "
                    "Leap Festival.", True))
    return out
