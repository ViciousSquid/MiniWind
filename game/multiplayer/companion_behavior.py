"""Small, serialisable human habits, independent of combat/loot dice and Qt."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Personality:
    courage: float
    focus: float
    thrift: float
    sociability: float
    reaction: float
    style: str


class CompanionMind:
    """Campaign identity supplies fresh habits; a saved counter continues choices.

    Personality draws use a separate stream from moment-to-moment decisions.
    Neither stream consumes the game's combat, character creation or loot RNG.
    The counter-based stream keeps saves small and portable through JSON.
    """

    VERSION = 1

    def __init__(self, campaign_id, player_id, saved=None):
        self.seed = hashlib.sha256(f"{campaign_id}:{player_id}".encode()).hexdigest()
        self.draws = 0
        if isinstance(saved, dict) and saved.get("version") == self.VERSION:
            seed, draws = saved.get("seed"), saved.get("draws")
            if (isinstance(seed, str) and len(seed) == 64
                    and all(c in "0123456789abcdef" for c in seed)
                    and type(draws) is int and 0 <= draws < 2**63):
                self.seed, self.draws = seed, draws
        rng = random.Random(self.seed)
        self.personality = Personality(
            courage=rng.uniform(0.15, 0.9),
            focus=rng.uniform(0.35, 0.95),
            thrift=rng.random(),
            sociability=rng.random(),
            reaction=rng.uniform(0.22, 0.55),
            style=rng.choice(("melee", "ranged", "magic")),
        )

    def to_dict(self):
        return {"version": self.VERSION, "seed": self.seed, "draws": self.draws}

    def uniform(self, low, high):
        digest = hashlib.sha256(f"{self.seed}:{self.draws}".encode()).digest()
        self.draws += 1
        value = (int.from_bytes(digest[:8], "big") >> 11) / 2**53
        return low + (high - low) * value

    def preference(self, identity):
        """Stable favourites, rather than rescoring identical gear at random."""
        digest = hashlib.sha256(f"{self.seed}:favourite:{identity}".encode()).digest()
        return 0.8 + int.from_bytes(digest[:2], "big") / 65535 * 0.4

    def reaction_delay(self):
        return self.personality.reaction * self.uniform(0.8, 1.3)

    def think_interval(self):
        return self.uniform(0.18, 0.3) + (1 - self.personality.focus) * 0.1

    @property
    def awareness(self):
        return 440 + 160 * self.personality.focus

    @property
    def heal_at(self):
        return 0.52 - 0.18 * self.personality.thrift

    @property
    def retreat_at(self):
        return 0.16 + 0.2 * (1 - self.personality.courage)

    @property
    def follow_radius(self):
        return 190 + 80 * (1 - self.personality.sociability)

    def lapse_chance(self, fatigue=0.0):
        return 0.025 + (1 - self.personality.focus) * 0.07 + fatigue * 0.07

    def aim_error(self, fatigue=0.0):
        degrees = 1.5 + (1 - self.personality.focus) * 5 + fatigue * 3
        return math.radians(self.uniform(-degrees, degrees))

    def inspector_rows(self):
        """Read-only descriptions of the very traits used by the decision code."""
        p = self.personality

        def trait(value, low, high):
            return f"{high if value >= 0.5 else low} ({value:.0%})"

        return [
            ("Courage", trait(p.courage, "Cautious", "Bold")),
            ("Concentration", trait(p.focus, "Easily distracted", "Attentive")),
            ("Thrift", trait(p.thrift, "Free with supplies", "Frugal")),
            ("Sociability", trait(p.sociability, "Independent", "Stays close")),
            ("Fighting preference", {"melee": "Blades and close combat",
                                      "ranged": "Bows and ranged weapons",
                                      "magic": "Staves and magic"}[p.style]),
            ("Typical reaction", f"{p.reaction:.2f} seconds"),
            ("Healing habit", f"Below {self.heal_at:.0%} health"),
            ("Falls back", f"Below {self.retreat_at:.0%} health or exhausted"),
            ("Following distance", f"About {self.follow_radius:.0f} units"),
        ]
