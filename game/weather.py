"""Saveable weather, independent of world size and of the combat RNG.

The simulation owns only a few numbers. Camera-local precipitation is drawn
from an immutable snapshot; there are no weather actors, cells or particles in
the persistent world.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import random


MODES = ("clear", "cloudy", "rain", "storm", "snow")
TRANSITION_SECONDS = 6.0
MIN_WEATHER_HOURS = 2.0
MAX_WEATHER_HOURS = 5.0
STORE_KEY = "weather.state"

# rain, snow, overcast, wind strength. Direction belongs to each weather front.
_PROFILES = {
    "clear": (0.0, 0.0, 0.0, 0.10),
    "cloudy": (0.0, 0.0, 0.45, 0.18),
    "rain": (0.65, 0.0, 0.62, 0.30),
    "storm": (1.0, 0.0, 0.90, 0.75),
    "snow": (0.0, 0.75, 0.52, 0.20),
}
_AUTO_MODES = ("clear", "clear", "clear", "cloudy", "cloudy",
               "rain", "rain", "storm", "snow")


@dataclass(frozen=True)
class WeatherSnapshot:
    kind: str = "clear"
    rain: float = 0.0
    snow: float = 0.0
    overcast: float = 0.0
    wind_x: float = 0.0
    wind_z: float = 0.0
    lightning: float = 0.0
    time: float = 0.0


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


def _channels(values, fallback):
    if not isinstance(values, (list, tuple)) or len(values) != 5:
        return tuple(fallback)
    return tuple(_clamp(_number(v, fallback[i]), -1.0 if i >= 3 else 0.0)
                 for i, v in enumerate(values))


class Weather:
    """A small automatic weather clock, with an optional manual override.

    ``absolute_hours`` is the game's day/hour clock. Automatic fronts last
    two to five game hours; visual transitions and animation use gameplay
    seconds, so pausing the simulation pauses the weather too. A large time
    jump selects one new front instead of replaying every missed hour.
    """

    def __init__(self, store):
        self.store = store
        self._rng = random.Random(0x57454154)
        self.mode = "clear"
        self.automatic = True
        self._intensity = 1.0
        self._time = 0.0
        self._last_hours = None
        self._next_change = None
        self._from = (0.0,) * 5
        self._target = self._from
        self._transition = TRANSITION_SECONDS
        self._next_lightning = 12.0
        self._flash_started = -1000.0
        self.snapshot = WeatherSnapshot()
        self.restore()

    def _current(self):
        phase = _clamp(self._transition / TRANSITION_SECONDS)
        blend = phase * phase * (3.0 - 2.0 * phase)
        return tuple(a + (b - a) * blend for a, b in zip(self._from, self._target))

    def _publish(self):
        rain, snow, overcast, wind_x, wind_z = self._current()
        lightning = (max(0.0, 1.0 - (self._time - self._flash_started) / 0.22)
                     if self.mode == "storm" else 0.0)
        self.snapshot = WeatherSnapshot(self.mode, rain, snow, overcast,
                                        wind_x, wind_z, _clamp(lightning), self._time)

    def _begin(self, kind, intensity):
        self._from = self._current()
        self.mode, self._intensity = kind, intensity
        rain, snow, overcast, wind = _PROFILES[kind]
        angle = self._rng.uniform(-math.pi, math.pi)
        self._target = (rain * intensity, snow * intensity, overcast * intensity,
                        math.cos(angle) * wind * intensity,
                        math.sin(angle) * wind * intensity)
        self._transition = 0.0
        self._next_lightning = self._time + self._rng.uniform(8.0, 18.0)
        self._flash_started = -1000.0
        self._publish()

    def set_weather(self, kind, intensity=1.0):
        """Override the cycle with a named front; intensity is clamped to 0..1."""
        kind = str(kind).strip().lower()
        if kind not in MODES:
            raise ValueError("Weather must be one of: " + ", ".join(MODES))
        try:
            intensity = float(intensity)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Weather intensity must be a finite number") from exc
        if not math.isfinite(intensity):
            raise ValueError("Weather intensity must be a finite number")
        self.automatic = False
        self._next_change = None
        self._begin(kind, _clamp(intensity))
        self.persist()

    def set_auto(self):
        """Resume natural fronts from the current weather."""
        self.automatic = True
        self._next_change = (None if self._last_hours is None else
                             self._last_hours + self._rng.uniform(
                                 MIN_WEATHER_HOURS, MAX_WEATHER_HOURS))
        self.persist()

    def tick(self, delta, absolute_hours):
        delta = max(0.0, _number(delta))
        hours = _number(absolute_hours, self._last_hours or 0.0)
        self._time += delta
        self._transition = min(TRANSITION_SECONDS, self._transition + delta)
        changed = False
        if self.automatic:
            if (self._next_change is None or
                    (self._last_hours is not None and hours < self._last_hours)):
                self._next_change = hours + self._rng.uniform(
                    MIN_WEATHER_HOURS, MAX_WEATHER_HOURS)
                changed = True
            elif hours >= self._next_change:
                choices = tuple(mode for mode in _AUTO_MODES if mode != self.mode)
                self._begin(self._rng.choice(choices), self._rng.uniform(0.65, 1.0))
                self._next_change = hours + self._rng.uniform(
                    MIN_WEATHER_HOURS, MAX_WEATHER_HOURS)
                changed = True
        self._last_hours = hours
        if (self.mode == "storm" and self._current()[0] > 0.25
                and self._time >= self._next_lightning):
            self._flash_started = self._time
            self._next_lightning = self._time + self._rng.uniform(8.0, 18.0)
        self._publish()
        if changed:
            self.persist()

    def persist(self):
        if self.store is None:
            return
        state = {
            "version": 1, "mode": self.mode, "automatic": self.automatic,
            "intensity": self._intensity, "time": self._time,
            "last_hours": self._last_hours, "next_change": self._next_change,
            "from": self._from, "target": self._target,
            "transition": self._transition, "next_lightning": self._next_lightning,
            "flash_started": self._flash_started, "rng": self._rng.getstate(),
        }
        self.store.set(STORE_KEY, json.dumps(state, separators=(",", ":")))

    def restore(self):
        """Restore a saved front and its transition without changing game time."""
        if self.store is None:
            return
        try:
            raw = self.store.get(STORE_KEY, None)
            state = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return
        if not isinstance(state, dict) or state.get("version") != 1:
            return
        mode = state.get("mode")
        if mode not in MODES:
            return
        self.mode = mode
        self.automatic = str(state.get("automatic", True)).lower() in ("true", "1", "on")
        self._intensity = _clamp(_number(state.get("intensity"), 1.0))
        self._time = max(0.0, _number(state.get("time")))
        self._last_hours = (None if state.get("last_hours") is None else
                            _number(state["last_hours"]))
        self._next_change = (None if state.get("next_change") is None else
                             _number(state["next_change"]))
        self._from = _channels(state.get("from"), self._from)
        self._target = _channels(state.get("target"), self._target)
        self._transition = _clamp(_number(state.get("transition"), TRANSITION_SECONDS),
                                  0.0, TRANSITION_SECONDS)
        self._next_lightning = _number(state.get("next_lightning"), self._time + 12.0)
        self._flash_started = _number(state.get("flash_started"), -1000.0)
        try:
            version, values, gaussian = state["rng"]
            self._rng.setstate((version, tuple(values), gaussian))
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        self._publish()
