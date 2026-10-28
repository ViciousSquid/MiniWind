"""A liquid-damped compass needle, independent of the map's rotation."""

import math

# Critically damped: a turn settles in about 0.3 seconds, without oscillating.
RESPONSE = 16.0
# Reopening a hidden HUD should not animate an old heading.
RESET_GAP = 0.5


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class CompassNeedle:
    """Per-session presentation state; angles are radians, time is seconds."""

    def __init__(self):
        self.angle = 0.0
        self.velocity = 0.0
        self.last_time = None

    def update(self, target, now):
        if self.last_time is None or now - self.last_time >= RESET_GAP:
            self.angle = _wrap(target)
            self.velocity = 0.0
            self.last_time = now
            return self.angle
        dt = max(0.0, now - self.last_time)
        self.last_time = now
        # Exact damped-spring step, taking the short path through ±pi.
        error = _wrap(self.angle - target)
        drive = self.velocity + RESPONSE * error
        decay = math.exp(-RESPONSE * dt)
        self.angle = _wrap(target + (error + drive * dt) * decay)
        self.velocity = (self.velocity - RESPONSE * drive * dt) * decay
        return self.angle
