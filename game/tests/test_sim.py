"""
Headless tests for the reactive simulation layer (:mod:`game.sim`).

These do not test scenarios — they test that the *mechanisms* compose. The
centrepiece is :func:`test_stabbing_a_townie_produces_the_whole_chain`, which
never mentions a quest, a script or a branch: it stabs somebody and asserts
that crime → witness → report → bounty → guard response falls out of the
general rules, and that removing the witness removes the consequence.

Run:  python -m pytest game/tests/test_sim.py -q
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.sim import appraisal, crime, knowledge, ownership, perception, production
from game.sim.director import Director, PLAYER_KEY, actor_key
from game.sim.events import EventBus, WorldEvent


# --------------------------------------------------------------- fixtures --
class _Thing:
    def __init__(self, name, pos=(0, 0, 0), **props):
        self.pos = list(pos)
        self.properties = dict(props)
        self.properties.setdefault("name", name)
        self.properties.setdefault("display_name", name)


class _Store:
    """A dict-backed stand-in for the MiniWind KV store."""

    def __init__(self):
        self.d = {}

    def get(self, key, default="false"):
        return self.d.get(str(key), default)

    def set(self, key, value):
        self.d[str(key)] = str(value)

    def all(self):
        return dict(self.d)


class _Clock:
    def __init__(self, day=1, hour=12.0):
        self.day = day
        self.hour = hour


def _player(pos=(0, 0, 0)):
    return _Thing("You", pos, is_player=True, faction="player")


def _director(store=None, clock=None, bounties=None):
    store = store or _Store()
    clock = clock or _Clock()

    def _hostile(a, b):
        return {"bandits", "monsters"} & {str(a), str(b)} and a != b

    def _on_bounty(amount, event, reporter):
        if bounties is not None:
            bounties.append((amount, event.kind if event else "", reporter))

    return Director(store=store, clock=clock, rng=random.Random(7),
                    hostile=_hostile, on_bounty=_on_bounty)


# ------------------------------------------------------------------ events --
def test_event_kinds_carry_tags_and_a_readable_phrase():
    ev = WorldEvent("death", actor_name="You", target_name="Mara")
    assert "grave" in ev.tags and "violence" in ev.tags
    assert ev.describe() == "Mara was killed by You"
    assert ev.severity == 1.0


def test_bus_history_is_bounded_and_round_trips():
    bus = EventBus(cap=3)
    for i in range(5):
        bus.make("talk", actor_name=f"a{i}")
    assert len(bus.history) == 3
    assert [e.id for e in bus.history] == [3, 4, 5]
    other = EventBus()
    assert other.load_json(bus.to_json()) == 3
    assert other.recent(1)[0].describe() == bus.recent(1)[0].describe()


def test_unknown_event_kinds_still_work():
    ev = WorldEvent("sang_a_song", actor_name="Wick")
    assert ev.tags == ()
    assert "Wick" in ev.describe()


# -------------------------------------------------------------- perception --
def test_sight_beats_sound_and_distance_lowers_clarity():
    near = _Thing("Near", (100, 0, 0), sight_range=1000)
    far = _Thing("Far", (900, 0, 0), sight_range=1000)
    ev = WorldEvent("attack", pos=(0, 0, 0))
    pn = perception.can_perceive(near, ev.pos, ev.loudness)
    pf = perception.can_perceive(far, ev.pos, ev.loudness)
    assert pn.mode == "sight" and pf.mode == "sight"
    assert pn.clarity > pf.clarity


def test_a_blind_actor_can_still_hear_it():
    listener = _Thing("Blind", (300, 0, 0), sight_range=0)
    ev = WorldEvent("attack", pos=(0, 0, 0))
    pc = perception.can_perceive(listener, ev.pos, ev.loudness)
    assert pc is not None and pc.mode == "sound"
    assert pc.clarity <= perception.SOUND_CLARITY


def test_sleeping_actors_do_not_see_but_a_loud_event_wakes_them():
    sleeper = _Thing("Sleeper", (120, 0, 0), sight_range=1200, sched_state="SLEEPING")
    quiet = WorldEvent("theft", pos=(0, 0, 0))
    loud = WorldEvent("death", pos=(0, 0, 0))
    assert perception.can_perceive(sleeper, quiet.pos, quiet.loudness) is None
    pc = perception.can_perceive(sleeper, loud.pos, loud.loudness)
    assert pc is not None and pc.mode == "sound" and pc.woke


def test_sneaking_shrinks_everyones_sight():
    watcher = _Thing("Watch", (600, 0, 0), sight_range=800)
    ev = WorldEvent("theft", pos=(0, 0, 0))
    seen = perception.can_perceive(watcher, ev.pos, ev.loudness, actor_props={})
    hidden = perception.can_perceive(watcher, ev.pos, ev.loudness,
                                     actor_props={"sneaking": True})
    assert seen is not None and seen.mode == "sight"
    assert hidden is None


def test_night_dims_sight_unless_you_carry_a_torch():
    dark = _Thing("Dark", (700, 0, 0), sight_range=1000)
    lit = _Thing("Lit", (700, 0, 0), sight_range=1000, torch=True)
    assert perception.sight_range(dark.properties, hour=23.0) < 1000
    assert perception.sight_range(lit.properties, hour=23.0) == 1000


def test_the_actor_is_never_their_own_witness():
    actor = _Thing("Thief", (0, 0, 0), sight_range=1000)
    bystander = _Thing("Baker", (100, 0, 0), sight_range=1000)
    ev = WorldEvent("theft", pos=(0, 0, 0))
    seen = perception.witnesses(ev, [actor, bystander], actor_thing=actor)
    assert [w.observer for w in seen] == [bystander]


# --------------------------------------------------------------- knowledge --
def test_a_fact_decays_when_told_on_and_dies_out():
    store = _Store()
    ev = WorldEvent("death", actor="player", actor_name="You",
                    target="mara", target_name="Mara", event_id=1)
    knowledge.learn(store, "a", knowledge.fact_from_event(ev, 1.0, "witnessed"))
    chain = ["a", "b", "c", "d", "e", "f"]
    for speaker, listener in zip(chain, chain[1:]):
        knowledge.gossip(store, speaker, listener)
    certainties = [
        (knowledge.knows(store, who, 1) or {}).get("certainty", 0.0)
        for who in chain]
    assert certainties[0] == 1.0
    # Strictly falling, and the tail of the chain never hears it at all.
    assert all(b < a for a, b in zip(certainties, certainties[1:]) if b)
    assert certainties[-1] == 0.0


def test_hearing_the_same_rumour_twice_is_not_news():
    store = _Store()
    ev = WorldEvent("death", target_name="Mara", event_id=9)
    fact = knowledge.fact_from_event(ev, 0.9, "witnessed")
    knowledge.learn(store, "a", fact)
    knowledge.learn(store, "b", fact)
    assert knowledge.gossip(store, "a", "c")
    assert knowledge.gossip(store, "b", "c") == []


def test_a_clearer_account_upgrades_a_vague_one():
    store = _Store()
    ev = WorldEvent("death", target_name="Mara", event_id=3)
    knowledge.learn(store, "a", knowledge.fact_from_event(ev, 0.3, "heard"))
    assert knowledge.learn(store, "a", knowledge.fact_from_event(ev, 0.9, "witnessed"))
    f = knowledge.knows(store, "a", 3)
    assert f["certainty"] == 0.9 and f["source"] == "witnessed"


def test_hearsay_fades_faster_than_testimony():
    store = _Store()
    ev = WorldEvent("death", target_name="Mara", event_id=4)
    knowledge.learn(store, "seer", knowledge.fact_from_event(ev, 0.9, "witnessed"))
    knowledge.learn(store, "gossip", knowledge.fact_from_event(ev, 0.9, "told"))
    knowledge.decay(store, "seer", 5)
    knowledge.decay(store, "gossip", 5)
    assert (knowledge.knows(store, "seer", 4)["certainty"]
            > knowledge.knows(store, "gossip", 4)["certainty"])


def test_only_notable_things_are_worth_repeating():
    store = _Store()
    dull = WorldEvent("talk", target_name="Bram", event_id=5)
    knowledge.learn(store, "a", knowledge.fact_from_event(dull, 1.0, "witnessed"))
    assert knowledge.gossip(store, "a", "b") == []


# --------------------------------------------------------------- ownership --
def test_taking_an_owned_thing_is_theft_and_taking_your_own_is_not():
    milk = {"owner": "thalen", "owner_name": "Thalen", "value": 6}
    assert ownership.is_theft(milk, PLAYER_KEY)
    assert not ownership.is_theft(milk, "thalen")
    assert not ownership.is_theft({}, PLAYER_KEY)


def test_faction_property_is_shared_by_its_members():
    crate = {"owner_faction": "guards"}
    assert not ownership.is_theft(crate, "someguard", "guards")
    assert ownership.is_theft(crate, PLAYER_KEY, "player")


def test_stolen_goods_stay_branded_until_laundered():
    stack = ownership.mark_stolen({"id": "milk"}, "thalen", "Thalen")
    assert ownership.is_stolen(stack) and stack["stolen_from"] == "Thalen"
    assert not ownership.is_stolen(ownership.launder(stack))


# -------------------------------------------------------------- production --
def test_a_cow_produces_owned_milk_on_a_clock():
    cow = {"produces": "milk", "produce_every_hours": 8.0,
           "owner": "thalen", "owner_name": "Thalen"}
    assert production.advance(cow, 5.0) == []
    made = production.advance(cow, 4.0)
    assert len(made) == 1 and made[0].item_id == "milk"
    assert made[0].owner == "thalen"


def test_production_stops_when_yields_pile_up_and_resumes_when_collected():
    cow = {"produces": "milk", "produce_every_hours": 1.0, "produce_max": 2}
    assert len(production.advance(cow, 10.0)) == 2
    assert production.advance(cow, 10.0) == []
    production.note_collected(cow, 2)
    assert production.advance(cow, 10.0)


def test_a_dead_cow_gives_no_milk():
    cow = {"produces": "milk", "produce_every_hours": 1.0, "dead": True}
    assert production.advance(cow, 50.0) == []


# --------------------------------------------------------------- appraisal --
def _fact(kind, actor="player", actor_name="You", target="mara",
          target_name="Mara", certainty=1.0, source="witnessed", eid=1, **extra):
    f = knowledge.fact_from_event(
        WorldEvent(kind, actor=actor, actor_name=actor_name, target=target,
                   target_name=target_name, event_id=eid),
        certainty, source)
    f.update(extra)
    return f


def test_one_murder_reads_differently_to_five_different_people():
    fact = _fact("death")
    brother = {"name": "Bram", "relationships": {"Mara": "sibling"}, "courage": 0.6}
    guard = {"name": "Kestrel", "faction": "guards", "combatant": True}
    baker = {"name": "Wick", "courage": 0.5}
    coward = {"name": "Elowen", "courage": 0.05}
    rival = {"name": "Vex", "relationships": {"Mara": "rival"}}
    reactions = {
        "brother": appraisal.appraise(brother, "bram", fact).reaction,
        "guard": appraisal.appraise(guard, "kestrel", fact).reaction,
        "baker": appraisal.appraise(baker, "wick", fact).reaction,
        "coward": appraisal.appraise(coward, "elowen", fact).reaction,
        "rival": appraisal.appraise(rival, "vex", fact).reaction,
    }
    assert reactions == {
        "brother": appraisal.FIGHT,
        "guard": appraisal.ARREST,
        "baker": appraisal.REPORT,
        "coward": appraisal.FLEE,
        "rival": appraisal.IGNORE,
    }


def test_every_intent_explains_itself():
    intent = appraisal.appraise(
        {"name": "Bram", "relationships": {"Mara": "sibling"}, "courage": 0.9},
        "bram", _fact("death"))
    assert "Mara" in intent.reason and "sibling" in intent.reason
    assert appraisal.explain([intent]).startswith("Attack You")


def test_a_coward_who_is_attacked_runs_and_a_brave_one_fights():
    fact = _fact("attack", target="wick", target_name="Wick")
    assert appraisal.appraise({"courage": 0.05}, "wick", fact).reaction == appraisal.FLEE
    assert appraisal.appraise({"courage": 0.9}, "wick", fact).reaction == appraisal.FIGHT


def test_a_vague_rumour_is_not_enough_to_act_on():
    fact = _fact("death", certainty=0.1, source="told")
    assert appraisal.appraise({"faction": "guards"}, "kestrel", fact) is None


def test_one_response_per_offender_not_one_per_fact():
    facts = [_fact("attack", eid=1, target="wick", target_name="Wick"),
             _fact("theft", eid=2, target="wick", target_name="Wick"),
             _fact("death", eid=3)]
    intents = appraisal.appraise_all({"courage": 0.9, "name": "Wick"}, "wick", facts)
    assert len(intents) == 1 and intents[0].reaction == appraisal.FIGHT


# ------------------------------------------------------------------ crime --
def test_nobody_charges_themselves():
    """A guard who commits the crime himself walks away from it."""
    store = _Store()
    fact = _fact("death", actor="kestrel", actor_name="Kestrel", eid=21)
    assert crime.report(store, fact, "kestrel", {"faction": "guards"}) == 0
    assert crime.report(store, fact, "other", {"faction": "guards"}) > 0


def test_the_player_is_not_the_law():
    store = _Store()
    fact = _fact("theft", eid=22, value=10)
    assert crime.report(store, fact, PLAYER_KEY, {"faction": "player"}) == 0


def test_a_theft_bounty_scales_with_what_was_taken():
    small = WorldEvent("theft", data={"value": 5})
    large = WorldEvent("theft", data={"value": 900})
    assert crime.bounty_for(large) > crime.bounty_for(small) > 0
    assert crime.bounty_for(WorldEvent("talk")) == 0


def test_only_the_law_lays_a_charge_and_only_once():
    store = _Store()
    fact = _fact("death", eid=11)
    assert crime.report(store, fact, "wick", {"faction": "villagers"}) == 0
    first = crime.report(store, fact, "kestrel", {"faction": "guards"})
    assert first == crime.CRIME_BOUNTY["death"]
    assert crime.report(store, fact, "other_guard", {"faction": "guards"}) == 0


# ------------------------------------------------------- the whole pipeline --
def test_stabbing_a_townie_produces_the_whole_chain():
    """crime → witness → report → bounty → guard response, unscripted."""
    bounties = []
    d = _director(bounties=bounties)
    player = _player((0, 0, 0))
    mara = _Thing("Mara", (60, 0, 0), faction="villagers", courage=0.2)
    wick = _Thing("Wick", (200, 0, 0), faction="villagers", sight_range=900,
                  courage=0.5)
    guard = _Thing("Kestrel", (260, 0, 0), faction="guards", combatant=True,
                   sight_range=900)
    actors = [player, mara, wick, guard]

    d.emit("attack", actor=player, target=mara, observers=actors, damage=12)

    # PERCEPTION: the bystanders know; nobody had to be told to look.
    assert knowledge.facts(d.store, "wick"), "the baker saw it"
    # INTERPRETATION: each reads it their own way.
    assert d.top_intent(wick).reaction in (appraisal.REPORT, appraisal.FLEE)
    assert d.top_intent(guard).reaction == appraisal.ARREST
    # STATE CHANGE: a charge is laid, once, and it costs the player.
    d.resolve_reports(actors)
    assert len(bounties) == 1 and bounties[0][0] == crime.CRIME_BOUNTY["attack"]
    d.resolve_reports(actors)
    assert len(bounties) == 1, "one crime, one bounty"
    # ...and the victim's own opinion of the player has moved.
    from game.rpg import disposition as disp
    assert disp.delta(d.store, mara.properties) < 0


def test_murder_with_no_witness_costs_nothing_until_someone_finds_out():
    bounties = []
    d = _director(bounties=bounties)
    player = _player((0, 0, 0))
    victim = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    guard = _Thing("Kestrel", (9000, 0, 0), faction="guards", sight_range=800)
    lone_witness = _Thing("Wick", (300, 0, 0), faction="villagers", sight_range=900)

    # (a) alone in the dark: nobody perceives it, so nothing happens.
    d.clock.hour = 2.0
    ev = d.emit("death", actor=player, target=victim, observers=[player, victim, guard])
    d.resolve_reports([player, guard])
    assert bounties == []
    assert "nobody saw it" in ev.consequences

    # (b) the same act with one witness who never reaches a guard: still nothing.
    victim2 = _Thing("Bram", (60, 0, 0), faction="villagers", dead=True)
    d.clock.hour = 12.0
    d.emit("death", actor=player, target=victim2,
           observers=[player, victim2, lone_witness, guard])
    d.resolve_reports([player, lone_witness, guard])
    assert bounties == [], "the guard is across the map"

    # (c) the witness walks into town and tells the guard: now it lands.
    lone_witness.pos = [8900, 0, 0]
    d.resolve_reports([player, lone_witness, guard])
    d.resolve_reports([player, lone_witness, guard])
    assert bounties and bounties[0][0] == crime.CRIME_BOUNTY["death"]


def test_silencing_the_only_witness_buries_the_crime():
    bounties = []
    d = _director(bounties=bounties)
    player = _player((0, 0, 0))
    victim = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    witness = _Thing("Wick", (300, 0, 0), faction="villagers", sight_range=900)
    guard = _Thing("Kestrel", (9000, 0, 0), faction="guards", sight_range=800)

    d.emit("death", actor=player, target=victim,
           observers=[player, victim, witness, guard])
    assert knowledge.facts(d.store, "wick")

    # The player kills the witness too — out of everyone else's sight.
    witness.properties["dead"] = True
    d.emit("death", actor=player, target=witness, observers=[player, witness])

    # A dead witness never walks to the guard, so no charge is ever laid.
    witness.pos = [8900, 0, 0]
    d.resolve_reports([player, guard])
    assert bounties == []


def test_news_travels_by_foot_traffic_and_reaches_the_law_late():
    bounties = []
    d = _director(bounties=bounties)
    player = _player((0, 0, 0))
    victim = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    seer = _Thing("Wick", (150, 0, 0), faction="villagers", sight_range=900)
    relay = _Thing("Elowen", (5000, 0, 0), faction="villagers", sight_range=900)
    guard = _Thing("Kestrel", (5100, 0, 0), faction="guards", sight_range=200)

    d.emit("death", actor=player, target=victim,
           observers=[player, victim, seer, relay, guard])
    assert not knowledge.facts(d.store, "kestrel"), "the guard was too far to see"

    # The witness walks across town; standing near Elowen, the story passes on.
    seer.pos = [5050, 0, 0]
    d.spread_rumours([seer, relay, guard])
    assert knowledge.facts(d.store, "elowen"), "gossip carried it"
    # And once it reaches the watch, the charge follows.
    d.resolve_reports([seer, relay, guard])
    d.resolve_reports([seer, relay, guard])
    assert bounties and bounties[0][0] == crime.CRIME_BOUNTY["death"]


def test_milking_someone_elses_cow_is_a_crime_with_no_milk_quest_in_sight():
    bounties = []
    d = _director(bounties=bounties)
    player = _player((0, 0, 0))
    farmer = _Thing("Thalen", (150, 0, 0), faction="villagers", sight_range=900)
    guard = _Thing("Kestrel", (200, 0, 0), faction="guards", sight_range=900)
    cow = _Thing("Cow", (60, 0, 0), produces="milk", produce_every_hours=1.0,
                 owner="thalen", owner_name="Thalen")

    # The cow makes milk; the milk belongs to the farmer because the cow does.
    d.tick_production([cow], 1.5)
    (_producer, milk), = d.drain_yields()
    assert milk.item_id == "milk" and milk.owner == "thalen"

    # Taking it is a theft, seen by the farmer and the guard.
    bucket = {"owner": milk.owner, "owner_name": milk.owner_name, "value": 6}
    ev = d.take(bucket, player, target_thing=farmer,
                observers=[player, farmer, guard], item_id="milk",
                item_name="bucket of milk", value=6, pos=(60, 0, 0))
    assert ev.kind == "theft"
    d.resolve_reports([player, farmer, guard])
    assert bounties and bounties[0][0] == crime.bounty_for(ev)

    # Taking your own milk is not a crime at all.
    d2 = _director()
    own = {"owner": "player", "owner_name": "You"}
    assert d2.take(own, player, observers=[player]).kind == "pickup"


def test_a_grieving_brother_turns_on_the_player_without_being_told_to():
    d = _director()
    player = _player((0, 0, 0))
    mara = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    bram = _Thing("Bram", (200, 0, 0), faction="villagers", sight_range=900,
                  courage=0.7, relationships={"Mara": "sibling"})
    d.emit("death", actor=player, target=mara, observers=[player, mara, bram])
    intent = d.top_intent(bram)
    assert intent.reaction == appraisal.FIGHT
    assert "sibling" in intent.reason
    assert "Bram" in d.why(bram) or "You" in d.why(bram)


def test_the_history_view_shows_causes_and_consequences():
    d = _director()
    player = _player((0, 0, 0))
    mara = _Thing("Mara", (60, 0, 0), faction="villagers", dead=True)
    guard = _Thing("Kestrel", (150, 0, 0), faction="guards", sight_range=900)
    d.emit("death", actor=player, target=mara, observers=[player, mara, guard])
    d.resolve_reports([player, guard])
    lines = d.report_lines()
    assert any("Mara was killed by You" in ln for ln in lines)
    assert any("laid a charge" in ln for ln in lines)


def test_history_survives_a_save_and_load():
    d = _director()
    player = _player()
    d.emit("death", actor=player, target=_Thing("Mara"), observers=[])
    d.persist()
    other = _director(store=d.store)
    assert other.restore() == 1
    assert other.bus.recent(1)[0].kind == "death"


def test_a_days_passing_lets_the_town_move_on():
    d = _director()
    player = _player()
    witness = _Thing("Wick", (100, 0, 0), sight_range=900)
    d.emit("theft", actor=player, target=_Thing("Thalen"),
           observers=[player, witness], value=5)
    before = knowledge.facts(d.store, "wick")[0]["certainty"]
    d.clock.day += 6
    d.tick([witness], hours=0.0)
    after = knowledge.knows(d.store, "wick", 1)
    assert after is None or after["certainty"] < before


def test_actor_keys_are_stable_and_the_player_is_just_another_actor():
    assert actor_key(_player()) == PLAYER_KEY
    assert actor_key(_Thing("Mara the Elder")) == "mara_the_elder"
    assert actor_key(None) == ""


# =========================================================================
# End-to-end, through the real runtime session and the real settlement.
# These prove the wiring, not the mechanisms: the same acts a player commits
# in Millbrook produce the chain without any of it being scripted.
# =========================================================================
class _MapThing:
    """A built map entity, as test_settlement/test_disposition stage them."""

    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakeLogic:
    def __init__(self, things, player):
        self.things = things
        self.player = player


class _FakeGlobals:
    def __init__(self):
        self._d = {}

    def get(self, key, default="false", store=None):
        return self._d.get((store, str(key)), default)

    def set(self, key, value, store=None):
        self._d[(store, str(key))] = str(value)

    def all(self, store=None):
        return {k[1]: v for k, v in self._d.items() if k[0] == store}


def _settlement(hour=12.0):
    """A live session over the authored settlement, as test_disposition builds it."""
    import json
    from game import data
    from game.runtime import MiniwindSession
    from game.tools import make_settlement
    base_path = os.path.join(os.path.dirname(__file__), "..", "tools", "data",
                             "base_terrain.json")
    with open(os.path.abspath(base_path)) as f:
        base = json.load(f)
    world = make_settlement.build(data.load("settlement"), base)
    things = [_MapThing(t["pos"], dict(t["properties"])) for t in world["things"]]
    player = _Thing("player", [300, 272, -100], is_player=True)
    session = MiniwindSession(_FakeLogic(things, player),
                              cfg={"start_hour": hour, "minutes_per_day": 999999.0},
                              globals_store=_FakeGlobals())
    session.clock.set_time(hour, 1)
    session.install()
    return session, things


def _named(things, name):
    return next((t for t in things
                 if t.properties.get("name") == name), None)


def test_session_exposes_one_simulation_seam():
    session, _things = _settlement()
    assert session.director is not None
    # The player is an ordinary actor, so NPCs can perceive and remember them.
    assert actor_key(session.player_actor) == PLAYER_KEY
    assert session.player_actor in session._sim_actors()


def test_striking_a_townsperson_in_front_of_a_guard_lands_a_bounty():
    session, things = _settlement()
    elowen = _named(things, "Elowen")
    guard = _named(things, "Kestrel")
    elowen.properties.update({"faction": "villagers", "team": "villagers"})
    guard.pos = list(elowen.pos)                 # the watch is right there
    assert session.game.character.bounty == 0

    session._provoke(elowen)                     # the player swings

    event = session.director.bus.recent(1)[0]
    assert event.kind == "attack" and event.is_crime
    session.director.resolve_reports(session._sim_actors())
    assert session.game.character.bounty >= crime.CRIME_BOUNTY["attack"]
    # And the guard can say why, in words the designer can read.
    assert "Kestrel" in session.director.why(guard) or \
        "arrest" in session.director.why(guard).lower()


def test_the_same_strike_out_of_sight_costs_nothing_yet():
    session, things = _settlement()
    elowen = _named(things, "Elowen")
    elowen.properties.update({"faction": "villagers", "team": "villagers"})
    for t in things:                             # send everyone else far away
        if t is not elowen and t.properties.get("type") in ("npc", "creature"):
            t.pos = [90000.0, t.pos[1], 90000.0]

    session._provoke(elowen)
    session.director.resolve_reports(session._sim_actors())
    assert session.game.character.bounty == 0, "no witness reached the watch"
    # The victim still knows perfectly well what happened to her.
    assert knowledge.facts(session.store, actor_key(elowen))


def test_a_witness_walks_to_the_watch_of_its_own_accord():
    session, things = _settlement()
    elowen = _named(things, "Elowen")
    wick = _named(things, "Wick")
    guard = _named(things, "Kestrel")
    for t in (elowen, wick):
        t.properties.update({"faction": "villagers", "team": "villagers"})
    wick.pos = [elowen.pos[0] + 150, elowen.pos[1], elowen.pos[2]]
    guard.pos = [elowen.pos[0] + 4000, elowen.pos[1], elowen.pos[2]]

    session._provoke(elowen)
    session._refresh_actor_cache()
    session._decide(wick)
    assert wick.properties.get("sched_state") == "REPORT"
    assert wick.properties.get("_dest")[0] == guard.pos[0]
    assert "watch" in wick.properties.get("_sim_reason", "").lower()


def test_a_cow_placed_in_the_world_makes_owned_milk_the_player_can_steal():
    session, things = _settlement()
    farmer = _named(things, "Thalen")
    cow = _Thing("Bessie", [farmer.pos[0] + 60, farmer.pos[1], farmer.pos[2]],
                 type="creature", npc_role="cow", produces="milk",
                 produce_every_hours=1.0, owner=actor_key(farmer),
                 owner_name="Thalen", faction="wildlife")
    things.append(cow)
    session._type_index_token = None

    session.director.tick_production([cow], 1.5)
    for producer, made in session.director.drain_yields():
        session._place_yield(producer, made)
    milk = next(t for t in session.logic.things
                if t.properties.get("item_id") == "milk")
    assert actor_key(farmer) == milk.properties["owner"]

    # Walking over it is a theft, because it belongs to somebody.
    session.logic.player.pos = list(milk.pos)
    session._type_index_token = None
    session._tick_pickups()
    stolen = session.director.bus.recent(1)[0]
    assert stolen.kind == "theft"
    assert any(s.get("stolen") for s in session.game.character.inventory)


def test_killing_the_cow_ends_the_milk():
    session, _things = _settlement()
    cow = _Thing("Bessie", [0, 0, 0], type="creature", produces="milk",
                 produce_every_hours=1.0)
    session.director.tick_production([cow], 5.0)
    assert session.director.drain_yields()
    cow.properties["dead"] = True
    session.director.tick_production([cow], 50.0)
    assert session.director.drain_yields() == []


def test_the_designer_can_inject_an_event_and_watch_it_answer():
    session, things = _settlement()
    mara = _named(things, "Mara")
    bram = _named(things, "Bram")     # Mara names Bram as her brother
    bram.pos = [mara.pos[0] + 120, mara.pos[1], mara.pos[2]]
    bram.properties["courage"] = 0.9
    mara.properties["dead"] = True

    event = session.emit_event("death", target=mara, crime=True)
    assert event.consequences, "somebody saw it"
    intent = session.director.top_intent(bram)
    assert intent is not None and intent.reaction == appraisal.FIGHT
    # And the runtime turns that intent into actual behaviour.
    session._refresh_actor_cache()
    session._decide(bram)
    assert bram.properties["aggression"] == "hostile"
    assert bram.properties["sched_state"] == "COMBAT"


def test_the_inspector_explains_the_behaviour_it_caused():
    from game import mental_state
    session, things = _settlement()
    mara = _named(things, "Mara")
    bram = _named(things, "Bram")
    bram.pos = [mara.pos[0] + 120, mara.pos[1], mara.pos[2]]
    bram.properties["courage"] = 0.9
    mara.properties["dead"] = True
    session.emit_event("death", target=mara, crime=True)
    session._refresh_actor_cache()
    session._decide(bram)

    snap = mental_state.snapshot(bram, session=session)
    headings = [h for h, _rows in snap["sections"]]
    assert "Why" in headings and "Knowledge" in headings
    why_rows = dict(next(rows for h, rows in snap["sections"] if h == "Why"))
    assert "my sister" in why_rows["Because"]
