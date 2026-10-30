"""
Day and night: the clock runs a 24-minute day, and night is painted over
the world with the lamps and torches left burning through it.

Run:  python -m pytest game/tests/test_daylight.py -q
"""

from __future__ import annotations

import pytest

from .fio_logic import FioLogic


class _T:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = props


class _Logic(FioLogic):
    def __init__(self, things):
        self.things = list(things)
        self.player = _T((0.0, 0.0, 0.0))


def test_one_real_minute_is_one_game_hour():
    from ..rpg.gametime import DEFAULT_HOURS_PER_SECOND, GameClock
    from ..runtime import MiniwindSession
    assert DEFAULT_HOURS_PER_SECOND * 60.0 == pytest.approx(1.0)
    clock = MiniwindSession(_Logic([]), cfg={"start_hour": 8.0}).clock
    clock.advance(60.0)
    assert clock.hour == pytest.approx(9.0)
    for _ in range(23):
        clock.advance(60.0)
    assert clock.day == 2 and clock.hour == pytest.approx(8.0)


def test_every_shipped_map_keeps_the_24_minute_day():
    import glob
    import json
    for path in glob.glob("maps/*.json"):
        with open(path, "rb") as f:
            raw = f.read()
        if b'"minutes_per_day"' not in raw:
            continue
        assert b'"minutes_per_day": 24.0' in raw, path


def test_the_sky_runs_from_day_through_dusk_to_night_and_back():
    from ..ui import daylight
    noon = daylight.sky_at(12.0)[1]
    evening = daylight.sky_at(18.5)[1]
    dusk = daylight.sky_at(20.5)[1]
    midnight = daylight.sky_at(0.0)[1]
    dawn = daylight.sky_at(6.3)[1]
    assert noon == 0.0
    assert 0.0 < evening < dusk < midnight
    assert 0.0 < dawn < midnight
    assert daylight.sky_at(23.99)[1] == pytest.approx(midnight, abs=1e-6)
    # Smooth: no jumps anywhere in the day.
    prev = daylight.sky_at(0.0)[1]
    for i in range(1, 24 * 60):
        cur = daylight.sky_at(i / 60.0)[1]
        assert abs(cur - prev) < 0.02
        prev = cur
    # Warm at sunset, blue at midnight.
    r, g, b = daylight.sky_at(18.5)[0]
    assert r > b
    r, g, b = daylight.sky_at(1.0)[0]
    assert b > r


class _View:
    def __init__(self):
        import glm
        self.projection_matrix = glm.ortho(-640, 640, -400, 400, -5000, 5000)
        self.view_matrix = glm.lookAt(glm.vec3(0, 2000, 0.01), glm.vec3(0, 0, 0),
                                      glm.vec3(0, 0, -1))


def _session(things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s._player_pos = lambda: [9e6, 0.0, 9e6]            # off screen: no moonlight
    return s


def test_lamps_cut_holes_in_the_dark_but_fill_lights_do_not(qt_app):
    pytest.importorskip("glm")
    from ..ui import daylight
    lamp = _T((300.0, 300.0, 0.0), type="light", radius=420.0, intensity=1.0,
              colour=[255, 200, 130], state="on")
    off = _T((-300.0, 300.0, 0.0), type="light", radius=420.0, intensity=1.0, state="off")
    fill = _T((0.0, 800.0, 0.0), type="light", radius=4096.0, intensity=2.0, state="on")
    s = _session([lamp, off, fill])
    found = daylight.holes(s, _View(), 1280, 800)
    assert len(found) == 1
    x, y, r, strength, rgb = found[0]
    assert x == pytest.approx(640 + 300, abs=2) and y == pytest.approx(400, abs=2)
    assert r == pytest.approx(420 * daylight.LIT_FRACTION, rel=0.05)
    assert rgb == (255, 200, 130)


def test_shadow_only_lights_do_not_brighten_the_night_mask(qt_app):
    from ..ui import daylight
    shadow = _T((100.0, 300.0, 0.0), type="light", radius=420.0,
                intensity=12.0, state="on", terrain_shadow_only=True,
                casts_shadows=True)
    normal = _T((300.0, 300.0, 0.0), type="light", radius=420.0,
                intensity=1.0, state="on")
    session = _session([shadow, normal])
    assert len(daylight._local_lights(session)) == 1
    assert daylight._local_lights(session)[0][0] == normal.pos
    shadow.properties["terrain_shadow_only"] = "false"
    assert len(daylight._local_lights(session)) == 2


def test_night_is_dark_except_by_the_lamp(qt_app):
    pytest.importorskip("glm")
    from PyQt5.QtGui import QColor, QPainter, QPixmap
    from ..ui import daylight
    lamp = _T((300.0, 300.0, 0.0), type="light", radius=420.0, intensity=1.5,
              colour=[255, 200, 130], state="on")
    s = _session([lamp])

    def frame(hour):
        s.clock.set_time(hour)
        pm = QPixmap(1280, 800)
        pm.fill(QColor(200, 200, 200))
        p = QPainter(pm)
        daylight.draw(p, s, _View(), 1280, 800)
        p.end()
        img = pm.toImage()
        return QColor(img.pixel(100, 100)).lightness(), QColor(img.pixel(940, 400)).lightness()

    day_far, day_lamp = frame(12.0)
    night_far, night_lamp = frame(1.0)
    assert day_far == day_lamp == 200                  # daylight: nothing drawn
    assert night_far < 90                               # the night is dark...
    assert night_lamp > night_far + 60                  # ...but not by the lamp
