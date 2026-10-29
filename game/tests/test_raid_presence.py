"""A faction force holds the place its order named: a hostile presence, made
of existing mechanisms, that never attacks anyone by fiat."""

from __future__ import annotations

import copy
import random

from ..living import journeys
from ..sim import knowledge, rumours
from ..sim.factions import identity
from .test_faction_spine import fact, prepare_raid
from .test_storyteller import actor


def locals_at_b(spine, living, cast, count=2):
    town = [actor(f"Local {i}", town="b", id=f"local{i}", type="npc", faction="villagers",
                  courage=0.2, _sim_tier=3) for i in range(count)]
    for who in town:
        who.pos = [2000, 0, 0]
    living._residents.update({a.properties["id"]: a for a in town})
    spine.bind(living.board, cast + town)
    return town


def arrive(living, raid, t=20.0):
    raid.depart_t = t - raid.length / raid.speed
    made = []
    living.board.arrive(raid, t, made)
    return made


def test_a_force_holds_its_destination_for_the_presence_period_on_the_same_draw():
    s, living, spine, cast, raid, _f = prepare_raid()
    b = living.board
    probe = random.Random()
    probe.setstate(b.rng.getstate())
    rest = 20.0 + probe.uniform(*journeys.REST_HOURS)
    made = arrive(living, raid)
    assert raid.state == "rest" and raid.dest == "b"
    assert raid.rest_until == max(rest, 20.0 + journeys.PRESENCE_HOURS)
    assert b.rng.getstate() == probe.getstate()        # one draw, as any rest
    assert b.holding("b") == [raid] and b.holding("a") == []
    news = b.news[made[-1]]
    assert news["place"] == "b" and news["kind"] == "presence"
    assert "Villagers out of a are holding b, asking after the stranger." == news["text"]
    assert made[-1] in raid.news


def test_locals_see_the_company_and_tell_it_what_they_know_of_its_quarry():
    s, living, spine, cast, raid, f = prepare_raid()
    town = locals_at_b(spine, living, cast)
    theft = fact(e=9, kind="theft")
    knowledge.learn(s.store, identity(town[0]), theft)
    arrive(living, raid)
    seen = [x for x in knowledge.facts(s.store, identity(town[1])) if x["kind"] == "muster"]
    assert len(seen) == 1
    muster = seen[0]
    assert muster["actor"] != "player" and muster["target"] == "player" and not muster["crime"]
    assert muster["cause"]["faction"] == raid.cause["faction"] and muster["journey"] == raid.id
    # Hearsay about the quarry travels with the force, decayed as any telling.
    member = identity(spine.member(raid.alive()[0]["resident"]))
    heard = knowledge.knows(s.store, member, 9)
    assert heard["source"] == knowledge.SOURCE_TOLD and heard["certainty"] < theft["certainty"]
    # Nobody learned the quarry's whereabouts, and the player learned nothing.
    assert knowledge.facts(s.store, "player") == []
    line = rumours.line(muster, lambda x, z: "b", 0, place_name=living.board.place_name)
    assert "came asking after you" in line and "Those were villagers out of a" in line


def test_only_raiding_factions_take_livestock_and_never_in_sight():
    calls = []
    for faction, live, expected in (("bandits", False, True), ("villagers", False, False),
                                    ("bandits", True, False)):
        s, living, spine, cast, raid, _f = prepare_raid()
        raid.cause["faction"] = faction
        raid.live = live
        living.board.hooks.raid_place = lambda place, strength: calls.append(place) or 2
        before = len(calls)
        made = arrive(living, raid)
        assert (len(calls) > before) == expected
        text = living.board.news[made[-1]]["text"]
        assert ("carried off 2 head of livestock" in text) == expected


def test_nobody_sets_out_from_a_held_town_until_the_force_moves_on():
    s, living, spine, cast, raid, _f = prepare_raid()
    town = locals_at_b(spine, living, cast)
    hooks = living.board.hooks
    rid = town[0].properties["id"]
    assert hooks.resident_can_leave(rid)
    arrive(living, raid)
    assert not hooks.resident_can_leave(rid)
    living.board.next_leg(raid, raid.rest_until)
    assert raid.state == "travel" and raid.dest == "a"
    assert hooks.resident_can_leave(rid)


def test_a_holding_force_meets_hostile_parties_that_come_near_it():
    s, living, spine, cast, raid, _f = prepare_raid()
    b = living.board
    arrive(living, raid)
    gang = b.plan("bandits", 20.0, origin="d", dest="b")
    gang.set_progress(gang.length - 300, 20.5)
    assert raid.state == "rest"
    before = set(b.news)
    b._encounters(20.5, [])
    assert gang.id in raid.fought and raid.id in gang.fought
    assert any(b.news[n]["kind"] in ("battle", "robbery") for n in set(b.news) - before)


def test_an_order_that_finds_no_one_still_rests_and_returns_home():
    s, living, spine, cast, raid, _f = prepare_raid()
    arrive(living, raid)
    living.board.next_leg(raid, raid.rest_until)
    assert raid.dest == raid.home == "a"
    made = arrive(living, raid, raid.arrives_at())
    assert raid.state in ("done", "rest") and not any(
        living.board.news[n]["kind"] == "presence" for n in made)


def test_pristine_ecology_has_no_presence_account():
    s, living, spine, cast, raid, _f = prepare_raid()
    town = locals_at_b(spine, living, cast)
    s.storyteller.set_enabled(False)
    snapshot = copy.deepcopy(s.store.d)
    assert spine.present(raid, 20.0) is None
    assert s.store.d == snapshot
    assert not any(x["kind"] == "muster" for x in knowledge.facts(s.store, identity(town[0])))
