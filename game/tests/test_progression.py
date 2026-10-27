"""
Levelling, learning by doing, and archery by one set of rules.

Run:  python -m pytest game/tests/test_progression.py -q
"""

from __future__ import annotations

import random

from ..rpg.character import Character, LEVEL_POOL_GAIN
from ..rpg import magic
from .. import npc_archery as arch


def _mage():
    return Character.create("M", "breton", "mage")


def test_choosing_magicka_grows_magicka_by_ten():
    c = _mage()
    before = c.max_magicka
    c.xp = c.xp_needed
    res = c.level_up(pool="magicka")
    assert res["pool"] == "magicka"
    assert c.max_magicka >= before + LEVEL_POOL_GAIN   # attributes may add more
    assert c.magicka == c.max_magicka       # a level-up restores you


def test_a_pool_choice_survives_a_save():
    c = _mage()
    c.xp = c.xp_needed
    c.level_up(pool="stamina")
    again = Character.from_dict(c.to_dict())
    assert again.max_stamina == c.max_stamina


def test_casting_a_spell_more_makes_it_fizzle_less():
    c = _mage()
    spell = magic.get(c.known_spells[0])
    first = magic.cast_chance(c, spell)
    rng = random.Random(4)
    c.magicka = c.max_magicka = 10_000
    for _ in range(300):
        magic.try_cast(c, spell.id, rng=rng)
        c.magicka = c.max_magicka
    assert magic.cast_chance(c, spell) > first + 0.1


def test_skill_rises_are_announced_once():
    c = _mage()
    school = magic.get(c.known_spells[0]).school
    while not c.use_skill(school, 5.0):
        pass
    raised = c.pop_skill_raises()
    assert raised and raised[-1][0] == school
    assert c.pop_skill_raises() == []


def test_a_fuller_draw_flies_further_and_hits_harder():
    assert arch.range_for(1.0) > arch.range_for(0.2)
    assert arch.damage_for(20, 1.0) == 20
    assert arch.damage_for(20, 0.0) == 10


def test_an_archer_draws_at_least_far_enough_to_reach():
    far = 2400.0
    plan = arch.plan_draw(far, level=1, roll=0.99, extra=0.0)   # no power shot
    assert arch.range_for(plan) >= far


def test_a_power_draw_is_a_long_one():
    plan = arch.plan_draw(500.0, level=1, roll=0.0, extra=0.0)  # power shot
    assert plan >= 0.7


def test_an_archer_with_only_a_bow_shoots_it():
    props = {"attack_style": "bow", "inventory": []}
    assert arch.is_bow_shot(props, 800.0)
    assert not arch.is_bow_shot({"attack_style": "melee"}, 800.0)
