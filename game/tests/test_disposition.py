"""
Tests for per-NPC memory of the player (:mod:`game.rpg.disposition`).

Covers the pure memory model (recording, once-guards, clamping, tiers, the
guilds+memory composition, price factor) and its live wiring through the runtime
session: an assault and a kin-murder are remembered and survive save/load, an
honest quest turn-in warms a giver, and authored dialogue reacts to the
conversation-scoped ``talk.*`` keys.

Run:  python -m pytest game/tests/test_disposition.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import disposition as disp
from game.rpg import guilds
from game.rpg.character import Character
from game.rpg.dialogue import DictStore


# --- pure memory model -----------------------------------------------------
def test_remember_accumulates_and_flags():
    store = DictStore()
    npc = {"id": "npc-1", "name": "Bram"}
    assert disp.delta(store, npc) == 0
    disp.remember(store, npc, "assaulted")
    assert disp.delta(store, npc) == -30
    assert disp.has_flag(store, npc, "wronged")
    assert not disp.has_flag(store, npc, "befriended")
    disp.remember(store, npc, "quest_helped")
    assert disp.delta(store, npc) == -15
    assert disp.has_flag(store, npc, "befriended")


def test_once_events_apply_a_single_time():
    store = DictStore()
    npc = {"id": "npc-1"}
    disp.remember(store, npc, "greeted")
    disp.remember(store, npc, "greeted")
    disp.remember(store, npc, "greeted")
    assert disp.delta(store, npc) == 2   # greeted is a once-event (+2)


def test_repeatable_events_stack_but_delta_is_clamped():
    store = DictStore()
    npc = {"id": "npc-1"}
    for _ in range(200):
        disp.remember(store, npc, "traded")   # +1 each, repeatable
    assert disp.delta(store, npc) == disp.DELTA_MAX


def test_gift_amount_overrides_catalogue_weight():
    store = DictStore()
    npc = {"id": "g"}
    disp.remember(store, npc, "gift", amount=12)
    assert disp.delta(store, npc) == 12
    assert disp.has_flag(store, npc, "befriended")


def test_of_composes_guilds_disposition_with_memory():
    store = DictStore()
    char = Character()
    npc = {"id": "npc-1"}
    base = guilds.disposition(char, npc)
    disp.remember(store, npc, "quest_helped")   # +15
    assert disp.of(char, npc, store) == max(0, min(100, base + 15))


def test_tiers_span_the_band():
    assert disp.tier(5) == "hostile"
    assert disp.tier(20) == "unfriendly"
    assert disp.tier(45) == "neutral"
    assert disp.tier(70) == "friendly"
    assert disp.tier(95) == "devoted"


def test_price_factor_favours_the_liked_player():
    char = Character()
    store = DictStore()
    liked = {"id": "liked"}
    disliked = {"id": "disliked"}
    disp.remember(store, liked, "gift", amount=60)
    disp.remember(store, disliked, "assaulted")
    f_liked = disp.price_factor(char, liked, store)
    f_disliked = disp.price_factor(char, disliked, store)
    assert f_liked < 1.0 < f_disliked
    # bounded so a single relationship can't make trade absurd
    assert 0.85 <= f_liked and f_disliked <= 1.15


def test_memory_persists_across_a_fresh_store_view():
    npc = {"id": "npc-1"}
    store1 = DictStore()
    disp.remember(store1, npc, "assaulted")
    # A brand-new store rehydrated from the first's serialized contents (a
    # "save/load") still knows what happened.
    store2 = DictStore(store1.all())
    assert disp.delta(store2, npc) == -30
    assert disp.has_flag(store2, npc, "wronged")


def test_write_talk_keys_publishes_generic_partner_standing():
    store = DictStore()
    char = Character()
    npc = {"id": "npc-1", "name": "Thalen"}
    disp.remember(store, npc, "assaulted")
    disp.write_talk_keys(store, char, npc)
    assert store.get("talk.wronged") == "1"
    assert store.get("talk.befriended") == "0"
    assert store.get("talk.tier") in ("hostile", "unfriendly", "neutral",
                                      "friendly", "devoted")


# --- live wiring through the settlement session ----------------------------
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


def _build_world():
    import json
    from game import data
    from game.tools import make_settlement
    base_path = os.path.join(os.path.dirname(__file__), "..", "tools", "data",
                             "base_terrain.json")
    with open(os.path.abspath(base_path)) as f:
        base = json.load(f)
    return make_settlement.build(data.load("settlement"), base)


def _session_from(world, hour=12.0, globals_store=None):
    """A live session over a copy of *world*'s things — reusing the same world
    (and thus the same entity UUIDs) models reloading a saved map."""
    from game.runtime import MiniwindSession
    things = [_FakeThing(t["pos"], dict(t["properties"])) for t in world["things"]]
    session = MiniwindSession(_FakeLogic(things, _FakePlayer([300, 272, -100])),
                              cfg={"start_hour": hour, "minutes_per_day": 999999.0},
                              globals_store=globals_store)
    session.clock.set_time(hour, 1)
    session.install()
    return session, things


def _settlement_session(hour=12.0, globals_store=None):
    return _session_from(_build_world(), hour, globals_store)


def _find(things, name):
    return next((t for t in things if t.properties.get("name") == name), None)


def test_assault_is_remembered_and_survives_save_load():
    g = _FakeGlobals()
    world = _build_world()                 # one world = stable entity UUIDs
    session, things = _session_from(world, globals_store=g)
    elowen = _find(things, "Elowen")
    # Give her a side the player is friendly with (the headless fixture skips the
    # entity constructor that would set it), so striking her is a crime.
    elowen.properties.update({"faction": "villagers", "team": "villagers"})
    session._provoke(elowen)
    assert disp.has_flag(session.store, elowen.properties, "wronged")
    assert disp.delta(session.store, elowen.properties) <= -30
    # The bounty is no longer an automatic tax on the swing: it is levied when a
    # witness reaches the watch (game.sim.crime). Elowen saw it happen to her,
    # so putting her next to a guard is all it takes.
    guard = _find(things, "Kestrel")
    guard.pos = list(elowen.pos)
    session.director.resolve_reports(session._sim_actors())
    session.director.resolve_reports(session._sim_actors())
    assert session.game.character.bounty >= 40
    # Reloading the same map (same UUIDs) over the same persistent store still
    # remembers the assault — the wound is durable, not session-local.
    session2, things2 = _session_from(world, globals_store=g)
    elowen2 = _find(things2, "Elowen")
    assert disp.has_flag(session2.store, elowen2.properties, "wronged")


def test_player_killing_kin_turns_relatives_cold():
    g = _FakeGlobals()
    session, things = _settlement_session(globals_store=g)
    bram = _find(things, "Bram")
    mara = _find(things, "Mara")   # Mara names Bram as her brother
    assert disp.delta(session.store, mara.properties) == 0
    session.record_kill(bram)           # the player struck the killing blow
    bram.properties["dead"] = True
    session.tick(0.1)                   # reaping turns it into a consequence
    assert disp.delta(session.store, mara.properties) <= -35
    assert disp.has_flag(session.store, mara.properties, "wronged")


def test_a_bandit_killing_kin_is_not_blamed_on_the_player():
    g = _FakeGlobals()
    session, things = _settlement_session(globals_store=g)
    bram = _find(things, "Bram")
    mara = _find(things, "Mara")
    # Bram dies, but NOT by the player's hand (no record_kill) — a bandit got him.
    bram.properties["dead"] = True
    session.tick(0.1)
    assert disp.delta(session.store, mara.properties) == 0   # grief, not blame


def test_authored_dialogue_reacts_to_a_grudge():
    from game.rpg.dialogue import DialogueRunner
    from game import data
    thalen = next(n for n in data.load("settlement")["npcs"] if n["name"] == "Thalen")
    tree = thalen["dialogue"]
    # No grudge: the reproachful line stays hidden.
    r = DialogueRunner(tree, store=DictStore({"talk.wronged": "0"}))
    r.start()
    assert not any("cooled off" in resp["text"].lower() for resp in r.view()["responses"])
    # Wronged (published by write_talk_keys at conversation start): it opens.
    r2 = DialogueRunner(tree, store=DictStore({"talk.wronged": "1"}))
    r2.start()
    assert any("cooled off" in resp["text"].lower() for resp in r2.view()["responses"])
