"""Mechanism pins: actors author causes; the sampler can only price choices."""

import copy
import json
from types import SimpleNamespace

import pytest

from .. import footprint, mental_state
from ..living import journeys
from ..living.world import LivingWorld, SessionHooks
from ..rpg import factions as teams
from ..sim import appraisal, knowledge, moods
from ..sim.director import Director
from ..sim.events import WorldEvent
from ..sim.factions import FactionSpine, STORE_KEY, VERSION, identity, ledger
from ..storyteller import Storyteller, TUNING
from .test_storyteller import Store, actor, board, setup


def fact(e=1, kind="death", **values):
    ev = WorldEvent(kind, actor="player", target="victim", event_id=e, pos=[2000, 0, 0],
                    data=dict(actor_faction="player", target_faction="villagers", crime=True))
    result = knowledge.fact_from_event(ev, 1, "witnessed")
    result.update(values)
    return result


def world(count=2, enabled=True):
    story, director, hooks, store = setup()
    director.ctx.hostile = teams.is_hostile
    session = SimpleNamespace(storyteller=story, director=director, store=store,
                              clock=SimpleNamespace(day=0, hour=8),
                              game=SimpleNamespace(character=SimpleNamespace(bounty=0, alignment=0)))
    living = LivingWorld(session, population=0)
    session.living = living
    b = board(story)
    b.population = 0
    b.hooks = SessionHooks(living)
    b.hooks.journey_levers = lambda: {}
    living.board, living.places = b, b.places
    cast = [actor(f"Guard {i}", id=f"guard{i}", type="npc", faction="villagers", npc_role="guard",
                  courage=0.6, combatant=True, health=100, max_health=100, damage=15,
                  _sim_tier=3) for i in range(count)]
    living._residents = {a.properties["id"]: a for a in cast}
    spine = FactionSpine(store, director, lambda: story.enabled and enabled)
    session.faction_spine = spine
    spine.bind(b, cast)
    director.mood_context = spine.mood
    director.ctx.goodwill = lambda a, other: spine.goodwill(a, other) if spine.enabled() else 0
    return session, living, spine, cast


def prepare_raid(count=2, **values):
    session, living, spine, cast = world(count)
    f = fact(**values)
    event = session.director.bus.make(f["kind"], actor=f["actor"], target=f["target"], pos=f["pos"],
                                      data={k: f[k] for k in ("actor_faction", "target_faction", "crime")})
    assert event.id == f["e"]
    knowledge.learn(session.store, identity(cast[0]), f)
    spine.decide(8)
    assert len(spine.pending()) == 1
    living.board._faction_departures(8)
    raid = next(j for j in living.board.journeys.values() if j.cause)
    return session, living, spine, cast, raid, f


@pytest.mark.parametrize("combatant,courage,reaction", [(True, 0.8, appraisal.FIGHT), (False, 0.8, appraisal.FLEE), (True, 0.1, appraisal.FLEE)])
def test_appraisal_branch_five_survives_faction_and_karma_snapshots(combatant, courage, reaction):
    store = Store()
    d = Director(store=store, hostile=teams.is_hostile)
    attacker = actor("Bandit", faction="bandits", alignment=-65)
    victim = actor("Stranger", faction="adventurers")
    observer = actor("Observer", faction="villagers", combatant=combatant, courage=courage)
    ev = d.emit("attack", attacker, victim, observers=[observer], crime=False)
    attacker.properties.update(faction="villagers", alignment=80)
    copied = knowledge.facts(store, identity(observer))[0]
    assert copied["actor_faction"] == "bandits" and copied["target_faction"] == "adventurers"
    assert copied["actor_alignment"] == -65
    assert knowledge.tell(store, identity(observer), "listener", copied)
    stored = Store()
    stored.d = dict(store.d)
    f = knowledge.facts(stored, "listener")[0]
    intent = appraisal.appraise(observer.properties, "listener", f, d.ctx)
    assert intent.reaction == reaction and intent.event_id == ev.id
    assert intent.target == identity(attacker)
    assert appraisal.appraise(observer.properties, "listener", dict(f, identified=False), d.ctx) is None
    assert appraisal.appraise(observer.properties, "listener", dict(f, actor_faction=""), d.ctx) is None


def test_goodwill_counts_crimes_rescues_and_trades_once_per_known_event():
    murder = fact()
    rescue = fact(2, "heal", crime=False)
    trade = fact(3, "trade", crime=False)
    accounts = [("eyewitness", [murder, rescue, trade]),
                ("gossip", [dict(murder, certainty=0.8), rescue, trade])]
    result = ledger("villagers", accounts)
    assert result["totals"] == {"player": -26.0}
    assert [(r["event"], r["amount"]) for r in result["receipts"]] == [(1, -40), (2, 12), (3, 2)]
    assert all(r["holder"] == "eyewitness" or r["holder"] == "gossip" for r in result["receipts"])
    # No history access, unidentified accusations, missing legacy factions, or
    # lawful deaths can create a debit. Forgetting really removes goodwill.
    assert ledger("villagers", [("w", [dict(murder, identified=False),
                                        dict(rescue, certainty=0.1),
                                        dict(trade, actor_faction="")])])["totals"] == {}
    assert ledger("villagers", [("w", [dict(murder, crime=False)])])["totals"] == {}
    assert ledger("villagers", []) == dict(totals={}, receipts=[])


def test_goodwill_is_directed_and_weights_the_strongest_account():
    f = fact(kind="attack", certainty=0.5)
    better = dict(f, certainty=0.8)
    assert ledger("villagers", [("a", [f]), ("b", [better])])["totals"] == {"player": -9.6}
    assert ledger("player", [("a", [f])])["totals"] == {}
    assert ledger("guards", [("a", [f])])["totals"] == {}


def test_faction_cannot_learn_unperceived_history_or_remote_members():
    s, living, spine, cast = world()
    s.director.bus.make("death", actor="player", target="secret", data={"actor_faction": "player"})
    spine.decide(8)
    assert not spine.pending() and not spine.ledgers[next(iter(spine.entities))]["receipts"]
    knowledge.learn(s.store, identity(cast[0]), fact())
    cast[0].pos = [2000, 0, 0]
    living.places["a"]["radius"] = 900
    spine.decide(9)
    assert not spine.pending()
    cast[0].pos = [0, 0, 0]
    spine.decide(10)
    assert spine.pending()[0]["cause"]["event"] == 1


def test_hostile_journey_has_faction_home_real_roster_cause_and_physical_return():
    s, living, spine, cast, raid, f = prepare_raid()
    b = living.board
    assert raid.kind == "faction_raid" and raid.faction == "villagers" and raid.hostile
    assert raid.origin == raid.home == "a" and raid.dest == "b" and raid.depart_t == 8
    assert raid.position_at(8) == (0, 0)
    assert raid.position_at(9)[0] == pytest.approx(90)
    assert raid.cause["fact"]["e"] == f["e"] and raid.cause["holder"] in spine.entities
    assert all(m["resident"] in living._residents for m in raid.members)
    assert all(a.properties["away_on_journey"] == raid.id for a in cast)
    assert knowledge.knows(s.store, raid.cause["holder"], 1)
    assert all(knowledge.knows(s.store, identity(a), 1) for a in cast)
    assert appraisal.appraise_all(dict(cast[0].properties, _faction_cause=raid.cause), identity(cast[0]),
                                 knowledge.facts(s.store, identity(cast[0])), s.director.ctx)[0].reaction == appraisal.FIGHT
    payload = raid.provenance()
    payload["fact"]["e"] = 999
    assert raid.cause["fact"]["e"] == 1
    # An order is discharged; sampling it again cannot duplicate the force.
    b._faction_departures(8)
    assert len(b.journeys) == 1
    arrival = raid.arrives_at()
    b.arrive(raid, arrival, [])
    b.next_leg(raid, raid.rest_until)
    assert raid.origin == "b" and raid.dest == raid.home and raid.position_at(raid.depart_t) == (2000, 0)
    b.arrive(raid, raid.arrives_at(), [])
    assert raid.state == "done"
    b._retire(raid)
    assert not b.residents_on_trips and not b.journeys
    assert all(not a.properties.get("away_on_journey") and not a.properties["hidden"] for a in cast)
    spine.decide(50)
    assert not spine.pending()


@pytest.mark.parametrize("invalid", ["home", "route", "identified", "force", "uncertain"])
def test_no_departure_without_home_route_identification_and_available_people(invalid, monkeypatch):
    s, living, spine, cast = world()
    f = fact()
    if invalid == "home":
        f["pos"] = [0, 0, 0]
    elif invalid == "route":
        monkeypatch.setattr(living.board, "_route", lambda *_: None)
    elif invalid == "identified":
        f["identified"] = False
    elif invalid == "force":
        for a in cast:
            a.properties["_sim_tier"] = 0
    else:
        f["certainty"] = 0.1
    knowledge.learn(s.store, identity(cast[0]), f)
    spine.decide(8)
    before_rng = living.board.rng.getstate()
    living.board._faction_departures(8)
    assert not living.board.journeys
    assert living.board.rng.getstate() == before_rng


def test_faction_can_hold_intent_against_another_faction_without_hunting_player():
    s, living, spine, cast, raid, _f = prepare_raid(actor="rival", actor_faction="adventurers")
    assert raid.cause["target"] == "rival" and raid.cause["target_faction"] == "adventurers"
    assert raid.faction == "villagers" and not raid.hostile
    assert spine.intents[raid.cause["entity"]][0]["reaction"] == appraisal.FIGHT


def test_survivor_outcomes_reenter_knowledge_only_when_someone_gets_home():
    s, living, spine, cast, raid, _f = prepare_raid()
    b = living.board
    enemy = b.plan("bandits", 8, origin="d", dest="b", members=[
        dict(name="raider", display="Raider", role="bandit", health=1000, damage=20, alive=True)])
    dead = raid.members[0]
    dead.update(alive=False, health=0)
    b.hooks.encounter_resolved(enemy, raid, 30, (1000, 0), [(raid, dead)])
    key = raid.cause["entity"]
    death = next(ev for ev in s.director.bus.history if ev.kind == "death" and ev.id > raid.cause["event"])
    assert death.day == 1 and death.hour == 6
    survivor_facts = knowledge.facts(s.store, identity(cast[1]))
    observed = next(f for f in survivor_facts if f["e"] == death.id)
    assert observed["kind"] == "death" and observed["actor_faction"] == "bandits"
    assert observed["target_faction"] == "villagers" and observed["day"] == 1 and observed["hour"] == 6
    assert observed["home"] == "a" and observed["journey"] == raid.id
    assert not knowledge.knows(s.store, key, death.id)
    spine.returned(raid)  # still abroad
    assert not knowledge.knows(s.store, key, death.id)
    raid.dest = raid.home
    spine.returned(raid)
    assert knowledge.knows(s.store, key, death.id)["from"] == identity(cast[1])
    assert not any(f["e"] == death.id for f in knowledge.facts(s.store, identity(cast[0])))
    spine.decide(50)
    attack = next(ev for ev in s.director.bus.history if ev.kind == "attack" and ev.id > raid.cause["event"])
    # Existing appraisal keeps the first equally urgent intent per offender;
    # both the witnessed blow and death are retained as knowledge receipts.
    assert any(i["event"] == attack.id and i["target"] == "raider" and i["reaction"] == appraisal.FIGHT
               for i in spine.intents[key])


def test_no_survivor_means_no_faction_testimony():
    s, living, spine, cast, raid, _f = prepare_raid()
    for m in raid.members:
        m.update(alive=False, health=0)
    before = knowledge.facts(s.store, raid.cause["entity"])
    raid.dest = raid.home
    spine.returned(raid)
    assert knowledge.facts(s.store, raid.cause["entity"]) == before


def test_footprint_wires_notoriety_to_hunters_and_prosperity_only_to_legal_bandit_weights():
    s, living, spine, cast = world()
    story, b = s.storyteller, living.board
    story.hooks.cast = cast
    story.hooks.player_wealth = lambda: 2000
    story.hooks.law = {"a": dict(bounty=200, phase="writ")}
    story.hooks.market_traffic = lambda: {"a": 4}
    knowledge.learn(s.store, identity(cast[0]), fact(kind="heal", crime=False))
    story.tick(8)
    fp = story.sensors["footprint"]
    assert fp["prosperity"] == 1 and fp["notoriety"] == 0.2 and fp["legend"] == 1
    assert story.levers["hunter_bounty"] == 150 * (1 - TUNING["notoriety_hunter_scale"] * 0.2)
    assert b.hooks.bandit_destination_weight("a") == 3
    assert 1 < b.hooks.bandit_destination_weight("d") < 3
    # Sampling uses the existing choices draw and the authored camps, never
    # introduces the player's town as a new legal bandit destination.
    sampled = []
    b.places["c"]["kind"] = "camp"
    original = b.rng.choices
    def choices(options, weights=None, **kwargs):
        sampled.append((list(options), list(weights)))
        return original(options, weights=weights, **kwargs)
    b.rng.choices = choices
    trip = b.plan("bandits", 20, origin="d")
    assert trip is not None and trip.dest == "c"
    assert sampled[0][0] == ["c"]
    assert sampled[0][1][0] == pytest.approx((1 / (1 + (2000 ** 2 + 2000 ** 2) ** 0.5 / 6000) ** 2)
                                          * b.hooks.bandit_destination_weight("c"))


def test_footprint_projects_existing_karma_without_authoring_deeds():
    f = fact(kind="heal", crime=False, actor_alignment=75)
    good = footprint.evaluate([("w", [f])], karma=80)
    evil = footprint.evaluate([("w", [f])], karma=-80)
    assert good["karma_tier"] == "Saintly" and evil["karma_tier"] == "Villainous"
    assert good["legend"] == evil["legend"] == 1  # same known deeds
    assert good["notoriety"] == evil["notoriety"] == 0
    assert footprint.evaluate(karma=-100)["receipts"] == []


def test_moods_are_deterministic_pure_and_use_existing_karma_and_appraisal():
    p = dict(faction="villagers", npc_role="guard", courage=0.5, combatant=True)
    threat = fact(kind="attack", actor_faction="bandits", crime=False, actor_alignment=0)
    original = copy.deepcopy((p, threat))
    rich = moods.evaluate(p, [threat], 1, -30)
    poor = moods.evaluate(p, [threat], 0, 0)
    assert rich["state"] == "defiant" and poor["state"] == "afraid"
    ctx = appraisal.Context(hostile=teams.is_hostile)
    assert appraisal.appraise_all(p, "observer", [threat], ctx, mood=rich)[0].reaction == appraisal.FIGHT
    assert appraisal.appraise_all(p, "observer", [threat], ctx, mood=poor)[0].reaction == appraisal.FLEE
    good = moods.evaluate(p, [dict(threat, actor_alignment=80)], 0.5, 0)
    evil = moods.evaluate(p, [dict(threat, actor_alignment=-80)], 0.5, 0)
    assert good["courage"] > evil["courage"]
    for _ in range(20):
        assert moods.evaluate(p, [threat], 1, -30) == rich
    assert (p, threat) == original and "alignment" not in p
    assert moods.evaluate(p, [dict(threat, identified=False, actor_alignment=-100)])["known_karma"] == 0


def test_sampling_and_mentions_never_write_facts_intents_or_consume_rng(monkeypatch):
    s, living, spine, cast, raid, _f = prepare_raid()
    def simulation_store():
        return {k: v for k, v in s.store.d.items() if k != TUNING["store_key"]}
    before = copy.deepcopy((simulation_store(), s.director._intents, s.director._dirty,
                            [a.properties for a in cast], spine.snapshot()))
    rng = living.board.rng.getstate()
    def forbidden(*_a, **_k):
        pytest.fail("A read-only projection tried to author simulation state")
    monkeypatch.setattr(knowledge, "learn", forbidden)
    monkeypatch.setattr(s.director, "intents", forbidden)
    monkeypatch.setattr(s.director.bus, "emit", forbidden)
    monkeypatch.setattr(s.director, "invalidate", forbidden)
    for _ in range(3):
        s.director.evaluate(cast[0])
        s.director.knowledge_lines(cast[0])
        mental_state._knowledge_sections(cast[0], s)
        spine.pending()
        spine.goodwill("villagers", "player")
        living.board.hooks.resident_can_leave("guard0")
        living.board.hooks.faction_orders()
        s.storyteller.tick(9)
        s.storyteller.bandit_destination_weight(2000)
    assert (simulation_store(), s.director._intents, s.director._dirty,
            [a.properties for a in cast], spine.snapshot()) == before
    assert living.board.rng.getstate() == rng


def test_faction_and_storyteller_snapshots_restore_exactly_and_reject_other_versions(monkeypatch):
    s, living, spine, cast, raid, _f = prepare_raid()
    s.storyteller.hooks.player_wealth = lambda: 1000
    s.storyteller.tick(8)
    s.storyteller.persist()
    spine.persist()
    snapshot = spine.snapshot()
    raw_board = living.board.to_json()
    saved_story = s.store.get(TUNING["store_key"])
    restored = FactionSpine(s.store, s.director)
    assert restored.snapshot() == snapshot
    restored.bind(living.board, cast)
    assert restored.snapshot() == snapshot
    twin = board(s.storyteller)
    assert twin.load_json(raw_board) and twin.to_json() == raw_board
    assert twin.journeys[raid.id].cause == raid.cause
    weight = s.storyteller.bandit_destination_weight(2000)
    monkeypatch.setitem(TUNING, "prosperity_bandit_bias", 999)
    loaded_story = Storyteller(s.store, s.director, s.storyteller.hooks)
    loaded_story.persist()
    assert loaded_story.bandit_destination_weight(2000) == weight
    assert json.loads(s.store.get(TUNING["store_key"])) == json.loads(saved_story)
    assert json.loads(saved_story)["version"] == 3
    s.store.set(STORE_KEY, json.dumps(dict(snapshot, version=VERSION + 1)))
    assert not restored.restore() and not restored.entities and not restored.intents
    s.store.set(TUNING["store_key"], json.dumps(dict(json.loads(saved_story), version=2)))
    assert not loaded_story.restore() and loaded_story.state == "CALM"


def test_pristine_day_keeps_faction_journeys_moods_board_bytes_and_rng_authored(monkeypatch):
    s, living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact())
    spine.decide(8)  # a real pending order is present when pristine is selected
    assert spine.pending()
    monkeypatch.setitem(TUNING, "enabled", False)
    b = living.board
    control = board(s.storyteller)
    b.population = control.population = 26
    control.hooks = journeys.WorldHooks()
    def forbidden(*_a, **_k):
        pytest.fail("Pristine ecology queried a faction or mood sensor")
    monkeypatch.setattr(spine, "accounts", forbidden)
    monkeypatch.setattr(moods, "evaluate", forbidden)
    for name in ("market_traffic", "player_wealth", "player_karma", "actors"):
        monkeypatch.setattr(s.storyteller.hooks, name, forbidden)
    original = copy.deepcopy((s.store.d, spine.snapshot(), [a.properties for a in cast]))
    b.seed(0)
    control.seed(0)
    for step in range(97):
        t = step / 4
        s.storyteller.tick(t)
        spine.decide(t)
        assert spine.pending() == [] and spine.mood(cast[0], []) is None
        assert b.update(t) == control.update(t)
        assert b.to_json() == control.to_json(), f"Pristine board diverged at hour {t}"
        assert b.rng.getstate() == control.rng.getstate()
        assert b.hooks.bandit_destination_weight("a") == 1
    assert (s.store.d, spine.snapshot(), [a.properties for a in cast]) == original


def test_forgetting_the_cause_cancels_a_cached_order_without_new_appraisal():
    s, living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact())
    spine.decide(8)
    assert spine.pending()
    knowledge.forget_all(s.store, next(iter(spine.entities)))
    cached = copy.deepcopy(spine.intents)
    before = living.board.rng.getstate()
    living.board._faction_departures(8)
    assert not living.board.journeys and not spine.pending()
    assert spine.intents == cached and living.board.rng.getstate() == before


def test_streamer_materialises_faction_force_only_at_its_natural_board_position(monkeypatch):
    s, living, spine, cast, raid, _f = prepare_raid()
    s.logic = None
    s._player_pos = lambda: [2000, 0, 0]
    living.reach = lambda: 210
    spawned = []
    def spawn(j, t):
        spawned.append(j.position_at(t))
        j.live = True
        living.live[j.id] = {"things": []}
    monkeypatch.setattr(living, "_spawn", spawn)
    living._stream()
    assert not spawned and not raid.live
    # Twenty game hours of travel, not a staging teleport, brings it in range.
    s.clock.day, s.clock.hour = 1, 4
    living._stream()
    assert spawned == [(1800, 0)] and raid.live
    receipt = s.storyteller.world_view()["receipts"][0]
    assert receipt["events"] == [1] and receipt["provenance"] == raid.cause
    assert "faction_villagers_a" in receipt["reason"]


def test_actual_board_clash_writes_only_real_survivor_outcomes(monkeypatch):
    s, living, spine, cast, raid, _f = prepare_raid(3)
    b = living.board
    enemy = b.plan("bandits", 8, origin="d", dest="b", members=[dict(
        name="enemy", display="Enemy", role="bandit", health=10000, damage=200, alive=True)])
    # Winner draw, three casualty draws, then survivor wound draws. This pins
    # the board's real outcome path, including one witness who returns alive.
    draws = iter([0.0, 0.1, 0.9, 0.1])
    monkeypatch.setattr(b.rng, "random", lambda: next(draws, 0.5))
    monkeypatch.setattr(b.rng, "uniform", lambda lo, hi: (lo + hi) / 2)
    b._clash(enemy, raid, 30, (1000, 0), [])
    assert len(raid.alive()) == 1
    dead = [e for e in s.director.bus.history if e.kind == "death" and e.id > raid.cause["event"]]
    assert len(dead) == 2
    survivor = next(a for a in cast if any(m["resident"] == a.properties["id"] for m in raid.alive()))
    assert all(knowledge.knows(s.store, identity(survivor), e.id) for e in dead)
    assert all(not knowledge.knows(s.store, raid.cause["entity"], e.id) for e in dead)
    raid.dest = raid.home
    spine.returned(raid)
    assert all(knowledge.knows(s.store, raid.cause["entity"], e.id) for e in dead)


def test_session_footprint_hooks_project_real_inventory_traffic_and_karma_without_mutation():
    from ..storyteller_session import SessionStorytellerHooks
    from ..rpg.character import Character
    from ..rpg import items
    s, living, spine, cast = world()
    c = Character()
    c.alignment, c.gold = -80, 100
    c.inventory = [items.make("bread", 2)]
    s.game.character = c
    living.board.plan("trader", 8, origin="a", dest="b")
    hooks = SessionStorytellerHooks(s)
    before = copy.deepcopy((c.to_dict(), living.board.to_json(), s.store.d))
    assert hooks.player_karma() == -80
    assert hooks.player_wealth() == 100 + items.get("bread").value * 2
    assert hooks.market_traffic() == {"a": 1, "b": 1}
    assert (c.to_dict(), living.board.to_json(), s.store.d) == before


def test_faction_departure_restores_and_continues_with_identical_board_and_rng():
    s, living, spine, cast, raid, _f = prepare_raid()
    spine.persist()
    snapshot = spine.snapshot()
    b = living.board
    raw = b.to_json()
    saved_rng = b.rng.getstate()
    loaded_spine = FactionSpine(s.store, s.director)
    twin = board(s.storyteller)
    twin.population = 0
    twin.hooks = journeys.WorldHooks()
    # Both paths retain their already-dispatched actor action. Further hooks
    # are inert to isolate exact journey continuation from any fresh decisions.
    b.hooks = journeys.WorldHooks()
    assert twin.load_json(raw)
    twin.rng.setstate(saved_rng)
    for t in range(9, 65):
        assert b.update(t) == twin.update(t)
        assert b.to_json() == twin.to_json()
        assert b.rng.getstate() == twin.rng.getstate()
    assert loaded_spine.snapshot() == snapshot


def test_live_faction_intent_needs_actual_sight_and_never_tracks_an_unseen_target():
    s, living, spine, cast, raid, _f = prepare_raid()
    proxy = SimpleNamespace(properties=dict(cast[0].properties, _faction_cause=raid.cause), pos=[0, 0, 0])
    player = actor("You", faction="player", is_player=True)
    player.pos = [2000, 0, 0]
    s._sim_actor_by_key = lambda key: player if key == "player" else None
    s._nearest_hostile = lambda *_a: None
    s._law_visible = lambda *_a: False
    engaged = []
    s._apply_sim_intent = lambda x: engaged.append(x) or True
    assert not living._react(raid, proxy, player.pos) and not engaged
    player.pos = [500, 0, 0]
    assert not living._react(raid, proxy, player.pos) and not engaged
    s._law_visible = lambda *_a: True
    assert living._react(raid, proxy, player.pos) and engaged == [proxy]


def test_a_remembered_trail_can_justify_departure_after_an_offence_at_home():
    s, living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact(pos=[0, 0, 0]))
    spine.decide(8)
    assert not spine.pending()
    trail = fact(2, "trade", crime=False, hour=9, pos=[2000, 0, 0])
    knowledge.learn(s.store, identity(cast[0]), trail)
    spine.decide(9)
    order = spine.pending()[0]
    assert order["origin"] == "a" and order["dest"] == "b"
    assert order["cause"]["event"] == 1 and order["cause"]["trail"]["e"] == 2
    # The price includes the known trade, rather than silently ignoring mercy
    # or commerce just because a prior crime already produced a grievance.
    assert spine.ledgers[order["cause"]["entity"]]["totals"] == {"player": -38}
    knowledge.forget_all(s.store, order["cause"]["holder"])
    assert not spine.pending()


def test_unidentified_rumours_cannot_supply_a_faction_destination():
    s, living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact(pos=[0, 0, 0]))
    knowledge.learn(s.store, identity(cast[0]), fact(2, "talk", hour=9, pos=[2000, 0, 0], identified=False))
    spine.decide(9)
    assert not spine.pending()


def test_saving_a_live_faction_force_preserves_current_wounds_possessions_and_karma():
    s, living, spine, cast, raid, _f = prepare_raid(1)
    s.rng = living.board.rng
    proxy = SimpleNamespace(properties=dict(_member=0, health=37, inventory=[dict(id="bread", qty=1)],
                                           equipped_weapon="iron_dagger", alignment=-17), pos=[90, 0, 0])
    living.live[raid.id] = dict(things=[proxy])
    living.persist()
    restored = board(s.storyteller)
    assert restored.load_json(s.store.get("living.board"))
    saved = restored.journeys[raid.id]
    assert saved.members[0]["health"] == 37
    assert saved.members[0]["inventory"] == [dict(id="bread", qty=1)]
    props = living._actor_props(saved, saved.members[0], 0)
    assert props["inventory"] == proxy.properties["inventory"]
    assert props["equipped_weapon"] == "iron_dagger" and props["alignment"] == -17
    assert props["_memory_identity"] == cast[0].properties["id"]
