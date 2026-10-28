"""The top-left status frame (:mod:`game.ui.hud_frame`)."""

import math

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtGui  # noqa: E402

from game.ui import hud_frame, worldmap  # noqa: E402

pytestmark = pytest.mark.qt


class _Character:
    name = "Aldric"
    health, max_health = 50, 100
    magicka, max_magicka = 10, 40
    stamina, max_stamina = 80, 100
    level, gold, can_level_up = 3, 120, False
    race_id = "nord"
    class_id = "warrior"

    def can_use_magic(self):
        return True


class _Player:
    pos = [0.0, 0.0, 0.0]
    angle = 0.0


class _Session:
    logic = type("L", (), {"player_runtime": type("R", (), {"player": _Player()})()})()

    def _live_actors(self):
        return []

    def quest_arrow_targets(self):
        return []


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080), (800, 600)])
def test_the_minimap_fills_the_ring(size):
    """One geometry: the minimap's square is the inside of the frame's ring."""
    f = hud_frame.layout(*size)
    x, y, side = worldmap.minimap_rect(*size)
    assert (x + side / 2.0, y + side / 2.0) == pytest.approx((f.cx, f.cy))
    assert side / 2.0 == pytest.approx(f.r)
    assert x >= 0 and y >= 0, "the frame runs off the top left of the view"


def test_bars_come_out_from_behind_the_ring_in_order():
    f = hud_frame.layout(1280, 720)
    names = [name for name, _rect in f.bars]
    assert names == ["health", "stamina", "magicka"]
    for _name, rect in f.bars:
        assert rect.left() < f.cx + f.R, "a bar does not start behind the ring"
        assert rect.right() > f.cx + f.R
    tops = [rect.top() for _name, rect in f.bars]
    assert tops == sorted(tops)


def test_one_who_works_no_magic_has_no_magicka_bar():
    """Health and stamina always lead; a Warrior simply has no third bar."""
    mage = hud_frame.layout(1280, 720, magical=True)
    warrior = hud_frame.layout(1280, 720, magical=False)
    assert [n for n, _r in warrior.bars] == ["health", "stamina"]
    assert dict(warrior.bars)["stamina"] == dict(mage.bars)["stamina"]
    assert warrior.text_y < mage.text_y

    class _Warrior(_Character):
        max_magicka = magicka = 0

        def can_use_magic(self):
            return False

    assert not hud_frame._magical(_Warrior())
    assert hud_frame._magical(_Character())


def test_the_frame_paints_and_keeps_its_static_layers(qt_app):
    hud_frame._CACHE.clear()
    image = QtGui.QImage(1280, 720, QtGui.QImage.Format_ARGB32_Premultiplied)
    for _ in range(3):
        image.fill(0)
        painter = QtGui.QPainter(image)
        try:
            hud_frame.draw(painter, _Session(), _Character(), 1280, 720)
        finally:
            painter.end()
    assert len(hud_frame._CACHE) == 1, "the static layers were rebuilt per frame"
    f = hud_frame.layout(1280, 720)
    # The ring is opaque bronze; nothing was drawn at the far right.
    ring = QtGui.QColor.fromRgba(image.pixel(int(f.cx - (f.R + f.r) / 2.0), int(f.cy)))
    well = QtGui.QColor.fromRgba(image.pixel(int(f.cx), int(f.cy)))
    assert ring.alpha() == 255 and well.alpha() == 255
    assert QtGui.QColor.fromRgba(image.pixel(1270, 700)).alpha() == 0


def test_only_the_north_badge_lags_and_each_session_has_its_own_compass(qt_app, monkeypatch):
    now, maps, badges = [0.0], [], []
    monkeypatch.setattr(hud_frame.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(worldmap, "minimap_rotation", lambda s: s.rotation)
    monkeypatch.setattr(worldmap, "draw_minimap", lambda p, s, *args: maps.append(s.rotation))
    monkeypatch.setattr(hud_frame, "_paint_north", lambda p, f, angle: badges.append(angle))
    session = _Session()
    session.rotation = 0.0
    image = QtGui.QImage(1280, 720, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QtGui.QPainter(image)
    try:
        hud_frame.draw(painter, session, _Character(), 1280, 720)
        session.rotation, now[0] = math.pi / 2, .05
        hud_frame.draw(painter, session, _Character(), 1280, 720)
        assert maps[-1] == math.pi / 2
        lagged = badges[-1]
        assert 0 < lagged < math.pi / 2

        fresh = _Session()
        fresh.rotation = -math.pi / 2
        hud_frame.draw(painter, fresh, _Character(), 1280, 720)
        assert badges[-1] == pytest.approx(fresh.rotation)
        hud_frame.draw(painter, session, _Character(), 1280, 720)
        assert badges[-1] == pytest.approx(lagged)

        for _ in range(20):
            now[0] += .02
            hud_frame.draw(painter, session, _Character(), 1280, 720)
        assert maps[-1] == math.pi / 2
        assert abs(badges[-1] - session.rotation) < math.radians(1)
    finally:
        painter.end()
