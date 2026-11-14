"""The wind the terrain's grass sways in (``grass.vert``), without GL.

A game says what the wind is doing by setting ``renderer.grass_wind`` to
``(dir x, dir z, strength)`` before the scene (as it sets ``sky_state``);
anything else -- no game, a bad value -- is the default fair breeze. The
strength is the shader's ``windStrength``: 0.65 sways a field gently, and
past about 1 the shader's gale terms lay it over and thrash it.

The gust field the blades sample rolls downwind. Its offset is accumulated
here, frame by frame (:func:`advance_scroll`), rather than computed as
direction x time in the shader: a heading that drifts by a hair would
otherwise move the field by that hair times the whole clock and set every
blade jumping.
"""

from __future__ import annotations

import math

#: The default heading (normalised in the shader) and strength.
DEFAULT_DIR = (1.0, 0.35)
DEFAULT_STRENGTH = 0.65
#: How fast the field rolls at the default strength (noise units a second),
#: and the most a frame may roll it (a stall must not lurch the field).
SCROLL_SPEED = 0.6
MAX_STEP_SECONDS = 0.1
#: The shader samples the field at the offset and at 2.7 times it; the noise
#: repeats every 289 units, so wrapping at 2890 keeps both seamless.
SCROLL_WRAP = 2890.0
#: The strongest wind the shader is handed.
MAX_STRENGTH = 3.0


def resolve(value):
    """``((dir x, dir z), strength)`` from a ``grass_wind`` value: the unit
    heading and a strength in 0..MAX_STRENGTH, or the default breeze."""
    try:
        dx, dz, strength = (float(v) for v in value)
    except (TypeError, ValueError):
        return _default()
    length = math.hypot(dx, dz)
    if not (math.isfinite(length) and math.isfinite(strength)) or length < 1e-6:
        return _default()
    return (dx / length, dz / length), max(0.0, min(MAX_STRENGTH, strength))


def _default():
    length = math.hypot(*DEFAULT_DIR)
    return (DEFAULT_DIR[0] / length, DEFAULT_DIR[1] / length), DEFAULT_STRENGTH


def advance_scroll(scroll, direction, strength, seconds):
    """The field's offset after *seconds* more of wind blowing *direction*
    at *strength*: rolling faster the harder it blows."""
    seconds = max(0.0, min(MAX_STEP_SECONDS, float(seconds)))
    step = SCROLL_SPEED * (strength / DEFAULT_STRENGTH) * seconds
    return ((scroll[0] + direction[0] * step) % SCROLL_WRAP,
            (scroll[1] + direction[1] * step) % SCROLL_WRAP)
