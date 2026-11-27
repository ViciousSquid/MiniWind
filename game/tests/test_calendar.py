"""The Vale's calendar: years, leap years and Leap Day, seasons, sunrise and
sunset, solar hours, the sun and the moon (game/calendar.py)."""

import pytest

from engine import terrain_biomes

from .. import calendar as cal
from .. import chatter
from ..rpg.gametime import WEEKDAYS, GameClock


def clock(day, hour=12.0):
    return GameClock(hour=hour, day=day)


def first_day(predicate, start=1, limit=2000):
    for day in range(start, start + limit):
        if predicate(cal.date(clock(day, 0.0))):
            return day
    raise AssertionError("never happened")


# -- the year --------------------------------------------------------------------
def test_the_year_matches_the_farming_year():
    assert cal.YEAR_DAYS == terrain_biomes.YEAR_DAYS
    assert cal.SEASONS == terrain_biomes.SEASONS
    assert cal.YEAR_DAYS == len(cal.SEASONS) * cal.SEASON_DAYS


def test_a_new_game_opens_at_the_end_of_summer_in_year_one():
    d = cal.date(clock(1, 8.0))
    assert (d.year, d.season, d.day_of_season, d.leap_year) == (1, "summer", 7, False)


def test_every_fourth_year_is_a_leap_year_of_29_days():
    assert [y for y in range(1, 13) if cal.is_leap_year(y)] == [4, 8, 12]
    assert [cal.year_length(y) for y in (1, 2, 3, 4, 5)] == [28, 28, 28, 29, 28]
    # Count every day for 12 years: each year has its length, years run on.
    lengths = {}
    for day in range(1, 1 + 3 * cal.CYCLE_DAYS):
        d = cal.date(clock(day))
        lengths[d.year] = max(lengths.get(d.year, 0), d.day_of_year)
    for year in range(2, 12):
        assert lengths[year] == cal.year_length(year)


def test_leap_day_falls_after_winter_and_before_spring_and_lasts_one_whole_day():
    leap = first_day(lambda d: d.leap_day)
    before, today, after = (cal.date(clock(leap + k, 0.0)) for k in (-1, 0, 1))
    assert (before.season, before.day_of_season, before.day_of_year) == ("winter", 7, 28)
    assert today.leap_day and today.day_of_year == 29 and today.year == 4
    assert today.season_name == "Leap Day"
    assert (after.year, after.day_of_year, after.season) == (5, 1, "spring")
    assert all(cal.date(clock(leap, h)).leap_day for h in (0.0, 6.0, 12.0, 23.99))
    # The next one is four years on.
    nxt = first_day(lambda d: d.leap_day, start=leap + 1)
    assert nxt - leap == cal.CYCLE_DAYS
    assert cal.date(clock(nxt)).year == 8


def test_dates_turn_over_at_the_clocks_midnight():
    key = (lambda d: (d.year, d.day_of_year, d.leap_day))
    for day in range(1, 1 + cal.CYCLE_DAYS):
        assert key(cal.date(clock(day, 0.0))) == key(cal.date(clock(day, 23.999)))
        assert key(cal.date(clock(day, 23.999))) != key(cal.date(clock(day + 1, 0.0)))


def test_year_fraction_runs_through_the_year_and_holds_on_leap_day():
    leap = first_day(lambda d: d.leap_day)
    assert cal.date(clock(leap + 1, 0.0)).year_fraction == 0.0
    assert 0.99 < cal.date(clock(leap, 12.0)).year_fraction < 1.0
    fractions = [cal.year_fraction(clock(d)) for d in range(leap + 1, leap + 29)]
    assert fractions == sorted(fractions)


def test_season_blend_eases_into_the_next_season():
    start = first_day(lambda d: d.season == "spring" and d.day_of_season == 1)
    assert cal.season_blend(clock(start, 12.0)) == ("spring", "summer", 0.0)
    late = cal.season_blend(clock(start + 6, 23.0))
    assert late[:2] == ("spring", "summer") and 0.5 < late[2] <= 1.0


# -- day and night ---------------------------------------------------------------
def test_day_length_follows_the_seasons():
    summer = cal.sun_times(cal.MIDSUMMER)
    winter = cal.sun_times(cal.MIDSUMMER + 0.5)
    spring = cal.sun_times(0.125)
    assert summer[1] - summer[0] == pytest.approx(cal.DAY_HOURS_MEAN + cal.DAY_HOURS_SWING)
    assert winter[1] - winter[0] == pytest.approx(cal.DAY_HOURS_MEAN - cal.DAY_HOURS_SWING)
    assert spring == pytest.approx((cal.EQUINOX_SUNRISE, cal.EQUINOX_SUNSET))
    for day in range(1, 1 + cal.CYCLE_DAYS):
        rise, set_ = cal.sunrise_sunset(clock(day))
        assert 0.0 < rise < cal.SOLAR_NOON < set_ < 24.0


def test_solar_hours_are_clock_hours_at_the_equinox_and_stretch_otherwise():
    rise, set_ = cal.EQUINOX_SUNRISE, cal.EQUINOX_SUNSET
    for hour in (0.0, 3.0, 6.3, 9.0, 12.0, 18.5, 21.0, 23.5):
        assert cal.solar_hour_at(hour, rise, set_) == pytest.approx(hour)
    rise, set_ = cal.sun_times(cal.MIDSUMMER)
    assert cal.solar_hour_at(rise, rise, set_) == pytest.approx(cal.EQUINOX_SUNRISE)
    assert cal.solar_hour_at(set_, rise, set_) == pytest.approx(cal.EQUINOX_SUNSET)
    # Monotonic through the day (wrapping once at midnight).
    hours = [cal.solar_hour_at(h / 10.0, rise, set_) for h in range(240)]
    drops = sum(1 for a, b in zip(hours, hours[1:]) if b < a)
    assert drops <= 1


@pytest.mark.qt
def test_is_daytime_dusk_and_night_all_follow_the_season():
    summer_day = first_day(lambda d: d.season == "summer" and d.day_of_season == 4)
    winter_day = first_day(lambda d: d.season == "winter" and d.day_of_season == 4)
    assert clock(summer_day, 20.5).is_daytime          # long summer evening
    assert not clock(winter_day, 19.0).is_daytime      # winter dark by seven
    assert clock(summer_day, 21.0).is_daytime          # summer still light at nine
    assert not clock(winter_day, 7.0).is_daytime       # and late to light
    assert clock(winter_day, 12.0).is_daytime
    from ..ui import daylight
    assert daylight.night_amount(daylight.solar_hour(clock(winter_day, 18.5))) > \
        daylight.night_amount(daylight.solar_hour(clock(summer_day, 18.5)))


def test_the_sun_peaks_at_solar_noon_higher_in_summer_and_sets_below_the_horizon():
    summer_day = first_day(lambda d: d.season == "summer" and d.day_of_season == 4)
    winter_day = first_day(lambda d: d.season == "winter" and d.day_of_season == 4)
    s_noon, az = cal.sun(clock(summer_day, cal.SOLAR_NOON))
    w_noon, _ = cal.sun(clock(winter_day, cal.SOLAR_NOON))
    assert az == pytest.approx(180.0, abs=1.0)
    assert s_noon > w_noon > 0.0
    assert cal.sun(clock(winter_day, 1.0))[0] < 0.0
    rise, _set = cal.sunrise_sunset(clock(summer_day))
    assert cal.sun(clock(summer_day, rise))[0] == pytest.approx(0.0, abs=1.0)


def test_the_moon_cycles_through_its_phases():
    names = {cal.moon_name(clock(1 + h // 24, h % 24)) for h in range(int(cal.LUNAR_DAYS * 24))}
    assert names == set(cal.MOON_PHASES)
    assert 0.0 <= cal.moon_phase(clock(50, 7.0)) < 1.0


# -- the clock, the HUD, the townsfolk -------------------------------------------
def test_leap_day_has_no_weekday_and_the_week_carries_on_around_it():
    leap = first_day(lambda d: d.leap_day)
    assert clock(leap).day_name == "Leap Day"
    assert clock(leap).clock_text.startswith("Leap Day, Day ")
    assert clock(leap - 1).day_name == WEEKDAYS[(leap - 2) % 7]
    assert clock(leap + 1).day_name == WEEKDAYS[leap % 7]


def test_announcements_mark_leap_day_its_eve_new_years_and_seasons():
    leap = first_day(lambda d: d.leap_day)
    eve = cal.announcements(clock(leap - 1, 0.0))
    assert any("Tomorrow is Leap Day" in text and toast for text, toast in eve)
    day = cal.announcements(clock(leap, 0.0))
    assert len(day) == 1 and day[0][1] and day[0][0].startswith("LEAP DAY!")
    new_year = cal.announcements(clock(leap + 1, 0.0))
    assert new_year[0] == ("A new year begins: Year 5.", True)
    assert ("Spring has come to the Vale.", False) in new_year
    leap_year_start = first_day(lambda d: d.leap_year and d.day_of_year == 1)
    assert "leap year" in cal.announcements(clock(leap_year_start, 0.0))[0][0]
    summer = first_day(lambda d: d.season == "summer" and d.day_of_season == 1)
    assert cal.announcements(clock(summer, 0.0)) == [("Summer has come to the Vale.", True)]
    assert cal.announcements(clock(summer + 1, 0.0)) == []


def test_festival_and_leap_day_small_talk():
    leap = first_day(lambda d: d.leap_day)
    assert cal.festival(clock(leap)) == cal.LEAP_FESTIVAL
    assert cal.festival(clock(leap + 1)) is None
    opener, reply = chatter.small_talk("Bram Cooper", "Mara Thatch", 14.0, festival="leap")
    assert "Leap" in opener + reply
    ordinary = chatter.small_talk("Bram Cooper", "Mara Thatch", 14.0)
    assert ordinary == chatter.small_talk("Bram Cooper", "Mara Thatch", 14.0, festival=None)


def test_describe_names_the_year_season_sun_and_moon():
    text = cal.describe(clock(1, 8.0))
    assert text.startswith("Year 1 · Summer, day 7 of 7 · Day 1 08:00")
    assert "sunrise" in text and "sunset" in text and "moon" in text
    leap = first_day(lambda d: d.leap_day)
    assert "Leap Day — the Leap Festival" in cal.describe(clock(leap))
    assert "(leap year)" in cal.describe(clock(leap - 3))
