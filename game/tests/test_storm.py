"""Stormy weather (game/weather.py, game/wind.py, game/lightning.py): a gale
in gusts, grass thrashing in it, lightning by chance with thunder after, and
no one travelling -- all fading in and out with the storm."""

from __future__ import annotations

import math
import random

import pytest

from .. import lightning as lt
from .. import wind as wind_mod
from ..living import journeys, roads
from ..weather import NO_TRAVEL_TEXT, STORM, Weather
from ..wind import Wind


# -- the weather ---------------------------------------------------------------
def test_a_storm_eases_in_and_out_and_storms_from_the_moment_it_turns():
    w = Weather(random.Random(1), kind="clear")
    assert w.storm == 0.0 and not w.storming()
    assert w.set("stormy", hours=2.0)
    assert w.kind == STORM and w.storming()          # no one travels from now
    assert w.storm == 0.0                             # but the gale fades in
    w.update(1 / 60.0)                                # a real second
    assert 0.0 < w.storm < 0.1
    for _ in range(60):
        w.update(1 / 60.0)
    assert w.storm > 0.6
    w.set("rain")
    assert not w.storming() and w.storm > 0.6         # it eases off
    for _ in range(240):
        w.update(1 / 60.0)
    assert w.storm < 0.05


def test_storm_level_is_saved_and_old_saves_take_their_skys():
    w = Weather(random.Random(2))
    w.set("storm", at_once=True)
    assert w.storm == 1.0 and w.snapshot()["storm"] == 1.0
    back = Weather(random.Random(3))
    back.restore(w.snapshot())
    assert back.storm == 1.0 and back.storming()
    old = {"kind": "storm", "left": 1.0, "rain": 1.0, "gloom": 0.45, "wet": 0.5}
    back = Weather(random.Random(4))
    back.restore(old)
    assert back.storm == 1.0


# -- the wind ------------------------------------------------------------------
def _blow(w, seconds, storm, step=0.05, hours_per_second=1 / 60.0):
    forces = []
    for _ in range(int(seconds / step)):
        w.update(step * hours_per_second, step, storm)
        forces.append(w.force())
    return forces


def test_storm_wind_blows_far_harder_in_gusts():
    calm = _blow(Wind(random.Random(5)), 60.0, 0.0)
    gale = _blow(Wind(random.Random(5)), 60.0, 1.0)
    assert max(calm) <= 1.0
    assert min(gale[100:]) > max(calm) + 0.5            # much stronger throughout
    assert max(gale) <= 1.0 + wind_mod.STORM_FORCE + wind_mod.GUST_FORCE + 1e-9
    spread = max(gale[100:]) - min(gale[100:])
    assert spread > 0.3, "the gale comes in gusts"
    # The vector carries it: rain leans and fire runs harder in a gale.
    w = Wind(random.Random(6))
    _blow(w, 10.0, 1.0)
    assert math.hypot(*w.vector()) == pytest.approx(w.force())
    assert math.hypot(*w.vector()) > 1.0


def test_gusts_veer_the_wind_a_little_in_a_storm_only():
    w = Wind(random.Random(7))
    headings = []
    for _ in range(400):
        w.update(0.0, 0.05, 1.0)
        dx, dz = w.direction()
        headings.append(math.atan2(dz, dx))
    assert max(headings) - min(headings) > 0.05
    assert max(headings) - min(headings) <= 2 * wind_mod.GUST_VEER + 1e-6
    w.update(0.0, 0.05, 0.0)
    for _ in range(100):
        w.update(0.0, 0.05)
    assert abs(w.veer) < 1e-3 and abs(w.gust) < 1e-3   # the gale dies away


def test_calm_weather_draws_no_gust_numbers_and_the_old_call_still_works():
    a, b = Wind(random.Random(8)), Wind(random.Random(8))
    for _ in range(50):
        a.update(0.01)
        b.update(0.01, 0.6, 0.0)
    assert (a.angle, a.strength) == (b.angle, b.strength)
    assert a.force() == a.strength


def test_the_wind_is_the_same_for_the_same_seed():
    a, b = Wind(random.Random(9)), Wind(random.Random(9))
    assert _blow(a, 20.0, 1.0) == _blow(b, 20.0, 1.0)


def test_grass_sways_gently_in_a_breeze_and_violently_in_a_storm():
    assert wind_mod.grass_sway(None) is None             # the engine's default
    w = Wind(random.Random(10))
    w.strength = 0.55
    dx, dz, breeze = wind_mod.grass_sway(w)
    assert math.hypot(dx, dz) == pytest.approx(1.0)
    assert (dx, dz) == pytest.approx(w.direction())
    assert 0.5 < breeze < 0.85                           # about the engine's 0.65
    _blow(w, 10.0, 1.0)
    w.strength = 0.55
    _sx, _sz, storm = wind_mod.grass_sway(w)
    assert storm >= 1.0 > breeze + 0.15                  # into the shader's gale terms


# -- lightning -----------------------------------------------------------------
def _storm(rng_seed, seconds, storm=1.0, origin=(100.0, -50.0), dryness=0.0, step=0.05):
    sky = lt.Lightning(random.Random(rng_seed), ground=lambda x, z: 7.0)
    strikes = []
    for _ in range(int(seconds / step)):
        strikes += sky.update(step, storm, origin, dryness)
    return sky, strikes


def test_lightning_strikes_by_chance_in_a_storm_and_never_out_of_one():
    _sky, none = _storm(1, 600.0, storm=0.0)
    assert none == []
    _sky, strikes = _storm(1, 600.0)
    # About one every ten seconds: 60 expected in ten minutes.
    assert 35 <= len(strikes) <= 90
    _sky, faint = _storm(1, 600.0, storm=0.25)
    assert len(faint) < len(strikes)                     # it builds as the storm fades in
    seen = [s for s in strikes if s.distance <= lt.SEEN]
    assert 0.15 * len(strikes) <= len(seen) <= 0.5 * len(strikes)   # some in sight
    for s in strikes:
        assert lt.NEAR - 1e-6 <= s.distance <= lt.FAR + 1e-6
        assert math.hypot(s.x - 100.0, s.z + 50.0) == pytest.approx(s.distance)
        assert s.y == 7.0


def test_lightning_is_the_same_for_the_same_seed():
    _a, one = _storm(4, 300.0)
    _b, two = _storm(4, 300.0)
    assert one == two and one
    _c, other = _storm(5, 300.0)
    assert one != other


def test_thunder_follows_after_a_delay_by_distance_once():
    sky = lt.Lightning(random.Random(0))
    near = lt.Strike(0.0, 0.0, 0.0, 300.0, 300.0, 300.0 / lt.THUNDER_SPEED, 11, False)
    far = lt.Strike(0.0, 0.0, 0.0, 6000.0, 6000.0, 6000.0 / lt.THUNDER_SPEED, 12, False)
    sky.strikes = (near, far)
    assert sky.thunder_due() == []                       # not yet: sound is slow
    sky.update(0.25, 0.0)
    heard = sky.thunder_due()
    assert [s for s, _v in heard] == [near]
    sky.update(0.25, 0.0)
    assert sky.thunder_due() == []                       # each heard once
    for _ in range(4):
        sky.update(1.0, 0.0)
    (got, quiet), = sky.thunder_due()
    assert got == far and quiet < heard[0][1]             # the far one mutters


def test_a_strike_flashes_and_one_in_view_shows_a_bolt_briefly():
    sky = lt.Lightning(random.Random(0))
    sky.clock = 10.0
    near = lt.Strike(10.0, 0, 0, 0, 500.0, 11.0, 1, False)
    far = lt.Strike(10.0, 0, 0, 0, 8000.0, 15.0, 2, False)
    sky.strikes = (far,)
    assert sky.bolts() == [] and 0.0 < sky.flash() < 0.6
    sky.strikes = (near, far)
    assert [s for s, _age in sky.bolts()] == [near] and sky.flash() > 0.9
    assert sky.flash(10.1) == 0.0                        # the dark beat
    assert sky.flash(10.2) > 0.0                         # the second flicker
    assert sky.bolts(10.0 + lt.BOLT_SECONDS) == [] and sky.flash(10.5) == 0.0


def test_old_strikes_are_forgotten():
    sky, strikes = _storm(2, 120.0)
    assert strikes
    for _ in range(int(lt.KEEP_SECONDS) + 2):
        sky.update(1.0, 0.0)
    assert sky.strikes == ()


def test_only_a_near_strike_on_dry_ground_sets_the_grass_alight():
    def strikes(dryness):
        sky = lt.Lightning(random.Random(3))
        return [sky._strike((0.0, 0.0), dryness) for _ in range(6000)]
    assert not any(s.ignites for s in strikes(0.0))       # soaked ground never
    dry = strikes(1.0)
    lit = [s for s in dry if s.ignites]
    near = [s for s in dry if s.distance < lt.IGNITE_RANGE]
    assert lit and all(s.distance < lt.IGNITE_RANGE for s in lit)
    assert len(lit) < len(near)                           # a chance, not a rule
    damp = [s for s in strikes(0.3) if s.ignites]
    assert len(damp) < len(lit)


# -- no travel ----------------------------------------------------------------
class _Hooks(journeys.WorldHooks):
    def __init__(self):
        self.storm = False

    def storming(self):
        return self.storm


def _board(hooks, seed=17):
    places = {"a": dict(x=0, z=0, kind="town"), "b": dict(x=2000, z=0, kind="town"),
              "c": dict(x=-2000, z=0, kind="town"), "e": dict(x=0, z=-2000, kind="hamlet")}
    net = roads.RoadNetwork.build([], [(k, p["x"], p["z"]) for k, p in places.items()])
    return journeys.JourneyBoard(net, places, 1, rng=random.Random(seed), hooks=hooks)


def test_no_one_sets_out_on_the_roads_in_a_storm():
    hooks = _Hooks()
    hooks.storm = True
    board = _board(hooks)
    for hour in range(8, 14):
        board.update(float(hour))
    assert board.journeys == {}
    hooks.storm = False
    board.update(14.0)
    assert board.journeys, "they set out once it passes"


def test_a_party_resting_waits_out_the_storm():
    hooks = _Hooks()
    board = _board(hooks)
    board.update(8.0)
    resting = next(iter(board.journeys.values()))
    resting.state, resting.rest_until = "rest", 9.0
    hooks.storm = True
    board.update(10.0)
    assert resting.state == "rest"
    hooks.storm = False
    board.update(10.5)
    assert resting.state != "rest" or resting.rest_until > 10.5


# -- what the renderer and the overlay are handed ------------------------------
class _Renderer:
    pass


def _host_with(session):
    from types import SimpleNamespace
    from ..host import MiniwindGame
    game = MiniwindGame()
    game._host = SimpleNamespace(logic=SimpleNamespace(_miniwind=session))
    return game


@pytest.mark.qt
def test_the_host_hands_the_renderer_the_wind_for_the_grass():
    from types import SimpleNamespace
    w = Wind(random.Random(11))
    weather = Weather(random.Random(12))
    session = SimpleNamespace(wind=w, weather=weather, weather_enabled=lambda: True,
                              clock=SimpleNamespace(hour=12.0), sky_drift=(0.0, 0.0))
    game = _host_with(session)
    renderer = _Renderer()
    game._on_pre_scene({"play_mode": True, "renderer": renderer})
    dx, dz, breeze = renderer.grass_wind
    assert (dx, dz) == pytest.approx(w.direction()) and breeze < 0.85
    _blow(w, 10.0, 1.0)
    game._on_pre_scene({"play_mode": True, "renderer": renderer})
    assert renderer.grass_wind[2] >= 1.0                  # it thrashes in the storm
    # Out of Play the editor's grass is back in the default breeze.
    game._on_pre_scene({"play_mode": False, "renderer": renderer})
    assert renderer.grass_wind is None


@pytest.mark.qt
def test_a_bolt_is_drawn_where_the_strike_lands_under_the_flash():
    from PyQt5.QtGui import QColor, QImage, QPainter
    from ..ui import rain
    weather = Weather(random.Random(13))
    weather.set("storm", at_once=True)
    sky = lt.Lightning(random.Random(0))
    sky.clock = 5.0 + 0.1                                  # the dark beat: no wash
    sky.strikes = (lt.Strike(5.0, 10.0, 0.0, 20.0, 600.0, 6.0, 77, False),)
    image = QImage(320, 200, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0))
    painter = QPainter(image)
    rain.draw(painter, weather, (0.0, 0.0), 320, 200, 0.0, lightning=sky,
              to_screen=lambda x, y, z: (160.0, 170.0))
    painter.end()
    trunk, branches = rain.bolt_path(77, (160.0, 170.0), 320, 200)
    assert trunk[-1] == (160.0, 170.0) and trunk[0][1] < 100 and branches
    assert rain.bolt_path(77, (160.0, 170.0), 320, 200) == (trunk, branches)
    mid = trunk[len(trunk) // 2]
    lit = QColor(image.pixel(int(mid[0]), int(mid[1])))
    assert lit.lightness() > 120, "the bolt's core"
    corner = QColor(image.pixel(5, 5))
    assert corner.lightness() < 60
    # Once its moment has passed, nothing of it is drawn.
    sky.clock = 7.0
    image.fill(QColor(0, 0, 0))
    painter = QPainter(image)
    rain.draw(painter, weather, (0.0, 0.0), 320, 200, 0.0, lightning=sky,
              to_screen=lambda x, y, z: (160.0, 170.0))
    painter.end()
    assert QColor(image.pixel(int(mid[0]), int(mid[1]))).lightness() < 60


# -- the howl ------------------------------------------------------------------
def test_the_wind_loop_howls_through_a_storm_and_follows_its_gusts():
    howl = wind_mod.StormHowl()
    assert howl.update(0.1, 0.0, 0.0) == []                     # calm: silence
    start = howl.update(0.1, 0.2, 0.0)
    assert len(start) == 1 and start[0]["looping"] and start[0]["keep_playing"]
    assert start[0]["file"] == wind_mod.HOWL_SOUND == "Ambient_Wind01.wav"
    assert start[0]["global"] and start[0]["entity_id"] == wind_mod.HOWL_ID
    assert howl.update(0.1, 1.0, 1.0) == []                     # not every tick
    refresh = howl.update(wind_mod.HOWL_EVERY, 1.0, 1.0)
    assert refresh[0]["action"] == "play" and refresh[0]["volume"] > start[0]["volume"]
    assert howl.volume(1.0, 0.0) < howl.volume(1.0, 1.0) <= wind_mod.HOWL_LOUD
    assert howl.update(0.1, 0.04, 0.0) == []                    # between stop and start
    stop = howl.update(0.1, 0.01, 0.0)
    assert stop == [{"action": "stop", "file": wind_mod.HOWL_SOUND,
                     "entity_id": wind_mod.HOWL_ID}]
    assert howl.update(0.1, 0.0, 0.0) == []


def test_the_howl_ships_with_the_game():
    from ..runtime import sound_available
    assert sound_available(wind_mod.HOWL_SOUND)
