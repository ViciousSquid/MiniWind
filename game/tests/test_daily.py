"""
Tests for off-screen daily resolution + the settlement event log
(:mod:`game.rpg.daily`).

Covers the pure day-resolver (baseline, once-per-day guard, merchant restock,
debt settlement, mourning fade, harvest, disposition decay, catch-up cap) and
the persistent day log, then the runtime hook that fires it on an in-game day
rollover.

Run:  python -m pytest game/tests/test_daily.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import daily
from game.rpg import disposition as disp
from game.rpg.dialogue import DictStore


# --- baseline & the once-per-day guard -------------------------------------
def test_first_call_only_sets_the_baseline():
    store = DictStore()
    events = daily.resolve_pending(store, 1, [{"merchant": True, "merchant_gold": 5}])
    assert events == []                                   # nothing "passed" yet
    assert store.get("world.last_resolved_day") == "1"


def test_no_new_day_is_a_noop():
    store = DictStore()
    daily.resolve_pending(store, 3, [])
    assert daily.resolve_pending(store, 3, []) == []
    assert daily.resolve_pending(store, 2, []) == []      # clock can't go back


# --- merchant restock ------------------------------------------------------
def test_merchant_coin_purse_refills_to_baseline():
    store = DictStore()
    merchant = {"name": "Elowen", "merchant": True, "merchant_gold": 300,
                "merchant_gold_base": 300}
    daily.resolve_pending(store, 1, [merchant])           # baseline
    merchant["merchant_gold"] = 20                        # spent down in trade
    events = daily.resolve_pending(store, 2, [merchant])
    assert merchant["merchant_gold"] == 300
    assert any("restock" in e.lower() for e in events)
    assert merchant.get("merchant_gold_base") == 300


# --- debts derived from relationships --------------------------------------
def test_debt_is_seeded_and_paid_down_then_cleared():
    store = DictStore()
    # Wick owes Thalen (his relationships name Thalen as a "creditor").
    wick = {"name": "Wick", "relationships": {"Thalen": "creditor"}}
    daily.resolve_pending(store, 1, [wick])               # baseline
    daily.resolve_pending(store, 2, [wick])               # seed(3) then pay 1 -> 2
    assert store.get("debt.Wick.Thalen") == "2"
    daily.resolve_pending(store, 3, [wick])               # -> 1
    events = daily.resolve_pending(store, 4, [wick])      # -> 0 (cleared)
    assert store.get("debt.Wick.Thalen") == "0"
    assert any("cleared" in e.lower() for e in events)


# --- mourning fades a couple of days after a death -------------------------
def test_active_mourning_quiets_after_two_days():
    store = DictStore()
    store.set("town.mourning", "1")
    store.set("town.last_death", "Elowen the Trader")
    store.set("town.last_death_day", 5)
    daily.resolve_pending(store, 5, [])                   # baseline at the death day
    daily.resolve_pending(store, 6, [])                   # one day later: still raw
    assert store.get("town.mourning") == "1"
    events = daily.resolve_pending(store, 7, [])          # two days later: quiets
    assert store.get("town.mourning") == "0"
    assert any("grief" in e.lower() for e in events)


# --- farmer harvest --------------------------------------------------------
def test_farmer_brings_in_a_daily_harvest():
    store = DictStore()
    bram = {"name": "Bram", "npc_role": "farmer"}
    daily.resolve_pending(store, 1, [bram])
    daily.resolve_pending(store, 2, [bram])
    assert int(store.get("stock.Bram", "0")) == 2


# --- disposition decay -----------------------------------------------------
def test_remembered_feelings_soften_by_one_each_day():
    store = DictStore()
    npc = {"id": "npc-1"}
    disp.remember(store, npc, "quest_helped")             # +15
    disp.remember(store, npc, "gift", amount=5)           # +20 total
    daily.resolve_pending(store, 1, [])                   # baseline (no decay)
    daily.resolve_pending(store, 2, [])                   # one day: 20 -> 19
    assert disp.delta(store, npc) == 19
    grudge = {"id": "npc-2"}
    disp.remember(store, grudge, "assaulted")             # -30
    daily.resolve_pending(store, 3, [])                   # -30 -> -29
    assert disp.delta(store, grudge) == -29


# --- multi-day catch-up is bounded -----------------------------------------
def test_catchup_resolves_each_missed_day_up_to_the_cap():
    store = DictStore()
    bram = {"name": "Bram", "npc_role": "farmer"}
    daily.resolve_pending(store, 1, [bram])               # baseline
    daily.resolve_pending(store, 4, [bram])               # days 2,3,4 resolved
    assert int(store.get("stock.Bram", "0")) == 6         # 3 harvests * 2
    assert store.get("world.last_resolved_day") == "4"


# --- the persistent day log ------------------------------------------------
def test_day_log_records_and_reads_back():
    store = DictStore()
    bram = {"name": "Bram", "npc_role": "farmer"}
    daily.resolve_pending(store, 1, [bram])
    daily.resolve_pending(store, 2, [bram])
    day2 = daily.log_for_day(store, 2)
    assert any("harvest" in line.lower() for line in day2)
    recent = daily.recent_log(store)
    assert recent and recent[-1]["day"] == 2
    assert isinstance(recent[-1]["text"], str)


# --- runtime hook: a day rollover fires the resolution ---------------------
class _FakeThing:
    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakePlayer:
    def __init__(self, pos):
        self.pos = list(pos)
        self.properties = {}


class _FakeLogic:
    def __init__(self, things, player):
        self.things = things
        self.player = player


class _FakeGlobals:
    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default="false", store=None):
        return self._d.get((store, str(key)), default)

    def set(self, key, value, store=None):
        self._d[(store, str(key))] = str(value)

    def all(self, store=None):
        return {k[1]: v for k, v in self._d.items() if k[0] == store}


def _settlement_session(hour, globals_store):
    import json
    from game import data
    from game.tools import make_settlement
    from game.runtime import MiniwindSession
    base_path = os.path.join(os.path.dirname(__file__), "..", "tools", "data",
                             "base_terrain.json")
    with open(os.path.abspath(base_path)) as f:
        base = json.load(f)
    world = make_settlement.build(data.load("settlement"), base)
    things = [_FakeThing(t["pos"], t["properties"]) for t in world["things"]]
    session = MiniwindSession(_FakeLogic(things, _FakePlayer([300, 272, -100])),
                              cfg={"start_hour": hour, "minutes_per_day": 999999.0},
                              globals_store=globals_store)
    session.clock.set_time(hour, 1)
    session.install()
    return session, things


def _find(things, name):
    return next((t for t in things if t.properties.get("name") == name), None)


def test_session_resolves_the_day_on_a_rollover():
    g = _FakeGlobals()
    session, things = _settlement_session(12.0, g)
    session.tick(0.1)                                     # establishes baseline (day 1)
    assert session.store.get("world.last_resolved_day") == "1"
    elowen = _find(things, "Elowen")
    elowen.properties["merchant_gold"] = 5               # she traded down
    # Advance the world clock to the next day and tick: the rollover resolves it.
    session.clock.set_time(8.0, 2)
    session.tick(0.1)
    assert session.store.get("world.last_resolved_day") == "2"
    assert int(elowen.properties["merchant_gold"]) > 5   # restocked overnight
    assert daily.log_for_day(session.store, 2)           # something was logged
