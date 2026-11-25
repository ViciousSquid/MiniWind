"""Slow Time: the world at half speed for 5 s (+1 s a level past 5), tinted icy blue."""
import pytest

from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _session():
    from ..runtime import MiniwindSession
    logic = _Logic([])
    logic.player = _Thing("You", (0.0, 0.0, 0.0), is_player=True)
    logic.time_scale = 1.0
    s = MiniwindSession(logic, cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    return s


def test_slow_time_lasts_five_seconds_and_a_second_a_level_past_five():
    from ..runtime import slow_time_seconds
    assert [slow_time_seconds(n) for n in (1, 5, 6, 10)] == [5.0, 5.0, 6.0, 10.0]


def test_it_is_a_spell_the_game_knows():
    import game.rpg.magic as magic
    spell = magic.get("slow_time")
    assert spell is not None and spell.delivery == magic.SELF
    assert [e["kind"] for e in spell.effects] == ["slow_time"]


def test_the_world_runs_at_half_speed_then_as_before(monkeypatch):
    import time
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    s = _session()
    s.logic.time_scale = 1.5                     # the debug tools' speed
    assert s.slow_time(7) == pytest.approx(7.0)
    assert s.logic.time_scale == pytest.approx(0.75)
    now[0] += 0.2
    assert 0.0 < s.slow_time_tint() < 1.0        # fading in
    now[0] += 3.0
    assert s.slow_time_tint() == pytest.approx(1.0)
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(0.75)
    now[0] += 4.0                                # 7.2 s since the cast
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(1.5) and s.slow_time_tint() == 0.0


def test_leaving_the_map_ends_it(monkeypatch):
    s = _session()
    s.slow_time(1)
    s.end_slow_time()
    assert s.logic.time_scale == 1.0 and s.slow_time_left() == 0.0


def test_the_screen_takes_an_icy_tint(qt_app):
    from PyQt5.QtGui import QImage, QPainter, QColor
    from ..ui import hud
    s = _session()
    s.slow_time(1)
    s._slow_time_from -= 1.0                     # past the fade-in
    img = QImage(64, 64, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    hud.draw_slow_time(p, s, 64, 64)
    p.end()
    c = img.pixelColor(10, 10)
    assert c.blue() > c.red() > 0


def test_casting_slow_time_plays_its_sound(monkeypatch):
    from .. import runtime
    s = _session()
    played = []
    monkeypatch.setattr(type(s), "play_ui_sound", lambda self, name, volume=1.0: played.append(name) or True)
    s.slow_time(1)
    assert played == [runtime.SLOW_TIME_SOUND] and runtime.SLOW_TIME_SOUND == "slowtime.wav"
