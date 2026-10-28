"""Weather follows the real session clock, save lifecycle and console queue."""

from types import SimpleNamespace

import pytest

from plugins.api import GlobalStore
from game import console
from game.runtime import MiniwindSession
from game.ui import hits
from game.weather import STORE_KEY, TRANSITION_SECONDS
from .test_cast_controls import _Logic


@pytest.fixture
def session(monkeypatch):
    store = GlobalStore()
    monkeypatch.setitem(store._registry(), "weather-integration", {})
    active = MiniwindSession(_Logic(), cfg={"state_store": "weather-integration"},
                             globals_store=store)
    active.needs_char_creation = False
    active.open_screen = None
    active.logic._miniwind = active
    hits.clear()
    yield active
    hits.clear()


def test_weather_animates_on_game_ticks_and_freezes_with_paused_ui(session):
    session.weather.set_weather("rain")
    session.tick(TRANSITION_SECONDS)
    frame = session.weather.snapshot
    assert frame.rain > 0.
    assert frame.time == TRANSITION_SECONDS
    session.tick_ui(2.)
    assert session.weather.snapshot == frame


def test_session_saves_and_restores_the_current_weather_transition(session):
    session.weather.set_weather("snow", .8)
    session.tick(2.)
    frame = session.weather.snapshot
    session.persist(force=True)
    session.tick(2.)
    assert session.weather.snapshot != frame
    session.restore()
    assert session.weather.snapshot == frame
    assert not session.weather.automatic


def test_older_saves_without_weather_start_with_automatic_clear_skies(session):
    session.weather.set_weather("storm")
    session.store._g.delete(STORE_KEY, store="weather-integration")
    session.restore()
    assert session.weather.mode == "clear"
    assert session.weather.automatic


def test_weather_console_changes_are_applied_by_the_game_queue(session):
    ctx = console.ConsoleContext(logic_thread=session.logic, play_mode=True)
    console.cmd_weather(ctx, "rain 0.8")
    assert session.weather.mode == "clear"
    hits.run_clicks(session)
    session.tick(TRANSITION_SECONDS)
    assert session.weather.mode == "rain"
    assert session.weather.snapshot.rain == pytest.approx(.65 * .8)
    console.cmd_weather(ctx, "auto")
    hits.run_clicks(session)
    assert session.weather.automatic


@pytest.mark.parametrize("command", ["tornado", "rain nan", "rain -1", "rain 2", "auto 1", "rain 1 extra"])
def test_invalid_weather_commands_leave_the_world_unchanged(session, command):
    console.cmd_weather(console.ConsoleContext(logic_thread=session.logic, play_mode=True), command)
    hits.run_clicks(session)
    assert session.weather.mode == "clear" and session.weather.automatic


@pytest.mark.parametrize("cfg, origin", [({}, "make_caves"), ({"weather_enabled": False}, "")])
def test_interior_maps_suppress_outdoor_weather(cfg, origin):
    logic = _Logic()
    logic.editor_state = SimpleNamespace(things=[], brushes=[], created_at=origin)
    assert not MiniwindSession(logic, cfg=cfg).weather_enabled
