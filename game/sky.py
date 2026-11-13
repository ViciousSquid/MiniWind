"""
The sky -- the one a top-down game's water reflects.

The camera looks down, so the sky is only ever seen in water. The water's
shader draws it (engine/shaders.py ``skyColor``): a gradient with the sun,
dusk's colour, stars and the moon at night, and a layer of clouds far
above the world that the reflected rays look up into. This module says what
that sky is like this frame, from the game's hour, weather and wind.
"""

from __future__ import annotations

#: How much of the sky is cloud under clear skies, and with full gloom.
CLEAR_COVER = 0.32
#: How fast the wind carries the clouds (world units a second at full wind).
DRIFT_SPEED = 180.0


def dusk_amount(hour: float) -> float:
    """0 by day and night, rising to 1 in the hour around sunrise and
    sunset (game/ui/daylight.py's dawn at 6.3, dusk at 18.5)."""
    h = float(hour) % 24.0
    return max(0.0, 1.0 - abs(h - 6.2) / 1.0, 1.0 - abs(h - 18.8) / 1.3)


def state(session):
    """``((night, cover, gloom, dusk), (drift x, drift z))`` for the
    renderer's ``sky_state`` and ``sky_drift``."""
    import game.ui.daylight as daylight
    hour = float(getattr(getattr(session, "clock", None), "hour", 12.0))
    night = daylight.night_amount(hour)
    weather = getattr(session, "weather", None)
    on = weather is not None and getattr(session, "weather_enabled", lambda: False)()
    gloom = float(weather.gloom) if on else 0.0
    cover = min(1.0, CLEAR_COVER + gloom * 1.6)
    drift = getattr(session, "sky_drift", (0.0, 0.0))
    return (night, cover, gloom, dusk_amount(hour) * (1.0 - night * 0.5)), drift
