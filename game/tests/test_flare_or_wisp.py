"""Given Flare, a player is given Wisp instead 15% of the time."""

import random

from game.rpg import magic
from game.rpg.character import Character


class _Roll:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_flare_is_wisp_fifteen_percent_of_the_time():
    assert magic.FLARE_WISP_CHANCE == 0.15
    assert magic.awarded("flare", rng=_Roll(0.14)) == "wisp"
    assert magic.awarded("flare", rng=_Roll(0.15)) == "flare"
    rng = random.Random(4)
    wisps = sum(magic.awarded("flare", rng=rng) == "wisp" for _ in range(20000))
    assert 0.13 < wisps / 20000 < 0.17


def test_only_flare_is_ever_swapped_and_never_for_a_wisp_already_known():
    assert magic.awarded("firebolt", rng=_Roll(0.0)) == "firebolt"
    assert magic.awarded("flare", known=["wisp"], rng=_Roll(0.0)) == "flare"


def test_a_new_mage_may_start_with_wisp_instead_of_flare():
    lucky = Character.create("Ana", "imperial", "mage", rng=_Roll(0.0))
    assert "wisp" in lucky.known_spells and "flare" not in lucky.known_spells
    usual = Character.create("Ana", "imperial", "mage", rng=_Roll(0.9))
    assert "flare" in usual.known_spells and "wisp" not in usual.known_spells
