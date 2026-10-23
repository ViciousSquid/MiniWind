"""Mouse-lifted tumblers. Catch each pin during its pause at the top.

Pure rules: inventory, drawing and rewards belong to the session and UI.
"""


def difficulty(value=25):
    try:
        return max(1, min(100, int(value)))
    except (TypeError, ValueError):
        return 25


def label(value):
    value = difficulty(value)
    return ("Simple" if value <= 20 else "Common" if value <= 40 else
            "Sturdy" if value <= 60 else "Intricate" if value <= 80 else "Masterwork")


class Tumbler:
    def __init__(self, spring):
        self.spring = spring
        self.height = 0.0
        self.phase = "rest"
        self.timer = 0.0
        self.latched = False
        self.strokes = 0
        self.rise = 0.2
        self.hold = 0.2


class Lockpick:
    BREAK_DURATION = 0.85
    BREAK_STYLES = ("tip", "shaft", "buckle", "shatter")

    def __init__(self, level, security, rng, last_break_style=None):
        self.difficulty = difficulty(level)
        self.security = max(0, min(100, int(security)))
        self.rng = rng
        self.pins = [Tumbler(rng.uniform(0.8, 1.2))
                     for _ in range((self.difficulty + 19) // 20)]
        self.selected = 0
        self.pick_height = 0.1
        self.opened = False
        self.break_elapsed = None
        self.break_index = 0
        self.break_height = 0.1
        self.break_pin_height = None
        self.break_style = None
        self.break_motion = None
        self._last_break_style = last_break_style
        self.message = "Lift a tumbler and feel for the pause at the top."

    def select(self, index, height=None):
        if self.breaking:
            return
        self.selected = max(0, min(len(self.pins) - 1, int(index)))
        if height is not None:
            self.pick_height = max(0.0, min(1.0, float(height)))

    @property
    def can_set(self):
        return self.pins[self.selected].phase == "hold"

    @property
    def broken(self):
        return self.break_elapsed is not None

    @property
    def breaking(self):
        return self.broken and self.break_elapsed < self.BREAK_DURATION

    def lift(self):
        pin = self.pins[self.selected]
        if self.opened or self.breaking or pin.latched or pin.phase in ("rise", "hold"):
            return False
        self.break_elapsed = None
        pin.strokes += 1
        slow = (pin.strokes + self.selected) % 3 == 0
        pin.rise = (0.24 if slow else 0.14) * pin.spring
        pin.hold = max(0.07, (0.23 - self.difficulty * 0.0013) *
                       (1.6 if slow else 0.8) * pin.spring + self.security * 0.002)
        pin.phase, pin.timer, pin.height = "rise", 0.0, 0.0
        self.message = "Feel for the pause at the top."
        return True

    def update(self, seconds):
        """Return the number of top contacts, each heard as a single click."""
        seconds = max(0.0, float(seconds))
        if self.broken:
            self.break_elapsed = min(self.BREAK_DURATION, self.break_elapsed + seconds)
        contacts = 0
        for pin in self.pins:
            remaining = seconds
            while remaining > 1e-8 and pin.phase in ("rise", "hold", "fall"):
                duration = {"rise": pin.rise, "hold": pin.hold,
                            "fall": 0.18 * pin.spring}[pin.phase]
                step = min(remaining, max(0.0, duration - pin.timer))
                remaining -= step
                pin.timer += step
                fraction = min(1.0, pin.timer / duration)
                pin.height = (fraction * (2.0 - fraction) if pin.phase == "rise"
                              else 1.0 if pin.phase == "hold" else 1.0 - fraction ** 2)
                if pin.timer >= duration - 1e-8:
                    pin.timer = 0.0
                    if pin.phase == "rise":
                        pin.phase = "hold"
                        contacts += 1
                        if pin is self.pins[self.selected]:
                            self.message = "There! Click to set the tumbler."
                    elif pin.phase == "hold":
                        pin.phase = "fall"
                        if pin is self.pins[self.selected]:
                            self.message = "It slipped. Lift it again."
                    else:
                        pin.phase, pin.height = "rest", 0.0
        return contacts

    def set_pin(self):
        pin = self.pins[self.selected]
        if self.opened or self.broken or pin.latched:
            return None
        if self.can_set:
            pin.latched, pin.phase, pin.height = True, "set", 1.0
            if all(p.latched for p in self.pins):
                self.opened = True
                return "opened"
            self.message = "Tumbler set. Move the pick to the next one."
            return "set"
        self.break_pin_height = pin.height if pin.phase in ("rise", "hold") else None
        # Security protects already-set tumblers when a pick snaps.
        settled = [p for p in self.pins if p.latched]
        lose = (len(settled) if self.security < 25 else 2 if self.security < 50
                else 1 if self.security < 75 else 0)
        for prior in settled[-lose:] if lose else ():
            prior.latched = False
        for prior in self.pins:
            if not prior.latched:
                prior.phase, prior.height, prior.timer = "rest", 0.0, 0.0
        self.break_elapsed = 0.0
        self.break_index, self.break_height = self.selected, self.pick_height
        self._fracture()
        self.message = "Lockpick broken. Lift a tumbler with a new pick."
        return "broken"

    def _fracture(self):
        """Sample once, never during painting; consecutive breaks differ."""
        self.break_style = self.rng.choice([style for style in self.BREAK_STYLES
                                           if style != self._last_break_style])
        self._last_break_style = self.break_style
        split, spin, drift, fall = {
            "tip": ((0.78, 0.88), (35, 75), (16, 38), (45, 68)),
            "shaft": ((0.48, 0.62), (-130, -75), (-38, -12), (60, 85)),
            "buckle": ((0.62, 0.75), (-70, -35), (20, 40), (50, 80)),
            "shatter": ((0.42, 0.56), (70, 130), (-20, 20), (55, 75)),
        }[self.break_style]
        self.break_motion = {
            "split": self.rng.uniform(*split), "spin": self.rng.uniform(*spin),
            "drift": self.rng.uniform(*drift), "fall": self.rng.uniform(*fall),
            "recoil": self.rng.uniform(7, 14), "second_split": self.rng.uniform(0.78, 0.87),
        }
