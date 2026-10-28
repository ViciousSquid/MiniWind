"""Weather transitions, override and saving do not depend on resident actors."""

from dataclasses import FrozenInstanceError
import json
import random

import pytest

from game.weather import (MAX_WEATHER_HOURS, MIN_WEATHER_HOURS, STORE_KEY,
                          TRANSITION_SECONDS, Weather)


class _Store:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = str(value)
        self.writes += 1


def test_manual_weather_eases_in_and_clear_eases_it_out():
    weather = Weather(_Store())
    weather.set_weather("storm")
    assert weather.mode == "storm" and not weather.automatic
    assert weather.snapshot.rain == 0.0
    weather.tick(TRANSITION_SECONDS / 2, 8.0)
    assert weather.snapshot.rain == pytest.approx(0.5)
    assert weather.snapshot.overcast == pytest.approx(0.45)
    weather.tick(TRANSITION_SECONDS / 2, 8.1)
    assert weather.snapshot.rain == 1.0
    weather.set_weather("clear")
    assert weather.snapshot.rain == 1.0
    weather.tick(TRANSITION_SECONDS, 8.2)
    assert weather.snapshot.rain == 0.0
    assert weather.snapshot.overcast == 0.0


def test_snapshot_is_an_immutable_frame_and_no_tick_means_no_animation():
    weather = Weather(_Store())
    weather.set_weather("rain")
    first = weather.snapshot
    with pytest.raises(FrozenInstanceError):
        first.rain = 1.0
    weather.tick(2.0, 8.0)
    assert first.time == 0.0
    assert weather.snapshot is not first
    paused = weather.snapshot
    weather.tick(0.0, 8.0)
    assert weather.snapshot == paused


def test_automatic_fronts_follow_game_hours_and_large_skips_are_bounded():
    store = _Store()
    weather = Weather(store)
    weather.tick(0.0, 8.0)
    deadline = json.loads(store.values[STORE_KEY])["next_change"]
    assert MIN_WEATHER_HOURS <= deadline - 8.0 <= MAX_WEATHER_HOURS
    weather.tick(0.1, deadline - 0.01)
    assert weather.mode == "clear"
    assert store.writes == 1
    weather.tick(0.1, deadline)
    assert weather.mode != "clear"
    assert weather.snapshot.rain == 0.0  # a new front does not pop in fully formed
    writes = store.writes
    weather.tick(0.1, 1e9)
    assert store.writes == writes + 1
    deadline = json.loads(store.values[STORE_KEY])["next_change"]
    assert MIN_WEATHER_HOURS <= deadline - 1e9 <= MAX_WEATHER_HOURS


def test_manual_override_survives_time_skips_until_auto_is_resumed():
    weather = Weather(_Store())
    weather.tick(0.0, 8.0)
    weather.set_weather("snow", 0.5)
    weather.tick(TRANSITION_SECONDS, 1e4)
    assert weather.mode == "snow"
    assert weather.snapshot.snow == pytest.approx(0.375)
    weather.set_auto()
    assert weather.automatic
    weather.tick(1.0, 1e4 + MAX_WEATHER_HOURS)
    assert weather.mode != "snow"


def test_save_load_resumes_the_same_transition_and_future_lightning():
    store = _Store()
    original = Weather(store)
    original.set_weather("storm", 0.9)
    original.tick(3.0, 8.0)
    original.persist()
    restored = Weather(_Store(store.values))
    assert restored.snapshot == original.snapshot
    assert restored.mode == original.mode
    assert restored.automatic == original.automatic
    flashes = []
    for i in range(60):
        original.tick(0.5, 8.0 + i / 120)
        restored.tick(0.5, 8.0 + i / 120)
        assert restored.snapshot == original.snapshot
        flashes.append(original.snapshot.lightning)
    assert max(flashes) == 1.0
    assert flashes[-1] == 0.0


def test_saving_automatic_weather_preserves_its_next_front():
    store = _Store()
    original = Weather(store)
    original.tick(1.0, 8.0)
    original.persist()
    restored = Weather(_Store(store.values))
    for hours in (9.0, 11.0, 14.0, 18.0, 22.0):
        original.tick(1.0, hours)
        restored.tick(1.0, hours)
        assert restored.snapshot == original.snapshot
        assert restored.mode == original.mode


@pytest.mark.parametrize("raw", [None, "false", "broken", "[]", '{"version":99}'])
def test_absent_or_unreadable_saved_weather_starts_clear(raw):
    weather = Weather(_Store({STORE_KEY: raw}))
    assert weather.mode == "clear"
    assert weather.automatic
    assert weather.snapshot.rain == 0.0


@pytest.mark.parametrize("kind,intensity", [("sandstorm", 1), ("rain", "bad"),
                                            ("storm", float("nan"))])
def test_invalid_overrides_leave_the_existing_front_unchanged(kind, intensity):
    weather = Weather(_Store())
    before = weather.snapshot
    with pytest.raises(ValueError):
        weather.set_weather(kind, intensity)
    assert weather.snapshot == before
    assert weather.automatic


def test_intensity_and_lightning_are_bounded_and_clear_weather_does_not_flash():
    weather = Weather(None)
    weather.set_weather("storm", 9)
    for i in range(100):
        weather.tick(0.2, 8 + i / 300)
        frame = weather.snapshot
        assert all(0 <= value <= 1 for value in
                   (frame.rain, frame.snow, frame.overcast, frame.lightning))
        assert -1 <= frame.wind_x <= 1 and -1 <= frame.wind_z <= 1
    weather.set_weather("clear")
    weather.tick(100, 100)
    assert weather.snapshot.lightning == 0
    assert weather.snapshot.rain == 0


def test_weather_does_not_change_the_games_global_random_sequence():
    before = random.getstate()
    weather = Weather(_Store())
    weather.set_weather("storm")
    weather.tick(60.0, 8.0)
    weather.set_auto()
    weather.tick(60.0, 20.0)
    weather.persist()
    weather.restore()
    assert random.getstate() == before
