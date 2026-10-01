"""
The reactive simulation by level of detail (the world streamer's tiers).

NEAR / ACTIVE actors are simulated in full every tick; DISTANT ones in one
coarse pass per :data:`~game.sim.director.COARSE_INTERVAL_HOURS`; DORMANT ones
(parked) not at all, catching up from their own stamps when they come back.
"""

from __future__ import annotations

from engine.spatial import TIER_ACTIVE, TIER_DISTANT, TIER_DORMANT, TIER_NEAR

from ..runtime import MiniwindSession
from ..sim import knowledge
from ..sim.director import COARSE_INTERVAL_HOURS, SIM_AT_KEY, SIM_DAY_KEY
from .test_sim import _Clock, _Thing, _director, _player


def _cow(name="Cow"):
    return _Thing(name, (60, 0, 0), produces="milk", produce_every_hours=1.0,
                  owner="thalen", owner_name="Thalen")


def _witnessed(d):
    """A death seen by Wick only; Elowen stands beside Wick."""
    player = _player((0, 0, 0))
    victim = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    seer = _Thing("Wick", (150, 0, 0), faction="villagers", sight_range=900)
    relay = _Thing("Elowen", (9000, 0, 0), faction="villagers", sight_range=900)
    d.emit("death", actor=player, target=victim, observers=[player, victim, seer, relay])
    assert knowledge.facts(d.store, "wick") and not knowledge.facts(d.store, "elowen")
    relay.pos = [180, 0, 0]
    return seer, relay


# ------------------------------------------------------------- production --
def test_a_distant_producer_works_in_coarse_steps():
    d = _director()
    cow = _cow()
    d.tick([], 0.5, distant=[cow])
    assert not d.drain_yields(), "no coarse pass before the interval is up"
    d.tick([], COARSE_INTERVAL_HOURS - 0.4, distant=[cow])
    d.tick([], 0.5, distant=[cow])
    (_producer, milk), = d.drain_yields()
    assert milk.item_id == "milk"


def test_a_near_producer_advances_every_tick():
    d = _director()
    cow = _cow()
    d.tick([cow], 0.6)
    assert not d.drain_yields()
    d.tick([cow], 0.6)
    assert len(d.drain_yields()) == 1
    assert cow.properties[SIM_AT_KEY] == d.sim_time


def test_a_parked_producer_catches_up_when_it_comes_back():
    d = _director()
    cow = _cow()
    d.tick([cow], 0.1)                 # stamped
    for _ in range(10):                # parked for five hours: untouched
        d.tick([], 0.5)
    assert cow.properties[SIM_AT_KEY] == 0.1
    d.tick([cow], 0.1)                 # back: one step covering the gap
    assert d.drain_yields(), "the time it was parked counted"


def test_a_stale_stamp_from_an_earlier_session_does_not_stall_production():
    d = _director()
    cow = _cow()
    cow.properties[SIM_AT_KEY] = 999.0
    d.tick([cow], 1.5)
    assert len(d.drain_yields()) == 1


# ----------------------------------------------------------------- gossip --
def test_near_actors_gossip_on_the_fine_clock():
    d = _director()
    seer, relay = _witnessed(d)
    d.tick([seer, relay], 0.5)
    assert knowledge.facts(d.store, "elowen")


def test_distant_actors_gossip_only_on_the_coarse_clock():
    d = _director()
    seer, relay = _witnessed(d)
    d.tick([], 0.5, distant=[seer, relay])
    assert not knowledge.facts(d.store, "elowen")
    d.tick([], COARSE_INTERVAL_HOURS, distant=[seer, relay])
    assert knowledge.facts(d.store, "elowen")


def test_dormant_actors_do_not_gossip_at_all():
    d = _director()
    seer, relay = _witnessed(d)
    for _ in range(8):
        d.tick([], 0.5)
    assert not knowledge.facts(d.store, "elowen")


# ----------------------------------------------------------- memory fade --
def test_a_parked_actor_forgets_by_every_day_it_missed(monkeypatch):
    clock = _Clock(day=1)
    d = _director(clock=clock)
    calls = []
    monkeypatch.setattr(knowledge, "decay",
                        lambda store, key, days=1: calls.append((key, days)) or 0)
    wick = _Thing("Wick", faction="villagers")
    elowen = _Thing("Elowen", faction="villagers")
    d.tick([wick, elowen], 0.1)        # baseline day
    clock.day = 2
    d.tick([wick, elowen], 0.1)
    assert sorted(calls) == [("elowen", 1), ("wick", 1)]
    calls.clear()
    clock.day = 3                      # Elowen is parked through day 3 and 4
    d.tick([wick], 0.1)
    clock.day = 4
    d.tick([wick], 0.1)
    clock.day = 5
    d.tick([wick, elowen], 0.1)
    assert ("elowen", 3) in calls and calls.count(("wick", 1)) == 3
    assert elowen.properties[SIM_DAY_KEY] == 5


# ---------------------------------------------------------------- runtime --
class _Session:
    _tier_of = staticmethod(MiniwindSession._tier_of)
    _sim_by_tier = MiniwindSession._sim_by_tier
    _sim_observers = MiniwindSession._sim_observers

    def __init__(self, actors, player):
        self._actors = actors
        self.player_actor = player

    def _sim_actors(self):
        return list(self._actors) + [self.player_actor]


def _tiered(name, tier):
    return _Thing(name, _sim_tier=tier)


def test_the_session_splits_the_cast_by_tier():
    near, active, far, parked = (_tiered("a", TIER_NEAR), _tiered("b", TIER_ACTIVE),
                                 _tiered("c", TIER_DISTANT), _tiered("d", TIER_DORMANT))
    player = _tiered("You", TIER_DORMANT)          # never mind the stamp
    s = _Session([near, active, far, parked], player)
    full, coarse = s._sim_by_tier()
    assert full == [near, active, player]
    assert coarse == [far]
    assert parked not in s._sim_observers()
    assert far in s._sim_observers()


def test_an_unclassified_actor_is_fully_simulated():
    plain = _Thing("x")
    s = _Session([plain], _player())
    full, coarse = s._sim_by_tier()
    assert plain in full and not coarse
