"""Alchemy: a potion drunk restores x (1 + 0.003 x Alchemy), and every potion
drunk trains Alchemy. Food is only food.

Run:  python -m pytest game/tests/test_alchemy.py -q
"""

from __future__ import annotations

import pytest

from ..rpg import inventory as inv, items, skills as sk
from ..rpg.game_state import GameState, POTION_PRACTICE, alchemy_potency


class _Store:
    def get(self, *_a, **_k):
        return "false"

    def set(self, *_a):
        pass


def _game(alchemy):
    g = GameState.new_game(_Store(), "Brewer", "valian", "mage")
    g.character.skills[sk.ALCHEMY] = alchemy
    g.character.inventory = []
    return g


@pytest.mark.parametrize("alchemy, potency", [(0, 1.0), (50, 1.15), (100, 1.3)])
def test_a_potion_restores_more_for_one_who_knows_potions(alchemy, potency):
    g = _game(alchemy)
    c = g.character
    assert alchemy_potency(c) == pytest.approx(potency)
    c.max_health = c.health = 500.0
    c.health = 100.0
    inv.add_item(c.inventory, items.make("potion_heal_minor", 1))
    assert g.use_item("potion_heal_minor")
    assert c.health == pytest.approx(100.0 + 30 * potency)
    c.max_magicka, c.magicka = 500.0, 0.0
    inv.add_item(c.inventory, items.make("potion_magicka", 1))
    assert g.use_item("potion_magicka")
    assert c.magicka == pytest.approx(60 * potency)


def test_every_potion_drunk_trains_alchemy_and_food_does_not():
    g = _game(10)
    c = g.character
    practice = []
    real = c.use_skill
    c.use_skill = lambda sid, difficulty=1.0: (practice.append((sid, difficulty)),
                                               real(sid, difficulty))[1]
    c.health = c.max_health - 50
    inv.add_item(c.inventory, items.make("bread", 1))
    assert g.use_item("bread")
    assert c.health == pytest.approx(c.max_health - 42)   # bread's 8, as ever
    assert not [p for p in practice if p[0] == sk.ALCHEMY]
    inv.add_item(c.inventory, items.make("potion_stamina", 1))
    assert g.use_item("potion_stamina")
    assert (sk.ALCHEMY, POTION_PRACTICE) in practice
    for _ in range(40):
        inv.add_item(c.inventory, items.make("potion_cure", 1))
        g.use_item("potion_cure")
    assert c.skill(sk.ALCHEMY) > 10
