"""Justified journeys: every strong, evidenced intent toward the player can
bias an ordinary trip or nearby arrival, through the vendetta mechanism."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from .. import chatter
from ..sim import appraisal, crime, knowledge
from ..sim import storyteller as story_mod
from ..sim.director import actor_key
from ..sim.storyteller import TUNING
from .test_storyteller import actor, board, rising, setup

REACTION = {"reckoning": appraisal.FIGHT, "restitution": appraisal.CONFRONT,
            "gratitude": appraisal.WARM}
KIND = {"reckoning": "attack", "restitution": "theft", "gratitude": "heal"}


def holder_with(story, director, hooks, store, purpose, **fact_fields):
    """A resident whose own account of a player deed backs *purpose*."""
    who = actor("Holder", id="holder_uuid", combatant=True)
    hooks.cast.append(who)
    key = actor_key(who)
    ev = director.bus.make(KIND[purpose], actor="player", target=key, target_name="Holder",
                           day=0, hour=0, data=dict(crime=purpose != "gratitude"))
    fact = knowledge.fact_from_event(ev, 1.0, knowledge.SOURCE_WITNESSED)
    fact.update(fact_fields)
    knowledge.learn(store, key, fact)
    intent = appraisal.Intent(REACTION[purpose], "player", "You", f"{purpose} reason", fact)
    director._intents[key] = [intent]
    return who, intent


@pytest.mark.parametrize("purpose", ["reckoning", "restitution", "gratitude"])
def test_each_justified_kind_stages_with_its_scaled_share_of_the_vendetta_bonus(purpose):
    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, purpose)
    rising(story)
    bias = story._levers["vendetta_bias"]
    scale = TUNING["justified_journeys"][purpose]
    assert story.materialisation_weight([actor_key(who)], 300) == pytest.approx(1 + (bias - 1) * scale)
    assert story.world_view()["vendettas"][actor_key(who)]["kind"] == purpose
    # The original sensor still counts only kin vendettas.
    assert story.sensors["vendettas"] == 0 and story.sensors["justified"] == 1


@pytest.mark.parametrize("case", ["lawful_attack", "reported_theft", "settled_theft",
                                  "uncertain", "unidentified", "someone_elses_theft"])
def test_unevidenced_or_resolved_intents_keep_ordinary_sampling(case):
    story, director, hooks, store = setup()
    purpose = "reckoning" if case == "lawful_attack" else "restitution"
    fields = {"lawful_attack": dict(crime=False), "reported_theft": dict(reported=True),
              "uncertain": dict(certainty=crime.REPORT_CERTAINTY / 2),
              "unidentified": dict(identified=False),
              "someone_elses_theft": dict(target="victim")}.get(case, {})
    who, intent = holder_with(story, director, hooks, store, purpose, **fields)
    if case == "settled_theft":
        store.set(f"crime.{intent.event_id}.settled", "1")
    rising(story)
    assert story.materialisation_weight([actor_key(who)], 300) == 1
    assert story.resident_destination(who.properties["id"], ["a", "b"], 100) is None


def test_stranger_warmth_and_friends_deaths_are_not_justified_journeys():
    fact = dict(e=1, kind="heal", actor="player", target="someone", target_name="Someone",
                certainty=1.0, identified=True)
    warm = appraisal.Intent(appraisal.WARM, "player", "You", "", fact)
    assert story_mod.justification({}, "me", warm, fact) is None
    assert story_mod.justification({"relationships": {"Someone": "friend"}}, "me", warm, fact) == "gratitude"
    death = dict(fact, kind="death")
    fight = appraisal.Intent(appraisal.FIGHT, "player", "You", "", death)
    assert story_mod.justification({"relationships": {"Someone": "friend"}}, "me", fight, death) is None
    assert story_mod.justification({"relationships": {"Someone": "brother"}}, "me", fight, death) == "vendetta"


def test_a_zero_scale_leaves_that_kind_ordinary(monkeypatch):
    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, "restitution")
    rising(story)
    monkeypatch.setitem(TUNING["justified_journeys"], "restitution", 0)
    assert story.materialisation_weight([actor_key(who)], 300) == 1
    assert story.resident_destination(who.properties["id"], ["a"], 100) is None


def test_a_reckoning_is_discharged_by_the_holders_own_blow():
    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, "reckoning")
    rising(story)
    assert story.materialisation_weight([actor_key(who)], 300) > 1
    director.bus.make("attack", actor=actor_key(who), target="player", hour=8)
    assert story.materialisation_weight([actor_key(who)], 300) == 1


def test_a_creditor_trip_heads_for_the_player_town_on_the_same_random_draws():
    story, director, hooks, store = setup()
    who, intent = holder_with(story, director, hooks, store, "restitution")
    hooks.town = "c"
    rising(story)
    b = board(story)
    b.resident_pool = [dict(id=who.properties["id"], name="Holder", display="Holder", home="a")]
    story._levers["market_chance"] = 1
    ordinary = board(story)
    ordinary.hooks.resident_destination = lambda *_args: None
    ordinary.resident_pool = copy.deepcopy(b.resident_pool)
    ordinary._resident_trips(8)
    before = intent.to_dict()
    b._resident_trips(8)
    trip = next(iter(b.journeys.values()))
    assert trip.dest == "c" and trip.route == b.network.route("a", "c")
    assert b.rng.getstate() == ordinary.rng.getstate()
    assert intent.to_dict() == before
    assert story.world_view()["vendettas"][actor_key(who)]["destination"] == "c"


def test_gratitude_visits_once_then_is_discharged_and_survives_resampling_and_reload():
    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, "gratitude")
    rising(story)
    key = actor_key(who)
    assert story.resident_destination(who.properties["id"], ["a", "b"], 100) == "a"
    story.tick(story.last_sample + TUNING["sample_hours"])
    # The trip's destination outlives the resample that rebuilds the view.
    assert story.world_view()["vendettas"][key]["destination"] == "a"
    journey = SimpleNamespace(id="j1", kind="market", dest="a", origin="b", legs=1, state="travel",
                              members=[dict(resident=who.properties["id"], display="Holder")],
                              cause=None, leader=lambda: dict(display="Holder"))
    story.record_journey(journey, 10, arrived=True)
    assert story.materialisation_weight([key], 300) == 1
    story.persist()
    loaded = story_mod.Storyteller(store, director, hooks)
    assert loaded.resident_destination(who.properties["id"], ["a", "b"], 100) is None


def test_pristine_ecology_leaves_every_justified_kind_inert():
    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, "reckoning")
    rising(story)
    story.set_enabled(False)
    assert story.materialisation_weight([actor_key(who)], 300) == 1
    assert story.resident_destination(who.properties["id"], ["a"], 100) is None


def test_arrival_lines_name_the_deed_and_never_the_speaker_themselves():
    assert "Bram" in chatter.justified_line("vendetta", "Bram", "Hester")
    thanks = chatter.justified_line("gratitude", "", "Hester")
    assert "me" in thanks and "Hester" not in thanks
    assert chatter.justified_line("unknown", "Bram") == ""
    # Stable: the same speaker says the same thing.
    assert chatter.justified_line("reckoning", "", "Hester") == chatter.justified_line("reckoning", "", "Hester")


def test_a_live_arrival_says_once_why_it_came_and_only_in_the_town_it_was_sent_to():
    from ..living.world import LivingWorld

    story, director, hooks, store = setup()
    who, _intent = holder_with(story, director, hooks, store, "restitution")
    rising(story)
    said = []
    living = LivingWorld(SimpleNamespace(storyteller=story, bark=lambda x, line, *a: said.append(line)))
    living.board = board(story)
    proxy = SimpleNamespace(properties=dict(_memory_identity="holder_uuid", name="Holder"), pos=[0, 0, 0])
    assert living._justified_line(proxy) == ""          # not sent anywhere yet
    assert story.resident_destination(who.properties["id"], ["a"], 100) == "a"
    elsewhere = SimpleNamespace(properties=dict(proxy.properties), pos=[2000, 0, 0])
    assert living._justified_line(elsewhere) == ""      # town b, not where it was sent
    living._say_why(proxy)
    living._say_why(proxy)
    assert len(said) == 1 and ("robbed" in said[0] or "took" in said[0])
