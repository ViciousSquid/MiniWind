"""
Guards break up a fight they can see.

A guard only ever engaged actors his own faction counts as enemies, so two NPCs
could brawl in the street right in front of two guards and neither would move —
nothing in the fight was an enemy of the watch, so as far as the guards were
concerned nothing was happening. A fight within a guard's sight is now his
business, whatever the combatants' factions.

The other half of the contract is cost: the fights in a settlement are indexed
once per decision pass, not re-scanned per guard, and read off state the combat
AI already maintains rather than anything new.

Run:  python -m pytest game/tests/test_guard_intervention.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import runtime
from game.rpg import schedule as sched
from game.runtime import MiniwindSession


class _Thing:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = dict(props)

    def __repr__(self):                              # readable assertion output
        return f"<{self.properties.get('name', '?')}>"


def _npc(name, pos, faction="villagers", **props):
    p = {"type": "npc", "name": name, "faction": faction, "triggered": False}
    p.update(props)
    return _Thing(pos, **p)


def _guard(name, pos, **props):
    p = {"npc_role": "guard", "combatant": True, "aggression": "defensive",
         "triggered": True}
    p.update(props)
    return _npc(name, pos, faction="guards", **p)


def _swings_at(actor, target):
    """Mark *actor* as swinging at *target*, the way the combat AI does."""
    actor.properties["_aggro_target"] = id(target)
    actor.properties["triggered"] = False


class _Session:
    """The settlement decision pass, over a scene of plain things."""

    _refresh_actor_cache = MiniwindSession._refresh_actor_cache
    _fight_to_break_up = MiniwindSession._fight_to_break_up
    _nearest_hostile = MiniwindSession._nearest_hostile
    _decide = MiniwindSession._decide
    _is_combatant = staticmethod(MiniwindSession._is_combatant)

    def __init__(self, things=(), player=None):
        self.things = list(things)
        self._actors = []
        self._dead_actors = []
        self._fights = []
        self._player_actor = player

    @property
    def player_actor(self):
        return self._player_actor

    def _type_buckets(self):
        buckets = {}
        for t in self.things:
            kind = str(t.properties.get("type", "")).replace("_", "").lower()
            buckets.setdefault(kind, []).append(t)
        return buckets


def _sighted(session, guard):
    return session._fight_to_break_up(guard, runtime.DEFEND_SIGHT)


# ------------------------------------------------------------------ the index

def test_a_fight_between_two_npcs_is_noticed():
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    session = _Session([bram, wick])
    session._refresh_actor_cache()
    assert session._fights == [(wick, bram)]


def test_a_peaceful_settlement_indexes_no_fights():
    session = _Session([_npc("Bram", (0, 0, 0)), _npc("Wick", (60, 0, 0))])
    session._refresh_actor_cache()
    assert session._fights == []


def test_a_mark_left_on_a_parked_actor_is_not_a_fight():
    """Stale aggro on an actor the combat AI is not running is a memory, not a brawl."""
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    wick.properties["triggered"] = True          # parked again
    session = _Session([bram, wick])
    session._refresh_actor_cache()
    assert session._fights == []


def test_a_fight_with_a_corpse_is_over():
    bram = _npc("Bram", (0, 0, 0), dead=True)
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    session = _Session([bram, wick])
    session._refresh_actor_cache()
    assert session._fights == []


def test_the_index_is_built_once_for_the_whole_settlement():
    """Not per guard: several guards on duty must not multiply the same walk."""
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    guards = [_guard(f"Watch{n}", (200 + n * 10, 0, 0)) for n in range(5)]
    session = _Session([bram, wick] + guards)

    walked = []
    real_buckets = session._type_buckets

    def _counting_buckets():
        walked.append(1)
        return real_buckets()

    session._type_buckets = _counting_buckets
    session._refresh_actor_cache()
    for guard in guards:
        _sighted(session, guard)
    assert len(walked) == 1


# ----------------------------------------------------------- who gets grabbed

def test_a_guard_wades_into_a_brawl_between_two_townsfolk():
    """The reported bug, in one assertion."""
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    guard = _guard("Watchman", (100, 0, 0))
    session = _Session([bram, wick, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) in (bram, wick)


def test_a_stranger_is_taken_on_before_one_of_his_own():
    wolf = _npc("Wolf", (0, 0, 0), faction="wildlife")
    townsman = _npc("Wick", (60, 0, 0), faction="villagers")
    _swings_at(wolf, townsman)
    guard = _guard("Watchman", (400, 0, 0))
    session = _Session([wolf, townsman, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) is wolf


def test_the_nearer_brawler_is_grabbed_when_both_are_his_own():
    near = _npc("Bram", (100, 0, 0))
    far = _npc("Wick", (600, 0, 0))
    _swings_at(far, near)
    guard = _guard("Watchman", (0, 0, 0))
    session = _Session([near, far, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) is near


def test_a_guard_never_wades_in_against_the_watch():
    """A guard already fighting is being handled; the other one joins him."""
    thief = _npc("Thief", (0, 0, 0), faction="bandits")
    first_guard = _guard("Watch1", (60, 0, 0))
    _swings_at(first_guard, thief)
    second_guard = _guard("Watch2", (120, 0, 0))
    session = _Session([thief, first_guard, second_guard])
    session._refresh_actor_cache()

    assert _sighted(session, second_guard) is thief


def test_two_guards_scuffling_are_left_to_it():
    one = _guard("Watch1", (0, 0, 0))
    two = _guard("Watch2", (60, 0, 0))
    _swings_at(two, one)
    onlooker = _guard("Watch3", (120, 0, 0))
    session = _Session([one, two, onlooker])
    session._refresh_actor_cache()

    assert _sighted(session, onlooker) is None


def test_a_guard_already_in_the_fight_does_not_re_target_it():
    thief = _npc("Thief", (0, 0, 0), faction="bandits")
    guard = _guard("Watchman", (60, 0, 0))
    _swings_at(guard, thief)
    session = _Session([thief, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) is None


def test_the_players_fights_are_left_to_the_arrest_flow():
    """A guard arrests a wanted man; he does not lynch him mid-duel."""
    player = _npc("You", (0, 0, 0), faction="player")
    victim = _npc("Wick", (60, 0, 0))
    _swings_at(victim, player)
    guard = _guard("Watchman", (100, 0, 0))
    session = _Session([player, victim, guard], player=player)
    session._refresh_actor_cache()

    assert _sighted(session, guard) is None


def test_a_brawl_across_the_settlement_is_out_of_sight():
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    guard = _guard("Watchman", (runtime.DEFEND_SIGHT * 4, 0, 0))
    session = _Session([bram, wick, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) is None


def test_the_nearest_of_two_brawls_is_the_one_broken_up():
    near_a = _npc("Bram", (100, 0, 0))
    near_b = _npc("Wick", (140, 0, 0))
    _swings_at(near_b, near_a)
    far_a = _npc("Cade", (600, 0, 0))
    far_b = _npc("Dill", (640, 0, 0))
    _swings_at(far_b, far_a)
    guard = _guard("Watchman", (0, 0, 0))
    session = _Session([near_a, near_b, far_a, far_b, guard])
    session._refresh_actor_cache()

    assert _sighted(session, guard) in (near_a, near_b)


# --------------------------------------------------------------- the decision

def test_the_decision_pass_sends_the_guard_in():
    """End to end: a brawl in sight leaves the guard in combat with a brawler."""
    bram = _npc("Bram", (0, 0, 0))
    wick = _npc("Wick", (60, 0, 0))
    _swings_at(wick, bram)
    guard = _guard("Watchman", (100, 0, 0))
    session = _Session([bram, wick, guard])
    session._refresh_actor_cache()
    session._decide(guard)

    p = guard.properties
    assert p["sched_state"] == sched.COMBAT
    assert p["_aggro_target"] in (id(bram), id(wick))
    assert p["triggered"] is False and p["awake"] is True


def test_a_guard_still_prefers_an_enemy_of_his_own_faction():
    """The existing rule wins: a bandit at hand outranks a brawl further off."""
    bandit = _npc("Cutthroat", (50, 0, 0), faction="bandits")
    bram = _npc("Bram", (300, 0, 0))
    wick = _npc("Wick", (340, 0, 0))
    _swings_at(wick, bram)
    guard = _guard("Watchman", (0, 0, 0))
    session = _Session([bandit, bram, wick, guard])
    session._refresh_actor_cache()
    session._decide(guard)

    assert guard.properties["_aggro_target"] == id(bandit)
