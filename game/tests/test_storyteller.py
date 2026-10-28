"""Headless mechanism tests for the sampler and its real lever consumers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

import pytest

from .. import mental_state
from ..living import journeys, roads
from ..sim import appraisal, crime, knowledge
from ..sim.director import Director, actor_key
from ..sim.law import Writs
from ..storyteller import Storyteller, StorytellerHooks, TUNING
from ..storyteller_session import SessionStorytellerHooks


class Store:
    def __init__(self):
        self.d = {}

    def get(self, key, default="false"):
        return self.d.get(str(key), default)

    def set(self, key, value):
        self.d[str(key)] = str(value)


def actor(name="Witness", town="a", **props):
    return SimpleNamespace(properties=dict(name=name, town=town, **props), pos=[0, 0, 0])


class Hooks(StorytellerHooks):
    def __init__(self):
        self.cast = []
        self.health = 1.0
        self.town = "a"
        self.hostiles = {}
        self.law = {}
        self.region = (0, 0, 2000)
        self.arrivals = (None, 0)

    def actors(self):
        return self.cast

    def actor_town(self, actor):
        return actor.properties["town"]

    def player_town(self):
        return self.town

    def player_health_fraction(self):
        return self.health

    def hostile_counts_by_tier(self):
        return self.hostiles

    def law_pressure(self):
        return self.law

    def player_region(self):
        return self.region

    def hostile_materialisations(self):
        return self.arrivals


def setup():
    store, hooks = Store(), Hooks()
    director = Director(store=store, rng=random.Random(7))
    return Storyteller(store, director, hooks), director, hooks, store


def remember(store, bus, holder, kind="theft", **kwargs):
    ev = bus.make(kind, actor="player", target="victim", day=0, hour=0, **kwargs)
    fact = knowledge.fact_from_event(ev, 1.0, knowledge.SOURCE_WITNESSED)
    knowledge.learn(store, actor_key(holder), fact)
    return ev, fact


def rising(story):
    story.tick(0)
    story.tick(TUNING["states"]["CALM"]["max_hours"])
    assert story.state == "RISING"


class BoardHooks(journeys.WorldHooks):
    def __init__(self, story):
        self.story = story
        self.bounty = 0

    def journey_levers(self):
        return self.story.board_levers()

    def destination_weight(self, place):
        return self.story.destination_weight(place)

    def player_bounty(self):
        return self.bounty

    def player_place(self):
        return "a"

    def resident_can_leave(self, resident_id):
        return True

    def resident_destination(self, resident_id, towns, origin):
        return self.story.resident_destination(resident_id, towns, self.trip_distance)

    trip_distance = 2000

    def journey_weight(self, kind, position, hostile):
        return self.story.journey_weight(kind, position, hostile)

    def journey_sampled(self, journey, t, *, arrived=False, destination_sampled=False):
        self.story.record_journey(journey, t, arrived=arrived, destination_sampled=destination_sampled)


def board(story, seed=17):
    places = {"a": dict(x=0, z=0, kind="town"),
              "b": dict(x=2000, z=0, kind="town"),
              "c": dict(x=-2000, z=0, kind="town"),
              "d": dict(x=0, z=2000, kind="danger"),
              "e": dict(x=0, z=-2000, kind="hamlet")}
    net = roads.RoadNetwork.build([], [(k, p["x"], p["z"]) for k, p in places.items()])
    return journeys.JourneyBoard(net, places, 1, rng=random.Random(seed), hooks=BoardHooks(story))


def vendetta(story, director, hooks, store):
    kin = actor("Kin", id="kin_uuid", relationships={"Victim": "sister"}, combatant=True)
    hooks.cast.append(kin)
    _ev, fact = remember(store, director.bus, kin, "death", target_name="Victim")
    intent = appraisal.Intent(appraisal.FIGHT, "player", "You",
                              "You killed Victim, my sister", fact)
    director._intents[actor_key(kin)] = [intent]
    return kin, intent


def test_module_imports_and_runs_without_engine_qt_or_third_party_packages():
    # The application's game/__init__ boots the GUI. Load this module under a
    # namespace package, as for game.sim, to verify its own import boundary.
    root = str(Path(__file__).resolve().parents[1])
    script = f"""
import importlib.abc, sys, types
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('engine', 'PyQt5', 'OpenGL', 'numpy', 'glm'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
pkg = types.ModuleType('game')
pkg.__path__ = [{root!r}]
sys.modules['game'] = pkg
from game.storyteller import Storyteller
s = Storyteller()
s.tick(0)
s.tick(8)
assert s.state == 'RISING'
"""
    result = subprocess.run([sys.executable, "-S", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_sampler_never_emits_writes_knowledge_or_changes_intents(monkeypatch):
    story, director, hooks, store = setup()
    kin, intent = vendetta(story, director, hooks, store)
    uninspected = actor("Uninspected")
    hooks.cast.append(uninspected)
    original_store = dict(store.d)
    original_events = [ev.to_dict() for ev in director.bus.history]
    original_props = copy.deepcopy(kin.properties)
    untouched = copy.deepcopy(uninspected.properties)
    original_intent = copy.deepcopy(intent.to_dict())
    original_cache = director._intents.copy()

    def forbidden(*args, **kwargs):
        pytest.fail("A sampler tried to author simulation state")

    for name in ("emit", "make", "subscribe"):
        monkeypatch.setattr(director.bus, name, forbidden)
    for name in ("learn", "_write"):
        monkeypatch.setattr(knowledge, name, forbidden)
    monkeypatch.setattr(director, "intents", forbidden)
    monkeypatch.setattr(director, "invalidate", forbidden)
    rising(story)
    story.destination_weight("a")
    story.materialisation_weight([actor_key(kin)], 300)
    story.resident_destination(kin.properties["id"], ["a", "b"], 300)
    story.journey_weight("wolves", (0, 0), True)
    story.edit_lever("RISING", ("population",), 28)
    story.persist()
    assert {k: v for k, v in store.d.items() if k != TUNING["store_key"]} == original_store
    assert [ev.to_dict() for ev in director.bus.history] == original_events
    assert kin.properties == original_props
    assert uninspected.properties == untouched
    assert director._intents == original_cache
    assert director._intents[actor_key(kin)][0] is intent
    assert intent.to_dict() == original_intent


def test_unperceived_crimes_cannot_affect_any_decision():
    a, da, ha, _sa = setup()
    b, db, hb, _sb = setup()
    for i in range(10):
        db.bus.make("death", actor="player", target=f"secret{i}", pos=[99999, 0, 99999])
    for t in (0, 3, 4, 8):
        a.tick(t)
        b.tick(t)
        assert a.sensors == b.sensors
        assert a.state == b.state
        assert a.levers == b.levers
        assert a.inspector_rows() == b.inspector_rows()
    assert b.destination_weight("a") == 1


def test_loose_threads_require_living_holders_and_follow_the_holder_not_event_location():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    ev, _fact = remember(store, director.bus, witness, pos=[99999, 0, 99999])
    story.tick(0)
    assert story.sensors["loose_threads"] == 1
    assert story.destination_weight("b") > story.destination_weight("a")
    witness.properties["town"] = "c"
    story.tick(1)
    assert story.destination_weight("b") == 1
    assert story.destination_weight("c") > 1
    crime.mark_reported(store, ev.id)
    story.tick(2)
    assert story.sensors["loose_threads"] == 0
    assert story.destination_weight("c") == 1
    witness.properties["dead"] = True
    remember(store, director.bus, witness)
    story.tick(3)
    assert story.sensors["loose_threads"] == 0


def test_player_memory_alone_does_not_create_a_town_thread():
    story, director, hooks, store = setup()
    player = actor("You", is_player=True)
    hooks.cast = [player]
    remember(store, director.bus, player)
    story.tick(0)
    assert story.sensors["loose_threads"] == 0


def test_unperceived_events_cannot_erase_a_thread_by_rolling_the_history_tail():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    remember(store, director.bus, witness)
    story.tick(0)
    before = story.destination_weight("b")
    for i in range(500):
        director.bus.make("theft", actor="unseen", target=f"unseen{i}")
    story.tick(1)
    assert story.sensors["loose_threads"] == 1
    assert story.destination_weight("b") == before


def test_tension_uses_only_recent_events_targeting_player_and_relevant_hostiles():
    story, director, hooks, _store = setup()
    director.bus.make("attack", actor="bandit", target="player", day=0, hour=10)
    director.bus.make("death", actor="player", target="bandit", day=0, hour=10)
    director.bus.make("death", actor="bandit", target="player", day=0, hour=1)
    director.bus.make("death", target="player", day=1, hour=0)  # future
    hooks.hostiles = {0: 2, 1: 1, 2: 100, 3: 100}
    hooks.health = 0.8
    story.tick(11)
    assert story.sensors["attacks"] == 1
    assert story.sensors["deaths"] == 0
    assert story.sensors["hostiles"] == 3
    assert story.sensors["tension"] == pytest.approx(0.2 + 0.18 + 3 * 0.08)


@pytest.mark.parametrize("sensor", ["thread", "vendetta", "bounty", "phase"])
def test_existing_pressure_can_start_rising_after_the_minimum_quiet_time(sensor):
    story, director, hooks, store = setup()
    if sensor == "thread":
        witness = actor()
        hooks.cast = [witness]
        remember(store, director.bus, witness)
    elif sensor == "vendetta":
        vendetta(story, director, hooks, store)
    elif sensor == "bounty":
        hooks.law = {"region": dict(bounty=200, phase="writ")}
    else:
        hooks.law = {"region": dict(bounty=0, phase="search")}
    story.tick(0)
    story.tick(2)
    assert story.state == "CALM"
    story.tick(3)
    assert story.state == "RISING"


def test_four_state_cycle_minimum_dwell_and_recovery_gate():
    story, _director, hooks, _store = setup()
    rising(story)
    story.tick(9)
    assert story.state == "RISING"
    story.tick(14)
    assert story.state == "PEAK"
    hooks.health = 0.2
    story.tick(14.25)
    assert story.state == "RESPITE"
    story.tick(100)
    assert story.state == "RESPITE"  # recovery cannot time out while wounded
    hooks.health = 1.0
    story.tick(101)
    assert story.state == "CALM"


def test_samples_use_game_time_and_do_not_advance_on_same_tick_or_backward_time():
    story, _director, hooks, store = setup()
    story.tick(0)
    saved = store.d[TUNING["store_key"]]
    hooks.health = 0.1
    story.tick(0.1)
    story.tick(-100)
    assert store.d[TUNING["store_key"]] == saved
    story.tick(0.25)
    assert story.sensors["health"] == 0.1


@pytest.mark.parametrize("condition", ["healthy_town", "wounded", "wilderness", "distant",
                                        "changed_intent", "forgotten", "dirty", "non_kin", "discharged"])
def test_vendetta_bonus_requires_a_current_known_justified_undischarged_fight(condition):
    story, director, hooks, store = setup()
    kin, intent = vendetta(story, director, hooks, store)
    rising(story)
    distance = 300
    if condition == "wounded":
        hooks.health = 0.5
    elif condition == "wilderness":
        hooks.town = None
    elif condition == "distant":
        distance = 5000
    elif condition == "changed_intent":
        intent.reaction = appraisal.MOURN
    elif condition == "forgotten":
        store.set(f"npc.{actor_key(kin)}.facts", "[]")
    elif condition == "dirty":
        director._dirty.add(actor_key(kin))
    elif condition == "non_kin":
        kin.properties["relationships"] = {"Victim": "friend"}
    elif condition == "discharged":
        director.bus.make("attack", actor=actor_key(kin), target="player", hour=8)
    weight = story.materialisation_weight([actor_key(kin)], distance)
    assert (weight > 1) == (condition == "healthy_town")
    assert dict(story.inspector_rows())["Vendetta staging"]


def test_discharged_vendettas_stay_discharged_after_event_history_rolls_off_and_reload():
    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    rising(story)
    director.bus.make("attack", actor=actor_key(kin), target="player", hour=8)
    assert story.materialisation_weight([actor_key(kin)], 100) == 1
    story.persist()
    director.bus.clear()
    loaded = Storyteller(store, director, hooks)
    assert loaded.materialisation_weight([actor_key(kin)], 100) == 1


@pytest.mark.parametrize("state", list(TUNING["states"]))
def test_kv_round_trip_restores_timers_and_exact_levers_even_after_retuning(state, monkeypatch):
    story, director, hooks, store = setup()
    data = dict(version=TUNING["version"], state=state, entered_at=7.5, last_sample=9,
                levers=copy.deepcopy(TUNING["states"][state]["levers"]),
                sensors={}, threads={}, reasons={"Saved": "A saved reason."})
    store.set(TUNING["store_key"], json.dumps(data))
    assert story.restore()
    before = story.levers
    detached = story.levers
    detached["kind_weights"]["trader"] = 999
    assert story.levers == before
    story.persist()
    monkeypatch.setitem(TUNING["states"][state]["levers"], "population", 999)
    loaded = Storyteller(store, director, hooks)
    assert loaded.state == state
    assert loaded.entered_at == 7.5
    assert loaded.last_sample == 9
    assert loaded.levers == before
    assert loaded.inspector_rows() == story.inspector_rows()


def test_every_sampling_decision_has_a_reason_next_to_inspector_intents():
    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    rising(story)
    story.destination_weight("a")
    story.materialisation_weight([actor_key(kin)], 100)
    rows = dict(story.inspector_rows())
    assert all(isinstance(reason, str) and len(reason) > 10 for reason in rows.values())
    assert "RISING" in rows["Pacing"]
    assert "health" in rows["State decision"]
    sections = dict(mental_state._knowledge_sections(kin, SimpleNamespace(director=director, storyteller=story)))
    assert "Intents (ranked)" in sections
    assert sections["Storyteller decisions"] == story.inspector_rows()


def test_reseeded_rng_repeats_state_and_real_board_choices_after_restore():
    story, director, hooks, store = setup()
    rising(story)
    witness = actor(town="b")
    hooks.cast.append(witness)
    remember(store, director.bus, witness)
    story.tick(9)
    story.persist()
    loaded = Storyteller(store, director, hooks)
    a, b = board(story), board(loaded)
    for t in (9.25, 10, 11, 12, 20):
        story.tick(t)
        loaded.tick(t)
        a.update(t)
        b.update(t)
        assert a.to_json() == b.to_json()
        assert story.state == loaded.state
        assert story.levers == loaded.levers


def test_night_windows_and_hostile_weights_reach_the_actual_board():
    story, _director, _hooks, _store = setup()
    before = copy.deepcopy(journeys.KINDS)
    rising(story)
    b = board(story)
    assert b._lever("kind_weights", {})["bandits"] > journeys.KINDS["bandits"]["weight"]
    assert {b._pick_kind(12) for _ in range(100)}.isdisjoint({"bandits", "wolves", "greenskins"})
    assert "bandits" in {b._pick_kind(23) for _ in range(100)}
    assert "bandits" in {b._pick_kind(2) for _ in range(100)}
    assert not b._in_hours(6, b._hours("bandits"))
    assert journeys.KINDS == before


def test_destination_bias_changes_the_real_destination_sampling_without_removing_options():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    remember(store, director.bus, witness)
    rising(story)
    b = board(story)
    counts = {town: 0 for town in ("b", "c", "e")}
    for _ in range(300):
        j = b.plan("trader", 8, origin="a")
        counts[j.dest] += 1
    assert counts["b"] > counts["c"] * 2
    assert all(n > 0 for n in counts.values())


def test_population_and_hunter_threshold_are_instance_scoped_and_consume_actual_levers():
    story, _director, _hooks, _store = setup()
    rising(story)
    b = board(story)
    b.bounty_news = "known"
    b.heard["a"] = ["known"]
    b.hooks.bounty = 130
    assert b.hooks.bounty < journeys.HUNTER_BOUNTY
    for _ in range(10):
        b._departures(23)
    assert any(j.kind == "hunters" for j in b.journeys.values())
    active = [j for j in b.journeys.values() if j.kind != "market"]
    assert len(active) == story.levers["population"]
    assert b.population == 26


def test_market_frequency_and_lair_delay_use_the_saved_levers():
    from ..map_memory import MapMemory, RESPAWN_HOURS, RESPAWN_JITTER

    story, _director, _hooks, store = setup()
    b = board(story)
    b.resident_pool = [dict(id="resident", name="Resident", display="Resident", home="a")]
    # Extreme values isolate the probability gate rather than a whole scene.
    story.persist()
    data = json.loads(store.get(TUNING["store_key"]))
    data["levers"]["market_chance"] = 0
    data["levers"]["lair_refill_scale"] = 2
    store.set(TUNING["store_key"], json.dumps(data))
    story.restore()
    b._resident_trips(8)
    assert not b.residents_on_trips
    data["levers"]["market_chance"] = 1
    store.set(TUNING["store_key"], json.dumps(data))
    story.restore()
    b._resident_trips(8)
    assert b.residents_on_trips
    mem = MapMemory(SimpleNamespace(storyteller=story))
    expected = RESPAWN_HOURS + RESPAWN_JITTER * (sum(map(ord, "lair")) % 97) / 96
    assert mem._delay("lair") == expected * 2
    mem.record["dead"]["lair"] = dict(t=0, d=mem._delay("lair"), r=True)
    rising(story)
    assert mem.record["dead"]["lair"]["d"] == expected * 2


def test_session_sensor_reads_law_without_mutation_and_counts_only_visible_hostiles():
    from ..world_index import WorldIndex

    store = Store()
    law = Writs(store)
    law.charge("a", 1, 200, 0)
    before = copy.deepcopy(law.regions)
    hostile = actor("Hostile", aggression="hostile")
    hidden = actor("Hidden", aggression="hostile", hidden=True)
    distant = actor("Distant", aggression="hostile", _sim_tier=2)
    neutral = actor("Neutral")
    blocked = actor("Blocked", aggression="hostile")
    index = WorldIndex()
    index.rebuild([hostile, hidden, distant, neutral, blocked])
    session = SimpleNamespace(
        world_index=index, law=law, player_actor=actor("Player"),
        _natively_hostile=lambda p: p.get("aggression") == "hostile",
        _tier_of=lambda a: a.properties.get("_sim_tier", 0),
        _law_visible=lambda _observer, pos: pos is not blocked.pos)
    hooks = SessionStorytellerHooks(session)
    assert hooks.hostile_counts_by_tier() == {0: 1}
    assert hooks.law_pressure() == {"a": dict(bounty=200, phase="writ")}
    assert law.regions == before
    assert index.counts_by_tier() == {0: 4, 2: 1}


@pytest.mark.parametrize("healthy_in_town", [True, False])
def test_stream_prioritises_a_natural_nearby_vendetta_without_moving_or_creating_anyone(monkeypatch, healthy_in_town):
    from ..living import world

    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    rising(story)
    if not healthy_in_town:
        hooks.health = 0.4
    b = board(story)
    b.hooks.materialisation_weight = story.materialisation_weight
    ordinary = b.plan("trader", 0, origin="a", dest="b")
    avenger = b.plan("trader", 0, origin="a", dest="b",
                     members=[dict(name="Kin", id=actor_key(kin), role="merchant", alive=True)])
    ordinary.set_progress(300, 0)
    avenger.set_progress(600, 0)
    before = b.to_json()
    session = SimpleNamespace(clock=SimpleNamespace(day=0, hour=0), _player_pos=lambda: [0, 0, 0])
    living = world.LivingWorld(session)
    living.board = b
    living.places = b.places
    living.reach = lambda: 2000
    spawned = []

    def spawn(j, t):
        spawned.append((j.id, j.position_at(t)))
        living.live[j.id] = {"things": []}

    living._spawn = spawn
    monkeypatch.setattr(world, "MAX_LIVE", 1)
    living._stream()
    expected = avenger if healthy_in_town else ordinary
    assert spawned == [(expected.id, expected.position_at(0))]
    assert b.to_json() == before


def test_real_session_persists_and_restores_storyteller_with_the_same_save_store():
    from ..runtime import MiniwindSession
    from .test_sim import _FakeGlobals, _FakeLogic, _player

    globals_store = _FakeGlobals()
    session = MiniwindSession(_FakeLogic([], _player()), globals_store=globals_store)
    rising(session.storyteller)
    session.persist(force=True)
    expected = session.storyteller.levers
    snapshot = session.store.get(TUNING["store_key"])
    session.storyteller.reset()
    session.restore()
    assert session.storyteller.state == "RISING"
    assert session.storyteller.levers == expected
    assert session.store.get(TUNING["store_key"]) == snapshot
    fresh = MiniwindSession(_FakeLogic([], _player()), globals_store=globals_store)
    assert fresh.storyteller.state == "RISING"
    assert fresh.storyteller.levers == expected


@pytest.mark.parametrize("raw", ["false", "[]", "{", '{"version": 99}',
                                 '{"version": 1, "state": "PEAK", "levers": {}}'])
def test_legacy_or_invalid_saved_state_starts_quietly(raw):
    store = Store()
    store.set(TUNING["store_key"], raw)
    story = Storyteller(store)
    assert story.state == "CALM"
    assert story.levers == TUNING["states"]["CALM"]["levers"]


def test_resident_materialises_with_the_identity_that_holds_the_kin_fact():
    from ..living.world import LivingWorld

    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    session = SimpleNamespace(rng=random.Random(7), game=SimpleNamespace(character=SimpleNamespace(head="")))
    living = LivingWorld(session)
    living._residents[kin.properties["id"]] = kin
    living._tree = lambda *_args: {}
    b = board(story)
    living.board = b
    member = dict(name="Kin", display="Kin", role="merchant", alive=True,
                  resident=kin.properties["id"])
    j = b.plan("market", 0, origin="a", dest="b", members=[member])
    props = living._actor_props(j, member, 0)
    props["id"] = "proxy_uuid"       # the scene and save overlay identity
    assert props["id"] != kin.properties["id"]
    assert actor_key(SimpleNamespace(properties=props)) == actor_key(kin)


def test_many_destination_decisions_keep_the_current_pacing_reason_visible():
    story, _director, _hooks, _store = setup()
    story.tick(0)
    for i in range(100):
        story.destination_weight(f"town_{i}")
    rows = dict(story.inspector_rows())
    assert len(rows) <= TUNING["reason_cap"]
    assert "Pacing" in rows
    assert "State decision" in rows


def test_small_cast_sensor_does_not_read_a_stale_disabled_session_index():
    from ..runtime import MiniwindSession
    from .test_sim import _FakeGlobals, _FakeLogic, _Thing, _player

    hostile = _Thing("Hostile", type="creature", aggression="hostile", faction="monsters")
    session = MiniwindSession(_FakeLogic([hostile], _player()), globals_store=_FakeGlobals())
    assert not session._wi_live
    assert session.world_index.counts_by_tier() == {}
    session.storyteller.tick(0)
    assert session.storyteller.sensors["hostiles"] == 1
    assert session.world_index.counts_by_tier() == {}


def test_observations_keep_last_ten_real_samples_and_repeat_unchanged_inputs():
    story, _director, hooks, _store = setup()
    for i in range(15):
        story.tick(i * TUNING["sample_hours"])
    observations = story.observations
    assert len(observations) == 10
    assert [o["time"] for o in observations] == [i * TUNING["sample_hours"] for i in range(14, 4, -1)]
    assert all(o["sensors"]["health"] == 1 and o["reason"] for o in observations)
    # Reads are detached; skipped/backward ticks and lever queries aren't samples.
    observations[0]["sensors"]["health"] = 0
    assert story.observations[0]["sensors"]["health"] == 1
    original = story.observations
    hooks.health = 0.2
    story.tick(story.last_sample)
    story.tick(-1)
    story.destination_weight("a")
    assert story.observations == original


def test_observations_round_trip_and_legacy_saves_start_without_fabricated_history():
    story, director, hooks, store = setup()
    for t in (0, 1, 2):
        story.tick(t)
    loaded = Storyteller(store, director, hooks)
    assert loaded.observations == story.observations
    saved = json.loads(store.get(TUNING["store_key"]))
    del saved["observations"]
    store.set(TUNING["store_key"], json.dumps(saved))
    loaded.restore()
    assert loaded.observations == []
    assert loaded.state == story.state
    assert loaded.levers == story.levers
    loaded.tick(3)
    assert len(loaded.observations) == 1
    loaded.reset()
    assert loaded.observations == []


def set_state(story, state, now=0):
    story.state, story.entered_at = state, now
    story._base_levers = copy.deepcopy(TUNING["states"][state]["levers"])
    story._levers = copy.deepcopy(story._base_levers)


@pytest.mark.parametrize("condition", ["ready", "discharged", "distant", "dirty", "forgotten", "wounded", "wilds"])
def test_kin_market_trip_uses_a_route_to_player_town_only_while_staging_is_healthy(condition):
    from ..living.world import LivingWorld, SessionHooks

    story, director, hooks, store = setup()
    kin, intent = vendetta(story, director, hooks, store)
    hooks.town = "c"
    rising(story)
    b = board(story)
    living = LivingWorld(SimpleNamespace(storyteller=story))
    living.board, living.places = b, b.places
    b.hooks = SessionHooks(living)
    b.hooks.resident_can_leave = lambda _rid: True
    b.hooks.resident_left = lambda *_args: None
    b.resident_pool = [dict(id=kin.properties["id"], name="Kin", display="Kin", home="a")]
    story._levers["market_chance"] = 1
    if condition == "discharged":
        director.bus.make("attack", actor=actor_key(kin), target="player", hour=8)
    elif condition == "distant":
        b.places["c"]["x"] = TUNING["vendetta_trip_distance"] + 1
    elif condition == "dirty":
        director._dirty.add(actor_key(kin))
    elif condition == "forgotten":
        store.set(f"npc.{actor_key(kin)}.facts", "[]")
    elif condition == "wounded":
        hooks.health = 0.5
    elif condition == "wilds":
        hooks.town = None
    # Same RNG, ordinary hooks: ineligible holders must keep authored choices.
    ordinary = board(story)
    ordinary.places = copy.deepcopy(b.places)
    ordinary.hooks.resident_destination = lambda *_args: None
    ordinary.resident_pool = copy.deepcopy(b.resident_pool)
    ordinary._resident_trips(8)
    before = copy.deepcopy(intent.to_dict())
    rng_before = b.rng.getstate()
    b._resident_trips(8)
    trip = next(iter(b.journeys.values()))
    control = next(iter(ordinary.journeys.values()))
    assert trip.dest == ("c" if condition == "ready" else control.dest)
    assert trip.route == b.network.route("a", trip.dest)
    assert trip.position_at(8) == trip.route[0]  # no move to destination
    assert trip.resident == kin.properties["id"] and trip.home == "a"
    assert trip.legs == 2 and intent.to_dict() == before
    assert b.rng.getstate() == ordinary.rng.getstate() != rng_before
    assert dict(story.inspector_rows())["Vendetta market destination"]


def test_respite_suppresses_only_incoming_local_hostiles_and_preserves_distant_ecology(monkeypatch):
    from ..living import world

    story, _director, hooks, _store = setup()
    set_state(story, "RESPITE")
    hooks.health = 0.5
    story.tick(0)
    b = board(story)
    hooks.region = (0, 0, 900)
    living = world.LivingWorld(SimpleNamespace(clock=SimpleNamespace(day=0, hour=0),
                                               _player_pos=lambda: [0, 0, 0]))
    living.board, living.places = b, b.places
    living.reach = lambda: 2000
    close = b.plan("wolves", 0, origin="a", dest="b")
    distant = b.plan("wolves", 0, origin="a", dest="b")
    hunter = b.plan("hunters", 0, origin="a", dest="b")
    peaceful = b.plan("trader", 0, origin="a", dest="b")
    distant.set_progress(1500, 0)
    before = b.to_json()
    spawned = []

    def spawn(j, _t):
        spawned.append(j.id)
        living.live[j.id] = {"things": []}

    monkeypatch.setattr(living, "_spawn", spawn)
    living._stream()
    assert close.id not in spawned and hunter.id not in spawned
    assert distant.id in spawned and peaceful.id in spawned
    assert b.hostile_materialisations == {"a": 1}
    assert json.loads(b.to_json())["journeys"] == json.loads(before)["journeys"]
    for kind in ("bandits", "wolves", "greenskins"):
        assert b._lever("kind_weights", {}).get(kind, journeys.KINDS[kind]["weight"]) == journeys.KINDS[kind]["weight"]
    assert b._lever("hunter_bounty", 0) == journeys.HUNTER_BOUNTY
    assert b.hooks.journey_weight("wolves", distant.position_at(0), True) == 1
    assert b.hooks.journey_weight("wolves", close.position_at(0), True) == 0
    # Gates are sampling decisions: no actor kill, journey retirement or time change.
    assert all(j.state == "travel" and j.depart_t <= 0 for j in b.journeys.values())


def test_streamer_counts_only_successful_hostile_materialisations_and_sensors_only_read(monkeypatch):
    from ..living import world

    story, _director, _hooks, _store = setup()
    b = board(story)
    session = SimpleNamespace(clock=SimpleNamespace(day=0, hour=0), _player_pos=lambda: [0, 0, 0])
    living = world.LivingWorld(session)
    session.living = living
    living.board, living.places = b, b.places
    living.reach = lambda: 2000
    failed = b.plan("wolves", 0, origin="a", dest="b")
    arrived = b.plan("hunters", 0, origin="a", dest="b")
    b.plan("trader", 0, origin="a", dest="b")

    def spawn(j, _t):
        if j is not failed:
            j.live = True
            living.live[j.id] = {"things": [actor(j.id)]}

    monkeypatch.setattr(living, "_spawn", spawn)
    living._stream()
    assert arrived.id in living.live and b.hostile_materialisations == {"a": 1}
    living._stream()
    assert b.hostile_materialisations == {"a": 1}  # already live is not another arrival
    before = b.to_json()
    sensor = SessionStorytellerHooks(session)
    assert sensor.hostile_materialisations() == ("a", 1)
    assert b.to_json() == before
    restored = board(story)
    assert restored.load_json(before)
    assert restored.hostile_materialisations == b.hostile_materialisations
    saved = json.loads(before)
    saved["streaming"]["version"] = 99
    restored.load_json(json.dumps(saved))
    assert restored.hostile_materialisations == {}


def test_empty_pressure_window_caps_population_then_real_arrivals_release_it():
    story, _director, hooks, _store = setup()
    hooks.arrivals = ("a", 0)
    rising(story)
    start = story.last_sample
    calm_population = TUNING["states"]["CALM"]["levers"]["population"]
    assert story.levers["population"] > calm_population
    story.tick(start + TUNING["arrival_window_hours"])
    assert story.state in ("RISING", "PEAK")
    assert story.sensors["arrival_stalled"]
    assert story.levers["population"] == calm_population
    b = board(story)
    b.seed(story.last_sample)
    assert len(b.journeys) == calm_population
    story.tick(start + TUNING["states"]["RISING"]["max_hours"])
    assert story.state == "PEAK" and story.levers["population"] == calm_population
    hooks.arrivals = ("a", 2)
    story.tick(story.last_sample + TUNING["sample_hours"])
    assert story.sensors["hostile_arrivals_per_hour"] > 0
    assert not story.sensors["arrival_stalled"]
    assert story.levers["population"] == TUNING["states"]["PEAK"]["levers"]["population"]


def test_arrival_window_rebases_on_region_change_and_counter_reset():
    story, _director, hooks, _store = setup()
    hooks.arrivals = ("a", 20)
    rising(story)
    story.tick(10)
    assert story.sensors["arrival_stalled"]
    hooks.arrivals = ("b", 300)
    story.tick(10.25)
    assert story.sensors["arrival_hours"] == 0
    assert not story.sensors["arrival_stalled"]
    hooks.arrivals = ("b", 0)
    story.tick(10.5)
    assert story.sensors["hostile_arrivals"] == 0
    assert story.sensors["arrival_hours"] == 0


def test_old_unpaid_writs_lower_the_actual_hunter_threshold_and_settlement_clears_age():
    story, _director, hooks, _store = setup()
    hooks.health = 0.5  # hold CALM while observing an unpaid writ
    hooks.law = {"a": dict(bounty=130, phase="writ")}
    story.tick(0)
    base = story.levers["hunter_bounty"]
    story.tick(TUNING["unpaid_writ_hours"] - TUNING["sample_hours"])
    assert story.levers["hunter_bounty"] == base
    story.tick(TUNING["unpaid_writ_hours"])
    assert story.levers["hunter_bounty"] == base * story.levers["writ_hunter_scale"]
    b = board(story)
    b.bounty_news, b.heard["a"], b.hooks.bounty = "known", ["known"], 130
    b._departures(23)
    assert any(j.kind == "hunters" for j in b.journeys.values())
    hooks.law = {"a": dict(bounty=0, phase="clear")}
    story.tick(25)
    assert story.levers["hunter_bounty"] == base and not story._writ_since
    hooks.law["a"] = dict(bounty=130, phase="writ")
    story.tick(26)
    assert story.levers["hunter_bounty"] == base


def test_pristine_switch_keeps_sensors_idle_and_a_day_of_board_bytes_and_rng_authored(monkeypatch):
    from ..map_memory import MapMemory, RESPAWN_HOURS, RESPAWN_JITTER

    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    rising(story)
    story.set_enabled(True)  # a saved Studio preference cannot defeat the kill switch
    monkeypatch.setitem(TUNING, "enabled", False)

    def forbidden(*_args):
        pytest.fail("Pristine ecology queried a storyteller sensor")

    for name in ("actors", "actor_town", "player_town", "player_health_fraction",
                 "hostile_counts_by_tier", "law_pressure", "player_region", "hostile_materialisations"):
        monkeypatch.setattr(hooks, name, forbidden)
    saved = copy.deepcopy(story.sensors), story.last_sample, story.observations
    a, b = board(story), board(story)
    b.hooks = journeys.WorldHooks()
    b.hooks.resident_can_leave = lambda _rid: True
    b.hooks.player_place = lambda: "a"
    b.hooks.player_bounty = lambda: 200
    a.hooks.bounty = 200
    for cast in (a, b):
        cast.resident_pool = [dict(id=kin.properties["id"], home="b", name="Kin", display="Kin")]
        cast.seed(0)
    for step in range(97):
        t = step / 4
        story.tick(t)
        assert a.update(t) == b.update(t)
        assert a.to_json() == b.to_json(), f"Pristine board diverged at hour {t}"
        assert a.rng.getstate() == b.rng.getstate()
        assert story.destination_weight("a") == 1
        assert story.materialisation_weight([actor_key(kin)], 10) == 1
        assert story.resident_destination(kin.properties["id"], ["a"], 10) is None
        assert story.journey_weight("wolves", (0, 0), True) == 1
    assert (story.sensors, story.last_sample, story.observations) == saved
    mem = MapMemory(SimpleNamespace(storyteller=story))
    assert mem._delay("lair") == RESPAWN_HOURS + RESPAWN_JITTER * (sum(map(ord, "lair")) % 97) / 96
    assert dict(story.inspector_rows())["Ecology switch"]


def test_holder_map_is_cached_per_sample_and_board_levers_once_per_update(monkeypatch):
    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    calls = []
    monkeypatch.setattr(hooks, "actors", lambda: calls.append("actors") or hooks.cast)
    rising(story)
    for _ in range(20):
        story.materialisation_weight([actor_key(kin)], 100)
        story.resident_destination(kin.properties["id"], ["a", "b"], 100)
    assert calls == ["actors", "actors"]
    story.tick(8.25)
    assert len(calls) == 3
    b = board(story)
    reads = []
    monkeypatch.setattr(b.hooks, "journey_levers", lambda: reads.append("levers") or story.board_levers())
    b.seed(23)
    assert reads == ["levers"]
    reads.clear()
    b.update(24)
    assert reads == ["levers"]


def test_feedback_writ_age_and_rng_restore_exactly_in_an_active_pressure_window():
    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    hooks.arrivals, hooks.town = ("a", 0), "c"
    hooks.law = {"a": dict(bounty=130, phase="writ")}
    rising(story)
    story.tick(10)
    story.persist()
    original = store.get(TUNING["store_key"])
    loaded = Storyteller(store, director, hooks)
    loaded.persist()
    assert store.get(TUNING["store_key"]) == original
    a, b = board(story), board(loaded)
    for cast in (a, b):
        cast.resident_pool = [dict(id=kin.properties["id"], home="b", name="Kin", display="Kin")]
        cast.seed(10)
    rng_state = director.rng.getstate()
    for t in (10.25, 11, 14, 16, 20, 24, 32):
        story.tick(t)
        loaded.tick(t)
        a.update(t)
        b.update(t)
        assert a.to_json() == b.to_json()
        assert a.rng.getstate() == b.rng.getstate()
        assert story.levers == loaded.levers and story.sensors == loaded.sensors
        assert story.observations == loaded.observations
    assert director.rng.getstate() == rng_state


def test_tuning_loads_mod_overlays_replaces_hour_windows_and_keeps_code_fallbacks(tmp_path, monkeypatch):
    from .. import data, storyteller

    monkeypatch.setattr(data, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(data, "_MODS_DIR", str(tmp_path / "mods"))
    mod = tmp_path / "mods" / "quiet"
    mod.mkdir(parents=True)
    (tmp_path / "storyteller.json").write_text(json.dumps({"enabled": False,
        "states": {"RISING": {"levers": {"kind_hours": {"bandits": [18, 6]}}}}}))
    (mod / "storyteller.json").write_text(json.dumps({"states": {"RISING": {
        "levers": {"kind_hours": {"bandits": [20, 4]}, "population": 27}}}}))
    tuning = storyteller.load_tuning()
    assert tuning["enabled"] is False
    assert tuning["states"]["RISING"]["levers"]["kind_hours"]["bandits"] == [20, 4]
    assert tuning["states"]["RISING"]["levers"]["population"] == 27
    assert tuning["states"]["CALM"] == storyteller.DEFAULT_TUNING["states"]["CALM"]
    assert storyteller.DEFAULT_TUNING["enabled"] is True
    # Existing content keeps append semantics; only tuning opts into replacement.
    assert data._merge([1], [2]) == [1, 2]
    assert data._merge([1], [2], replace_lists=True) == [2]


def test_studio_edits_live_respite_admission_and_future_state_table_without_sampling():
    story, director, hooks, store = setup()
    set_state(story, "RESPITE")
    hooks.health = 0.5
    story.tick(0)
    before = copy.deepcopy(story.sensors), story.observations, director.rng.getstate()
    assert story.journey_weight("wolves", (0, 0), True) == 0
    story.edit_lever("RESPITE", ("kind_weights", "wolves"), 2)
    assert story.journey_weight("wolves", (0, 0), True) == 2
    story.edit_lever("RISING", ("population",), 27)
    story.edit_lever("RISING", ("kind_hours", "wolves", 0), 22)
    assert story.state_levers("RISING")["population"] == 27
    assert story.state_levers("RISING")["kind_hours"]["wolves"] == [22, 6]
    assert (story.sensors, story.observations, director.rng.getstate()) == before
    expected = story.levers, story.state_levers("RISING"), story.world_view(), story.inspector_rows()
    loaded = Storyteller(store, director, hooks)
    assert (loaded.levers, loaded.state_levers("RISING"), loaded.world_view(), loaded.inspector_rows()) == expected
    loaded.reset_edits("RESPITE")
    assert loaded.journey_weight("wolves", (0, 0), True) == 0
    loaded.set_enabled(False)
    assert not Storyteller(store, director, hooks).enabled


@pytest.mark.parametrize("path,value", [(("population",), -1), (("market_chance",), 2),
    (("kind_hours", "wolves", 0), 25), (("health",), 1), (("kind_weights", "dragon"), 1),
    (("destination_bias",), float("nan")), (("population",), float("inf"))])
def test_studio_rejects_invalid_data_cells_without_writing(path, value):
    story, _director, _hooks, store = setup()
    before = dict(store.d), story.levers
    with pytest.raises(ValueError):
        story.edit_lever("CALM", path, value)
    assert (store.d, story.levers) == before


def test_world_view_links_actual_sampled_trips_to_holder_memories_and_preserves_causes():
    from ..storyteller_studio import world_explanations

    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    ev, _fact = remember(store, director.bus, witness)
    rising(story)
    b = board(story)
    sampled = [b.plan("trader", 8, origin="a") for _ in range(20)]
    trip = next(j for j in sampled if j.dest == "b")
    receipt = next(r for r in story.world_view()["receipts"] if r["journey"] == trip.id)
    assert receipt["events"] == [ev.id]
    assert actor_key(witness) in receipt["reason"] and f"theft #{ev.id}" in receipt["reason"]
    story.record_journey(trip, 9, arrived=True)
    arrival = story.world_view()["receipts"][0]
    assert arrival["outcome"] == "Materialised in the live region"
    assert arrival["reason"] == receipt["reason"] and arrival["events"] == [ev.id]
    explicit = b.plan("trader", 9, origin="a", dest="b")
    assert story.world_view()["receipts"][0] == arrival  # ordinary planning is quiet
    story.record_journey(explicit, 10, arrived=True)
    authored = story.world_view()["receipts"][0]
    assert authored["journey"] == explicit.id and not authored["events"]
    before = dict(store.d), copy.deepcopy(story._reasons), director.rng.getstate()
    rows = world_explanations(story)
    thread = next(r for r in rows if r[0] == "Unreported threads")
    assert "b" in thread[1] and f"weight {story.levers['destination_bias']:g}" in thread[1]
    assert thread[3] == [ev.id]
    assert (store.d, story._reasons, director.rng.getstate()) == before
    story.persist()
    assert Storyteller(store, director, hooks).world_view() == story.world_view()


def test_busy_ordinary_planning_preserves_causal_receipts_and_inspector_outcomes():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    remember(store, director.bus, witness)
    rising(story)
    b = board(story)
    for _ in range(20):
        if b.plan("trader", 8, origin="a").dest == "b":
            break
    receipts = story.world_view()["receipts"]
    assert receipts and receipts[0]["events"]
    outcome = dict(story.inspector_rows())["Journey outcome"]
    control = board(story)
    control.rng.setstate(b.rng.getstate())
    control.next_id = b.next_id
    control._names_used = set(b._names_used)
    control.hooks.journey_sampled = lambda *_args, **_kwargs: None
    sampler_rng = director.rng.getstate()
    for i in range(TUNING["receipt_cap"] * 2):
        # Explicit destinations and their later homeward legs are authored.
        trip = b.plan("trader", 9 + i, origin="a", dest="c")
        other = control.plan("trader", 9 + i, origin="a", dest="c")
        trip.legs = other.legs = 1
        b.next_leg(trip, 9.5 + i)
        control.next_leg(other, 9.5 + i)
        assert trip.to_dict() == other.to_dict()
        assert b.rng.getstate() == control.rng.getstate()
    assert story.world_view()["receipts"] == receipts
    assert dict(story.inspector_rows())["Journey outcome"] == outcome
    assert director.rng.getstate() == sampler_rng
    story.persist()
    loaded = Storyteller(store, director, hooks)
    assert loaded.world_view() == story.world_view()
    assert loaded.inspector_rows() == story.inspector_rows()


def test_neutral_memory_weight_does_not_emit_planning_receipts_but_arrivals_do():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    remember(store, director.bus, witness)
    rising(story)
    story.edit_lever("RISING", ("destination_bias",), 1)
    b = board(story)
    for _ in range(20):
        trip = b.plan("trader", 8, origin="a")
        if trip.dest == "b":
            break
    assert trip.dest == "b"
    assert not story.world_view()["receipts"]
    assert "Journey outcome" not in dict(story.inspector_rows())
    story.record_journey(trip, 9, arrived=True)
    receipt = story.world_view()["receipts"][0]
    assert receipt["journey"] == trip.id and not receipt["events"]
    assert receipt["outcome"] == "Materialised in the live region"


def test_receipt_causes_follow_only_the_matching_leg_including_a_resting_arrival():
    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    ev, _fact = remember(store, director.bus, witness)
    rising(story)
    b = board(story)
    for _ in range(20):
        trip = b.plan("trader", 8, origin="a")
        if trip.dest == "b":
            break
    assert trip.dest == "b"
    initial_leg = trip.legs
    b.arrive(trip, 9, [])
    assert trip.state == "rest" and trip.legs == initial_leg - 1
    story.record_journey(trip, 9, arrived=True)
    receipt = story.world_view()["receipts"][0]
    assert receipt["events"] == [ev.id] and receipt["leg"] == initial_leg
    # A later authored leg can reuse the same endpoints. Suppressing its
    # planning receipt must not attach the old leg's theft to its arrival.
    trip.state, trip.origin, trip.dest = "travel", "a", "b"
    story.record_journey(trip, 10)
    story.record_journey(trip, 11, arrived=True)
    assert not story.world_view()["receipts"][0]["events"]
