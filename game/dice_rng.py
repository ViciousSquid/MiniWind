"""
Where the dice get their randomness.

Every die the game rolls -- the player's and every NPC's and animal's: to
hit, damage, criticals, saves, casting, loot -- draws from the operating
system's cryptographic random source (``random.SystemRandom``: /dev/urandom,
or the Windows equivalent), which the OS keeps fed from hardware randomness
(the CPU's random-number instructions, interrupt timing). Nothing can predict
or replay a roll, and no seed is ever stored. Everything else that is merely
"random" (where a wolf wanders, which line an NPC says) keeps the game's
ordinary generator; only dice come from here.

For chasing a bug, a developer can make the dice repeat exactly: set
``dice_seed`` under ``[GAME]`` in settings.ini to any text. The same seed
then gives the same rolls in the same order, every time. Leave it empty (the
default) for truly random dice.
"""

from __future__ import annotations

import random

#: settings.ini key, under [GAME]: empty = truly random dice (the default).
SEED_KEY = "dice_seed"


def source(seed=None):
    """The random source for dice: the OS's cryptographic one, or -- given a
    developer *seed* -- a repeatable generator seeded from it."""
    text = "" if seed is None else str(seed).strip()
    if not text:
        return random.SystemRandom()
    return random.Random(f"miniwind-dice:{text}")


def is_true_random(rng) -> bool:
    """Whether *rng* is the OS's cryptographic source (not a seeded one)."""
    return isinstance(rng, random.SystemRandom)
