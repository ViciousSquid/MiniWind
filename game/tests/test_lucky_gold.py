"""The lucky find more gold: however much lies in a purse on the ground, a
chest or a body, a player of high Luck takes 10% more (game/rpg/fortune.py)."""

from ..rpg import attributes as attr, fortune, inventory as inv, items
from .test_world_entities import _FakePlayer, _FakeThing, _session


def _lucky(c, luck):
    c.attrs[attr.LUCK] = luck
    return c


def test_ten_percent_more_for_the_lucky_rounded_up():
    c = _lucky(type("C", (), {"attrs": {}})(), fortune.LUCKY_GOLD_FROM)
    assert fortune.lucky_gold(c, 100) == 110
    assert fortune.lucky_gold(c, 25) == 28          # 2.5 rounds up to 3
    assert fortune.lucky_gold(c, 1) == 2            # never less than one more
    assert fortune.lucky_gold(c, 0) == 0
    c.attrs[attr.LUCK] = fortune.LUCKY_GOLD_FROM - 1
    assert fortune.lucky_gold(c, 100) == 100


def test_gold_on_the_ground_goes_to_the_purse_and_luck_adds_to_it():
    purse = _FakeThing([0, 0, 0], {"type": "itempickup", "item_id": "gold",
                                   "quantity": 50, "pickup_radius": 60.0})
    s = _session([purse], _FakePlayer([30, 0, 0]))
    c = _lucky(s.game.character, 70)
    before = c.gold
    s.tick(0.1)
    assert c.gold == before + 55
    assert not inv.has_item(c.inventory, "gold")     # coin is counted, not carried
    assert any("+5 by luck" in n["text"] for n in s.notifications)


def test_gold_from_a_chest_is_found_the_same_way():
    chest = _FakeThing([20, 0, 0], {"type": "container", "name": "Chest",
                                    "inventory": [items.make("gold", 40)]})
    s = _session([chest], _FakePlayer([0, 0, 0]))
    c = _lucky(s.game.character, 90)
    before = c.gold
    s.open_container(chest)
    assert s.take_from_container(0)
    assert c.gold == before + 44


def test_the_unlucky_find_what_is_there():
    chest = _FakeThing([20, 0, 0], {"type": "container", "name": "Chest",
                                    "inventory": [items.make("gold", 40)]})
    s = _session([chest], _FakePlayer([0, 0, 0]))
    c = _lucky(s.game.character, 40)
    before = c.gold
    s.open_container(chest)
    s.take_from_container(0)
    assert c.gold == before + 40


def test_the_fortune_page_says_so():
    from ..rpg.character import Character
    ch = Character.create("L", "imperial", "thief", "none")
    ch.attrs[attr.LUCK] = 75
    rows = {name: (value, good) for name, value, _why, good in fortune.benefits(ch)}
    assert rows["Gold found"] == ("+10%", True)
