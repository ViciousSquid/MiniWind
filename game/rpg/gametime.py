"""
World time for the Miniwind RPG plugin (§5).

Fio has no game-clock of its own — the engine ticks in real seconds
(``LogicThread`` passes a ``delta`` per tick). NPC schedules must run on *game*
time, not wall-clock time, so this module adds a tiny, deterministic clock that:

* advances game-hours from the per-tick ``delta`` (scaled),
* wraps at 24h and counts days,
* can be paused,
* serialises to/from a plain dict so it round-trips through Fio's existing
  save/load with no new format.

The clock is intentionally simple and *not* per-frame expensive: advancing it
is a couple of float adds. Schedule evaluation keys off :attr:`hour` and only
runs on the plugin's low-frequency decision tick (see ``schedule.py`` /
``runtime.py``), never every frame.

Pure Python — safe everywhere.
"""

from __future__ import annotations

from typing import Dict

#: Default: one full game-day every 20 real minutes → 24h / 1200s = 0.02 game-h
#: per real-second. Tunable per map via the MiniwindSettings entity.
DEFAULT_HOURS_PER_SECOND = 24.0 / (20.0 * 60.0)


class GameClock:
    """A deterministic, saveable game clock measured in hours and days."""

    def __init__(self, hour: float = 8.0, day: int = 1,
                 hours_per_second: float = DEFAULT_HOURS_PER_SECOND,
                 paused: bool = False):
        self.hour = float(hour) % 24.0
        self.day = int(day)
        self.hours_per_second = float(hours_per_second)
        self.paused = bool(paused)

    def advance(self, delta_seconds: float) -> None:
        """Advance the clock by *delta_seconds* of real time (no-op if paused)."""
        if self.paused or delta_seconds <= 0.0:
            return
        self.hour += delta_seconds * self.hours_per_second
        while self.hour >= 24.0:
            self.hour -= 24.0
            self.day += 1

    def set_time(self, hour: float, day: int = None) -> None:
        self.hour = float(hour) % 24.0
        if day is not None:
            self.day = int(day)

    @property
    def is_daytime(self) -> bool:
        return 6.0 <= self.hour < 20.0

    @property
    def clock_text(self) -> str:
        """A 'Day 3  14:30' style label for HUD display."""
        h = int(self.hour)
        m = int((self.hour - h) * 60.0)
        return f"Day {self.day}  {h:02d}:{m:02d}"

    # --- persistence: plain-dict round-trip (§12) -------------------------
    def to_dict(self) -> Dict:
        return {
            "hour": round(self.hour, 4),
            "day": self.day,
            "hours_per_second": self.hours_per_second,
            "paused": self.paused,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "GameClock":
        data = data or {}
        return cls(
            hour=data.get("hour", 8.0),
            day=data.get("day", 1),
            hours_per_second=data.get("hours_per_second", DEFAULT_HOURS_PER_SECOND),
            paused=data.get("paused", False),
        )
