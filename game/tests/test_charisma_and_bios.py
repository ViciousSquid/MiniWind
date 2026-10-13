"""
Rolled STRENGTH / ENDURANCE / CHARISMA, the bios they write, and what a face
does to the world (prices, greetings, refusals, cowed brigands).

Run:  python -m pytest game/tests/test_charisma_and_bios.py -q
"""

from __future__ import annotations

import itertools
import random

from ..rpg import bios
from ..rpg import charisma as cha
from ..rpg.character import Character


def test_every_combination_of_rolls_has_a_bio():
    for s, e, c in itertools.product(range(3, 19), repeat=3):
        bio = bios.bio_for(s, e, c)
        assert bio["title"] and len(bio["text"]) > 60


def test_the_extremes_have_names_of_their_own():
    assert bios.bio_for(3, 4, 3)["title"] == "The Wretch"
    assert bios.bio_for(18, 17, 18)["title"] == "The Paragon"
    assert bios.bio_for(18, 16, 3)["title"] == "The Brute"
    assert bios.bio_for(4, 5, 17)["title"] == "The Frail Beauty"


def test_a_roll_moves_its_attribute_both_ways():
    assert cha.delta_for(18) > 0 > cha.delta_for(3)
    assert cha.delta_for(10) in (-2, 0, 2)
    c = Character.create("A", "imperial", "warrior")
    before = dict(c.attrs)
    cha.apply_rolls(c, {"strength": [6, 6, 6], "endurance": [1, 1, 1],
                        "personality": [3, 3, 4]})
    assert c.attrs["strength"] > before["strength"]
    assert c.attrs["endurance"] < before["endurance"]
    assert c.rolls == {"strength": 18, "endurance": 3, "personality": 10}
    again = Character.from_dict(c.to_dict())
    assert again.rolls == c.rolls


def test_the_ugly_pay_more_and_the_handsome_less():
    assert cha.price_multiplier(5, buying=True) > 1.0
    assert cha.price_multiplier(90, buying=True) < 1.0
    assert cha.price_multiplier(5, buying=False) < 1.0


def test_only_the_truly_repulsive_are_turned_away_and_not_by_friends():
    assert cha.merchant_refuses(5, disposition=40)
    assert not cha.merchant_refuses(5, disposition=80)
    assert not cha.merchant_refuses(25, disposition=10)


def test_brigands_are_only_cowed_by_a_dreadful_face():
    assert cha.repel_chance(40) == 0.0
    assert 0.0 < cha.repel_chance(10) < cha.repel_chance(0) <= 0.7


def test_strangers_remark_only_on_the_remarkable():
    assert cha.greeting_line(45, "Bob") == ""
    assert cha.greeting_line(5, "Bob")
    assert cha.greeting_line(5, "Bob") == cha.greeting_line(5, "Bob")


def test_an_npc_always_rolls_the_same_and_leans_by_trade():
    assert bios.npc_rolls("Thalen", "blacksmith") == bios.npc_rolls("Thalen", "blacksmith")
    smiths = [bios.npc_rolls(f"Smith{i}", "blacksmith")[0] for i in range(200)]
    beggars = [bios.npc_rolls(f"Beggar{i}", "beggar")[0] for i in range(200)]
    assert sum(smiths) / 200 > sum(beggars) / 200
    assert all(3 <= v <= 18 for v in smiths + beggars)


def test_every_person_gets_stats_and_their_body_follows_them():
    from ..runtime import MiniwindSession

    class _T:
        def __init__(self, props):
            self.properties = props
            self.pos = [0.0, 0.0, 0.0]

    people = [_T({"type": "npc", "name": f"N{i}", "npc_role": "villager",
                  "health": 60, "max_health": 60, "damage": 6}) for i in range(5)]
    sheep = _T({"type": "creature", "name": "Sheep", "npc_role": "sheep",
                "monster_type": "human", "health": 20})

    class _Logic:
        class editor_state:
            things = people + [sheep]

    s = MiniwindSession.__new__(MiniwindSession)
    s.logic = _Logic()
    s._assign_npc_stats()
    for t in people:
        p = t.properties
        assert all(3 <= int(p[k]) <= 18 for k in ("strength", "endurance", "charisma"))
        assert p["body_from_stats"]
    assert "strength" not in sheep.properties
    hp = [t.properties["max_health"] for t in people]
    s._assign_npc_stats()                     # a second pass changes nothing
    assert hp == [t.properties["max_health"] for t in people]


def test_carrying_too_much_slows_the_player_to_a_third():
    from ..runtime import MiniwindSession, ENCUMBERED_SPEED
    from ..rpg import items
    from ..rpg.game_state import GameState

    class _Store:
        def get(self, *_a, **_k):
            return "false"

        def set(self, *_a):
            pass

    class _Player:
        move_speed_scale = 1.0
        pos = [0.0, 0.0, 0.0]

    player = _Player()

    class _Logic:
        class player_runtime:
            pass
    _Logic.player_runtime.player = player

    from ..rpg.gametime import GameClock
    s = MiniwindSession.__new__(MiniwindSession)
    s.logic = _Logic()
    s.clock = GameClock()
    s.notifications = []
    s.game = GameState.new_game(_Store(), "Mule", "imperial", "warrior")
    s._update_encumbrance()
    assert player.move_speed_scale == 1.0
    for _ in range(40):
        s.game.character.inventory.append(items.make("plate_armour", 1))
    s._update_encumbrance()
    assert player.move_speed_scale == ENCUMBERED_SPEED
    assert s.notifications[-1]["text"] == "You are encumbered!"
