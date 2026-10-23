"""Deterministic, engine-free pin-and-tension lockpicking.

Aim, find the binding point, then follow it as the plug turns. Pins latch
individually. Only sustained forcing can break a pick; neither missed clicks
nor random rolls decide a successful set. Snap consequences belong to the host.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import random


@dataclass(frozen=True)
class Lock:
    pins: int
    tolerance: float
    drift: float
    seconds: float


LOCKS = {
    "novice": Lock(3, 14.0, 4.0, 0.85),
    "apprentice": Lock(3, 11.0, 8.0, 1.0),
    "adept": Lock(4, 8.0, 14.0, 1.2),
    "expert": Lock(4, 5.0, 22.0, 1.4),
    "master": Lock(5, 3.5, 30.0, 1.6),
}
ANGLE_LIMIT = 80.0
SHEAR_SKILL_LIMIT = 15


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def shear_chance(security):
    """Only an inexperienced character can leave a snapped tip in the lock."""
    return 0.25 * _clamp((SHEAR_SKILL_LIMIT - _number(security)) /
                         SHEAR_SKILL_LIMIT, 0.0, 1.0)


class LockpickAttempt:
    def __init__(self, difficulty="novice", security=5, seed="", saved=None):
        self.difficulty = difficulty if difficulty in LOCKS else "novice"
        self.lock = LOCKS[self.difficulty]
        self.security = _clamp(_number(security), 0.0, 100.0)
        identity = f"{seed}:{self.difficulty}"
        self.signature = hashlib.sha256(identity.encode()).hexdigest()
        rng = random.Random(self.signature)
        self.targets = tuple(rng.uniform(-44, 44) for _ in range(self.lock.pins))
        self.directions = tuple(rng.choice((-1, 1)) for _ in self.targets)
        self.pins_set = 0
        self.turn = 0.0
        self.angle = 0.0
        self.assisted = False
        if isinstance(saved, dict) and saved.get("signature") == self.signature:
            self.pins_set = int(_clamp(_number(saved.get("pins_set")), 0, self.lock.pins - 1))
            self.turn = _clamp(_number(saved.get("turn")), 0.0, 0.999)
            self.angle = _clamp(_number(saved.get("angle")), -ANGLE_LIMIT, ANGLE_LIMIT)
            self.assisted = saved.get("assisted") is True
        self.tension = False
        self.strain = 0.0
        self.binding_time = 0.0
        self.feedback_time = 0.0
        self.elapsed = 0.0
        self.last_event = None
        self.message = "Find the sweet spot, then apply tension."

    @property
    def complete(self):
        return self.pins_set >= self.lock.pins

    @property
    def tolerance(self):
        return (self.lock.tolerance + self.security * 0.08) * (1.6 if self.assisted else 1.0)

    @property
    def target(self):
        i = min(self.pins_set, self.lock.pins - 1)
        drift = self.lock.drift * (1.0 - self.security * 0.004)
        return self.targets[i] + self.directions[i] * drift * math.sin(self.turn * math.pi / 2)

    @property
    def distance(self):
        return abs(self.angle - self.target)

    @property
    def aligned(self):
        return self.distance <= self.tolerance

    @property
    def resistance(self):
        if not self.tension or self.complete:
            return 0.0
        return _clamp((self.distance / self.tolerance - 0.6) / 1.8, 0.0, 1.0)

    @property
    def cue(self):
        if self.strain >= 0.65:
            return "OVERLOAD — release tension!"
        if self.tension and not self.aligned:
            return "Binding — ease off and reposition"
        if self.aligned:
            return "Sweet spot — follow the turning plug"
        if self.distance < self.tolerance * 2.5:
            return "Getting closer"
        return "Search along the rim"

    def move(self, degrees, mouse=False):
        """Mouse motion meets spring resistance, but can always escape binding."""
        delta = _clamp(_number(degrees), -160.0, 160.0)
        if mouse:
            delta *= 1.0 - 0.72 * self.resistance
        self.angle = _clamp(self.angle + delta, -ANGLE_LIMIT, ANGLE_LIMIT)

    def set_tension(self, enabled):
        self.tension = bool(enabled) and not self.complete
        if not self.tension:
            self.binding_time = 0.0

    def snapshot(self):
        return {"signature": self.signature, "pins_set": self.pins_set,
                "turn": self.turn, "angle": self.angle, "assisted": self.assisted}

    def tick(self, delta):
        """Return ``pin_set``, ``unlocked``, ``pick_broke`` or None.

        Cap one tick at 100ms: a stalled frame never destroys a pick. Release
        tension to recover strain. Progress never rolls back when binding.
        """
        dt = _clamp(_number(delta), 0.0, 0.1)
        self.elapsed += dt
        self.feedback_time = max(0.0, self.feedback_time - dt)
        if self.complete:
            return None
        if not self.tension:
            self.strain = max(0.0, self.strain - dt * 0.7)
            return None
        if self.aligned:
            self.binding_time = 0.0
            self.strain = max(0.0, self.strain - dt * 0.35)
            self.turn = min(1.0, self.turn + dt / self.lock.seconds)
            if self.turn >= 1.0:
                self.pins_set += 1
                self.turn = 0.0
                self.set_tension(False)
                self.feedback_time = 0.35
                self.message = "Pin set. Release, reposition, then tension again."
                self.last_event = "unlocked" if self.complete else "pin_set"
                return self.last_event
        else:
            self.binding_time += dt
            if self.binding_time > 0.65:
                rate = (0.24 - self.security * 0.001) * (0.6 if self.assisted else 1.0)
                self.strain = min(1.0, self.strain + dt * rate)
            if self.strain >= 1.0:
                self.strain = 0.0
                self.set_tension(False)
                self.feedback_time = 0.8
                self.message = "Pick snapped. Set pins are still latched."
                self.last_event = "pick_broke"
                # Kick the pick away from the binding point, without warping
                # the OS pointer or introducing random control wobble.
                self.move(-12 if self.angle < self.target else 12)
                return "pick_broke"
        return None
