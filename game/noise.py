"""
How much noise the player is making, as a radius (world units): how far off
they can be heard.

Footsteps make a little -- more running, very little sneaking, none standing
still -- and everything the player does that the world hears (a blow, a
theft, a spell: its event's loudness, game/sim/events.py) makes as much as
that deed carries. The level jumps up to whatever is loudest at once, and
dies away when the noise stops, to nothing while the player stands still.

Shown, when asked for, as a light blue circle round the player (``showsound``
in the console, or ``[developer] show_sound`` in settings.ini;
game/ui/debug_overlays.py). Pure Python, no Qt.
"""

from __future__ import annotations

import math

#: Footsteps (radius at full pace): walking, running, sneaking.
WALK_NOISE = 160.0
SPRINT_NOISE = 340.0
SNEAK_NOISE = 50.0
#: The walking pace footsteps are measured against (world units a second).
WALK_SPEED = 200.0
#: How fast the noise dies away once its cause stops (units a second).
FADE_PER_SECOND = 320.0
#: The ground underfoot, as in the Dark Engine's footstep materials: grass
#: and earth muffle a step, a built floor (stone, boards) carries it.
SOFT_GROUND = 0.7
HARD_FLOOR = 1.4
#: Seconds between footsteps (walking, running).
STEP_SECONDS = 0.45
SPRINT_STEP_SECONDS = 0.3
#: A blow struck or taken, and a yell ("Get them!", "Help me!").
FIGHT_NOISE = 480.0
YELL_NOISE = 950.0
#: The ear every radius here is measured for: Fio's monster hearing range
#: (a monster hears a noise within its own hearing x radius / this).
STANDARD_EAR = 1024.0


def footstep_noise(speed: float, sneaking: bool = False, sprinting: bool = False) -> float:
    """The noise footsteps make at *speed*: none standing still."""
    if not math.isfinite(speed) or speed <= 1.0:
        return 0.0
    pace = min(1.5, float(speed) / WALK_SPEED)
    full = SNEAK_NOISE if sneaking else (SPRINT_NOISE if sprinting else WALK_NOISE)
    return full * min(1.0, pace)


class PlayerNoise:
    def __init__(self):
        self.level = 0.0

    def hear(self, loudness: float) -> None:
        """Something the player did that carries *loudness* far."""
        try:
            loud = float(loudness)
        except (TypeError, ValueError):
            return
        if math.isfinite(loud) and loud > self.level:
            self.level = loud

    def update(self, seconds: float, footsteps: float) -> float:
        """Advance by *seconds*; *footsteps* is the noise of moving now."""
        footsteps = max(0.0, float(footsteps))
        if footsteps >= self.level:
            self.level = footsteps
        else:
            self.level = max(footsteps, self.level - FADE_PER_SECOND * max(0.0, float(seconds)))
        return self.level
