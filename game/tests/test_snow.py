"""Snow: only in the cold, blizzards for storms, settling and thawing, what it
does to fire and lightning, the console, saves, the flakes and the terrain."""

import random
from types import SimpleNamespace

import pytest

from .. import calendar as cal
from .. import weather as wx
from ..rpg.gametime import GameClock
from ..weather import Weather


def first_day(predicate):
    for day in range(1, 400):
        if predicate(cal.date(GameClock(hour=0.0, day=day))):
            return day
    raise AssertionError("never happened")


def run(w, hours, cold, step=0.25):
    for _ in range(int(hours / step)):
        w.update(step, cold=cold)


# -- the cold -----------------------------------------------------------------------
def test_it_is_cold_only_from_late_autumn_through_winter():
    autumn = first_day(lambda d: d.season == "autumn" and d.day_of_season == 1)
    winter = first_day(lambda d: d.season == "winter" and d.day_of_season == 1)
    spring = first_day(lambda d: d.season == "spring" and d.day_of_season == 1)
    assert cal.coldness(GameClock(hour=12, day=autumn)) == 0.0
    assert cal.coldness(GameClock(hour=12, day=winter + 3)) == 1.0
    assert cal.coldness(GameClock(hour=12, day=spring + 2)) == 0.0
    # It comes in over the end of autumn and goes over the end of the year.
    assert 0.0 < cal.coldness(GameClock(hour=12, day=winter - 1)) < 1.0
    assert 0.0 < cal.coldness(GameClock(hour=6, day=spring - 1)) < 1.0
    # Leap Day falls in the thaw.
    leap = first_day(lambda d: d.leap_day)
    assert 0.0 < cal.coldness(GameClock(hour=0, day=leap)) < 1.0


def test_coldness_never_jumps_through_a_year():
    last = None
    for step in range(cal.CYCLE_DAYS * 48):
        now = cal.coldness(GameClock(hour=(step % 48) / 2.0, day=1 + step // 48))
        if last is not None:
            assert abs(now - last) < 0.25
        last = now


# -- the sky ------------------------------------------------------------------------
def test_snow_falls_in_the_cold_and_never_of_itself_in_the_warm():
    kinds_warm, kinds_cold = set(), set()
    for seed in range(40):
        warm, cold = Weather(random.Random(seed)), Weather(random.Random(seed))
        run(warm, 200, 0.0, step=1.0)
        run(cold, 200, 1.0, step=1.0)
        kinds_warm.add(warm.kind)
        kinds_cold.add(cold.kind)
        assert warm.snow == 0.0
    assert wx.SNOW not in kinds_warm
    assert wx.SNOW in kinds_cold and wx.RAIN not in kinds_cold


def test_every_kind_has_its_tables():
    for table in (wx.RAIN_OF, wx.SPELL_HOURS, wx.GLOOM_OF, wx.STORM_OF, wx.NEXT, wx.NEXT_COLD):
        assert set(table) == set(wx.KINDS)
    for table in (wx.NEXT, wx.NEXT_COLD):
        for options in table.values():
            assert all(kind in wx.KINDS for kind, _w in options)


def test_snow_settles_while_it_falls_and_thaws_after():
    w = Weather(random.Random(1))
    w.set("snow", hours=6, at_once=True)
    w.cold = 1.0
    assert w.snowing() and not w.raining()
    run(w, 2.0, 1.0)
    assert w.snow > 0.5
    deep = w.snow
    w.set("clear", hours=48)
    run(w, 24.0, 1.0)
    assert 0.0 < w.snow < deep                     # lies through the cold
    lying = w.snow
    run(w, 0.5, 0.0)
    assert w.wet > 0.0                             # its meltwater wets the ground
    run(w, 1.5, 0.0)
    assert w.snow < lying * 0.2                    # gone soon once it is warm


def test_rain_washes_snow_away_faster():
    a, b = Weather(random.Random(2)), Weather(random.Random(2))
    for w in (a, b):
        w.snow = 1.0
    a.set("clear", hours=10, at_once=True)
    b.set("rain", hours=10, at_once=True)
    run(a, 1.0, 0.0)
    run(b, 1.0, 0.0)
    assert b.snow < a.snow


def test_a_storm_in_the_cold_is_a_blizzard():
    w = Weather(random.Random(3))
    w.cold = 1.0
    w.set("storm", hours=2, at_once=True)
    assert w.blizzard() and w.storming()            # no one travels in it either
    assert w.rain == 0.0 and w.snowfall == wx.BLIZZARD_SNOWFALL
    assert w.lightning() == pytest.approx(w.storm * wx.BLIZZARD_LIGHTNING)
    warm = Weather(random.Random(3))
    warm.set("storm", hours=2, at_once=True)
    assert not warm.blizzard() and warm.rain == 1.0 and warm.lightning() == warm.storm


def test_snow_lying_barely_burns_and_falling_snow_fights_fire():
    w = Weather(random.Random(4))
    dry = w.dryness()
    w.snow = 1.0
    assert w.dryness() < 0.1 < dry
    w.snow = 0.0
    w.set("snow", at_once=True)
    assert w.douse() == pytest.approx(0.5 * wx.SNOWFALL_OF[wx.SNOW])


def test_snow_is_saved_and_old_saves_have_none():
    w = Weather(random.Random(5))
    w.set("snow", at_once=True)
    w.snow, w.cold = 0.7, 1.0
    back = Weather(random.Random(6))
    back.restore(w.snapshot())
    assert (back.kind, back.snow, back.cold) == ("snow", 0.7, 1.0)
    assert back.snowfall == pytest.approx(w.snowfall, abs=1e-3)
    old = Weather(random.Random(7))
    old.snow = 0.4
    old.restore({"kind": "rain", "left": 2.0, "rain": 0.5, "gloom": 0.3, "wet": 0.2})
    assert old.snow == 0.0 and old.snowfall == 0.0


def test_the_console_makes_it_snow():
    from .. import console
    session = SimpleNamespace(weather=Weather(random.Random(8), kind="clear"))
    logic = SimpleNamespace(_miniwind=session)
    lines = []
    original = console.debug_log
    console.debug_log = lambda category, message: lines.append(message)
    try:
        console.cmd_weather(console.ConsoleContext(logic_thread=logic, play_mode=True), "snowy 3")
        assert session.weather.kind == "snow" and session.weather.left == 3.0
        console.cmd_weather(console.ConsoleContext(logic_thread=logic, play_mode=True), "")
        assert "snow" in lines[-1] and "snow lying" in lines[-1]
    finally:
        console.debug_log = original


# -- the look -----------------------------------------------------------------------
def test_flakes_fall_in_three_bands_and_the_wind_carries_them():
    from ..ui import rain
    calm = rain.flake_bands(1.0, (0.0, 0.0), 1280, 720, 10.0)
    # Some start out of view near the camera (they fall in toward the middle).
    assert all(calm) and sum(map(len, calm)) > rain.FLAKES * 0.4
    assert rain.flake_bands(1.0, (0.0, 0.0), 1280, 720, 10.0) == calm   # stable, no state
    windy = rain.flake_bands(1.0, (1.0, 0.0), 1280, 720, 10.0)
    assert windy != calm
    assert rain.flake_bands(0.0, (0.0, 0.0), 1280, 720, 10.0) == ([], [], [])


@pytest.mark.qt
def test_snow_is_drawn_white_over_the_scene():
    from PyQt5.QtGui import QColor, QImage, QPainter
    from ..ui import rain
    w = Weather(random.Random(9))
    w.set("snow", at_once=True)
    image = QImage(640, 400, QImage.Format_ARGB32)
    image.fill(QColor(20, 60, 30))
    painter = QPainter(image)
    rain.draw(painter, w, (0.0, 0.0), 640, 400, 4.0)
    painter.end()
    light = sum(QColor(image.pixel(x, y)).lightness() > 170
                for x in range(640) for y in range(400))
    assert light > 100


@pytest.mark.qt
def test_the_host_hands_the_renderer_the_snow_on_the_ground():
    from .test_storm import _Renderer, _host_with
    from ..wind import Wind
    weather = Weather(random.Random(10))
    weather.snow = 0.65
    on = {"weather": True}
    session = SimpleNamespace(wind=Wind(random.Random(11)), weather=weather,
                              weather_enabled=lambda: on["weather"],
                              clock=SimpleNamespace(hour=12.0), sky_drift=(0.0, 0.0))
    game = _host_with(session)
    renderer = _Renderer()
    game._on_pre_scene({"play_mode": True, "renderer": renderer})
    assert renderer.snow_cover == pytest.approx(0.65)
    on["weather"] = False
    game._on_pre_scene({"play_mode": True, "renderer": renderer})
    assert renderer.snow_cover == 0.0
    on["weather"] = True
    game._on_pre_scene({"play_mode": False, "renderer": renderer})
    assert renderer.snow_cover == 0.0
