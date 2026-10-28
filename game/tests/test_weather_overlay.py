"""Top-down weather costs depend on the viewport, never the world."""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("PyQt5")

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPainter

from game.ui import weather

pytestmark = pytest.mark.qt


def _snapshot(**changes):
    values = dict(kind="rain", rain=1., snow=0., overcast=0., wind_x=0.,
                  wind_z=0., lightning=0., time=2.5)
    values.update(changes)
    return SimpleNamespace(**values)


def _paint(snapshot, width=800, height=450):
    image = QImage(width, height, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    session = SimpleNamespace(weather=SimpleNamespace(snapshot=snapshot))
    weather.draw_weather(painter, session, width, height)
    painter.end()
    pointer = image.bits()
    pointer.setsize(image.byteCount())
    return np.frombuffer(pointer, np.uint8).reshape(height, width, 4).copy()


def test_clear_weather_leaves_the_scene_untouched():
    assert not _paint(_snapshot(rain=0.)).any()


def test_rain_moves_with_game_time_and_stays_frozen_between_repaints():
    first = _paint(_snapshot(time=1.))
    assert np.array_equal(first, _paint(_snapshot(time=1.)))
    assert not np.array_equal(first, _paint(_snapshot(time=1.1)))


def test_top_down_rain_is_stronger_at_the_edges_with_a_readable_centre():
    alpha = _paint(_snapshot())[..., 3].astype(float)
    centre = alpha[150:300, 267:533]
    border = np.ones(alpha.shape, dtype=bool)
    border[90:-90, 160:-160] = False
    assert centre.sum() > 0.                     # light rain still crosses it
    assert alpha[border].mean() > centre.mean() * 2.


def test_top_down_rain_falls_inward_towards_the_ground():
    streaks, _ = weather.rain_geometry(_snapshot(), 1280, 720)
    peripheral = [s for s in streaks
                  if abs(s.head_x - 640.) > 350. or abs(s.head_y - 360.) > 230.]
    assert peripheral
    assert all((s.head_x - s.tail_x) * (640. - s.tail_x)
               + (s.head_y - s.tail_y) * (360. - s.tail_y) > 0.
               for s in peripheral)


def test_particle_work_is_capped_even_for_a_large_viewport():
    for width, height in ((320, 180), (1920, 1080), (16384, 16384)):
        streaks, splashes = weather.rain_geometry(_snapshot(), width, height)
        assert 0 < len(streaks) <= weather.MAX_RAIN
        assert len(splashes) <= weather.MAX_SPLASHES


def test_weather_draw_never_asks_for_world_or_bigworld_entities():
    class LocalSession:
        weather = SimpleNamespace(snapshot=_snapshot())

        def __getattr__(self, name):
            raise AssertionError(f"weather queried the world through {name}")

    image = QImage(800, 450, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        weather.draw_weather(painter, LocalSession(), 800, 450)
    finally:
        painter.end()


def test_snow_clouds_and_lightning_all_have_visible_output():
    for values in (dict(rain=0., snow=1.), dict(rain=0., overcast=1.),
                   dict(rain=0., lightning=1.)):
        assert _paint(_snapshot(**values))[..., 3].sum() > 0


def test_small_rain_strength_changes_fade_drops_without_bright_pops():
    # Cross several points where a density-based integer particle count would
    # add a new drop. Existing drops should simply become slightly brighter.
    for count in (60., 70., 80., 90., 100.):
        before = _paint(_snapshot(rain=(count - .01) / 120.)).astype(int)
        after = _paint(_snapshot(rain=(count + .01) / 120.)).astype(int)
        assert np.abs(after[..., 3] - before[..., 3]).max() <= 4


def test_snow_never_restarts_its_fall_in_the_middle_of_the_view():
    class Capture:
        def __init__(self):
            self.points = []

        def setPen(self, _pen):
            pass

        def setBrush(self, _brush):
            pass

        def drawEllipse(self, centre, _rx, _ry):
            self.points.append((centre.x(), centre.y()))

    for start_time in (0., 10000.):
        previous = None
        for tick in range(200):
            painter = Capture()
            weather._draw_snow(painter, _snapshot(
                rain=0., snow=1., time=start_time + tick * .05,
                wind_x=tick / 400., wind_z=tick / 400.), 800, 450)
            if previous is not None:
                for old, new in zip(previous, painter.points):
                    if 10. < old[1] < 440. and 10. < new[1] < 440.:
                        assert abs(new[1] - old[1]) < 9.
                    if 10. < old[0] < 790. and 10. < new[0] < 790.:
                        assert abs(new[0] - old[0]) < 16.
            previous = painter.points


def test_drawing_weather_preserves_the_existing_viewport_clip_and_painter_state():
    image = QImage(400, 300, QImage.Format_RGBA8888)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setClipRect(100, 50, 200, 200)
    painter.setOpacity(.5)
    try:
        weather.draw_weather(painter, SimpleNamespace(
            weather=SimpleNamespace(snapshot=_snapshot(overcast=1.))), 400, 300)
        assert painter.opacity() == .5
        assert painter.clipBoundingRect().getRect() == (100., 50., 200., 200.)
    finally:
        painter.end()
    pointer = image.bits()
    pointer.setsize(image.byteCount())
    rgba = np.frombuffer(pointer, np.uint8).reshape(300, 400, 4)
    assert not rgba[:50].any()
    assert not rgba[:, :100].any()
    assert not rgba[:, 300:].any()
    assert not rgba[250:].any()
