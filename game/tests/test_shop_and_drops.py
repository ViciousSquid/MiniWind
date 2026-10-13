"""
Healing potions: on the starting town's shelf, and on the bodies of enemies.

* Elowen the Trader, Millbrook's general merchant, sells healing potions in
  limited numbers: buying takes them off the shelf, a sold-out row cannot be
  bought, and the daily resolution puts the shelf back overnight. Stock rows
  without a quantity stay endless, as all stock used to be.
* Any slain enemy now and then carries a healing potion, taken by looting the
  body -- unless its own loot table already offers one.

Run:  python -m pytest game/tests/test_shop_and_drops.py -q
"""

from __future__ import annotations

import json
import os
import random

from ..rpg import daily, loot
from .test_corpse_loot import _Thing, _session

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class _Store:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = str(v)


def _merchant():
    return _Thing("Elowen", type="npc", npc_role="merchant", merchant=True,
                  merchant_gold=300, merchant_gold_base=300,
                  stock=[{"id": "potion_heal", "qty": 2, "restock": 2},
                         {"id": "potion_heal_minor", "qty": 3}, "torch"])


def _carried(s, item_id):
    return sum(int(st.get("qty", 1)) for st in s.game.character.inventory
               if st.get("id") == item_id)


# --- the shop ---------------------------------------------------------------
def test_the_starting_vendor_sells_healing_potions_that_restock():
    with open(os.path.join(ROOT, "maps", "village_walled_source.json"), encoding="utf-8") as fh:
        things = json.load(fh)["things"]
    elowen = next(t for t in things if t.get("properties", {}).get("name") == "Elowen")
    p = elowen["properties"]
    assert p.get("merchant")
    rows = {r["id"]: r for r in p["stock"] if isinstance(r, dict)}
    for potion in ("potion_heal", "potion_heal_minor"):
        assert rows[potion]["qty"] > 0 and rows[potion]["restock"] == rows[potion]["qty"]


def test_buying_takes_potions_off_the_shelf_until_it_is_sold_out():
    elowen = _merchant()
    s = _session(elowen)
    s.merchant_npc = elowen
    s.game.character.gold = 1000
    assert [s.buy("potion_heal") for _ in range(3)] == [True, True, False]
    assert _carried(s, "potion_heal") == 2
    assert s.stock_left(s.stock_entry(elowen, "potion_heal")) == 0
    # An endless row never runs out.
    assert all(s.buy("torch") for _ in range(5))
    assert s.stock_left(s.stock_entry(elowen, "torch")) is None


def test_the_shelf_is_full_again_the_next_day():
    elowen = _merchant()
    s = _session(elowen)
    s.merchant_npc = elowen
    s.game.character.gold = 1000
    s.buy("potion_heal")
    s.buy("potion_heal")
    s.buy("potion_heal_minor")             # first sale remembers the full shelf
    store = _Store()
    props = elowen.properties
    daily.resolve_pending(store, 1, [props])            # baseline
    events = daily.resolve_pending(store, 2, [props])   # a night passes
    shelf = {r["id"]: r["qty"] for r in props["stock"] if isinstance(r, dict)}
    assert shelf == {"potion_heal": 2, "potion_heal_minor": 3}
    assert any("Elowen restocked the shop" in e for e in events)
    assert props["merchant_gold"] == 300                # the purse untouched


# --- drops ----------------------------------------------------------------
def _kill(s, body, seeds=200):
    """How many of *seeds* kills of *body* leave a healing potion on it."""
    found = 0
    for seed in range(seeds):
        body.properties.pop("loot_rolled", None)
        body.properties["inventory"] = []
        s.game.rng = random.Random(seed)
        s.game.on_kill(body.properties)
        if any(st.get("id") in loot.HEALING_POTIONS for st in body.properties["inventory"]):
            found += 1
    return found


def test_a_slain_enemy_sometimes_carries_a_healing_potion():
    skeleton = _Thing("Skeleton", type="creature", npc_role="skeleton", loot="skeleton",
                      aggression="hostile", health=0)
    s = _session(skeleton)
    dropped = _kill(s, skeleton)
    assert 0 < dropped < 200                            # sometimes, not always
    assert abs(dropped / 200 - loot.ENEMY_POTION_CHANCE) < 0.08


def test_a_body_with_nothing_else_still_drops_one_and_a_friend_never_does():
    brute = _Thing("Brute", type="creature", npc_role="", aggression="hostile", health=0)
    s = _session(brute)
    assert _kill(s, brute) > 0                          # no table of its own at all
    villager = _Thing("Tam", type="npc", npc_role="villager", faction="villagers",
                      aggression="passive", health=0)
    s = _session(villager)
    assert _kill(s, villager) == 0


def test_a_table_that_already_offers_healing_is_left_to_its_own_odds():
    assert loot.offers_healing("bandit") and loot.offers_healing("wolf")
    assert not loot.offers_healing("skeleton") and not loot.offers_healing("")
