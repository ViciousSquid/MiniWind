"""
Tests for character/NPC handedness (which side the weapon is wielded).

Covers the persistent Character field and its save/load round-trip, that
character creation records the chosen hand, and that the runtime assigns NPCs a
random hand (left rare) while always respecting an authored one.

Run:  python -m pytest game/tests/test_handedness.py -q
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg.character import Character


def test_character_defaults_to_right_handed():
    assert Character().handed == "right"


def test_handedness_round_trips_through_save_load():
    c = Character()
    c.handed = "left"
    c2 = Character.from_dict(c.to_dict())
    assert c2.handed == "left"
    # a garbage value normalises to right
    c3 = Character.from_dict({"handed": "sideways"})
    assert c3.handed == "right"


# --- runtime wiring --------------------------------------------------------
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


def _session(things):
    from game.runtime import MiniwindSession
    s = MiniwindSession(_FakeLogic(things, _FakePlayer([0, 272, 0])),
                        cfg={"start_hour": 12.0, "minutes_per_day": 999999.0})
    s.clock.set_time(12.0, 1)
    return s


def test_begin_new_character_records_the_chosen_hand():
    s = _session([])
    s.begin_new_character("Lefty", "imperial", "warrior", "none", "male",
                          handed="left")
    assert s.game.character.handed == "left"


def test_runtime_assigns_handedness_respecting_authored_values():
    authored = _FakeThing([0, 272, 0], {"type": "npc", "name": "Southpaw",
                                        "npc_role": "guard", "handed": "left"})
    unset = _FakeThing([0, 272, 0], {"type": "npc", "name": "Anon",
                                     "npc_role": "villager"})
    creature = _FakeThing([0, 272, 0], {"type": "creature", "npc_role": "wolf"})
    s = _session([authored, unset, creature])
    s._assign_npc_handedness()
    assert authored.properties["handed"] == "left"        # authored preserved
    assert unset.properties["handed"] in ("left", "right")   # rolled
    assert creature.properties["handed"] in ("left", "right")


def test_left_handedness_is_rare():
    # Roll a large population and confirm left stays a minority (the flag is rare).
    things = [_FakeThing([0, 272, 0], {"type": "npc", "npc_role": "villager"})
              for _ in range(400)]
    s = _session(things)
    s.rng = random.Random(0)      # deterministic
    s._assign_npc_handedness()
    lefties = sum(1 for t in things if t.properties["handed"] == "left")
    assert 0 < lefties < len(things) * 0.35   # some, but clearly a minority
